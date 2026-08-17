# OpenWrt porting / upstream-submit scaffold — Ooredoo R291 v2 (ASR1802S / "KAGU")

> Goal #1 من طلبك: استخراج كل المعلومات الداخلية → بناء نسخة خاصة من OpenWrt → commit للمشروع الرسمي.
> ملفّات العينة (DTS/Makefile/device-data) في هذا المجلد جاهّة للنظر فيها، لكن **لم تُختبر على الجهاز بعد** — انظر CHECKLIST.

## 1. ملخص العتاد المستخرج مباشرةً من الراوتر (root shell)

| الحقل | القيمة | مصدر |
|---|---|---|
| اللوحة / الطراز | **ASR 1826s (KAGU) Board EVB** (board code 1826s) | `/proc/device-tree/model` |
| الـ SoC | **ASR ASR1802S** (ARMv7) — *ليس PXA1826 ولا MediaTek* | `kernel-a.bin strings` = `asr,1802s` |
| Device-Tree compatible | `asr,1802s-evb` , `asr,1802s` | `/proc/device-tree/compatible` + kernel strings |

> ⚠️ **توضيح أسماء:** "ASR 1826s" هو اسم اللوحة (board code KAGU)؛ والـ SoC الفعلي هو **ASR1802S** — تم التقاطه في `kernel-a.bin` كـ `asr,1802s` (ويُشير إلى `marvell,asr1802s-clock/thermal` لكنه ليس منصة Marvell). اسم "pxa1826_cfg" (منصة Intel/Marvell PXA1826 أو موديم ASR1826 LTE) **غير موجود على هذه الوحدة** — ظهر ربما في إصدار firmware آخر؛ ولا يُستَخدم في الفلاش. كذلك صور `mt7621`/`mt7663` الواردة في `flashing_files/` (MediaTek) بعيدون عن هذا الجهاز.
| معالج | ARMv7 rev 3 ، **Cortex-A9** (`[410fc073]`) ، 2505 BogoMIPS (~1.0 GHz single-core) | `/proc/cpuinfo` |
| الذاكرة | 128 MB إجمالاً (MemTotal ≈ 90 MB)؛ 32 MB محجوز للـ CP (`cpmem=32M@0x6000000`) | kernel cmdline + `/proc/meminfo` |
| نواة الجذر | OpenWrt **Barrier Breaker 14.07** r47068 ، `mmp/generic` | `/etc/openwrt_release` |
| opkg / حزم | **✅ موجود ومفعّل**: `/rom/bin/opkg` (في PATH) + `/rom/usr/lib/opkg/`؛ ومعه `curl,dropbearkey,nodogsplash,telnet,wget` على `/rom` | `ls /rom/bin/opkg` عبر root-shell |
| النواة المشغّلة | Linux **3.10.33** (gcc 4.8.3 OpenWrt/Linaro) | `/proc/version` |
| الترتيبات (Layout) | **Dual-bank A/B** على MTD_SPI_NAND + UBI overlay | `/proc/mtd` + `/proc/mounts` + `ooredoo_backup/probe/*` |
| الذاكرة الليفية | **SPI-NAND** `F35UQA001G` (mfr=0xcd, dev=0x6161 ، 128 MB)، إيراس 0x20000 | `dmesg` + `/proc/mtd` |
| UART console | `ttyS0` ، `pxa2xx-uart @ d4017000` irq 59 ، 115200n8 | `/proc/iomem` + `dmesg` |
| المشغّل اللاسلكي | **Realtek RTL8812FE ×2** (wlan0 + wlan1) على PCIe gen1×1 — `rtl8192cd.ko` (3.0 MB، binary-only، لا `srcversion`/`vermagic`)؛ للنواة الحديثة استبدله `rtw88` (يدعم 8812FE ≥ Linux 5.13) | `dmesg rtl8192cd_init_one` + `/rom/lib/modules/3.10.33/rtl8192cd.ko` |
| سويش الإيثرنت | MAC **ASR eth @ d4281800** irq42/43 + سويتش **YT9215 (yt_switch.13)** | `dmesg` + `/proc/iomem` |
| الـ VoIP | **MAXLINEAR SLIC** ، GPIO23 reset / GPIO24 wakeup (2× FXS) | `dmesg maxlinear_slic_dt_init` |
| الطاقة/واجهات أخرى | PMIC **88PM802** (I2C@0x30) + **ASR USB3/DWC3** (c0000000 irq76) + **MMC0** (d4280000 irq71) + I2C/spi/thermal | `dmesg` + `/proc/iomem` |

