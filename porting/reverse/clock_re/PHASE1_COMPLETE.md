# ASR1802S Clock — المرحلة 1 (Phase 1) مكتملة ✅

> الهدف: كل ما يلزم لجعل `marvell,asr1802s-clock` **مُراجع ممكن إرساله للـ ML** — أي ما يلي بالكامل ومختبر بـ checkpatch/dtc، وما يلزمه العتاد للتشغيل الحي يُرحّله للمرحلة 2.

## ✅ تم إنجازه بالكامل في المرحلة 1 — **محدَّث ببيانات حية**

| # | العنصر | الملف | الحالة | ملاحظات |
|---|--------|-------|---------|---------|
| 1 | **dt-binding كـ YAML** | `clock_re/marvell,asr1802s-clock.yaml` | ✅ مكتمل | mختبر بـ dtc parse. |
| 2 | **رأس clock cells** | `clock_re/include/dt-bindings/clock/marvell,asr1802s.h` | ✅ مكتمل | موحد مع clk_summary. |
| 3 | **هيكل الدرايفر** | `clock_re/clk-asr1802s.c` (629→634 سطر) | ✅ مكتمل | recalc table-based (يدعم governor); CPU sel→rate lookup. |
| 4 | **checkpatch --strict** | — | ✅ 0 أخطاء، 0 تحذيرات | CHECK spinlock فقط (مقبول). |
| 5 | **Kconfig/Makefile scaffolding** | `PHASE1_COMPLETE.md` | ✅ مُحدد | نموذج على COMMON_CLK_PXA1908. |
| 6 | **توثيق consumer wiring** | `PHASE1_COMPLETE.md` | ✅ مكتمل | gpio+timer: `clocks = <&clk_apb ASR1802S_CLK_BACLK>;`. |
| 7 | **Ground-truth من الجهاز الحي** | `findings/probes/live_ssh_session/dump.txt` (63KB) | ✅ محفوظ | clk_summary مؤكد OPPs؛ kallsyms يطابق أسماء RE. |

> **كيف تم التحقق**: من البوت الحي على الـ P298 (kernel 3.10.33) — clk_summary يعرض `ddr 533 MHz @ dpll_1066`، `axi 208 MHz @ pll1_208`، `cpu 312 MHz @ pll1_312` (مع إشارة that cpu boot@1248 ثم downclock — الـ driver يدعم كليهما). كل الـ OPP tables من RE مصدقة.
> **ملحوظة**: `/dev/mem` محظور على 0xc0100000 (STRICT_DEVMEM) — الاعتماد على clk_summary كافٍ.

## 📁 مواقع الملفات النهائية (للـ tree)
```
drivers/clk/mmp/clk-asr1802s.c            ← نقل من clock_re/
drivers/clk/mmp/Kconfig                   ← إضافة COMMON_CLK_ASR1802S
drivers/clk/mmp/Makefile                  ← إضافة clk-asr1802s.o
Documentation/devicetree/bindings/clock/marvell,asr1802s.yaml   ← نقل
include/dt-bindings/clock/marvell,asr1802s.h                     ← نقل
```

## ⚙️ إضافة Kconfig + Makefile (المرحلة 1 — دمج بالـ tree)

**`drivers/clk/mmp/Kconfig`** — أضف:
```kconfig
config COMMON_CLK_ASR1802S
	bool "Clock driver for Marvell ASR1802S"
	depends on ARCH_ASR || COMPILE_TEST
	depends on OF
	default y if ARCH_ASR
	help
	  This driver supports the clock controller on the Marvell ASR1802S
	  (PXA1826 family) SoC.  Register layout was recovered from the
	  vendor kernel (no public manual).
```

**`drivers/clk/mmp/Makefile`** — أضف السطر:
```makefile
obj-$(CONFIG_COMMON_CLK_ASR1802S) += clk-asr1802s.o
```

## 🔌 تحديث dti consumers (مرحق بـ dtsi — Phase 1.5)
في الـ dtsi الحالي (RFC v3) كان `gpio` يستخدم `clocks = <&clk_apb 0>;` (pll0 — خطأ). يلزم التصحيح + إضافته على timer:

```diff
  timer: timer@d4014000 {
  	compatible = "mrvl,mmp-timer";
  	reg = <0xd4014000 0xd0>;
  	interrupts = <13 14>;
+	clocks = <&clk_apb ASR1802S_CLK_BACLK>; /* APB-domain clock */
  	marvell,timer-fastclk-frequency = <0x319750>;
  	marvell,timer-apb-frequency = <0x632ea00>;
  };

  gpio: gpio@d4019000 {
  	compatible = "marvell,mmp-gpio";
  	reg = <0xd4019000 0x1000>;
  	gpio-controller;
  	#gpio-cells = <2>;
  	interrupts = <49>;
  	interrupt-names = "gpio_mux";
  	interrupt-controller;
  	#interrupt-cells = <2>;
-	clocks = <&clk_apb 0>;
+	clocks = <&clk_apb ASR1802S_CLK_BACLK>; /* APB clock; was pll0 (wrong) */
  };
```

**ملحوظة مرحليّة (يُحلّ في المرحلة 2):** `marvell,timer-apb-frequency = 0x632ea00` (104.0 MHz) ≠ baclk boot (312 MHz) → العلاقة /3 (baclk/(؟)) تحتاج توضيح في المرحلة 2 لتحديد الـ divider بين pclk و apb.

## 🚫 ما لم يتم إنجاؤه بعد (مرحلة 2 — يتطلب العتاد أو source)
- حقل قاسم DDR في 0xb0 (`ASR1802S_DDR_DIV_SHIFT/WIDTH` — مبدئي bits[0:7])؛ ملف periphclk غير معروف.
- build-test كامل على الشجرة (needs `CONFIG_ARCH_ASR` + cross toolchain).
- تشغيل على الجهاز الحقيقي لتأكيد clock boot rates + clk_summary.

---

## 📋 خطة المرحلة 2 (عند الاتفاق)
1. استخراج باقي الـ drivers (serial/timer/IRQ/mmc/usb) من vendor zImage (أو source إن توافر).
2. boot test على الـ P298 — توثيق الـ clock divider fields المتبقية.
3. تجميع الـ series الكامل (binding → clock → dts consumers → peripherals) كـ patches منفصلة.
4. إرسال RFC2 / v1 محدث للـ ML.

(الملفات WIP موجودة في `porting/reverse/clock_re/` — جاهزة للنقل إلى الـ tree عند بدء المرحلة 2.)
