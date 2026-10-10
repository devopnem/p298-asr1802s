# ASR1802S Clock Controller — Reverse-Engineering Notes

التاريخ: 2026-08-03 — المصدر: `kernel-decomp.bin` (نواة البائع المفكوكة، link base **0xC0008000** المؤكد: literal @0x1ebf9c = 0xc03dfc28 → 0x3d7c28 = "CORE FCCR Write failure")

## الحقول المؤكدة من كود البائع (ثنائي Thumb-2)

### CPU FCCR @ `base + 0x110` (يقوده clk_cpu/clk_pclk)
| البتات | الحقل | الدلالة |
|--------|-------|---------|
| [0:2]  | sel   | اختيار PLL (قيمة مطبوعة "312:1,0" = sel=1) — RMW bfi (0x1eb8da)؛ get_parent يقرأ `& 7` (0x1eb8c0/0x1ec198) |
| [3:5]  | l2div | قاسم l2clk (+1) — bfi في cpu_set (0x1ec84e/0x1ec856) |
| [6:8]  | pddiv | قاسم pdclk (+1) — bfi (0x1ec85e-ish) |
| [9:11] | baclkdiv | قاسم baclk (+1) — bfi (0x1ec890: `bfi r3, r2, #9, #3`) |
| [12]   | GO    | 0x1000 (orr 0x1ec894) — يُكتب قبل الانتظار |

- مُعاد حساب المعدلات (recalc) برمجياً: `clk_cpu_recalc_rate` @0x1ebfa0 (muls ×1000000، pool 0x1ebfcc = "clk_cpu_recalc_rate")؛ التخزين في `cur_cpu_op` (global — "cur_cpu_op NULL" عند البدء)؛ الـ set_rate يحفظ OPP الجديد إلى cur_cpu_op @0x1ec944.
- `periphclk` refresh @0x1eb914: يقرأ 0x110 ويستخرج l2/pd/baclk (bits 3-5/6-8/9-11، +1) ويحسب المعدلات المتسلسلة — لا يوجد حقل periphclk في 0x110.
- `periphclk` في dmesg الفعلي = `0([NULL],0)` دائماً (الأب غير مسجل) → periphclk ليس مقسوماً في 0x110؛ حقله في سجل آخر غير مبرمج من البائع (راجع الملاحظات أدناه).

