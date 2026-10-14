#!/usr/bin/env python3
"""Second-stage patch: force SWDownloader's platform enum past the Nezha gate.

WHY
---
With the VID/PID whitelist fixed (`--whitelist`), the tool opens the board,
exchanges the preamble and reads its identity:

    Version: 3311   Date: 06012014   Processor: NZA3
    Unknown platform type
    Get type of device failed

`CWtptpDownLoad::GetDeviceBootType` (0x081361f0) then does:

    81369fd  cmp  DWORD PTR [esi+0x1c4c],0x12
    8136a04  jbe  8136a30
    8136a06  fprintf(...,"Unknown platform type")
    8136a30  mov  eax,DWORD PTR [esi+0x1c4c]
    8136a36  jmp  DWORD PTR [eax*4+0x83371dc]    ; 19 entries, index 0..0x12

The enum is copied out of a record found by looking the device identity up in
a table the tool assembles at runtime, so it cannot be read statically. The
name fields are `std::string` globals in BSS built by the CWtptpDownLoad
global constructor; the version codes survive as 4-character dwords in
.rodata but the dates do not appear as dwords at all, so the record layout is
string-based.

Our board reports version `3311` and date `06012014`, which the tool pairs
with `HLN2`, while its processor string says `NZA3`. That mismatch is the
most likely reason the lookup resolves to an out-of-range enum.

WHY NOT JUST PATCH THE BOUNDS CHECK
-----------------------------------
Bypassing `jbe` would be unsafe: the dispatch table is *indexed by* the enum,
so an out-of-range index reads past the 19-entry table and jumps to garbage.
Instead this replaces the load of the enum with a constant that is a valid
table index. Exactly six bytes, the same length as the instruction replaced:

    8b 86 4c 1c 00 00     mov eax,[esi+0x1c4c]
 -> b8 12 00 00 00 90     mov eax,0x12 ; nop

`0x12` is the last valid index and has a real handler that calls
`SetBootDeviceType`; indices 0, 6 and 12 all land on the
"Unknown platform type" stub instead.

HONESTY
-------
`0x12` is a reasoned guess, not a proven name-to-enum mapping, which could
not be recovered statically. This is a probe of which branch a Nezha-class
board takes. It may select the wrong platform branch. Always run it against
`p298_probe.blf` first, which carries no image payloads.

    ./swdl-platform-patch.py swdl_linux -o swdl_linux_p298 --enum 0x12
"""

import argparse
import struct
import sys
from pathlib import Path

LOAD1_VA, LOAD1_END = 0x08048000, 0x34C404
LOAD2_VA, LOAD2_OFF = 0x08395404, 0x34C404

LOAD_VA = 0x08136A30
EXPECT = bytes.fromhex("8b864c1c0000")
MAX_ENUM = 0x12
DEAD_ENUMS = {0x00, 0x06, 0x0C}   # all land on the "Unknown platform type" stub


def v2f(va: int) -> int:
    off = va - LOAD1_VA
    if 0 <= off < LOAD1_END:
        return off
    return LOAD2_OFF + (va - LOAD2_VA)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--enum", type=lambda s: int(s, 0), default=0x12,
                    help=f"platform enum to force, 0..0x{MAX_ENUM:x} "
                         f"(default 0x{MAX_ENUM:x})")
    args = ap.parse_args()

    enum = args.enum
    if not 0 <= enum <= MAX_ENUM:
        print(f"enum {enum:#x} is outside the dispatch table "
              f"(0..0x{MAX_ENUM:x})", file=sys.stderr)
        return 1
    if enum in DEAD_ENUMS:
        print(f"warning: enum {enum:#x} lands on the "
              f"'Unknown platform type' stub, so this will not help")

    src = Path(args.input).read_bytes()
    buf = bytearray(src)

    off = v2f(LOAD_VA)
    found = bytes(buf[off:off + 6])
    if found != EXPECT:
        print(f"unexpected bytes at file {off:#x}: {found.hex(' ')}",
              file=sys.stderr)
        print("wrong binary, or already patched", file=sys.stderr)
        return 1

    buf[off:off + 6] = bytes.fromhex("b8") + struct.pack("<I", enum) + b"\x90"

    Path(args.output).write_bytes(bytes(buf))

    # verify by re-reading from disk
    chk = Path(args.output).read_bytes()
    got = chk[off:off + 6]
    ok = got == bytes.fromhex("b8") + struct.pack("<I", enum) + b"\x90"
    changed = [i for i, (a, b) in enumerate(zip(src, chk)) if a != b]
    # every changed byte must fall inside the 6-byte patch window
    inside = all(off <= i < off + 6 for i in changed)

    print(f"va 0x{LOAD_VA:08x}  file 0x{off:x}")
    print(f"  before: {EXPECT.hex(' ')}")
    print(f"  after : {got.hex(' ')}")
    print(f"bytes differing: {len(changed)} (all inside the 6-byte window: {inside})")
    print(f"patch window: 0x{off:x}..0x{off + 5:x}")
    print(f"size unchanged: {len(chk) == len(src)}")
    if not ok or not inside or len(changed) > 6:
        print("FAILED verification", file=sys.stderr)
        return 1
    print(f"wrote {args.output}")
    print(f"forced platform enum = {enum:#x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
