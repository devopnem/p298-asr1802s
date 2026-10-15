#!/usr/bin/env python3
"""Build a patched U-Boot environment block for mtd21 from the stock dump.

WHY
---
The goal of the mtd21 flash is a usable U-Boot console. Flashing
`autostart=no` and `bootdelay=10` alone does not get there: the board prints
five lines from the OBM and then goes quiet.

    SoC:   PXA 88AP1829-A0
    I2C:   ready
    DRAM:  128 MiB
    Start=00308000, relocation Offset is: 010f1000
    get_quiet_from_obm params->quiet: 1

and nothing further. `get_quiet_from_obm` is the OBM deciding to suppress the
rest of the console. Neither `quiet` nor `silent` appears in the stock env
block, so the flag cannot be cleared by editing what is already there -- it has
to be *added*, which is exactly what `fw_setenv quiet 0` did on the one boot
where OpenWrt was up and we had a shell. That shell is not reliably available,
so the same two variables have to be written by the flash instead.

LAYOUT
------
U-Boot environment partition, 32 KB, on this board:

    0x0000  uint32  crc32 over bytes 4..32767, little endian
    0x0004  char[]  NUL-separated "name=value" entries
            ...    padded to 32768 with 0x00

The fill is 0x00, verified against the stock mtd21.bin dump: its populated
area ends at 0x1f0 and the remaining 32272 bytes are all NUL. Getting this
wrong produces a block whose CRC is valid for its own contents but whose
contents differ from what the tool intends, and it will not match a
reference build.

CRC is computed over the *whole* remaining partition, padding included.

Refusing an invalid block is silent in U-Boot. A bad CRC means the whole
environment is discarded and defaults are used, which looks identical to "the
flash did not take". `--verify` recomputes and compares so that case is
distinguishable.

WHAT THIS SCRIPT DOES
---------------------
Applies an ordered list of variable edits and writes the result.

  set      NAME=VALUE   replace an existing variable, or append if absent
  del      NAME         remove a variable entirely

Then it recomputes the CRC, pads to the partition size, and reports exactly
which variables moved.

USAGE
-----
    ./mk-uboot-env.py --inspect flashing_tools/p298-swd/mtd21.bin
    ./mk-uboot-env.py -i flashing_tools/p298-swd/mtd21.bin \
        -o flashing_tools/p298-swd/mtd21.env32k.console.bin \
        --set autostart=no --set bootdelay=10 --set quiet=0 --set silent=0 \
        --verify
    ./mk-mtb21-blf.py ...   # wrap the result in a .blf
"""

import argparse
import binascii
import struct
import sys
from pathlib import Path

ENV_SIZE = 0x8000
HEADER = 4
PAD = 0x00  # verified against the stock mtd21.bin dump, which pads with NUL


def parse(block: bytes):
    """Return (crc, [(name, value)]) from a raw env block.

    The partition pads with NUL, and so does every entry terminator, so the
    populated area is simply the run of non-empty NUL-separated fields. Do not
    look for a 0xff sentinel here: there is none, and searching for one finds
    the end of the *first* variable instead.
    """
    crc = struct.unpack("<I", block[0:HEADER])[0]
    out = []
    for entry in block[HEADER:].split(b"\x00"):
        if not entry:
            continue
        name, _, value = entry.partition(b"=")
        out.append((name.decode("ascii", "replace"),
                    value.decode("ascii", "replace")))
    return crc, out


def build(variables, size: int = ENV_SIZE) -> bytes:
    """Serialise variables, CRC it, pad to size."""
    payload = b"".join(
        f"{n}={v}".encode("ascii") + b"\x00" for n, v in variables)
    if HEADER + len(payload) > size:
        raise SystemExit(
            f"env does not fit: {HEADER + len(payload)} bytes into {size}")
    block = bytearray(b"\x00" * size)
    crc = binascii.crc32(payload + bytes([PAD]) *
                         (size - HEADER - len(payload))) & 0xFFFFFFFF
    block[0:HEADER] = struct.pack("<I", crc)
    block[HEADER:HEADER + len(payload)] = payload
    for i in range(HEADER + len(payload), size):
        block[i] = PAD
    return bytes(block)