## 3. يقشة الأجهزة والمقاطع البرية (لبناء DTS موحص — `ooredoo_backup/probe/proc_iomem.txt`، `proc_interrupts.txt`)
| الطقم | المدى (physical) | IRQ | الملاحظات |
|---|---|---|---|
| UART1 | d4017000 | 59 | `console=ttyS0,115200` |
| RTC/PMIC | d4010000 | 20 | ASRPM802 |
| Thermal | d4013300 | 65 | ASR1802S thermal |
| QSPI/SPI-NAND | d401b000 / d420b000 | 35, 77 | F35UQA001G → 25 MTD |
| I2C.2 | d4037000 | 12089 | PMIC 88PM802 @0x30 |
| Ethernet MAC | d4281800 | 42, 43 | YT9215 DSA على MDC/MDIO |
| PCIe0/PCIe1 | d4210000/d4220000 | 50, 51 | gen1×1 → wlan1 / wlan0 (MSI 26/250) |
| MMC0 | d4280000 | 71 | eMMC/SD |
| USB3 DWC3 | c0000000 | 76 | dwc3 |
| ACIPC (CP) | d403d100 | 21998 | واجهة CP (الموديم) |

### 2. تخطيط MTD الكامل (`/proc/mtd`) — استخراج شلبي دقيق
```
mtd0  bootloader           0x00040000   (U-Boot أولي)
mtd1  cp_reliabledata      0x00020000   ← U-Boot env + NVM/PLATFORM (TTPCom)
mtd2  ap_reliabledata      0x00020000
mtd3/4   cp/ap reliabledata_backup
mtd5/6   mep-ota (+_backup)
mtd7/8   dtim-a / dtim-b        (الإعدادات اللاسلكية الاحتياطية)
mtd9/10  cpimage-a / cpimage-b   0x00f00000 (صور الثنائيات؟)
mtd11/12  u-boot-a / u-boot-b    0x000c0000
mtd13/14  kernel-a / kernel-b     0x00500000  (~5 MB ، zImage ARM)
mtd15/16  rootfs-a / rootfs-b     0x01400000  (~20 MB ، squashfs xz) ← **/dev/root هو rootfs-a mounted ro على /rom**
mtd17/18  oem_data-a/b           0x00600000  (بيانات OEM للوحة)
mtd19  asr_flag                 0x000c0000
mtd20  rsa                      0x00040000
mtd21  bootargs                 0x00040000
mtd22  cust_info                0x00040000
mtd23  rootfs_data              0x018c0000  ← UBIFS overlay مُركّب على /overlay
mtd24  MRVL_BBM                 0x00600000
```
> ملاحظة هامة: رغم أسماء MTD ثنائية البنك (kernel-a/b, rootfs-a/b…)، **الجذر الذي يعمل عليه هو نظام UBI overlay**: `/rom` (squashfs ro من rootfs-a) + `/overlay` (UBIFS `ubi0_0` ← mtd23) + `/NVM/oem_data` (ubi1:oem_data). هذا يختلف عن مخطط MTD الخام.

### 3. الهوية الخاصة بالوحدة (مستخرجة من /overlay/root/NVM/)
- **MAC اللاسلكية 5 GHz**: `E4:7D:EB:E6:D4:E9` (من `wifi_5g_addr`) — OUI `E4:7D:EB` ينتمي إلى ASR.
- **NVM**: 30+ ملف TTPCom `NRAM2_*` (ME، AP، PLMN، APN/PDN lists، BA lists، Feature list، GSMCal/LTECal/RF cal، audio_gain، PLC، afcDacTable…). هذه **معوّقات RF/سلالية الوحدة** — يجب نسخها قبل أي فلاش OpenWrt لتعمل الواجهة اللاسلكية/الخلويّة.

### 4. لماذا لا نرسل صورة “mt7621”؟ ⚠️ تحذير مهم
في `flashing_files/` هناك `openwrt-ramipes-mt7621-sxx-u-boot.img` (135 KB) و `telnetd_extract/lib/modules/3.10.108/mt7663.ko` (برنامج نواة MediaTek MT7663). **هذه من صورةfirmware أصدرها أو رجعها مطوّرون لمنصة MediaTek MT7621/MT7663 — وليست لهذه اللوحة.** الراوتر الحي هنا SoCهو **ASR1802S (ARM)** ليس MT7621. فلاش `mt7621` سيدمّر هذه الوحدة. (قد تكون الصور مرفقة من تعديل للموديلات ذات الشريحة MediaTek من سلسلة R291.) النسخة المنقوصة/المخصصة يجب أن تستهدف `asr,1802s`.

### 5. مسار بناء نسخة OpenWrt مخصصة (هدفك)
1. **اختيار الهدف (target):** لا يوجد target ASR1802S في OpenWrt الرسمي. الخياران:
   - (أ) بناء `target/linux/` جديد للـ SoC ASR1802S باستخدام **kernel 3.10.x** من البائع (vendor fork) كقاعدة — عملية reverse-engineering كبيرة.
   - (ب) إعادة ترتيب نفس kernel+squashfs الأصلي بإضافة حزم OpenWrt فوق (نبرة "repackage"): استخراج rootfs-a بنوات `unsquashfs`، دمج `/overlay` الخاص بك، **وإعادة صياغة squashfs** ثم `dd` إلى rootfs-a. **ملحوظة: opkg موجود على /rom (`mmp/generic` fork)، لذا يمكنك تثبيت حزم .ipk إضافية مباشرة على النظام الجاهز قبل الترميز.**
