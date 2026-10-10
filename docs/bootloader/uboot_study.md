# دراسة: إمكانية عمل نسخة U-Boot مخصصة لـ R291 (ASR1802S / KAGU P298)

> التاريخ: 2026-08-13 | الجهاز: Ooredoo R291 V2 (Notion R291, HW: P298_N13)
> SoC: ASR Microelectronics ASR1802S (ARM Cortex-A7 — سليل Marvell PXA1826/MMP)
> المراجع: `REPORT.md`، `../ops/confirmed.md`، `../porting/mainlin.md`، RFC series: devopnem/linux-asr1802s-rfc

---

## 1) الخلاصة التنفيذية

**الحكم: بناء u-boot مخصص للجهاز ممكن عملياً، وليس مستحيلاً، لكنه مشروع على 3 مراحل
وكل مرحلة تنتهي بمنتج قابل للاستخدام بحد ذاته:**

| المرحلة | المنتج | الجهد | الخطورة |
|---|---|---|---|
| A | لا u-boot مخصص — إعادة بناء DTIM (mtd7/8) بهاشات صورنا | قليل | منخفضة |
| B | u-boot مخصص على أساس ثنائي مجتمعي معروف العمل (TFTP) | متوسط | منخفضة |
| C | u-boot مخصص من الصفر على u-boot حديث (تحكم كامل) | كبير | متوسطة (أمانها USB download) |

المحاور التي تجعل الأمر مجدياً:
1. **أدوات المجتمع تفلش u-boot مخصصاً على نفس العائلة بنجاح** — أي OBM يقبل استبدال الـ u-boot.
2. **OBM يهيّئ DDR والـ NAND قبل تحميل الـ u-boot** — u-boot مخصص لا يحتاج أكثر
   المهام صعوبة (تهيئة ذاكرة من الصفر).
3. **الجهاز عندنا PROD=0** → وضع USB download عبر Marvell SWDownloader مفعّل =
   شبكة أمان لإحياء جهاز حتى لو تعطل u-boot كلياً.
4. **مرجع بناء حي في upstream u-boot**: `arch/arm/mach-mmp` (لوحة Samsung coreprimevelte
   لـ PXA1908، أضيفت 2024 من مجتمع postmarketOS) — نفس عائلة السجلات.

المحاور التي تمنع "إعادة بناء نسخة المطابق للمصنع":
- مصدر ASR/Marvell للـ u-boot **غير منشور إطلاقاً** (الكوميت `g5f745ec` غير موجود في أي
  مستودع عام، ولا دعم PXA1826 في `MarvellEmbeddedProcessors/u-boot-marvell`).
- OBM (mtd0) احتكاري بالكامل، وله تحقق RSA في مساره (`check_notion_rsa`).
- سلسلة فحص SHA-256 في mrvlboot ضد جداول DTIM (mtd7/8) — لن يُفلت منها إلا بتعديل
  الـ u-boot نفسه أو بإعادة بناء الجداول.

---

## 2) سلسلة الإقلاع الموثقة (من تحليل الثنائيات)

```
ROM داخل الـ SoC
   │
   ▼
mtd0  OBM — "One Boot Manager" (SWDownloader 4.9.0.5 / OBM 4.9.0.0, 2024-04-11)
   │   • يهيّئ SPI-NAND و DDR (سلاسل: DDR Vendor: Samsung/Qimonda/Elpida/…,
   │     DDR size not right, ddr_size)   ← DDR جاهزة قبل u-boot
   │   • يتحقق من توقيع DTIM (RSA، مفاتيح في mtd20) + مسارات تجاوز:
   │     "skip any sign version", "RSAN image skip rsa", upgrade_mode RSA/UNRSA
   │   • منطق A/B للـ u-boot نفسه: "Uboot A" / "Uboot B" / "Load UBOOT at" /
   │     "rollback to …" (على أساس reboot_cnt)
   │   • وضع USB download مفعّل في غير الإنتاج: "[Non-Prod]Wait for download…"
   ▼
mtd11/12  U-Boot 2014.01-g5f745ec (Apr 11 2024) — "ASR KAGU EVB P298", prompt "Marvell>>"
   │   • رأس صورة: magic 0x12345678 @0x3c، Load Address 0x30008000 @0x40،
   │     أطوال @0x48-0x4c (≈445KB/482KB)، ثم 0x0BADC0DE
   │   • TEXT_BASE = 0x30008000 (مصادف مباشرة بعد OBM على RAM جاهزة)
   │   • لا أي كود شبكة (0 TFTP/DHCP — مثبت بفحص 2497 سلسلة)
   │   • أوامر متاحة: spi_flash r/w/erase، bootz/bootm/go، crc32، md/mw/mm،
   │     setenv/printenv/saveenv، ubi/ubifs، mmc، usb، gpio، watchdog
   │   • أمر خاص mrvlboot: يبني bootargs من env + system=a/b،
   │     يتحقق SHA-256 لكل صورة مقابل DTIM (ZIMG=kernel, SYSJ=rootfs…)
   ▼
mtd13/14  kernel-a/b — zImage خام ARM + DTB مرفق (لا uImage!)
   ▼
mtd15/16  rootfs-a/b — squashfs (OpenWrt Barrier Breaker 14.07 / kernel 3.10.33)
```

