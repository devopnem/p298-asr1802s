# Porting Ooredoo R291 v2 to mainline Linux + OpenWrt

Status: **RFC / bootstrap.** Everything below is grounded in runtime extraction
from a **shipping unit** (root shell via paramiko + U‑Boot env + bit‑exact
`rootfs-a.bin`/`kernel-a.bin` backups), not from the vendor source tree.

## المهم أولاً — الحالة الحقيقية (verified)
| البند | القيمة | المصدر |
|---|---|---|
| SoC | ASR ASR1802S — ARMv7‑Cortex‑A9 (0xc07)، 1 core | `/proc/cpuinfo`, `kernel-a.bin` strings |
| DT compatible | `asr,1802s-evb` ، `asr,1802s` | `/proc/device-tree/compatible` |
| رأس الصفحة | `ASR 1826s(KAGU) Board EVB` | `/proc/device-tree/model` |
| RAM | 128 MB (32 MB CP carve‑out @0x06000000) | bootargs |
| Flash | SPI‑NAND F35UQA001G 128 MB، 25 bank A/B+UBI | dmesg + /proc/mtd |
| UART | ttyS0 115200n8 → pxa2xx‑uart @ d4017000 irq 59 | /proc/iomem + dmesg |
| WiFi | RTL8812FE ×2 PCIe gen1x1 → rtl8192cd.ko (3 MB binary‑only) | dmesg; **binary لا يعمل على kernel جديد** |
| Eth | ASR MAC @ d4281800 irq 42/43 + YT9215 switch | dmesg + iomem |
| VoIP | MAX1919/SLIC (GPIO23/24) | dmesg |
| USB3 | DWC3 irq 76 + USB3 PHY @ c0030000 | dmesg + iomem |
| MMC | mmc0 @ d4280000 irq 71 | dmesg + iomem |
| PMIC | 88PM802 I2C@0x30 (i2c@d4037000 irq 12089) | dmesg |
| U‑Boot | bootcmd=`mrvlboot`، bootdelay=1، verify=no، loadaddr=0x8000 | mtd21 env |
| dropbear_password | 19222019 (U‑Boot env) | mtd21 env |
| OpenWrt | BB 14.07 r47068 mmp/asr1826s fork؛ /bin/opkg موجود | /etc/openwrt_release |

## لماذا «ليس مدعوماً»؟
- **ASR1802S غير موجود في kernel.org** — كل الـ drivers على الـ kernel 3.10 vendor fork (clock/reset/pinctrl/irq/SPI‑NAND/PCIe/eth/USB) مُضمّنة بالـ binary kernel وليست .ko.
- **`rtl8192cd` binary‑only** → لا ينقل للـ >=5.13؛ البديل `rtw88` (يدعم 8812FE).

## المسار إلى الـ upstream (phases)
- **Phase A — proof (هذا المستودع):** DTS binding + skeleton DTS + RFC cover letter ← **ملفّات جاهزة الآن**.
- **Phase B — SoC port to linux:** أرسل minimal SoC skeleton (clock/reset/pinctrl/irq/timer) إلى `linux-arm@`. **مطلوب:** مصدر kernel 3.4.x/3.10 vendor OR register‑by‑register reverse; دعم الـ community.
- **Phase C — board DTS + peripherhals:** أضف full board DTS (`asr1826s-kagu`) + WiFi rtw88 + YT9215 DSA + SLIC + USB + MMC.
- **Phase D — OpenWrt:** أعد إنشاء target `asr1826s`/`asr1802s` في `target/linux/` (Makefile.skeleton مرفق).

## كيف تجريب (بلا فلاش NAND)
1. UART على `pxa2xx-uart`؛ سجل boot log.
2. بناء initramfs.itb armv7a‑cortex‑a9 و`tftpboot 0x8000 …; bootm` — proof إن الـ SoC يوثّق.

> ملاحظة أمان: لم نلمس MTD/Flash؛ كل التحقق read‑only مع `ooredoo_backup/` كاسترداد احتياطي.
