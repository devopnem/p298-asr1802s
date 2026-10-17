#!/usr/bin/env python3
"""Clear the ASR1802S download latch in mtd19 so the board waits for a downloader.

WHY THIS EXISTS
---------------
The P298 is not losing a race against SWDownloader. Reverse engineering the OBM
(`docs/recovery/DOWNLOAD_MODE_RE.md`) shows the board *deliberately does not
enter download mode* on a normal boot, and that the decision is a two-field
latch in a flash record.

`FUN_003eeacc` (OBM, 0x3EEACC) decides the boot mode:

    if (FUN_003f1dcc() == 0xd)                        -> "User force to download"
    if (rec->DLFG == "DLFG" && rec->DLOK != "DLOK")   -> wait for download
    if ((fuse & 0x8000) == 0)                        -> normal boot

The second gate is the interesting one. On this unit mtd19 holds

    +0x8C  "DLFG"
    +0x90  "DLOK"

so `DLOK != "DLOK"` is false and the board boots straight through. The latch
was closed at some point in the unit's life -- most likely the first time the
OBM entered download mode, because the download path itself re-stamps it:

    rec->DLFG = "DLFG";  rec->DLOK = "DLOK";  save_config();

Clearing `DLOK` reopens the gate. It is evaluated *before* the fuse check and
before any timeout, so it should put the board into download mode on every
boot with no race against the host tool.

LAYOUT  (mtd19, 768 KiB; record is 0x110 bytes, the rest is 0xFF)
----------------------------------------------------------------
    +0x00  config record, 0x110 bytes
    +0x84  "OBMD"   signature
    +0x8C  "DLFG"   download flag      <- must equal "DLFG"
    +0x90  "DLOK"   download-ok latch  <- cleared by this tool
    +0x104 "NOCP"

The record is located by the OBM through the `IATO` entry in mtd0's TIM table,
whose address field is 0x05F00000 -- mtd19's flash base.

CAVEATS, READ BEFORE FLASHING
-----------------------------
* **It may defeat itself.** The OBM re-stamps `DLOK` when it enters download
  mode, so this may buy one boot per write rather than a permanent change. That
  is unverified.
* This has **not** been tested on hardware. It is a static-analysis prediction.
* mtd0's RSA signature covers the DTIM, not mtd19, so the trust chain is not
  touched -- same reasoning as `mtd21-unlock.py`. Worth re-confirming.
* Applying this needs a NAND clip or SWDownloader. It is not a serial-console
  operation.

    ./mtd19-force-download.py --inspect findings/nand-dumps/mtd19.bin
    ./mtd19-force-download.py findings/nand-dumps/mtd19.bin -o mtd19.dl.bin
"""

import argparse
import struct
import sys
from pathlib import Path

REC_SIZE = 0x110
SIG_OFF = 0x84
DLFG_OFF = 0x8C
DLOK_OFF = 0x90
NOCP_OFF = 0x108

SIG = b"OBMD"
DLFG = b"DLFG"
DLOK = b"DLOK"
NOCP = b"NOCP"

PART_SIZE = 0xC0000     # 768 KiB


def show(buf: bytes, label: str) -> None:
    print(f"{label}:")
    for off, name, tag in ((SIG_OFF, "signature", SIG),
                           (DLFG_OFF, "DLFG      ", DLFG),
                           (DLOK_OFF, "DLOK      ", DLOK),
                           (NOCP_OFF, "NOCP      ", NOCP)):
        got = buf[off:off + 4]
        print(f"  +0x{off:03X}  {name}  {got!r:16} "
              f"{'<-- ' + tag.decode() if got == tag else ''}")


def gate_open(buf: bytes) -> bool:
    """True when the OBM's `DLFG == "DLFG" && DLOK != "DLOK"` gate is open."""
    return buf[DLFG_OFF:DLFG_OFF + 4] == DLFG and \
        buf[DLOK_OFF:DLOK_OFF + 4] != DLOK


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Clear the mtd19 DLOK latch so the OBM waits for download.")
    ap.add_argument("input", nargs="?", help="mtd19.bin (768 KiB)")
    ap.add_argument("-o", "--output", help="patched copy")
    ap.add_argument("--inspect", action="store_true",
                    help="report the latch state and exit")
    ap.add_argument("--value", default="00000000",
                    help="replacement for DLOK, 8 hex digits (default 00000000)")
    args = ap.parse_args()

    if not args.input:
        ap.error("input is required (or use --inspect with one)")

    src = Path(args.input).read_bytes()
    if len(src) != PART_SIZE:
        print(f"warning: input is {len(src)} bytes, expected 0x{PART_SIZE:x}",
              file=sys.stderr)

    show(src, "input")

    # Structural checks. If these fail we are not looking at the record and
    # writing 4 bytes at 0x90 would be meaningless at best.
    problems = []
    if src[SIG_OFF:SIG_OFF + 4] != SIG:
        problems.append(f"+0x{SIG_OFF:03X} is not {SIG!r}")
    if src[DLFG_OFF:DLFG_OFF + 4] != DLFG:
        problems.append(f"+0x{DLFG_OFF:03X} is not {DLFG!r}")
    if src[NOCP_OFF:NOCP_OFF + 4] != NOCP:
        problems.append(f"+0x{NOCP_OFF:03X} is not {NOCP!r}")
    tail_ff = set(src[REC_SIZE:REC_SIZE + 0x100]) <= {0xFF}
    if not tail_ff:
        problems.append("bytes after +0x110 are not all 0xFF")

    if problems:
        print("\nrefusing: this does not look like the mtd19 config record:",
              file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    if args.inspect:
        print(f"\nDLOK latch     : {'OPEN (board will wait for download)' if gate_open(src) else 'CLOSED (board will boot normally)'}")
        return 0

    if not args.output:
        ap.error("-o/--output is required unless --inspect")

    try:
        new = bytes.fromhex(args.value)
    except ValueError:
        print(f"refusing: --value must be 8 hex digits, got {args.value!r}",
              file=sys.stderr)
        return 1
    if len(new) != 4:
        print(f"refusing: --value must be exactly 8 hex digits",
              file=sys.stderr)
        return 1
    if new == DLOK:
        print("refusing: --value is 'DLOK', which leaves the gate closed",
              file=sys.stderr)
        return 1

    out = bytearray(src)
    out[DLOK_OFF:DLOK_OFF + 4] = new

    Path(args.output).write_bytes(bytes(out))

    # re-read rather than trusting the write path
    check = Path(args.output).read_bytes()
    show(check, "output")
    ok = check[DLOK_OFF:DLOK_OFF + 4] == new and gate_open(check) and \
        check[DLFG_OFF:DLFG_OFF + 4] == DLFG
    print(f"\nonly bytes 0x{DLOK_OFF:X}..0x{DLOK_OFF + 3:X} changed: "
          f"{'yes' if sum(a != b for a, b in zip(src, check)) <= 4 else 'NO'}")
    print(f"gate now: {'OPEN -- board should wait for download on every boot' if ok else 'NOT OPEN'}")
    if not ok:
        return 1

    print(f"\nwrote {args.output}")
    print("\nNOT TESTED ON HARDWARE. The OBM re-stamps DLOK when it enters")
    print("download mode, so this may only buy one boot. Write it with a NAND")
    print("clip; then power-cycle and watch for 2ecc:3002 staying enumerated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
