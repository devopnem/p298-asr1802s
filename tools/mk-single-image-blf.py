#!/usr/bin/env python3
"""Cut a BLF down to exactly one enabled image and renumber it to slot 1.

WHY
---
The mtd21 recovery BLF declares three image slots:

    Number_of_Images = 3
    1_Image_Enable = 0   1_Image_ID_Name = TIMH   1_Image_Path = mtd7.bin
    2_Image_Enable = 0   2_Image_ID_Name = OBMI   2_Image_Path = Nezha_loader...bin
    3_Image_Enable = 1   3_Image_ID_Name = ENV0   3_Image_Path = mtd21.env32k.console.bin

Only slot 3 writes anything, but both SWDownloader 4.8.8.2 and 5.0.0.2 still
walk into a second "Begin DownloadImage" after slot 3 reports
"Completed DownLoad file". With 4.8.8.2 that second entry is where the device
fell off USB and the process crashed or stalled. With 5.0.0.2 the transfer
itself completes -- "Download data finished" appears for the first time -- but
the second entry still blocks, and the board never resets.

Two things are worth separating here, and neither is proven yet:

  * Whether the tool's planned image count comes from Number_of_Images rather
    than from the Enable flags. If it does, a disabled slot is still planned
    and still waited on.
  * Whether a successful download is expected to end with the board resetting.
    It is: a download that ends without a reset has left the FBF sitting in
    SRAM unexecuted, and the next power cycle discards it.

This tool does not claim which is true. It just removes the ambiguity, so the
next run either completes or fails in a way that means something.

WHAT IT DOES
------------
Keeps the comment header, rewrites Number_of_Images to 1, keeps only the
enabled image's block, and renumbers it from slot 3 to slot 1. The DKB and
TIMH entries are NOT silently re-added -- if the download needs an OBMI staged
into BootROM and this BLF has none, the run will say so immediately and
plainly, which is a better outcome than a stall that could be anything.

    ./mk-single-image-blf.py p298_mtd21_console.blf p298_mtd21_one.blf
    ./mk-single-image-blf.py p298_mtd21_console.blf -           # to stdout
"""

import argparse
import re
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="see the module docstring for the rationale")
    ap.add_argument("input")
    ap.add_argument("output", nargs="?", help="omit to write to stdout")
    args = ap.parse_args()

    src = Path(args.input).read_text(encoding="utf-8")
    lines = src.splitlines(True)

    # Which slot is enabled? Parse first so we fail loudly on a zero or
    # multiple-match BLF rather than emitting something subtly wrong.
    enabled = []
    for i, ln in enumerate(lines):
        m = re.match(r"^(\d+)_Image_Enable\s*=\s*(\d+)\s*$", ln)
        if m and int(m.group(2)):
            enabled.append(int(m.group(1)))
    if len(enabled) != 1:
        print(f"error: {args.input} has {len(enabled)} enabled image(s) "
              f"({enabled or 'none'}); this tool expects exactly 1",
              file=sys.stderr)
        return 1
    slot = enabled[0]

    out, keep = [], False
    for ln in lines:
        m = re.match(r"^(\d+)_Image_", ln)
        if m:
            keep = int(m.group(1)) == slot
            if keep:
                ln = re.sub(rf"^{slot}_Image_", "1_Image_", ln)
        if keep or not m:
            out.append(ln)

    txt = "".join(out)
    txt, n = re.subn(r"^Number_of_Images\s*=\s*\d+\s*$",
                     "Number_of_Images = 1", txt, count=1, flags=re.M)
    if n != 1:
        print("error: Number_of_Images not found", file=sys.stderr)
        return 1
    if not txt.endswith("\n"):
        txt += "\n"

    # Report what survived, so a mistake here is visible before a board run.
    kept = re.findall(r"^1_Image_(Enable|Path|ID_Name|Partition_Number)\s*=\s*(.*)$",
                      txt, flags=re.M)
    print(f"kept slot {slot}, renumbered to slot 1:")
    for k, v in kept:
        print(f"  1_Image_{k:<16} = {v}")

    if args.output:
        Path(args.output).write_text(txt, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        sys.stdout.write(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())