**رأس mtd11 (u-boot) مفكوك:**
```
+0x00  EA000013 …   → الفرع إلى بداية الكود الحقيقي (بعد الرأس)
+0x04..0x1C  LDR PC, [PC,#0xF14] ×7  (متجهات استثناء ARMv7 قياسية)
+0x20..0x2C  عناوين المعالجات → 0x30008160 … 0x300083A0  (TEXT_BASE=0x30008000)
+0x3C  78 56 34 12  = 0x12345678  (magic الرأس)
+0x40  00 80 30 00  = 0x30008000  (عنوان التحميل)
+0x44  98 CA 06 00  = 0x0006CA98  (طول 1)
+0x48  30 5F 07 00  = 0x00075F30  (طول 2)
+0x4C  B8 51 07 00  = 0x000751B8  (طول 3)
+0x50  DE C0 AD 0B  = 0x0BADC0DE  (magic ثانٍ)
```
المعنى العملي: الصورة تُحمَّل **خام** على 0x30008000 ثم يُقفز إليها — لا يوجد LZMA فوق
الـ u-boot، ولا تغليف TIM في mtd11 نفسه (جداول TIM في mtd7/8 منفصلة).

---

## 3) اكتشافات البحث الجديد (خارج تقارير البوتلودر السابقة)

| # | الاكتشاف | الدليل | الأثر |
|---|---|---|---|
| 1 | **مصدر ASR/Marvell مغلق نهائياً** | الكوميت `5f745ec` غير موجود في upstream (GitHub API 422)؛ `MarvellEmbeddedProcessors/u-boot-marvell` (فروع 2013.01→2020.10) كلها Armada/mvebu بلا أي MMP/88AP | استحالة إعادة بناء نسخة مطابقة من المصدر |
| 2 | **OBM يهيّئ DDR** | سلاسل `DDR Mode/Vendor/Size`، `DDR size not right` في mtd0.bin | u-boot مخصص لا يحتاج DDR init |
| 3 | **رأس mtd11 يحدد عنوان التحميل** | 0x12345678 + 0x30008000 + أطوال | أي u-boot مخصص يجب أن يُربط عند 0x30008000 بهذا الرأس (أو ما يثبته التجريب) |
| 4 | **مرجع mach-mmp في upstream الحالي** | `arch/arm/mach-mmp/board.c` لـ PXA1908 (Samsung coreprimevelte، 2024): timer عبر APBC 0xd4015064/COUNTER 0xd4101000 | نفس منطقة سجلات R291 (ttyS0 @0xd4017000، pxa910-squ) — قاعدة انطلاق قابلة للنسخ |
| 5 | **دليل ميداني على قبول OBM لـ u-boot خارجي** | أدوات المجتمع تفلش `uboot.bin` (312KB، md5 707b4f4c…) مع TFTP وقلع ناجح (REPORT.md بند 6) | استبدال الـ u-boot ممهد وموثق سلوكياً |
| 6 | **USB download كشبكة أمان** | `[Non-Prod]Wait for download…`، `bootMode=`، PROD=0 عندنا | حتى تعطل mtd0/mtd11 كلياً يُستعاد عبر Marvell SWDownloader (.blf) أو NAND clip |
| 7 | **u-boot الحالي بلا شبكة** | فحص سلاسل كامل: صفر أوامر TFTP/eth | TFTP = ميزة u-boot المخصص الأول (كما فعل المجتمع) |
| 8 | **التحقق من الـ uboot في OBM غير محسوم** | سلاسل `check_notion_rsa success/failed`، `Uboot in TIM`، `Uboot validation error(or DTIM load failed)` | يجب تأكيده: بتفكيك mtd0.bin أو بتجربة آمنة (القسم 6) |

