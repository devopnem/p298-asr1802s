# دراسة البوتلودر — Ooredoo R291 V2 (ASR1802S / KAGU)

> تاريخ النسخ: 2026-08-06 | المصدر: الجهاز الحي 192.168.1.1 (root SSH)
> النسخ الاحتياطية الخام: `bootloader_analysis/dumps/` (كل الـ 25 partition)
> قائمة التحقق: `bootloader_analysis/MANIFEST.sha256`

---

## 1) ماذا أخذنا؟ — النسخ الاحتياطي الكامل

| mtd | الاسم | الحجم | الحالة |
|-----|-------|-------|--------|
| mtd0 | **bootloader (OBM)** | 256KB | ✅ جديد — كان مفقوداً |
| mtd11 | **u-boot-a** | 768KB | ✅ جديد — كان مفقوداً |
| mtd12 | **u-boot-b** (مطابق تماماً لـ a) | 768KB | ✅ جديد — كان مفقوداً |
| mtd20 | **rsa** (مفاتيح الإقلاع الآمن) | 256KB | ✅ جديد — كان مفقوداً |
| mtd21 | **bootargs** (بيئة U-Boot + dropbear_password) | 256KB | ✅ جديد |
| mtd24 | **MRVL_BBM** (جدول الكتل التالفة) | 6.6MB | ✅ جديد |
| mtd5/6 | mep-ota | — | ⚠️ فارغة (0 بايت — ممسوحة في المصنع) |
| mtd1-4, 7-10, 13-19, 22-23 | البقية | — | ✅ مكتملة |

**نقاط مقارنة مهمة:**
- `u-boot-a` (mtd11) مطابق تماماً لـ `u-boot-b` (mtd12) — md5 = `ad86a848…`
- بيئة U-Boot (mtd21) محفوظة كاملة: `bootcmd=mrvlboot`, `bootdelay=1`, `dropbear_password=85719364` (كلمة المرور الحالية!), `baudrate=115200`
- كلمة مرور SSH الجديدة `85719364` **مشتقة من بيئة U-Boot نفسها** (متغير `dropbear_password`) — أي أن مالك الجهاز السابق عدّلها عبر `fw_setenv`

---

## 2) تسلسل الإقلاع الكامل (مؤكد من تحليل الثنائيات)

```
ROM داخل الـ SoC
   │
   ▼
mtd0  OBM — "One Boot Manager" (Marvell، SWDownloader 4.9.0.5 / OBM 4.9.0.0، 2024-04-11)
   │     • يقرأ DTIM (mtd7/8) ويتحقق من توقيعه RSA
   │     • يتحقق من أزواج A/B (DTIM A / DTIM B) مع حساب rollback
   │     • يفك LZMA ويحمّل OSLO (محمّل نظام التشغيل) ثم U-Boot
   ▼
mtd11/12  U-Boot 2014.01-g5f745ec (Apr 11 2024) — لوحة "ASR KAGU EVB P298"، الـ prompt: "Marvell>> "
   │     • أمر خاص: mrvlboot (يبني bootargs من الـ env + system=a/b)
   │     • يتحقق من SHA-256 لكل صورة مقابل الجدول في DTIM
   │     • منطق A/B: reboot_cnt + temp_active_slot (روجباك تلقائي)
   ▼
mtd13/14  kernel-a/b — zImage خام ARM + DTB مرفق في نهايته (لا uImage!)
   ▼
mtd15/16  rootfs-a/b — squashfs (OpenWrt Barrier Breaker 14.07 / kernel 3.10.33)
```

**بنية DTIM (mtd7/8) — اكتشاف مهم:** ليست "مكان وضع DTB" كما ظننا سابقاً!
- mtd7 يبدأ بـ `00 04 03 00 "TIMH"` — إنها **جداول TIM** (Table of Image Map) بصيغة Marvell
- تحتوي على 6 إدخالات: ARBI (CP/Arbel)، RFBI (RF)، OSLO (محمّل)، **ZIMG (kernel)**، **SYSJ (rootfs)**، OEMD — كل إدخال فيه **SHA-256 hash** للصورة (32 بايت) + عنوان فلاش + حجم
- يوجد جدول ثانٍ عند 0x20000 يحوي إدخال ENCK (مفتاح التشفير)
- الـ DTB الحقيقي **مرفق داخل zImage** نفسه (وجدنا FDT magic داخل kernel-a.bin بعد نهاية الضغط) — وليس في mtd7

**التحقق من الـ hash — تحذير مصيري لخطة التفليش:**
- `strings` في U-Boot تُظهر: `Kernel Hash mismatch`، `Rootfs Hash mismatch`،
  `PASS: Kernel verify.`، `System %s validation failed, try the other one...`
