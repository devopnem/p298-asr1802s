# SWDownloader 5.0.0.2 — state of play, 2026-10-16

Compaction survival document. Everything below is either **measured** or
explicitly marked as **inferred**. Where something failed, the failure is
recorded, because the list of falsified hypotheses is the most valuable
artefact here: it is what stops the next attempt from re-testing them.

## TL;DR

The Linux downloader can reach the board, complete the FBF TIM-header stage,
and then **stall before the payload**. No run has ever transmitted a payload,
so **the board has never been written to**. That one fact explains every
confusing observation in this project to date.

The goal was reframed from "patch mtd21 for a U-Boot shell" to "replace the
vendor kernel and rootfs with OpenWrt", once it was established that the
existing images are intact and that SSH is not available.

## The blocker

```
Begin DownloadImage...........   image 1  = FBF_Ntimheader.bin (248 B)   COMPLETES
Begin DownloadImage...........   image 2  = FBF_h.bin (the payload)      NEVER STARTS
```

Stalls with the process at `00:00:00` CPU, all threads sleeping, the board
still enumerated, per-device log frozen at **996 bytes**.

Not a crash and not slowness: a deadlock. The board is present and has
answered the previous stage.

### Falsified hypotheses

Every one of these was tested against the stall and failed to change it:

| variable | values tried | result |
|---|---|---|
| tool version | 4.8.8.2, 5.0.0.2 | same point (crash vs deadlock) |
| payload size | 36 KB, 7.4 MB | same point |
| chunk size | 248 (board-advertised), 4096 | same point |
| DKB | air720 `Nezha_loader…bin`, board's own `mtd0.bin` | same point |
| BLF content | mtd21-only, OpenWrt slot-B | same point |

The DKB result is the most informative: this board's own verified OBM behaves
exactly like a foreign board's loader, which argues the problem is not the
image being wrong but the protocol stage itself.

## The stall located statically, without running anything

Added 2026-10-16. Measured from the binary, not inferred.

`swdl_linux` is a statically linked, **stripped**, non-PIE ELF: load base 0 and
`vaddr == file_offset + 0x400000`, so addresses convert to file offsets
exactly. It also **hides most of its log strings**, assembling them at runtime
from `movabs` immediates. `Begin DownloadImage...........` does not exist in
`.rodata` at all:

```asm
movabs r11, "wnloadIm"      ; 49bb 776e6c6f6164 496d
movabs r10, "age...."       ; 49ba 6167652e2e2e2e2e
movabs r15, "egin Do"       ; 49bf 426567696e20 446f
movl    [r12+0x18], "...."  ; 41c7
movw    [r12+0x1c], ".."
movb    [r12+0x1e], 0
movl    [r14+0xd], 0x0a     ; append newline
```

So `strings` proximity analysis is weak and a naive symbolizer is useless. The
strings that *are* literals resolve cleanly though: scan `.text` for the
4-byte little-endian address of each literal, then read the control flow
between consecutive log prints with `objdump`.

### Result: the stall window is 238 bytes wide

Log lines that survive as literals, and their single xref each:

| `.rodata` string | vaddr | xref in `.text` |
|---|---|---|
| `Getting Version...` | `0x75e80a` | `0x51834e` |
| `download file name is %s` | `0x75e81f` | `0x51843c` |
| `Download data finished` | `0x75e8d7` | `0x518e56` |
| `Completed DownLoad file: %s` | `0x75e906` | `0x518eaa` |

`DownloadImage()` starts at `0x5181e0`. It checks `[rbx+0xd78] == 1` and
branches to `0x5185e0` before logging anything, which is why only some images
print. The stall lies between the `Getting Version...` print at `0x518357` and
the `download file name is %s` print at `0x518445`. In that window the tool
issues **two WTPTP commands** through the shared helper `0x5fe210`:

| call site | wrapper | string passed to the helper |
|---|---|---|
| `0x518376` | `0x5ffdb0` | `GetVersion command......` |
| `0x51839e` | `0x5ff970` | `SelectImage command` |

