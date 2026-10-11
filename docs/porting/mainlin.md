# رفع دعم SoC ASR1802S إلى نواة Linux الرسمية (mainlining)

> ملخص العمل المُنجز حتى الآن + المسار الكامل لإرسال الرقع رسمياً
> إلى نواة Linux (قوائم: linux-clk, devicetree, linux-arm-kernel).

---

## 1) الجهاز والـ SoC

- **الراوتر:** Ooredoo P298 v2 — SoC **ASR1802S** (شركة ASR Microelectronics، انبثقت من Marvell)، نواة **ARM Cortex-A7**، لوحة **KAGU / ASR1826s**.
- **Stock firmware:** OpenWrt Barrier Breaker 14.07 على kernel 3.10.33 — أي أن المصنّع نفسه يوزّع OpenWrt، وهذا يسهّل إقناع مشرفي النواة بأن المنصة مناسبة للمجتمع.
- **الذاكرة:** SPI-NAND 128MB، 25 partition (ترتيب A/B مزدوج) عبر `nand0`.
- **القرابة المعمارية:** عائلة Marvell/Armada (link base `0xC0008000`، سجلات FCCR/DDR/AXI مشابهة للعائلات الموجودة أصلاً في النواة).

---

## 2) ما أُنجز حتى الآن (شجرة kernel 6.12.94)

شجرة العمل: `/home/void/ow_kernel/linux-6.12.94/`

| الملف | المحتوى |
|---|---|
| `drivers/clk/clk-asr1802s.c` | مُعرّف ساعة ASR1802S مبني داخل النواة (`CONFIG_COMMON_CLK_ASR1802S=y`)، الرمز `asr1802s_clk_probe` مُحقَّق في `vmlinux` |
| `include/dt-bindings/clock/marvell,asr1802s.h` | تعريفات أرقام الساعات للـ DTS |
| `Documentation/devicetree/bindings/clock/marvell,asr1802s.yaml` | ربط DT (dt-binding) بصيغة YAML |
| `arch/arm/boot/dts/asr/asr1826s.dtsi` + `asr1826s-p298.dts` | وصف لوحة KAGU (clocks, serial, ethernet, SPI-NAND) |
| `arch/arm/boot/dts/asr/Makefile` | بناء `asr1826s-p298.dtb` |

### المعرفة المُستخرجة عن الساعات (من الجهاز الحي عبر SSH):

| الإزاحة (من `0xC0008000`) | الوظيفة |
|---|---|
| `+0xa0` | سجل busy/إرسال الأوامر |
| `+0xb0` | مقسم DDR + GO (bit24) |
| `+0x110` | CPU FCCR: s[0:2], l2div[3:5], pddiv[6:8], baclk[9:11], GO bit12 |
| `+0x144` | AXI: sel bit0, div[1:3], GO bit4 |
| `+0x15c` | DDR table index |
| `+0x400` | DDR OPP |

**باقٍ للبحث:** مقسّمات UART/SPI/EMAC وقفل PLL — تحتاج قراءة سجلات إضافية من الجهاز الحي.

---

## 3) كيف نرسل الرقع إلى النواة الرسمية

### الخطوة 0 — تقسيم الرقع (patch series) بالترتيب الإلزامي
1. **dt-bindings أولاً** — ملف YAML + header (مراجعو DT: Rob Herring / Krzysztof Kozlowski / Conor Dooley).
2. **الدرايفر** — `clk-asr1802s.c` (مشرفو الـ clk: Michael Turquette / Stephen Boyd).
3. **ملفات DTS** — `.dtsi`/`.dts` + `Makefile` (قائمة linux-arm-kernel + مشرفو قسم ARM).

أرسلها كسلسلة مع `--cover-letter`.

### الخطوة 1 — الفحوصات الإجبارية قبل الإرسال
```bash
./scripts/checkpatch.pl --strict *.patch

make dt_binding_check DT_SCHEMA_FILES=marvell,asr1802s.yaml
make dtbs_check DT_SCHEMA_FILES=marvell,asr1802s.yaml

# بناء نظيف لمنصة ARM
make ARCH=arm multi_v7_defconfig
make ARCH=arm -j$(nproc)

# تدقيق sparse
make ARCH=arm C=1 W=1 drivers/clk/clk-asr1802s.o
```

### الخطوة 2 — git والتوقيع (Signed-off-by — إلزامي)
```bash
git config user.name  "Your Full Name"
git config user.email "you@example.com"
# كل commit ينتهي بـ:
# Signed-off-by: Your Full Name <you@example.com>
```

### الخطوة 3 — الإرسال عبر git-email
```bash
git format-patch -v1 origin/master..HEAD --cover-letter
git send-email --to linux-clk@vger.kernel.org \
               --to devicetree@vger.kernel.org \
               --cc linux-arm-kernel@lists.infradead.org \
               --cc linux-kernel@vger.kernel.org \
               --cc mturquette@baylibre.com \
               --cc sboyd@kernel.org \
               --cc robh+dt@kernel.org \
               --cc krzk+dt@kernel.org \
               --cc conor+dt@kernel.org \
               v1/*.patch
```

> التوصية: ابدأ بإرسال `[RFC PATCH 0/3] clk: add support for ASR1802S SoC clock controller`،
> ثم عالج تعليقات المراجعين، وأرسل v1 ثم v2...

### الخطوة 4 — استراتيجية النجاح
- **ابدأ بالأصغر الأكثر قيمة:** driver + bindings + DTS للوحة واحدة في أول سلسلة.
- **قدّم الأدلة:** سجلات قراءة/كتابة حقيقية من الجهاز + نجاح إقلاع فعلي على اللوحة.
- **عالج كل تعليق** ولا تغفل طلبات `Reviewed-by`.
- **نقطة قوة مقنعة:** هذا الـ SoC يحمل OpenWrt على جهاز عائلي منتشر — اذكرها في رسالة الغلاف (يُظهر فائدة ملموسة للنواة).
- **المرجع البعيد:** ادفع نسخة RFC إلى `git@github.com:devopnem/linux-asr1802s-rfc.git` للتاريخ والمراجعة العلنية.

### الخطوة 5 — تذكيرات مهمة
- أضف سطر `F: drivers/clk/clk-asr1802s.c` في قسم MAINTAINERS ضمن نفس السلسلة.
- لا تُرسل للقوائم العامة فقط — المشرفون المتخصصون هم من يقبلون/يرفضون.
- تقبّل أن أول RFC قد يُرفض جزئياً — هذا طبيعي؛ الاستجابة الجيدة للمراجعات هي ما يُقنع المشرفين.

---

## 4) العمل المتبقي قبل الإرسال

1. إكمال التوثيق: مقسّمات UART/SPI/EMAC + قفل PLL.
2. اختبار `clk_dump`/التعطيل-والتشغيل على الجهاز الحي بعد إقلاع صورتنا الجديدة.
3. بناء كامل لـ `multi_v7_defconfig` وتشغيله على الجهاز (يُثبت أن المنصة تنجز إقلاعاً كاملاً).
4. إضافة MAINTAINERS.
5. المراجعة الذاتية بـ checkpatch + dt_binding_check حتى صفر أخطاء.