---

## 4) لماذا لا يمكن إعادة بناء u-boot المصنع من المصدر

1. `U-Boot 2014.01-g5f745ec`: الكوميت `g5f745ec` **غير موجود** في upstream u-boot
   (تحقق GitHub API: 422). أي أنه كوميت خاص بمارفيل/ASR لم يُنشر.
2. Marvell's public forks (`u-boot-marvell`): كل الفروع (2013.01-15t1 → 2020.10)
   تغطي عائلات Armada فقط (mvca9/pj4/armada-38x…). لا يوجد `mmp`/`88AP`/`PXA1826`.
3. القاعدة المفتوحة الوحيدة المتطابقة: **upstream u-boot v2014.01** (عام، بدون بكس
   مارفيل) — منها نأخذ البنية الأساسية فقط (start.S، لوحة الأوامر، bootz…)،
   وكل ما يخص ASR (mrvlboot، DTIM/TIM، A/B، QSPI `asr_qspi.c`، PMIC 88PM80x، شحن)
   موجود **في الثنائي فقط**.
4. طبقة OBM (mtd0) نفسها احتكارية — لسنا مطالبين بإعادة بنائها (تبقى كما هي
   وتحمّل u-boot الخاص بنا)، وهذا هو الخيط الذي تجرّه أدوات المجتمع.

**الخلاصة: لا نعيد بناء "نسخة المصنع"؛ نبني نسخة موازية تُرضي OBM وتخدم أهدافنا.**

---

## 5) المسارات المقترحة (مقارنة مفصلة)

### المسار A — إعادة بناء DTIM (بدون أي u-boot مخصص)
> **الأولوية القصوى — يرفع أول عائق تفليش أمامنا.**

- المشكلة: mrvlboot يرفض kernel/rootfs غير المطابقة لـ SHA-256 في DTIM (mtd7/8)
  → صور OpenWrt لدينا تُرفض ("Kernel Hash mismatch") والجهاز يقلع من slot آخر.
- العمل: هندسة عكسية لدالة الـ hash في mrvlboot (الـ hash لا يطابق SHA-256 المباشر
  للمقطع كاملاً — ربما يستثني DTB المرفق/الرأس/قناع). ثم إعادة بناء mtd7 بهاشات
  صورنا + تحديث الحجم/العنوان.
- الأدوات: Ghidra/radare2 على mtd11.bin، أو تجريب مضبوط على mtd7 النسخة b.
- النتيجة: تفليش OpenWrt من المصنع دون لمس أي بوتلودر. آمن تماماً (لا نكتب mtd0/11).
- مرجع: REPORT.md بند 2 (الحل الصحيح) + `flashing_guide.md`.

### المسار B — u-boot مخصص على أساس ثنائي مجتمعي (TFTP + إزالة الفحص)
- ماذا يوجد: `uboot.bin` (312KB، md5 `707b4f4c5f2cee77affcbd7d0cc731ec`) يُفلشه
  `flash.bat` لأدوات الفتح (r291-tunisia-unlock.exe…)، و`uboot.img` (132KB،
  ببانات U-Boot 1.1.3) بنسخة أقدم/أصغر.
- إجراءات:
  1. الحصول على الثنائيات (من أدوات المجتمع/تيليجرام/فيديوهات الفلاش).
  2. RE لها (نفس أساس 2014.01 تقريباً) → استخراج: درايفر الإيثرنت/PHY وتهيئة
     الـ switch Motorcomm YT9215RB، وكيف يلتف على فحص الـ hash، وشكل الرأس المقبول.
  3. تعديل ثنائي صغير (patch) أو إعادة تجميع على أساس Marvell 2014.01 + البكس
     المستخرجة → uboot بروح المجتمع لكن بتحكمنا.
- النتيجة: u-boot بـ TFTP (تفليش شبكي بلا UART أبداً) + إلغاء فحص DTIM.
- الخطورة: منخفضة إن اتبعنا خطة التجربة الآمنة (القسم 6) — الثنائي معروف العمل
  ميدانياً على نفس العائلة.