`0x5fe210` is the WTPTP command sender. It builds a header carrying `0x10` and
`0x30` at `[rsp+0x400]` and `[rsp+0x404]`, then waits for the reply.

Also in the window: `0x51838a` calls `0x6daef0`, a `lock cmpxchg` on
`(%fs:0x10)->0x8` — a refcount/mutex that can block independently.

### What that means

**The board stops answering WTPTP after the FBF TIM-header stage.** The tool
never gets as far as opening `FBF_h.bin`, so the payload is not merely rejected
— it is never offered. `SelectImage` is the command the board fails to answer.

Two candidates, not yet separated:

1. The tool may expect the board to reset or re-enumerate between the TIM
   header and the payload, and that event never happens. The binary does carry
   hotplug machinery (`init_hotplug_sock`, `socket`, `setsockopt`) plus a
   `TerminateBL.....` / `please wait .....` pair — all stack-built, so no xrefs
   exist for them. The USB timeline captured by `swd-diag-run.sh` settles this:
   if the device number never changes and the board never disappears, there is
   no reset to wait for.
2. There may be no timeout on this wait at all, so any unanswered command
   becomes an indefinite block. `strace -T` shows whether the syscall is still
   running or already returned with an error that is being ignored.

A backtrace plus strace separates these in a single run.

## What is proven and reusable

### The Linux binaries need `vsyscall=emulate`

All six Linux binaries in `SWDownloader_5_0_0_2/binlinux` segfaulted before
`main` at `0xffffffffff600000` — the legacy x86-64 vsyscall page — calling
`gettimeofday(tv, NULL)` through it directly. Fully static, so libc is
irrelevant; a container inherits the host kernel and fails identically.

Full write-up, the eight call sites, and the no-reboot patch alternative:
**`docs/tooling/vsyscall-emulate.md`**.

### The DTIM digest scheme

`sha256(partition with trailing 0xFF stripped)`, verified byte-for-byte against
every digest recorded in the stock DTIM:

| partition | digest found |
|---|---|
| mtd11 / mtd12 — u-boot a/b | yes |
| mtd13 / mtd14 — kernel a/b | yes |
| mtd15 / mtd16 — rootfs a/b | yes |
| mtd0 — OBM | no |
| mtd21 — U-Boot environment | no |

**The vendor kernel and rootfs are not corrupt.** They match their recorded
digests in both slots. Any flash of them writes identical bytes.

`mtd21` is not hashed at all, which is why an env write can never be rejected
by DTIM verification — and why patching mtd21 was a poor use of a flashing
campaign.

### `Trusted = 0` means no digest enforcement

`MakeDownloadPackage` regenerates the DTIM as **152 bytes containing no image
digests**, while the stock `mtd8` is 2,516 bytes of populated DDR and PP
settings. Verified by running the oracle and watching `mtd8.bin` in the working
directory shrink from 262,144 to 152 bytes.

Consequence: **never write the regenerated DTIM.** It would discard 2,364 bytes
of boot configuration. `tools/mk-openwrt-blf.py` leaves it at `Enable = 0`.

### mtd19 is a switch, not a latch

`asr_flag`, 272 bytes populated. The active slot is three ASCII bytes at
`0xb8`, `0xbc`, `0xc8` — all `'a'` on this unit.

This is what makes a safe A/B recovery possible: **flash slot B, flip those
three bytes, leave slot A completely untouched.** Rollback is the same 272
bytes written back.

`mtd19.slotb.bin` and `mtd19.slota.bin` are generated from the verified dump
with `DLOK` preserved.

### 5.0.0.2 natively supports this board