2. **التعامل مع NVM الخاص بالوحدة:** انسخ `overlay/root/NVM/*` إلى `/etc/NVM/` داخل النسخة الجديدة (هذه للـ baseband/RF). لا تفقد الملف `wifi_*_addr` (تحديد MAC الجديد بعد الفلاش لتفادي تعارض MAC).
3. **البوت:** `kernel-a` (zImage ARM) + سطر `cmdline` ← نظّفه من `system=a` و`crashkernel` غير الضرورية؛ استهدف `rootfstype=squashfs root=/dev/mtdblk15` (rootfs-a) مع `init=/etc/preinit`.
4. **التحقق:** شغل على راوتر اختبار. احفظ bitstream صحيح ← هذا ما يُرفق في PATCH للمنتدى/الـ mailing list.

#### ملف DTS مسودة (`openwrt_port/asr1802s-kagu.dts`)
```dts
/dts-v1/;
#include "asr1802s.dtsi"
/ {
        model = "Ooredoo R291 v2 (ASR 1826s / KAGU)";
        compatible = "asr,1802s-evb", "asr,1802s";
        soc {
                serial: serial@...... { ... };
                mac: ethernet@... { /* MAC من TTPCom_NVM */ };
        };
        chosen {
                stdout-path = "serial0";
        };
};
```
> استناداً إلى `arch/arm/boot/dts/` في kernel 3.10 vendor + إرساله إلى `openwrt-devel`.

## 4. ملاحظة: قفل الشبكة/الشريحة (SIM-lock) — للوثائق فقط، وليس للإنزال

تم التقاط **`dropbear_password=19222019`** في ملف البيئة U-Boot (`ooredoo_backup/probe/bootargs_txt.txt` ← `mtd21 bootargs`). لكن قفل الشبكة/الشريحة غير مخزّن هنا. المتغيّرات `nano_sim_print=1` و `sim_print=0` في الـ env هي مجرد علامات سلوك طباعة SIM، وليست "كلمة شراء".

آلية القفل الحقيقية تقع في **الطرف CP (Communication Processor)**: الـ CP نواة RTOS مستقلّة تُدرّس الـ cpmem (32 MB @ 0x6000000) وتُدير البروتوكول اللاسلكي. بيانات الشريحة + IMEI + الحالة الـ RIL/إعدادات الشبكة تُخزّن ضمن ملفات NVM الخاصة بالـ CP على الـ NAND:
- `/overlay/root/NVM/TTPCom_NRAM2_MOBILE_EQUIPMENT_DATA.gki` ← هنا يُخزّن IMEI + أحوال الشريحة + مفاتيح RIL.
- `/overlay/root/NVM/TTPCom_NRAM2_CUSTOMIZATION_DATA.gki` ← إعدادات OEM/الشبكة.
- `bootargs` U-Boot: `nano_sim_print` / `sim_print`.

**ملاحظة المكافأة (decryption):** تعديل أو فك هذه الملفات يتطلّب عكس بنية GKI/NVM الخاصة بـ TTPCom (واجهة NRAM2)، وهو **تجاوز وظيفي لحماية OEM/carrier lock** — لن نقدّم أي أداة أو تعليمات فتح. الوثائق أعلاه توضح موقع القفل فقط لتوجيه بحث المنصّحين المشروع الرسمي.

### 6. إرشادات إرسال upstream commit (للملفات في CHECKLIST)
انظر `UPSTREAM_SUBMIT_CHECKLIST.md` — العناصر المطلوبة: [ ] صورة تجريبية تشتغل، [ ] DTS مكتمل + Makefile جديد في `target/linux/`, [ ] `etc/board.d/01_leds` و `02_network`، [ ] مناققة حساسية NVM، [ ] توقيع S-o-b + CC مشرف الـ SoC.


## خلاصة
لقد استخرجنا **الملف التعريفي العتادي بالكامل** من root shell: SoC (ASR1802S/ARv7/128MB)، تخطيط MTD المزدوج البنك + UBI overlay، النواة 3.10.33، وNVM الخاصة بالوحدة (MAC + 30 ملف cal). ما تم إعداده هنا جاهز لتوجيه بناء نسخة OpenWrt مخصّصة وإرسالها للمشروع الرسمي — لكن الخطوة العملية الأولى المقترحة هي إعادة تركيب الـ rootfs الأصلي (repackage) بدلاً من بناء target من الصفر.
