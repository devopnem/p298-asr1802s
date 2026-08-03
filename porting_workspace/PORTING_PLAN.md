# PORTING PLAN — Ooredoo R291 v2 (ASR1802S / KAGU) → OpenWrt upstream

Three parallel paths. Choose one (or run 1 and 3 together — recommended).

## Path 1 — repackage على الـ vendor kernel 3.10 (أسرع، محليّ)
- **بعده:** `ooredoo_backup/rootfs-a.bin` (20MB، squashfs xz) + `overlay.tar.gz` + `ooredoo_backup/probe/` (dmesg/iomem/irq/env).
- **opkg:** نعم — `/bin/opkg` موجود (BB14.07 fork)؛ ولكن الـ feeds `downloads.openwrt.org/barrier_breaker/14.07/mmp/asr1826s` **آنهاً 404/502** → لا يمكن `opkg update` على الراوتر (الراوتر ما له إنترنت DNS أنفسه: nameserver 127.0.0.1).
- **الخطوة العمليّة الآن:**
  1. على الـ PC: `git clone` أهداف BB 14.07 أو استخرج `target/mmp/asr1826s/Makefile` لتعرف الـ `ARCH` tuple (armv7a/arm_cortex-a9 hard-float) — ثم نزّل pns من آخر mirror.
  2. استعمل `opkg install <local.ipk>` على الراوتر (local install، ما يلزمش إنترنت).
- ⚠️ الحدود: ليس "أحدث OpenWrt"؛ الـ kernel باقي 3.10، والـ WiFi rtl8192cd binary فقط (لا rtw88). مناسب جرّاب/اختبار مش للـ upstream.

## Path 2 — initramfs عبر U‑Boot (صالحة بلا fl‑اش)
- bootdelay=1 (ضيق)، `bootcmd=mrvlboot`، `loadaddr=0x8000`، console ttyS0@115200.
- بناء `initramfs.itb` armv7a‑cortex‑a9 → `tftp 0x8000 …; bootm` (UART لمراقبة).
- الغاية: دليل boot + dmesg جديد لتوثيق أول patch kernel إلى lkml.

## Path 3 — upstream kernel SoC port (المطلوّب للـ OpenWrt الحديث)
- **الواقع:** `ASR1802S` غير موجود في kernel.org. كان targetًا تاريخيًا في OpenWrt 14.07 (`mmp/asr1826s`) ثم **أُزيح** بعد تحويل OpenWrt لسياسة kernel‑in‑tree‑first.
- **ما تم إنجازه الآن للـ upstream PR:** `linux_kernel_patch/` — سلسلة 3 ملفات (cover + binding + DTS) مُوثّقة ومُختبرة `git am --check` على شجرة نظيفة. ترفق كل قيمة مصدرها.
- **ما ينقص للـ SoC‑port الحقيقي:**
  - مصدر الـ vendor kernel 3.10 (register defs / dtsi).
  - PCI IDs (wlan/eth) — خذها عبر initramfs boot مع `lspci`-like.
  - ربطها كـ RFC إلى `linux-arm-kernel@` (binding + skeleton أولاً — هذا ما أرسله).
- **بعد قبول الـ SoC upstream:** أعد إنشاء target `asr1826s` في `openwrt/target/linux/` (Makefile.skeleton مرفق)، ثم `rtw88` للـ RTL8812FE بدلاً rtl8192cd.

## الملفات (git repo ضمن porting_workspace)
```
porting_workspace/
├── PORTING_PLAN.md                  ← هذا الملف (3 مسارات)
├── linux_kernel_patch/
│   ├── 0000-cover-letter.patch      ← [RFC v1 0/2]
│   ├── 0001-dt-bindings-arm-asr-...patch   ← SoC + board YAML bindings (applies OK)
│   ├── 0002-arm-dts-asr1826s-kagu-...patch ← skeleton DTS (applies OK)
│   ├── Documentation/devicetree/bindings/arm/asr/{asr1802s,ooredoo-r291-v2}.yaml
│   ├── arch/arm/boot/dts/{asr1802s.dtsi, asr1826s-kagu.dts}
│   └── README.upstream.md
└── (مرتبط) openwrt_port/ + ooredoo_backup/
```
- `git -C linux_kernel_patch log --oneline` → سجلّية commit نظيفة (1/2 binding، 2/2 dts).

## الخطوة التالية المقترحة
**ابدأ بـ Path 3 (upstream kernel RFC)** — أرسل الملفّين الـ binding+DTS كـ RFC إلى `linux-arm-kernel`. أرفق التغييرات: `dt-bindings: asr1802s.yaml` أولاً (binding review بطيء وآمن)، ثم توالي. لكن لضمانة "it really boots" نحتاج initramfs boot log (Path 2) — **هل تفضل أولاً (أ) أرسل RFC الآن، أو (ب) أعد أولاً initramfs boot proof عبر UART/TFTP؟**
