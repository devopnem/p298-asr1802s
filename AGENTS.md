# Project: Notion R291 ASR1802S — OpenWrt port (KAGU)

## Strict Rule: asr1802s target completeness (MUST NOT REGRESS)

This repo has lost `target/linux/asr1802s/{Makefile,image/Makefile,base-files}` twice
during commit-chain rebuilds (`b1c0e2cf`, `86235444`). CI stayed green because the
target simply stopped building — no `Build asr1802s` job ran.

Before ANY `git reset --soft` chain rebuild, rebase, or `push --force`:

1. Save the old remote head: `OLD=$(git rev-parse origin/asr1802s-kagu-wip)`
2. After rebuilding, compare: `git diff --stat $OLD..HEAD` — review EVERY deletion.
3. Verify target exists:
   ```
   git ls-tree -r --name-only HEAD | grep -q ^target/linux/asr1802s/Makefile || exit 1
   git ls-tree -r --name-only HEAD | grep -q ^target/linux/asr1802s/image/Makefile || exit 1
   git ls-tree -r --name-only HEAD | grep -q ^target/linux/asr1802s/base-files || exit 1
   git ls-tree -r --name-only HEAD | grep -q ^target/linux/asr1802s/config-6.12 || exit 1
   ```
4. Verify per-commit bisect: `git log --stat HEAD~5..HEAD` — each commit's file list must match its message.
5. Abort push if any check fails. Never force-push a chain that deletes target files silently.

Reference: `docs/flashing_and_failsafe_guide.md` and `BRINGUP_MILESTONES.md`.

## OpenWrt Build Rules (from CI review regressions)

### config-6.12 format
- Must be a sorted delta over generic, NOT a raw .config dump.
- Never include banner, toolchain symbols, "# ... is not set" lines, or menu-section comments.
- Run `make kernel_oldconfig CONFIG.targets=... > target/linux/asr1802s/config-6.12` and hand-trim.
- Every symbol must be reachable: check `depends on` chains before adding.

### image/Makefile conventions
- Always start with: `include $(TOPDIR)/rules.mk` then `include $(INCLUDE_DIR)/image.mk`
- Use `DEVICE_VENDOR`, `DEVICE_MODEL`, `DEVICE_VARIANT` — never `DEVICE_TITLE`.
- Set `DEVICE_DTS_DIR` if DTS lives in a subdirectory (e.g. `$(DTS_DIR)/asr`).
- Variable names: `KERNEL_LOADADDR` (not KERNEL_LOAD_ADDR), no `KERNEL_INITRAMFS := 1`.
- Must end with `$(eval $(call BuildImage))`.
- **R291 needs**: `IMAGES := kernel.bin rootfs.bin`, `IMAGE/kernel.bin`, `IMAGE/rootfs.bin`, `KERNEL_SIZE := 5120k`, `IMAGE_SIZE := 20480k`, `FILESYSTEMS := squashfs` — without these, no firmware images are produced.

### Kernel patch format (patches-6.12/)
- Use `git format-patch` mbox format (a/...b/... prefixes), never quilt dump.
- No fabricated commit hashes — use `From 0000000000000000000000000000000000000000` for out-of-tree.
- Every patch must have Signed-off-by in the commit message body.
- New files: `--- /dev/null` not `--- a/path`.
- No `git format-patch` trailers in the patch body.
- Kconfig entries must be inside menu blocks (before endmenu/endif).
- Makefile entries must maintain alphabetical order.

### DTS/DTSI rules
- Node names: generic class (pmic@30, audio-codec@38) not part numbers (88pm801@30).
- No `spidev` node names — use device class name.
- Use standard bindings: `reset-gpios` (not pcie-rst-gpio), `GPIO_ACTIVE_*` macros.
- Compatible strings must exactly match what the driver's `of_device_id` table accepts.
- No vendor-only properties that mainline drivers don't read.

### Config symbol validation
- Before adding a symbol, trace its `depends on` chain to ensure it's reachable.
- Common traps: MMC_PXA needs ARCH_PXA, SERIAL_PXA is deprecated (use 8250_*),
  SND_* needs SOUND, MEDIA_* needs MEDIA_SUPPORT, VIDEO_MMP_CAMERA needs MEDIA.
- If kernel_oldconfig drops it, it doesn't belong in config-6.12.

### Series bisectability
- Each commit must be independently buildable.
- config-6.12 must be created in the same commit as the target Makefile that needs it.
- Driver patches and their DT bindings should be in the same or adjacent commits.

### Commit message format
- Subject line must use the `<scope>: <summary>` prefix matching the files touched.
- Body must contain a meaningful description of what the change does and why.
- Never leave the body empty or containing only trailers (Signed-off-by, etc.).
- CI rejects empty bodies — always write at least one paragraph before the trailers.

### Security
- Never ship known passwords (root hashes) in base-files or uci-defaults.
- OpenWrt's 600-allow-blank-root-password.patch handles first-boot setup.

### Backport honesty
- Never claim "backport from vX.Y" for out-of-tree code. Use proper attribution.
- Verify with `git grep` in the target kernel tree before claiming backport.

## Workspace Layout

- **Working dir (notion-r291)**: `~/Downloads/Modems/Notion_R291_ASR1802S_P298_N13/` — documentation, porting notes, need_to_push.md
- **OpenWrt fork**: `~/Downloads/openwrt/openwrt-fork/` — branch `asr1802s-kagu-wip`, remote `origin` = `devopnem/openwrt`
- **PR**: openwrt/openwrt#24614 (from `devopnem/openwrt:asr1802s-kagu-wip`)
- **Target**: `target/linux/asr1802s/` — ARM Cortex-A7, v6.12 kernel, musl
- **Patches**: `target/linux/asr1802s/patches-6.12/` — quilt series, 0001–0012
- **need_to_push.md**: tracks commits on `asr1802s-kagu-wip` not yet pushed to origin

## Patch Validation (before every commit)

Every patch in `patches-6.12/` must pass two checks before committing:

1. **Hunk count validation** — verify every `@@ -s,c +s,c @@` header matches
   actual body lines (context+removed for old, context+added for new).
   The body line count must exactly equal old_count (for `-` side) and
   new_count (for `+` side). A mismatch causes `patch` to read past the
   hunk boundary and produce "malformed patch" errors.
2. **Dry-run application** — apply against a clean kernel tree:
   ```
   cd <kernel-build-dir>
   patch --dry-run -p1 < target/linux/asr1802s/patches-6.12/NNNN-*.patch
   ```
   Both must pass with zero errors. Never commit a patch that only
   passed visual inspection.