| | 4.8.8.2 | 5.0.0.2 |
|---|---|---|
| USB whitelist | `0x2ECC` absent, needed a patch | `2ecc:3001/3002/3003` present |
| platform | `PXA1826` → ePlatForm 15, needed an enum patch | native `ASR1802S` processor type |
| identity constants | — | `06012014`, `3311` present |
| `Last Data` | device falls off USB | device stays |
| `Download data finished` | never appeared | appears |
| handover | crash / stall / removal | deadlock at the same point |

### Fast Download is reachable, §4b was wrong

`docs/recovery/SWDownloader-handoff.md` §4b claimed Fast Download was
structurally unreachable. Wrong: byte 4 of the WTP reply is bits 8..15 of the
length, so `test BYTE,0x4` asks whether the reply is ≥1024 bytes. It is. Five
logs show `Fast Download is NOW activated!`, including one from stock binary
plus a four-byte whitelist edit. Corrected in `92626bf`.

## The upload (read-back) path is blocked

The grammar differences are documented and committed in
`findings/tooling/blf/flash_read_mtd21.cfg` — per-area keys are 1-based,
`Area_Type` must be `SPI-NAND-FLASH`, `Blf_Version` is required, and the file
must end with a newline.

With all four fixed the config parses fully and the transfer reaches
`Begin to upload data from 0x6000000 to 0x6040000`, then writes **0 bytes**.

- BootROM does not serve `UploadData` (0x32/0x33) unaided
- Release notes 4.8.9.2: upload works "via loading new OBM into DDR"
- The staging list comes from a BLF's OBMI, and `swdl_linux` refuses `-D`
  together with `-U`

So read-back needs the one combination the CLI forbids. **Inference from the
release notes and the binary's strings, not a measurement.**

Correction on record: the `-D`/`-U` guard was earlier called dead code on the
evidence that its message string has no cross-references. It is enforced; the
string is reached by a reference form a linear scan does not model.

## Closed paths

- **Wine + `SWDownloader.exe`** — does not expose `2ecc:3002` via WinUSB, so
  the GUI never sees the board. Tested 2026-10-16.
- **Patching `swdl_linux` 4.8.8.2** — four site-level patches (whitelist,
  platform enum, chunk size, timeout, teardown) across ten binary versions.
  The teardown patch did fix a real use-after-free and got the download to
  `Completed DownLoad file`, but every version stalled at the same point and
  one introduced a glibc heap assertion. 5.0.0.2 supersedes all of it.
- **initramfs kernel** — 7,221,772 B against a 5,242,880 B partition. Needs
  repartitioning NAND, which means mtd23 and a new BBT. `mk-openwrt-blf.py
  --check` refuses it.

## Next step

One run, one harness. `tools/swd-diag-run.sh` launches the download under
`strace -ff`, watches the per-device log for the stall, and at the stall point
captures the backtrace, registers, every thread's `/proc/PID/task/*/syscall`,
the memory map, open fds and a full USB re-enumeration timeline.

```sh
cd /home/void/Downloads/Modems/Notion_P298_ASR1802S
sudo tools/swd-diag-run.sh \
  flashing_tools/p298-swd/p298_openwrt_b_p298dkb.blf 45
```

One command, unattended, no second terminal and no timing race — the earlier
backtrace was lost because the board was powered off while the process was
still stuck.

Then interpret the result:

```sh
python3 tools/swd-symbolize.py /tmp/swd-diag/run-*/gdb.txt /tmp/swd-diag/run-*/maps.txt
```

`tools/swd-symbolize.py` carries the landmark table derived above, so bare
addresses come back labelled. What to look for:

| observation | conclusion |
|---|---|
| thread inside `read()` on the USB fd, syscall still running, no `-T` value | no timeout on the WTPTP reply wait — an unanswered `SelectImage` blocks forever |
| `read()` already returned, code looping | the reply is arriving and being rejected, which is a different bug entirely |
| thread parked at the `lock cmpxchg` (`0x6daef0`) | a mutex is held by the terminated device thread, not a protocol failure |
| `usb-timeline.txt` shows the device number changing | the board *does* reset between stages and the tool is racing it |

