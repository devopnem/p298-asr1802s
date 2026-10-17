# Project: Notion P298 ASR1802S — OpenWrt port (KAGU)

## Strict Rule: never push without the gate passing (NON-NEGOTIABLE)

The `openwrt-ai` review bot catches things our own checks miss. Every check in
the gate exists because it caught us. Skipping it is how the same issues get
re-raised on every push.

```sh
python3 tools/push-gate.py          # full, incl. patch-apply against 6.18.55
python3 tools/push-gate.py --skip-slow   # everything except patch-apply
```

It is installed as `pre-push` on the fork
(`~/Downloads/openwrt/openwrt-fork/.git/hooks/pre-push`), so a push that would
fail is refused before it reaches the remote. If the hook ever needs to be
bypassed, that is an explicit, deliberate act — never routine.

**Never report a push as verified on the strength of a check you wrote that
does not cover the change.** Our first `formality.py` only inspected commit
messages, so it passed while the bot flagged a missing trailing newline in
README.md. A local reimplementation of someone else's linter is not evidence
that their linter is happy.

What the gate covers, and the mistake each check prevents:

| check | mistake it prevents |
|---|---|
| `eof-newline`, `eof-blank`, `crlf` | file hygiene (bot: *"missing a trailing newline"*) |
| `signoff`, `subject-len`, `body-len`, `dup-body`, `merge-commit` | commit-message form |
| `trailing-ws` | whitespace in non-diff files |
| `series-apply` | the 13-patch series applying cleanly to 6.18.55 |
| `dangling-include` | a binding example including a header that exists nowhere |
| `unused-prefix` | registering a vendor prefix no compatible string uses |
| `false-claim` | commit prose contradicting the code it describes |

