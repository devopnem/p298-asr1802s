#!/usr/bin/env python3
"""Patch the P298 U-Boot environment (mtd21) to allow an autoboot interrupt.

WHY THIS EXISTS
---------------
The board inits DDR, finds the SPI-NAND, starts U-Boot 2014.01, then goes
silent at `get_quiet_from_obm params->quiet: 1`. It is not flash-dead.

What actually happens after that:

  * mtd0 (OBM) hands U-Boot `quiet = 1`, so the countdown prints nothing.
  * `bootcmd=mrvlboot` runs, prints nothing, and never returns.

Earlier notes claimed there is no interrupt window because mtd21 has
`autostart=yes`. **That was wrong.** In U-Boot 2014.01 `autoboot_command()`
runs the countdown and the `tstc()` poll *before* `run_command_list()`. The
`autostart` variable is only consulted by `autoboot_command_autostart()`,
which is reached **only when `bootcmd` contains a `;` separator.**
`bootcmd=mrvlboot` has none, so `autostart` is never read. The window exists;
it is just `bootdelay=1` seconds and completely silent, which is why it looks
like there is no window.

Raising `bootdelay` makes the window real. Setting `autostart=no` is harmless
belt-and-braces and costs nothing if the above analysis is wrong.

ENV FORMAT  (reverse-engineered, not guessed)
--------------------------------------------
    offset 0x0000  4 bytes   CRC32, little-endian
    offset 0x0004  N         NUL-separated "name=value" entries,
                            terminated by a double NUL
    offset 0x8000            end of the 32 KiB env block

There is **no flags byte** -- offset 4 is already the first character of the
first entry ("apn_update=0"). Verified: `zlib.crc32(d[4:0x8000])` equals the
stored LE CRC exactly. The partition is 256 KiB but only the first 32 KiB is
environment.

mtd0's RSA signature covers the DTIM, **not** this partition, so editing it
does not touch the trust chain. Verified in docs/bootloader/bootloader_analyse.md.

    ./mtd21-unlock.py findings/nand-dumps/mtd21.bin -o mtd21.unlocked.bin
"""

import argparse
import struct
import sys
import zlib
from pathlib import Path

ENV_END = 0x8000          # 32 KiB env block
CRC_OFF = 0
BODY_OFF = 4

# (name, value) edits. Keep "name=" prefix length stable so the on-disk
# layout barely moves, but a shorter value is fine -- U-Boot reads a flat
# NUL-separated block and we recompute the CRC.
EDITS = [
    ("autostart", "no"),
    ("bootdelay", "10"),
]


def parse(buf: bytes) -> list[tuple[str, str]]:
    body = buf[BODY_OFF:ENV_END]
    end = body.find(b"\x00\x00")
    if end < 0:
        raise SystemExit("no double-NUL terminator found -- not a U-Boot env")
    out = []
    for entry in body[:end].split(b"\x00"):
        if not entry:
            continue
        name, _, value = entry.partition(b"=")
        out.append((name.decode("latin1"), value.decode("latin1")))
    return out


def verify(buf: bytes) -> tuple[int, int]:
    stored = struct.unpack_from("<I", buf, CRC_OFF)[0]
    calc = zlib.crc32(buf[BODY_OFF:ENV_END]) & 0xFFFFFFFF
    return stored, calc


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Patch mtd21 to open an autoboot interrupt window.")
    ap.add_argument("input", help="mtd21.bin (256 KiB)")
    ap.add_argument("-o", "--output", required=True, help="patched copy")
    ap.add_argument("--bootdelay", default="10")
    ap.add_argument("--autostart", default="no",
                    choices=["no", "yes", "unset"])
    args = ap.parse_args()

    src = Path(args.input).read_bytes()
    if len(src) != 0x40000:
        print(f"warning: input is {len(src)} bytes, expected 0x40000",
              file=sys.stderr)

    stored, calc = verify(src)
    print(f"input CRC stored=0x{stored:08x} computed=0x{calc:08x} "
          f"{'OK' if stored == calc else 'MISMATCH'}")
    if stored != calc:
        print("refusing: input is not a valid env, refusing to patch it",
              file=sys.stderr)
        return 1

    entries = parse(src)
    print(f"parsed {len(entries)} env entries")

    wanted = {"autostart": args.autostart, "bootdelay": args.bootdelay}
    edits = [(n, v) for n, v in wanted.items() if v != "unset"]
    changed = []
    for name, value in edits:
        old = dict(entries).get(name)
        if old is None:
            print(f"  ! {name} not present in env, skipping")
            continue
        changed.append((name, old, value))

    # rebuild the entry block
    cur = dict(entries)
    for name, _old, value in changed:
        cur[name] = value
    block = b"".join(f"{k}={v}".encode("latin1") + b"\x00" for k, v in cur.items())
    block += b"\x00"                       # double-NUL terminator
    if BODY_OFF + len(block) > ENV_END:
        print("refusing: rebuilt env would overflow the 32 KiB block",
              file=sys.stderr)
        return 1

    out = bytearray(src)
    out[BODY_OFF:ENV_END] = b"\x00" * (ENV_END - BODY_OFF)
    out[BODY_OFF:BODY_OFF + len(block)] = block

    new_crc = zlib.crc32(bytes(out[BODY_OFF:ENV_END])) & 0xFFFFFFFF
    struct.pack_into("<I", out, CRC_OFF, new_crc)

    Path(args.output).write_bytes(bytes(out))

    # verify the result by re-reading it, do not trust the write path
    check = Path(args.output).read_bytes()
    c2 = verify(check)
    ok = c2[0] == c2[1]
    print(f"output CRC stored=0x{c2[0]:08x} computed=0x{c2[1]:08x} "
          f"{'OK' if ok else 'MISMATCH'}")
    print(f"re-parsed {len(parse(check))} entries from the written file")
    print("\nchanges:")
    for name, old, value in changed:
        print(f"  {name}: {old!r} -> {value!r}")
    if not ok:
        return 1
    print(f"\nwrote {args.output}")
    print("sanity: 'bootcmd' is NOT modified, mtd0 is NOT modified, "
          "no RSA-signed partition is touched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
