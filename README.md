# Notion R291 (Ooredoo R291 V2) — ASR1802S — Workspace

راوتر Ooredoo R291 V2 (HW: P298_N13, board KAGU / ASR1826s) — SoC: **ASR Microelectronics ASR1802S**
(ARM Cortex-A7، مشتق Marvell MMP). الهدف: فتح الجهاز (root) ثم porting OpenWrt + mainlining kernel.

## بنية المجلد

| المجلد/الملف | الوظيفة |
|--------------|---------|
| `confirmed.md` | **المرجع الأول** — معلومات مؤكدة عن الجهاز والـ SoC والـ API |
| `info.md` | بيانات الدخول (admin/SSH) + الرقاقات الفيزيائية |
| `flashing_guide.md` | دليل التفليش (slot-a + تراجع) — **اقرأه قبل أي فلاش** |
| `mainlin.md` | ملخص mainlining نواة Linux (سلسلة RFC) |
| `openwrtr291ooredoo.md` | ملخص porting OpenWrt + حالة الـ PR |
| `docs/` | توثيق مفصّل: `api-rgw.md` (API xml_action.cgi)، `ssh_open.md`، `solution.md`، `info_on_board.md` |
| `ooredoo_backup/` | **النسخ الاحتياطية الأصلية** (rootfs-a.bin، kernel-a.bin، overlay، rootfs مستخرج، DTB) — لا تُمس |
| `bootloader_analysis/` | dumps كاملة لـ mtd0-24 (127MB) + تقارير U-Boot/TFTP |
| `probe_read_from_live_router/` | أدلة من الجهاز الحي (dmesg، /proc/iomem، /proc/mtd، /proc/interrupts) — مصدر التحقق |
| `porting_workspace/` | **عمل mainlining**: `linux_kernel_patch/` (سلسلة RFC + submission_package)، `clock_re/` (هندسة عكسية clk)، PORTING_PLAN.md |
| `modular_tests/` | أدوات API النشطة (acs_tr069.py، api_login، api_ssh، api_upload...) + logs |
| `sim_unlock/` | أعمال فك SIM (mep) |
| `modem/` | ملاحظات واجهة المودم AT |
| `board_pictures/` | صور اللوحة |
| `archive/` | **أرشيف** — أعمال قديمة/تجريبية غير نشطة (othet_test، openwrt_port، probing_workspace، logs) — لا تحذف، تُستشار فقط عند الحاجة |

## أين أبدأ؟

- معلومات الجهاز المؤكدة → `confirmed.md`
- خطة التفليش → `flashing_guide.md`
- حالة الـ OpenWrt PR → `openwrtr291ooredoo.md`
- حالة الـ mainlining → `mainlin.md` + `porting_workspace/PORTING_PLAN.md`
- أدوات فتح root → `modular_tests/` (`python3 acs_tr069.py root-check`)

## روابط خارجية

- PR OpenWrt: https://github.com/openwrt/openwrt/pull/24614 (فرع `asr1802s-kagu-wip`)
- RFC repo: https://github.com/devopnem/linux-asr1802s-rfc
- شجرة OpenWrt المحلية: `/home/void/Downloads/openwrt/openwrt-fork/`
- مصدر kernel 6.12 المحلي: `/home/void/ow_kernel/linux-6.12.94/`

## تحذيرات

- `bootloader_analysis/dumps/` و`ooredoo_backup/` نسخ فريدة من NAND — لا تعدّلها.
- لا تكتب NAND دون تراجع مؤكد (راجع flashing_guide.md).
- كلمات المرور هنا (admin، SSH root `19222019`) خاصة بجهاز المستخدم — لا تشاركها.