Add a check whenever the bot flags something new. A gate that has never failed
is not evidence of anything.

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
   git ls-tree -r --name-only HEAD | grep -q ^target/linux/asr1802s/config-6.18 || exit 1
   ```
4. Verify per-commit bisect: `git log --stat HEAD~5..HEAD` — each commit's file list must match its message.
5. Abort push if any check fails. Never force-push a chain that deletes target files silently.

Reference: `docs/recovery/flashing_and_failsafe_guide.md` and `docs/porting/BRINGUP_MILESTONES.md`.

## OpenWrt Build Rules (from CI review regressions)

### config-6.18 format
- Must be a sorted delta over generic, NOT a raw .config dump.
- Never include banner, toolchain symbols, "# ... is not set" lines, or menu-section comments.
- Run `make kernel_oldconfig CONFIG.targets=... > target/linux/asr1802s/config-6.18` and hand-trim.
- Every symbol must be reachable: check `depends on` chains before adding.

### image/Makefile conventions
- Always start with: `include $(TOPDIR)/rules.mk` then `include $(INCLUDE_DIR)/image.mk`
- Use `DEVICE_VENDOR`, `DEVICE_MODEL`, `DEVICE_VARIANT` — never `DEVICE_TITLE`.
- Set `DEVICE_DTS_DIR` if DTS lives in a subdirectory (e.g. `$(DTS_DIR)/asr`).
- Variable names: `KERNEL_LOADADDR` (not KERNEL_LOAD_ADDR), no `KERNEL_INITRAMFS := 1`.
- Must end with `$(eval $(call BuildImage))`.
- **P298 needs**: `IMAGES := kernel.bin rootfs.bin`, `IMAGE/kernel.bin`, `IMAGE/rootfs.bin`, `KERNEL_SIZE := 5120k`, `IMAGE_SIZE := 20480k`, `FILESYSTEMS := squashfs` — without these, no firmware images are produced.

### Kernel patch format (patches-6.18/)
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
- If kernel_oldconfig drops it, it doesn't belong in config-6.18.

### Series bisectability
- Each commit must be independently buildable.
- config-6.18 must be created in the same commit as the target Makefile that needs it.
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
- Check the tree the *target kernel* actually has, not upstream master. `flow_cls_offload_flow_rule()`
  takes a **non-const** pointer in 6.18 and only became const later, so a CI error
  citing master's signature does not apply to us.
- Patch 0010 (yt921x) is **David Yang's** driver, merged upstream in **v6.19**, carried
  as a 6.18 backport. Attributing it to ourselves was a real provenance error.
- Say what is *unverified* rather than implying hardware confirmation. A commit body
  claiming offsets were "read from the live unit" while the patch header said they still
  needed hardware verification is a capability overclaim.

## Recovery campaign: start here, do not read the history

The board's NAND is only writable over USB download mode. There is no SSH and no
U-Boot shell. Nothing has ever been written to the board.

**A new session should read, in this order, and nothing else until it has:**

1. `docs/recovery/SWD-v5-status.md` — **top section only** (banner + "Corrections
   and confirmations"). The file is long and append-only; the top is current.
2. `docs/recovery/NEXT-EXPERIMENTS.md` — what to try, plus the table of
   hypotheses already falsified. **Check this before proposing anything.**
3. `docs/recovery/YUGE-QUESTION.md` — the vendor letter, ready to send.

**Do not read these as if they described the current state.** They are kept for
provenance and each carries a status banner saying which parts still hold:

| doc | status |
|---|---|
| `SWDownloader-handoff.md` | historical. Superseded. §4b (Fast Download) and §7 (protocol constants) are still good. |
| `swdownloader_blf_findings.md` | historical. §2 BLF grammar and §5 flash map are still good. |
| `SWD-v5-stall-abstract.md` | current. Written for outside consultation — use when talking to the vendor. |
| `DOWNLOAD_MODE_RE.md` | reference. How download mode and device detection work. |
| `SWDownloader-windows-RE.md` | untracked. Windows is a dead end; it fails earlier and separately. |

`tools/archive/` holds superseded code — binary patches against `swdl_linux` and
BLF generators replaced by `mk-openwrt-blf.py`. Read-only provenance.

### The current blocker, in three lines

The board stops answering WTPTP immediately after the 248-byte FBF TIM header.
Everything we can construct is now either confirmed against the board or proven
not to matter. `-p <logfile>` is the only diagnostic never exercised.

## Workspace Layout

- **Working dir (notion-p298)**: `~/Downloads/Modems/Notion_P298_ASR1802S/` — docs, porting, ops
- **findings/**: nested git repository -> `devopnem/p298-asr1802s-findings`.
  Primary-source device data (probes, NAND dumps, firmware backup, PCB photos, flash tooling).
  Gitignored by the parent repo. Sync with `git -C findings pull` / `git -C findings push`.
  Single source of truth for that repo; never track or edit it from the parent.
- **data/**: local-only, never pushed. Second unit, unsanitised probes, extracted rootfs.
  Contains a file with live IMEI/IMSI/MAC. See `data/README.md`.
- **recovery** -> symlink to `flashing_tools/`, vendor flashing tools plus the working set
- **hardware** -> symlink to `findings/board`
- **docs/**: `docs/{hardware,bootloader,recovery,porting,ops}/`
- **porting/**: `porting/reverse/` (qspi, clock_re, emac_re), `porting/delivery/`
- **ops/**: `ops/api/` (TR-069/ACS), `ops/sim-unlock/`
- **RFC series**: `devopnem/linux-asr1802s-rfc` (5-patch series; the old in-tree copy under
  `porting_workspace/linux_kernel_patch/` was removed after confirming the remote was up to date)
- **OpenWrt fork**: `~/Downloads/openwrt/openwrt-fork/` — branch `asr1802s-kagu-wip`, remote `origin` = `devopnem/openwrt`
- **PR**: openwrt/openwrt#24614 (from `devopnem/openwrt:asr1802s-kagu-wip`)
- **Target**: `target/linux/asr1802s/` — ARM Cortex-A7, **v6.18** kernel (`KERNEL_PATCHVER:=6.18`), musl
- **Patches**: `target/linux/asr1802s/patches-6.18/` — quilt series, **13 patches**, 0001–0014 (0012 dropped)
- **docs/ops/need_to_push.md**: tracks commits on `asr1802s-kagu-wip` not yet pushed to origin

### Binary data rule

Every MTD dump, kernel, rootfs and probe used here is a **symlink into
`findings/`**, not a copy. Do not re-create duplicates - link instead, and
verify the hash matches before discarding anything.
`findings/nand-dumps/` and `findings/firmware-backup/` hold the only real copies.

## Patch Validation (before every commit)

Every patch in `patches-6.18/` must pass the push gate before pushing:

1. **Hunk count validation** — verify every `@@ -s,c +s,c @@` header matches
   actual body lines (context+removed for old, context+added for new).
   The body line count must exactly equal old_count (for `-` side) and
   new_count (for `+` side). A mismatch causes `patch` to read past the
   hunk boundary and produce "malformed patch" errors.
2. **Dry-run application** — apply against a clean kernel tree:
   ```
   cd <kernel-build-dir>
   patch --dry-run -p1 < target/linux/asr1802s/patches-6.18/NNNN-*.patch
   ```
   Both must pass with zero errors. Never commit a patch that only
   passed visual inspection.
