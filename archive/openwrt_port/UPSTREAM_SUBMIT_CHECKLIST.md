# قائمة مراجعة إرسال نسخة OpenWrt مخصصة للمشروع الرسمي

> مرجع `DEVICE_PROFILE.md` §6. ملفّاتك نفسها جاهّة؛ قائمة ما لا يزال مطلوباً لإرسال commit مقبول إلى openwrt/openwrt.

## أولاً — متطلبات الترقيم (Patch prerequisites)
- [x] ملف **DTS** اولي مكتمل (`asr-1802s-kagu.dts` + `.dtsi`) — مرفق كمسودة.
- [ ] **Makefile** جديد داخل `target/linux/asr1802s/` (أو `target/linux/asr/` إذا أُعيد توحيد الـ SoC) يعرّف الـ target/boards + images.
- [ ] **`etc/board.d/01_leds` و `02_network`** — تعريفات LED والشبكات برميز `ooredoo,r291-v2`.
- [ ] **image Makefile** ينتج صيغة سُكّرتشxz + uImage/zImage مناسبة للكونسول `ttyS0,115200`.

## ثانياً — الاختبار العملي (تمهيد commit)
- [ ] **صورة تجريبية** تُشغّل على راوتر Ooredoo R291 v2 الفعلي (ASR1802S).
- [ ] **UART console** يوصل إلى `init` OpenWrt بنجاح.
- [ ] **تهيئة الشبكة** (eth MAC) + **WiFi 5GHz** يأتي MACه من NVM (`wifi_5g_addr`) — لا يُعاد كتابة الـ OUI.
- [ ] **Preservation NVM**: `overlay/root/NVM/*` يُنسخ إلى النسخة الجديدة قبل كل فلاش.
- [ ] **Recovery path** موثّق (استخدام `ooredoo_backup/kernel-a.bin + rootfs-a.bin` كـ fallback).

## ثالثاً — حساسية / أمن
- [ ] تأكيد **عدم** احتواء أي صورة MediaTek MT7621/MT7663 (انظر تحذير DEVICE_PROFILE §4).
- [ ] إلغاء الاعتماد على `telnetd_extract/` (backdoor) — لا يُرفق مع الـ upstream.

## رابعاً — نمط الـ commit (ملتزم بالمشروع الرسمي)
```
target/linux/asr1802s: add support for Ooredoo R291 v2 (KAGU)

Initial port for ASR1802S-based IAD board (Ooredoo R291 v2):
- SoC: ASR1802S, ARMv7, 128MB RAM, dual-bank A/B + UBI overlay
- Dual-bank NAND/MTD layout (kernel-a/b, rootfs-a/b)
- Per-unit NVM (TTPCom NRAM2_*) preservation via /overlay/root/NVM
- Tested via UART on live unit (kernel 3.10.33).

[upstream-acknowledged-by: <reviewer>]
Signed-off-by: <you> <your@email>
---
Cc: openwrt-devel@lists.openwrt.org
```

> ⚠️ **ملحوظة واقعية:** لا يوجد target `asr1802s` في الشجرة الرسمية حالياً — بناء target/ من الصفر يتطلب مراجعة SoC بالكامل. المسار العملي الأسرع للبدء هو **repackage الـ squashfs الأصلي** (إضافة حزم OpenWrt إلى rootfs-a المنقول) ثم تقديمه كطلب دعم للـ SoC على المنتدى قبل أن يصبح target كامل. سجّل ذلك بوضوح في الـ cover letter.