### المسار C — u-boot من الصفر على u-boot حديث (المشروع الكامل)
- القاعدة: upstream u-boot (النسخة عندك) + `arch/arm/mach-mmp` كمرجع هيكلي.
- المطلوب بناؤه (بحسب ما يوفره OBM مقابل ما يجب علينا):
  | المكوّن | الحالة | المصدر |
  |---|---|---|
  | إقلاع/تحميل من OBM | جاهز | OBM يحمّل على 0x30008000 (نحتاج تأكيد شكل الرأس) |
  | UART ttyS0 115200 | شبه جاهز | درايفر pxa في `drivers/serial/` (serial.c يذكره) + سجلات pxa2xx |
  | SPI-NAND (F35UQA001G) | جاهز | stack الـ SPI-NAND العام في u-boot الحديث (spi-mem + spinand) + `asr_qspi` RE للتحكم |
  | DDR | غير مطلوب | OBM يهيّئها (لكن نضيف حماية إعادة-تهيئة لاحقاً) |
  | PMIC 88PM80x | اختياري | OBM يضبط التغذية؛ درايفر PMIC مطلوب فقط لـ charger/shutdown |
  | TIM/DTIM + A/B + mrvlboot | **الأصعب** | RE كامل من mtd11.bin (الأولوية: منطق hash + system=a/b) |
  | إيثرنت (EMAC + YT9215RB) | RE مطلوب | لا وجود له في upstream لهذه العائلة؛ من ثنائيات المجتمع أو mtd11 |
  | إقلاع CP (المودم) | خارج النطاق غالباً | CP يُحمَّل من kernel (cpimage mtd9/10) وليس من u-boot |
- النتيجة: u-boot حديث بالكامل (بنسخة حديثة، تصحيح مرن، TFTP، حذف A/B أو تبسيطه).
- الخطورة: متوسطة — إن لم يقلع نستعيد بـ USB download أو نعيد كتابة mtd11 من backup
  عبر SWDownloader. كل خطوة تُختبر بـ UART.

### المسار D — إعادة بناء u-boot المصنع من المصدر
**مستحيل** (مصدر مغلق، القسم 4). لا يُدرج إلا للتوثيق.

---

## 6) خطة التجربة الآمنة (تأكيد قبول OBM لـ u-boot مخصص)

> الفرضية المراد اختبارها: **OBM لا يتحقق من محتوى mtd11 نفسها** (فحصه RSA على DTIM
> فقط) — بمعنى آخر، أي صورة u-boot بالرأس الصحيح تُقلع.
> إن ثبت العكس (رسالة تحقق/رجوع)، نعرف أن `check_notion_rsa` يشمل u-boot
> وندرس الالتفاف (upgrade_mode / نسخ المجتمع).

**التحضير (قبل أي كتابة):**
1. نسخ احتياطية مؤكدة (موجودة): `bootloader_analysis/dumps/mtd11.bin` (u-boot-a)،
   `mtd12.bin` (u-boot-b)، `mtd7/8` (DTIM)، `mtd21` (env) — تحقق بـ MANIFEST.sha256.
2. UART: USB-TTL على 115200 8N1 (تأكيد باود من env: `baudrate=115200`).
3. توسيع نافذة المقاطعة: `fw_setenv bootdelay 10` (مؤقت للتجارب).
4. كتابة كامل `fw_printenv` + صورة mtd21 خام في الأرشيف.

**التسلسل:**
1. **لا تكتب mtd0 أبداً** (OBM) ولا mtd20 (rsa).
2. جرب أولاً على **u-boot-b (mtd12) فقط**: اكتب صورة الاختبار إلى mtd12.
   - لا يزال u-boot-a سليماً؛ إن أصر OBM على u-boot-a نعرف أنه لم يلاحظ mtd12.
3. مراقبة UART: إن رأينا `Marvell>>` من صورتنا → نجحت. إن لم يقلع الجهاز:
   - فحص UART لمعرفة الخطأ، ثم إعادة كتابة mtd12 من backup عبر SSH إن كان النظام
     حياً (النظام يقلع من slot المستقل عن البوتلودر؟ — الانتباه: bootargs تختار
     kernel-a/b؛ النظام الحي الحالي يقلع من u-boot-a الافتراضي).
4. مسار الطوارئ (تعطل كل شيء): USB download عبر Marvell SWDownloader (PROD=0)
   → إعادة كتابة mtd11 من backup. الأسوأ: NAND clip.
