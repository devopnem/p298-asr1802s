# خطة منشآت إضافة دعم OpenWrt — Ooredoo R291 v2 (ASR1802S / KAGU)

> الحالة الحالية: جهازٌ يعمل بنظام root (kernel 3.10.33 + squashfs vendor)، وتمّ استخراج جميع
> بيانات العتاد (`ooredoo_backup/`). الهدف: إصدارٌ موحّح في OpenWrt.

## المستوى 0 — أساسيات التكرار ذي المخاطر (قبل أي فلاش OpenWrt)
1. UART serial console على `pxa2xx-uart @ d4017000` (115200n8)؛ جرّب كابل FTDI.
2. حافظك على `ooredoo_backup/kernel-a.bin` + `rootfs-a.bin` + `overlay.tar.gz` كصورة استعلاة احتياطية.
3. سجِّل U-Boot env (`bootargs_txt.txt`): `bootcmd=mrvlboot`، `loadaddr=0x8000`، `dropbear_password=19222019` — احفظها.

> ⚠️ **حقيقة الـ drivers (تمّ توثيقها على الجهاز):**
> - `rtl8192cd.ko` (3 MB في `/rom/lib/modules/3.10.33/`) = **وحيد binary-only module** (لا `srcversion`/`vermagic`) → **لا يحمّل إلا على kernel 3.10.33**. النواة الحديثة ترفضه بـ `invalid module format`. البديل للـ OpenWrt الحديث = **`rtw88`** (يدعم RTL8812FE منذ Linux 5.13).
> - باقي الـ drivers (asr-eth، PCIe، qspi/SPI-NAND، dwc3، 88pm802، slic…) **مضمّنة بالـ kernel** وليست .ko — لذا أي صيغة kernel جديدة تفقدها إلا إذا أُرسِلت upstream أولاً.

## المستوى 1 — تشغيل initramfs OpenWrt (اختبار بدون كتابة NAND)
1. بناء `Image Initramfs` (kernel + squashfs) لـ `armv7/cortex-a9`.
2. عبر U-Boot: إما `tftp 0x00008000 openwrt-initramfs.itb && bootm 0x00008000`، أو عبر الـ `%EXE`/download إلى `/dev/mtd13` مؤقتاً (مخاطرة؟ راقب UART). هدف الاختبار: تشغيل userspace OpenWrt على الـ SoC بدون لمس NAND.
3. اقرأ الـ dmesg الناتج → عُرف الـ **PCI IDs** للـ RTL8812FE (wlan0/wlan1) وعنوان MAC eth.

## المستوى 2 — جرد برموز kernel الرسمي (driver audit)
| المكوّن | الحالة في mainline؟ | ما يُفتقد |
|---|---|---|
| ASR1802S CPU/SoC | ❌ ليس في kernel.org (vendor 3.10 فقط) | arch/arm/mach-asr* + clock/reset/serial |
| SPI-NAND F35UQA001G | ✅ `spi-nand` عام؛ mfr 0xcd | قد تحتاج quirk إيراس |
| PCIe gen1 ×1 (ASR) | ❌ driver vendor | `pcie-kagu` |
| Realtek RTL8812FE | ✅ `rtw88_8812fe` (kernel ≥5.13) | ربما تحتاج PCI IDs |
| YT9215 Ethernet switch | ✅ `dsa` / `yt8215` عام | DSA binding |
| MAXLINEAR SLIC | ✅ `dsoftval`/slic | GPIO إعدادات |
| USB3 DWC3 | ✅ `dwc3` + `xhci-platform` |  |
| 88PM802 PMIC | ✅ `88pm80x` | مفتاح regulator |

**الاستنتاج:** الصعوبة الكبرى = **دعم ASR1802S في kernel الرسمي** (الواجهات d4017000–d4281800 غير مدعومة). 

## المستوى 3 — المساران الممكنان للـ upstream commit
**أ) المسار "upstream first" (الأنظف للرسالة، وقت طويل):**
   1. أرسل أولاً **DTS/DTSI + drivers للـ ASR1802S** إلى `linux-arm-kernel` (vendor 3.10 → forward-port لأحدث kernel).
   2. بعد قبول الـ SoC → أضف **target `asr1802s`** في `openwrt/openwrt` (target.mk + Makefile.skeleton) + DTS KAGU.
   3. أرفق صورة initramfs تعمل على UART + dmesg كدليل اختبار.

**ب) المسار "repackage" (سريع، محدود النطاق):**
   - استخرج `rootfs-a.bin` (squashfs)، أضف حزم OpenWrt الثنائية (opkg) فوق، أعد الضغط → `sysupgrade.bin` جديد. لا يغيّر kernel/PXE (يبقى 3.10.33 vendor)، لكن يضيف package feed. ملائم للمستخدمين لكنه غير كامل للـ upstream (عيّن upstream-first).

## المستوى 4 — الحفاظ على NVM (إلزامي للـ OpenWrt)
- انسخ `overlay/root/NVM/*` (MAC wifi + إعدادات SIM/IMEI + cal RF) إلى `/etc/NVM/` داخل النظر الجديد **دائماً**.
- غيّر MAC الـ eth/wlan خارج الـ OUI الأصلي لتجنّب تصادم (regenerate addresses).
- لا تعيد كتابة `dropbear_password` الأصلي؛ استبدله بمفتاح SSH عام.

## المستوى 5 — صياغة الـ commit (cover letter مقترح للقائمة openwrt-devel)
```
[PATCH v1 0/2] target: add support for Ooredoo R291 v2 (ASR1802S / KAGU)
[PATCH v1 1/2] target/linux/asr1802s: new target for ASR1802S
[PATCH v1 2/2] target/linux/asr1802s: add Ooredoo R291 v2 device

SoC: ASR1802S (ARMv7/Cortex-A9), 128MB RAM, SPI-NAND dual-bank,
RTL8812FE x2 (PCIe), YT9215 eth, MAXLINEAR SLIC VoIP.
Tested-by: boot log on live unit (kernel 3.10.33 → see Porting/01-boot.txt).
NV UNHandled: ASR1802S has no mainline kernel support — prerequisite
patch series to linux-arm-kernel should precede this.
```
انظر `UPSTREAM_SUBMIT_CHECKLIST.md` للمتطلبات الكاملة.