Because the binary is stripped, a `rizin -A` function list is a fallback for
addresses outside the landmark table. It is not checked in — regenerate it
with:

```sh
r2 -2 -A -q -c 'afl~0x' flashing_tools/SWDownloader_5_0_0_2/binlinux/swdl_linux \
  > /tmp/swd-diag/afl.txt
```

## Ready to run once the payload stage is unblocked

## The downloader writes the A/B switch FIRST, not last

Corrected 2026-10-16. Everything below supersedes the earlier claim that the
switch is safe because it sits last in the chain. **It is not safe in a combined
package, and the chain order does not control write order.**

The `swdl_linux` startup log dumps the FBF image list before downloading. For a
BLF whose chain is `mtd12 -> mtd14 -> mtd16 -> mtd19`, the tool emitted:

```
m_dev.nOfImages = 4
mtd19.slotb.bin   partition 0x13   First_Sector 0x1
ow-rootfs.bin     partition 0x10   First_Sector 0x2
ow-kernel.bin     partition 0x0e   First_Sector 0x3c3
mtd12.bin         partition 0x0c   First_Sector 0x712
```

Exact reverse of the chain order, and exactly sorted by **partition number
descending**. mtd19 is the highest-numbered partition in the set, so the slot
switch is written **first** — before the u-boot, kernel and rootfs it is
switching to.

Consequence: an interrupted combined run leaves the board pointing at a slot B
that was never written. The "instant rollback" property is unaffected (slot A is
never touched), but the failure mode is worse than an unchanged board.

### The fix: two runs, never combined

`tools/mk-openwrt-blf.py` now builds both halves. Neither run can leave a
half-written slot selected.

```sh
# run 1 -- payload only. No mtd19 in the package at all, so the board keeps
#          booting slot A (the vendor firmware) no matter how it ends.
python3 tools/mk-openwrt-blf.py --slot b --dkb p298 \
  --kernel flashing_tools/p298-swd/ow-kernel.bin \
  --rootfs flashing_tools/p298-swd/ow-rootfs.bin \
  --uboot  flashing_tools/p298-swd/mtd12.bin \
  -o flashing_tools/p298-swd/p298_payload_b.blf --validate

# run 2 -- the switch alone, 272 bytes, after run 1 is known good
python3 tools/mk-openwrt-blf.py --dkb p298 \
  --slot-flag flashing_tools/p298-swd/mtd19.slotb.bin \
  -o flashing_tools/p298-swd/p298_switch_b.blf --validate
```

Image lists, as generated and oracle-validated:

| run | TIMH | OBMI | written |
|---|---|---|---|
| 1 | `mtd8` `Enable=0` | `mtd0` `Enable=0` | `mtd12`, `mtd14`, `mtd16` |
| 2 | `mtd7` `Enable=0` | `mtd0` `Enable=0` | `mtd19` only |

`Enable = 0` on TIMH and OBMI means *supply the file, do not write it*. The DTIM
is never written in either run — see `Trusted = 0` above.

Rollback is run 2 again with `mtd19.slota.bin`: 272 bytes, and it cannot
disturb slot A because it never writes slot A.

Payload is ~8.4 MB over the board's advertised 248-byte buffer — roughly
34,000 round trips — so `-T 1800`.

## Rollback

```sh
python3 -c "
d=bytearray(open('findings/nand-dumps/mtd19.bin','rb').read()[:0x110])
open('flashing_tools/p298-swd/mtd19.slota.bin','wb').write(bytes(d))
print('slot bytes ->', chr(d[0xb8]))"
```

Rebuild with `--slot-flag .../mtd19.slota.bin`.

## Current state of the board

Untouched. Still on vendor firmware in slot A, still enumerates in download
mode, `DLOK CLOSED`, all partitions as dumped. `findings/nand-dumps/MANIFEST.
sha256` verifies OK for every partition including mtd0, mtd7, mtd13–16, mtd19
and mtd21.