5. بعد إثبات القبول: نستبدل u-boot-a أيضاً ونحتفظ بـ u-boot-b **منسوخة من backup**
   كطبقة رجوع ثانية (لا تُلمس إلا للضرورة).

**قواعد ذهبية:**
- كل تجربة على slot واحد + backup + خطة استعادة مكتوبة قبل التنفيذ.
- لا تجعل u-boot-b بديلاً لـ u-boot-a إلا بعد أسبوعين من الاستقرار.
- قبل كل كتابة على mtd: `cat /proc/mtd` للمطابقة الفعلية للأقسام.

---

## 7) Roadmap زمني مقترح

| المرحلة | العمل | التسليم | المدة التقديرية |
|---|---|---|---|
| 1 | المسار A: RE معادلة hash في mrvlboot + إعادة بناء DTIM | تفليش OpenWrt من المصنع | 1-2 أسبوع |
| 2 | الحصول على ثنائيات المجتمع (uboot.bin 312KB + uboot.img 132KB) + تفحصها | فهم مقبول من OBM + نسخ درايفر الإيثرنت | 2-4 أيام (انتظار المجتمع) |
| 3 | فك OBM حول `check_notion_rsa`/`Uboot in TIM` (Ghidra على mtd0.bin) | تأكيد تحقق OBM من الـ uboot عدمه | 3-5 أيام |
| 4 | التجربة الآمنة (القسم 6) بأول صورة اختبار | قبول/رفض OBM مثبت تجريبياً | 1 يوم (عند جاهزية 3) |
| 5 | المسار B: u-boot مخصص بـ TFTP (أو مسار C جزئي) | أداة تفليش شبكي بديلة | أسبوعان بعد 2-4 |
| 6 | المسار C: mach-mmp جديد `asr1826s` + UART + SPI-NAND على u-boot حديث | u-boot حديث يقلع حتى قشرة U-Boot | 3-6 أسابيع |
| 7 | إعادة بناء mrvlboot/DTIM/A-B في الـ u-boot الحديث | u-boot كامل الوظائف بتحكمنا | أسبوعان بعد 6 |

**ملاحظات توقيت:** مدة كل مرحلة تقديرية وتعتمد على سرعة الهندسة العكسية؛ المرحلة 1
لا تتطلب أي أداة عتاد إضافية، ويمكن تشغيل 2+3 بالتوازي.

---

## 8) بيئة العمل والحزم المطلوبة

- نظامك: Void Linux (musl) — لتجميع u-boot ARM نحتاج **cross toolchain**:
  - `cross-arm-none-eabi-binutils`
  - `cross-arm-none-eabi-gcc`
  - (إن رغبت بأداة مصحح/فك: `rizin`/`radare2` أو Ghidra عبر xbps — نطلبها عند الحاجة)
- مجلدات العمل:
  - مجلد الدراسة والوثائق: `/home/void/Downloads/Modems/Notion_R291_ASR1802S_P298_N13/`
  - قاعدة المصدر: شجرة u-boot الحالية `/home/void/Downloads/openwrt/u-boot`
    (ملاحظة: clone سطحي بكوميت واحد و`.config` لـ ath79 — سننشئ fork/فرع جديد `kagu-r291`
    أو clone كامل نحته للـ R291، ونربطه بمجلد العمل عبر symlink `u-boot` كما هو حاصل
    مع `openwrt-fork`).

---

## 9) ملفات العمل المفتوحة (حالة المعرفة)

| السؤال المفتوح | أين يُحسم | الأثر |
|---|---|---|
| هل OBM يفحص الـ u-boot نفسه؟ | تفكيك mtd0.bin + التجربة الآمنة | يحدد حرية تغيير mtd11 |
| معادلة الـ hash في mrvlboot بدقة | تفكيك mtd11.bin | يحدد إمكانية المسار A |
| درايفر الإيثرنت للـ YT9215RB/EMAC | ثنائيات المجتمع (B) أو mtd11 | يحدد صعوبة TFTP (B/C) |
| شكل رأس u-boot المقبول بالضبط (أطوال/حقول) | مقارنة mtd11 + uboot.bin المجتمعي | شرط الإقلاع لأي صورة |
| مصدر OSLO ("U-Boot 1.1.3" 132KB؟) | تفحص uboot.img + سلاسل OBM | فهم كامل لسلسلة OBM→u-boot |
| قيم TIM4/ENCK في mtd7@0x20000 | RE لجدول OBM الثاني | مفاتيح التشفير/الترقية |
