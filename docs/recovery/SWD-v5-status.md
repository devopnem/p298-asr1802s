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

Get the backtrace of the stuck process. Everything else has been exhausted by
measurement; this is the only remaining source of information.

```sh
# terminal 1 — start the download, leave it running when it stalls
sudo env LC_ALL=C LANG=C \
  /home/void/Downloads/Modems/Notion_P298_ASR1802S/flashing_tools/SWDownloader_5_0_0_2/binlinux/swdl_linux \
  -D /home/void/Downloads/Modems/Notion_P298_ASR1802S/flashing_tools/p298-swd/p298_openwrt_b_p298dkb.blf \
  -S -T 1800 -N

# terminal 2 — about 30 s after it reaches the second "Begin DownloadImage"
sudo sh /tmp/opencode/swd-bt.sh
```

`swdl_linux` is stripped and statically linked, so the backtrace will give
addresses only — but the deadlock sits between known log strings, which is
enough to bound the region.

## Ready to run once the payload stage is unblocked

`tools/mk-openwrt-blf.py` produces an oracle-validated slot-B package.
Write order is the safety property, and it is deliberate:

```
1. mtd8   TIMH    Enable = 0   source only, NOT written (preserves DDR/PP)
2. mtd0   OBMI    Enable = 0   DKB into BootROM SRAM only
3. mtd12  u-boot-b Enable = 1  from the verified dump
4. mtd14  kernel-b Enable = 1  OpenWrt squashfs-kernel, 3,468,276 B
5. mtd16  rootfs-b Enable = 1  OpenWrt squashfs-rootfs, 3,932,164 B
6. mtd19  ASRF0   Enable = 1   slot switch, LAST
```

The tool writes in chain order, so an interrupted run leaves the switch
unwritten and the board on slot A. The rollback is the same 272 bytes the
other way.

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