- `FATAL Error, two systems were illegal` = كلا slot يرفض الصورة → توقف كامل
- **النظام الحالي (المصنع) يقلع لأن صوره مطابقة لـ hash في DTIM**
- أي تفليش صورة مخصصة في kernel-a/rootfs-a **دون تحديث DTIM** → رفض الصورة → سيتحول تلقائياً للـ slot الآخر (fallback آمن، لكن صورتنا لن تُقلع أبداً)
- ⚠️ **لا تكتب DTB خام في mtd7/8** (كما اقترح flashing_guide.md سابقاً) — ستدمر جداول TIM والتحقق من التوقيع وسيرفض OBM الإقلاع
- الحل الصحيح: إعادة بناء TIM في mtd7 بهاشات الصور الجديدة (يحتاج فك تجميع mrvlboot لمعرفة معادلة الـ hash بالضبط — لم تطابق SHA-256 المباشر للمقطع كاملاً في تجاربنا) — **عمل مفتوح**

---

## 3) هل البوتلودر مفتوح المصدر أم مغلق؟

| الطبقة | الأساس | تعديلات المصنّع | المصدر منشور؟ |
|--------|--------|-----------------|---------------|
| OBM (mtd0) | احتكاري Marvell/ASR | كامل | ❌ لا |
| U-Boot (mtd11) | U-Boot 2014.01 (رخصة GPL-2.0) | fork كبير: mrvlboot، TIM/DTIM، A/B، شحن، MMC | ❌ لا |

**الخلاصة: مغلق عملياً.** القاعدة النواة (U-Boot) مفتوحة المصدر بحكم رخصة GPL، لكن
تعديلات ASR/Marvell للـ ASR1802S لم تُنشر في أي مكان — لا يمكن إعادة بناء نفس البوتلودر
من المصدر. بالإضافة لذلك يوجد **إقلاع آمن RSA** في OBM:
- OBM يتحقق من توقيع DTIM (`Verify DTIM Signature Failed`)
- مفاتيح RSA في mtd20 (توقيع "FRSAN" — ~118KB بيانات مفاتيح)
- لكن يوجد مسارا تجاوز في الكود: `skip any sign version`، `RSAN image skip rsa`،
  وأنماط `upgrade_mode` (RSA/UNRSA) — أي أن الفحص مشروط بحالة صورة/إنتاج

## 4) هل يوجد تحديث للبوتلودر عبر الإنترنت؟

**لا.** لا يملك U-Boot ولا OBM أي آلية تحديث ذاتي أو اتصال بالشبكة:
- لا يوجد سطر أوامر TFTP/HTTP في U-Boot إطلاقاً (انظر البند 6)
- تحديث الـ firmware في النظام نفسه عبر daemon OTA لكنه **معطّل** في المصنع
  (`# start_instance 0 "ota"` معلّقة في services.init، و`ota/query` يرجع "failed")
- التحديث الوحيد للبوتلودر = تفليش يدوي (كما تفعل أداة المجتمع: ترفع uboot.bin مخصص)

## 5) هل يمكن استبداله ببوتلودر مفتوح المصدر؟

**نظرياً نعم، عملياً مشروع كبير ومحفوف بالمخاطر:**
1. لا يوجد دعم لـ ASR1802S في U-Boot الرسمي — يتطلب porting كامل (تهيئة DDR، ساعات، SPI-NAND، إقلاع CP/modem، منطق A/B وDTIM)
2. يجب تجاوز تحقق OBM من RSA (مسارات `skip` موجودة لكن غير موثقة)
3. يجب إعادة كتابة كل من mtd0 وmtd11 معاً
4. إن فشل البوتلودر الجديد في إقلاع = جهاز ميت إلا عبر UART أو USB download أو NAND clip

**التوصية: لا تستبدله.** البوتلودر الحالي متوافق تماماً مع نواة OpenWrt 6.12 التي
بنيناها (bootz لـ zImage خام + DTB مرفق). الأسهل: إعادة بناء DTIM بالهاشات الصحيحة
عندما نكمل هندسة mrvlboot.

---

## 6) TFTP — مستحيل على هذا البوتلودر (اكتشاف محوري)

**النتيجة بعد فحص كامل للثنائي (2497 سلسلة نصية): صفر أوامر شبكة.**
لا `tftpboot`، لا `dhcp`، لا `bootp`، لا `ping`، لا `mii`/PHY، لا `ethaddr`، لا `serverip/ipaddr` —
لا توجد واجهة إيثرنت في U-Boot إطلاقاً.

**هذا يفسر فشل كل محاولات TFTP السابقة** — ولماذا يقول فديو أداة التفليش:
"FLASHING BOOTLOADER... Done" ثم "Enabling TFTP Flashing... Done":
الأداة كانت **تستبدل البوتلودر أولاً** بـ uboot.bin مخصص (312KB، hash `707b4f4c…`)
يحوي دعم TFTP، ثم تضبط `bootcmd=tftp` و`serverip` و`ipaddr`.