### DDR FCCR @ `base + 0xb0` (يقوده clk_ddr)
- حقل القاسم: RMW بالـ desc (shift@desc[0x14], width@desc[0x18]) — قيم مطبوعة 0 و 4 فقط → الحقل ≥3 بت. **القيم الفعلية للـ shift/width قيد التحقق (desc ثابت في .rodata)** — الاستخدام الآمن مبدئياً: bits[0:7].
- GO = bit24 (0x1000000، orr @0x1ec178) — يُكتب داخل نفس RMW.
- `base + 0x400` = اختيار OPP: `1 << idx` (idx = tblindex 0/1) — من `clk_ddr_init` @0x1ec274.
- `base + 0x15c` bits[0:3] = حقل tblindex (bfi #0,#4 @0x1ec170).
- dclk = 1066MHz ÷ (div + 2): div=0 → 533، div=4 → 266 (مؤكد من dmesg).

### AXI FCCR @ `base + 0x144` (يقوده clk_axi)
| البتات | الحقل | الدلالة |
|--------|-------|---------|
| [0]    | sel   | 0 → 208MHz، 1 → 312MHz (get_parent: `and #1`؛ للنسخة 0xc07+0x1829: bits[0:1]) |
| [1:3]  | div   | قاسم aclk (+1): 312/2=156 (div=1) — bfi #1,#3 (0x1ed056)؛ للنسخة 0x1829: bits[2:3] (bfi #2,#2 @0x1ecf08) |
| [4]    | GO    | 0x10 (orr 0x1ecf0c) |
- `base + 0x15c` bits[2:3] = قاسم إضافي (aclk2/axi2 — يُقرأ في 0x1eb7a4) — يُكتب في axi_set (0x1ec17c).
- تفريق النسخ: `mrc p15,0,r2,c0,c0,#0` midr part = 0xc07، وعتبة ID عالمية 0x1829/0x1803 (نسخ أخرى) — جهازنا = 0xc07 بدون 0x1829 → المسار الافتراضي (sel bit0، div bits[1:3]).

### مشتركة
- `base + 0xa0` bit1 = علم busy للـ CPU/DDR fccr — يُمسح قبل التبديل (0x1ec10a/0x1ec85e/0x1ec106).
- `fc_wait(comp, base)` @0x1ec074 — ينتظر حتى **تعيّن** البتة (مهل ~1000 تكرار من pools 0x1ec0e0-0x1ec0e8)؛ عند انتهاء المدة يطبع "comp %d FC timeout" (0x3d7cfc) ثم panic (0x225ac):
  - comp=0 → 0x110 **bit12** — يستخدمه **DDR** بعد كتابة GO في 0xb0 bit24!
  - comp=1 → 0xb0 **bit24** — يستخدمه **CPU** بعد كتابة GO في 0x110 bit12!
  - comp=2 → 0x144 **bit4** — يستخدمه **AXI** (نفس البتة المكوّنة)
  - غير ذلك → "wrong fc comp" (0x3d7ce3)
  - **قاعدة متقاطعة (quirk):** بتة الإتمام للـ CPU = bit24@0xb0، وللـ DDR = bit12@0x110 (كلا المجالين يتشاركان إشارة واحدة ظاهرة في السجلين). مؤكد من 0x1ec89c (`movs r0,#1; bl fc_wait` = comp=1 بعد كتابة 0x110) و 0x1ec188-0x1ec190 (`movs r0,#0; b.w fc_wait` = comp=0 بعد كتابة 0xb0).
- تسلسل `ddr_set_rate` @0x1ec0f8 (مؤكد نهائياً): مسح 0xa0 bit1 (مع printk للقيمة الخام) → مقارنة OPP القديم/الجديد ([0x14] و [0]) → كتابة حقل 0xb0 (بدون GO) عبر desc {shift@[0x14], width@[0x18]} → bfi 0x15c bits[0:3] = tblindex → **dmb sy** → قراءة 0xb0 + orr 0x1000000 (GO) → str 0xb0 → fc_wait(comp=0).
- `cpu_set_rate` @~0x1ec7a4-0x1ec998: irq-off (cpsid i) → مسح 0xa0 bit1 → FCCR write (sel من [r4,#0x14] عبر `clk_cpu_fccr_write` @0x1ebf50: RMW 0x110 بحقل {shift@desc[4]=0, width@desc[8]=3} + تحقق قراءة + "CORE FCCR Write failure" عند التباين) → RMW كامل (bfi sel/l2/pd/baclk + orr 0x1000) → str 0x110 → `fc_wait(comp=1)` → استعادة IRQ → printk صف الجدول → إن تغيّر sel: كتابة ثانية عبر 0x1ebf50 → إعادة ربط الأب (bl 0x1f1c2c) وتحديث cur_cpu_op.
- `axi_set_rate` @~0x1ecec0-0x1ed066: axi_fccr_write @0x1ec000 (RMW 0x144، desc {0,1}) ثم بناء القيمة (bfi div + orr GO) → str 0x144 → fc_wait(2) → نسخ OPP → recalc @0x1eb7d8 → printk → كتابة sel عبر 0x1ec000 → تحديث cur_axi_op @0x1ed036.
- `ddr_set_rate` @~0x1ec0f8: مسح 0xa0 bit1 → 0x400=1<<idx → field 0xb0 (desc) + GO → 0x15c bfi [0:3] → fc_wait(1)؛ `clk_ddr_init` @0x1ec274 يطبع الجدول ("dclk(src:sel,div,tblindex)") ويختار idx.
- جداول OPP (بيانات ثابتة): صفوف CPU بطول 0x44 ([0]=rate، [4..0x10]=معدلات مشتقة، [0x14]=sel، [0x20]=l2div، [0x28]=pddiv، [0x2c]=baclkdiv، [0x30]=pll/src idx=0)، صفوف AXI/DDR بطول 0x20.

## جداول التشغيل الفعلية (من dmesg — dmesg.txt سطر 75-95)

### CPU — `pclk(src:sel,div) | l2clk | pdclk | baclk | periphclk | l1_rtc:l2_rtc`
| pclk | sel | l2div | pdclk (÷+1) | baclk (÷+1) |
|------|-----|-------|-------------|-------------|
| 312  | 1   | 0 (NULL) | 156 (1) | 156 (1) |
| 416  | 2   | 0 | 208 (1) | 208 (1) |
| 624  | 0   | 0 | 312 (1) | 208 (2) |
| 832  | 4   | 0 | 416 (1) | 208 (3) |
| 1248 | 6   | 0 | 624 (1) | 312 (3) |

**PLL (sel → MHz): 0→624، 1→312، 2→416، 4→832، 6→1248** (sel 3/5/7 غير مستخدمة). البوت عند 1248 (sel 6) — "CPU boot up @1248000000HZ".

### DDR — `dclk(src:sel,div,tblindex)` — src = 1066
- 266 (sel 0, div 4, idx 0)
- 533 (sel 0, div 0, idx 1) ← boot — "DDR boot up @533000000HZ"

### AXI — `aclk(src:sel,div)`
- 156 (312, sel 1, div 1)
- 208 (208, sel 0, div 0)
- 312 (312, sel 1, div 0) ← boot — "AXI boot up @312000000HZ"

## خريطة النطاقات في الملف
- 0x1e8864 `clk_lookup` (بحث بالاسم، 14 متصلاً)؛ 0x1eb654/0x1eb680 مساعدا OPP؛ 0x1eb780 `sel_table_lookup`؛ 0x1eb800/0x1eb7d8 `axi_get_parent/recalc`؛ 0x1eb8c0 `cpu_get_parent`.
- جداول الطباعة: CPU @0x1ebf04 (رؤوس من 0x1ebc34/0x1ebc3a)؛ AXI dump @0x1ebaf0-0x1ebc2c؛ رؤوس pclk/periphclk سطرا printk @0x3d7b61/0x3d7ba3.
- سلاسل: "pclk(src:sel,div)"@0x3d7b61، "periphclk(src,div)"@0x3d7ba3، "CPU boot up @%luHZ"@0x3d7c11، "CORE FCCR Write failure"@0x3d7c28، "cur_cpu_op NULL"@0x3d7c62، "AXI boot up"@0x3d7b3f، "AXI FCCR Write failure"@0x3d7c93، "axi_op NULL"@0x3d7ccc، "wrong fc comp"@0x3d7ce3، "comp %d FC timeout"@0x3d7cfc، "Cannot find parent for axi !"@0x3d7ae0، "dclk(src:sel,div,tblindex)"@0x3d7ba3-منطقة.
- 0x1ec4c0-0x1ed000-منطقة 0x1ec4c0-0x1ec7a0 = **ليست ساعة** (مسار idle/sleep — cpsid، حفظ sp، طباعة مرة واحدة) — تجاهلها.
- 0x1ed098+ = تخصيص عام/قوائم (ليس تسجيل ساعات).

## ملاحظات التصميم للدرايفر
- `mmp_clk_mix` (نوع V2 في clk-mix.c) يطابق النمط (GO + انتظار) لكنه يدعم حقلي mux+div واحد فقط — 0x110 فيه 4 حقول + sel → **أوبس مخصصة** هي الأفضل (تطابق سلوك البائع 1:1).
- فارق دلالي: البائع ينتظر حتى **تعيّن** بتة GO (fc_wait) بينما mmp V2 ينتظر **انطلاقها** — نعمل بمثل البائع.
- فجوة معروفة: حقل قاسم DDR في 0xb0 (shift/width من desc الثابت لم يُستخرج بعد — المبدئي bits[0:7])، وحقل periphclk (سجل غير معروف — periphclk = 1:1 من pclk حتى إثبات العكس).

## الدرايفر (WIP — غير مرسل بعد)
- `clk-asr1802s.c` + `include/dt-bindings/clock/marvell,asr1802s.h` في نفس المجلد — أوبس مخصصة (cpu/ddr/axi) + مقسمات recalc-only (l2/pd/baclk) + PLLs ثابتة من جدول البوت.
- checkpatch --strict: 0 أخطاء، 0 تحذيرات. لا يوجد مترجم محلي (لا gcc/clang في النظام) — لم يُفحص بالتحويل بعد.
- خلايا DT: 0-4 = PLLs (pll0/1/2/4/6)، 5 = cpu، 6-9 = l2/pd/baclk/periph، 10 = ddr، 11 = axi، 12-14 = مصادر داخلية ثابتة (pll_ddr 1066MHz، axi_src0 208، axi_src1 312).
- للدمج لاحقاً: drivers/clk/mmp/Kconfig + Makefile (`MARVELL_ASR1802S_CLK`، ملف `clk-asr1802s.o`) + توثيق YAML جديد + جعل عقدة `clock-controller@c0100000` تستهلك `clocks` عبر الخلايا.

## ملاحظة حية من الجهاز (live SSH)
ملف: `probe_read_from_live_router/live_ssh_session/dump.txt` (kernel 3.10.33، 2026-05-26).
- **clk_summary يؤكد كل معدلات البوت بالضبط**: dpll_1066→ddr 533MHz، pll1_208→axi 208MHz (بوت)، pll1_312→cpu 312MHz. ملاحظة: cpu بدأ عند 1248 (dmesg: "CPU boot up @1248000000HZ") ثم **downclock إلى 312 بواسطة الـ governor** — يعني البوت 0x110 sel=6 ثم انتقل sel=1 في الوقت الفعلي. درايفرنا يعالجها (recalc يقرأ 0x110).
- **kallsyms يطابق أسماء RE تماماً**: `clk_cpu_setrate`, `clk_cpu_recalc_rate`, `clk_ddr_init`, `clk_ddr_fc_seq`, `asr1802s_get_fc_spinlock` — توثيق أن منطقنا مستمد من نفس الفئة الثنائية. (ملاحظة: العناوين c01fxxxx ≠ kernel-decomp.bin @0x1ec840 — الصورة في الـ dump اختلاف إصدار بناء بسيط؛ clk_summary هو المرجع الأدق.)
- **CONFIG_STRICT_DEVMEM يحظر /dev/mem على 0xc0100000** (dd أعطى بيانات غير صالحة) — اعتمدنا على clk_summary + dmesg بدلاً من reads مباشرة.
- **الجداول OPP المطبوعة في boot** مؤكدة بالكامل (CPU sel 1/2/0/4/6 → 312/416/624/832/1248؛ DDR 533 boot؛ AXI 312 boot).

### صياغة recalc نهائية (محدثة للـ clk_summary)
- **CPU recalc** الآن: يقرأ sel الحيّ من 0x110 → يعيد معدل OPP المطابق (يدعم التغييرات الديناميكية للـ governor). ✅
- **DDR recalc**: ddr @ 533 = dpll_1066 ÷ 2 (field 0 → ÷2). بقي الـ field shift/width للـ set_rate مكتوباً كـ `bits[0:7]` (TODO على الأجهزة).
- **AXI recalc**: axi @ 208 = pll1_208 ÷ 1 (sel0، div0) — مُكتوب صحيحاً.