def apply_edits(variables, sets, dels):
    out = [list(v) for v in variables]
    for d in dels:
        before = len(out)
        out = [v for v in out if v[0] != d]
        if len(out) == before:
            print(f"  del {d}: NOT PRESENT", file=sys.stderr)
    for s in sets:
        name, _, value = s.partition("=")
        if not value and not s.endswith("="):
            print(f"  set {s}: needs NAME=VALUE form, ignored", file=sys.stderr)
            continue
        hit = False
        for v in out:
            if v[0] == name:
                if v[1] != value:
                    print(f"  set {name}={value}   (was {v[1]})")
                else:
                    print(f"  set {name}={value}   (already)")
                v[1] = value
                hit = True
                break
        if not hit:
            out.append([name, value])
            print(f"  set {name}={value}   (APPENDED)")
    return [(n, v) for n, v in out]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="see the module docstring for the layout and the rationale")
    ap.add_argument("input", nargs="?", help="stock env dump, e.g. mtd21.bin")
    ap.add_argument("-i", "--input", dest="input_kw")
    ap.add_argument("-o", "--output")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                    help="replace or append a variable (repeatable)")
    ap.add_argument("--del", dest="dels", action="append", default=[],
                    metavar="NAME", help="remove a variable (repeatable)")
    ap.add_argument("--inspect", action="store_true",
                    help="print the CRC and every variable, change nothing")
    ap.add_argument("--size", type=lambda s: int(s, 0), default=ENV_SIZE,
                    help="partition size in bytes (default 0x8000)")
    ap.add_argument("--verify", action="store_true",
                    help="recompute the CRC and compare against the header")
    args = ap.parse_args()

    src = args.input_kw or args.input
    if not src:
        ap.error("input required (or use --help)")

    raw = Path(src).read_bytes()
    block = raw[:args.size]
    if len(block) < args.size:
        raise SystemExit(f"{src}: only {len(block)} bytes, need {args.size}")

    crc, variables = parse(block)

    if args.inspect:
        computed = binascii.crc32(block[HEADER:]) & 0xFFFFFFFF
        print(f"{src}: {args.size} bytes ({args.size // 1024} KB)")
        print(f"  header CRC = {crc:#010x}")
        print(f"  computed   = {computed:#010x}   "
              f"{'MATCH' if computed == crc else '*** MISMATCH ***'}")
        print(f"  {len(variables)} variables, "
              f"{sum(len(n) + len(v) + 2 for n, v in variables)} bytes used")
        print()
        for n, v in variables:
            print(f"  {n}={v}")
        return 0

    print(f"editing {src}:")
    variables = apply_edits(variables, args.set, args.dels)
    out = build(variables, args.size)

    used = sum(len(n) + len(v) + 2 for n, v in variables)
    print(f"  {len(variables)} variables, {used} bytes used, "
          f"{args.size - HEADER - used} bytes padding")

    if args.verify:
        computed = binascii.crc32(out[HEADER:]) & 0xFFFFFFFF
        hdr = struct.unpack("<I", out[0:HEADER])[0]
        print(f"  CRC header = {hdr:#010x}")
        print(f"  CRC actual = {computed:#010x}   "
              f"{'MATCH' if computed == hdr else '*** MISMATCH ***'}")
        # and the round trip, which catches a variable that will not re-parse
        crc2, vars2 = parse(out)
        if crc2 != computed:
            print("  *** re-parse CRC disagrees ***", file=sys.stderr)
            return 1
        if [tuple(v) for v in vars2] != variables:
            print("  *** re-parse variable list differs ***", file=sys.stderr)
            return 1
        print("  re-parse round trip OK")

    if args.output:
        Path(args.output).write_bytes(out)
        print(f"wrote {args.output} ({args.size} bytes)")
    else:
        sys.stdout.buffer.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())