**ما الذي يملكه U-Boot فعلاً (للتفليش من قشرته عبر UART):**
```
spi_flash read/write/erase   ← القراءة والكتابة على SPI-NAND
bootz / bootm / go           ← إقلاع صور
crc32, md/mw/mm              ← ذاكرة
setenv / printenv / saveenv  ← بيئة
ubi / ubifs mount,ls,load    ← UBI
mmc, usb, gpio, echo, sleep, reset, watchdog
```

**بديل TFTP للتفليش بدون UART (المسار العملي):**
نملك root SSH على النظام الحي + `mtderase` (موثق في flashing_guide.md) —
الكتابة المباشرة على mtd13/mtd15 مع إعادة بناء DTIM بالهاشات الصحيحة.

---

## 7) Failsafe — ⚠️ يعمل عبر الكونسول UART فقط (استنتاج مصحح)

Failsafe ليست خاصية بوتلودر بل خاصية OpenWrt داخل `preinit` (نفس النظام المصنعي،
ملفات `lib/preinit/*` موجودة على الجهاز الحي). الآلية (من `/etc/preinit` + `lib/preinit/30_failsafe_wait`):

```
fs_failsafe_wait_timeout = قيمة "failsafe_wait" من /proc/cmdline
   └─ إن غابت أو = 0  →  failsafe معطّل تماماً (الوضع الافتراضي في المصنع!)
   └─ إن كانت > 0     →
        1) إن وُجدت "failsafe=" في cmdline  →  دخول فوري (بدون أي ضغطة مفتاح)
        2) أو ضغط المفتاح "f" على الكونسول خلال النافذة
   عند الدخول: قشرة ash root على الكونسول UART + telnetd -l /bin/login.sh (قشرة root)
```

**التصحيح المهم (بعد قراءة /etc/preinit كاملاً):** `pi_ifname=` و `fs_failsafe_ifname=`
فارغان في هذا الإصدار → preinit لا يعطي أي عنوان IP لأي واجهة إيثرنت → telnetd
الذي يشغّله `99_10_failsafe_login` **لا يمكن الوصول إليه من الشبكة**. الفائدة العملية
لـ failsafe هنا = **قشرة UART** فقط، وليست بوابة دخول LAN بدون أسلاك.

**طريق الدخول الواقعي بدون UART:** تفليش/إصلاح مباشر عبر SSH أثناء حيوية النظام،
أو تركيب "طوق نجاة" مسبق في `/overlay/etc/init.d/` يفتح dropbear/telnet على LAN
عند متغير بيئة (مثل `rescue=1`) — يُكتب بينما النظام يعمل، ويُستعمل لاحقاً
إذا تعطل النظام جزئياً. (عند تفليش صورة OpenWrt المخصصة لدينا، ستحترم تلك الصورة
preinit الرسمي الذي يهيّئ LAN بشكل صحيح — نصوصه قياسية.)

**التوضيح المهم**: زر reset لا يدخل failsafe (سكربت rc.button/failsafe يكتب
`/tmp/failsafe_button` والكود يتجاهله — مجرد سجل). الطريق الوحيد بلا UART هو
**حقن `failsafe_wait` + `failsafe` في bootargs عبر fw_setenv** (دليل كامل في
`TFTP_AND_FAILSAFE.md`).

---

## 8) بيانات التشغيل المرجعية (مؤكدة)

| العنصر | القيمة |
|--------|--------|
| UART console | ttyS0 @ **115200** 8N1 (baudrate=115200 في الـ env) |
| نافذة مقاطعة U-Boot | bootdelay=**1** ثانية (قابلة للزيادة عبر fw_setenv) |
| بيئة U-Boot | mtd21 @ offset 0x0، الحجم 0x8000، erasesize 0x20000 (`/etc/fw_env.config`) |
| أدوات البيئة | `/usr/sbin/fw_printenv` + `fw_setenv` (موجودان على الجهاز!) |
| hash صور DTIM | SHA-256 في mtd7/8 (ZIMG=kernel، SYSJ=rootfs، ARBI=CP…) |
| إقلاع المصنع الحالي | system=a، root=/dev/mtdblock15، PROD=0 (غير إنتاجي → OBM يقبل تحميل USB) |

## 9) مخرجات الحفظ في مجلد العمل

```
bootloader_analysis/
├── dumps/            ← 23 ملف .bin (كل partitions الراوتر الحي) + MANIFEST.sha256
├── MANIFEST.sha256   ← التحقق من سلامة النسخ
├── REPORT.md         ← هذه الدراسة
└── TFTP_AND_FAILSAFE.md ← دليل فتح TFTP/failsafe خطوة بخطوة
```
