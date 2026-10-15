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

SOLVED 2026-10-15 -- see findings/tooling/blf/swdl-platform-enum.md
------------------------------------------------------------------
This patch is now a FALLBACK, not the fix. The gate is not a board-side
lookup at all:

    [TIM_Configuration] Processor_Type = <SoC name>
      -> CBlfParser::GetPlatFormType      -> ePlatForm
      -> CIFL_SWD::Initilizeparameter      -> _InstanceParams+0x24
      -> CWtptpDownLoad::InitializeBL     -> this+0x1C4C

    Processor_Type = PXA1802  ->  ePlatForm 6   -> DEAD STUB (no handler)
    Processor_Type = PXA1826  ->  ePlatForm 15  -> the branch we want

`PXA1802` was in every BLF in this repo, and ePlatForm 6 is one of the three
slots (0, 6, 12) that land on "Unknown platform type". Editing the BLF to
`PXA1826` is the real fix and needs no binary patch:

    -Processor_Type = PXA1802
    +Processor_Type = PXA1826

The handler at enum 15 (0x08136b75) tests, as plain substring matches:

    date      resp[18..21] as "%02x%02x%02x%02x"  contains "06012014"
    processor resp[14..17] as "%c%c%c%c"          contains "NZA3"
    version   resp[6..9]   as "%c%c%c%c"          contains "3311"

which is exactly what our board reports. The lookup keys are NOT
unrecoverable: they are static `std::string`s constructed from .rodata
literals by _GLOBAL__I__...CWtptpDownLoad (0x0812fc40).

The original note below claimed the mapping was unrecoverable and that the
board's version/date pair disagreed with its processor string. Both were
wrong: NZA3 is version 3311 / date 06012014, and the pairing is consistent.

WHY NOT JUST PATCH THE BOUNDS CHECK
-----------------------------------
Bypassing `jbe` would be unsafe: the dispatch table is *indexed by* the enum,
so an out-of-range index reads past the 19-entry table and jumps to garbage.
Instead this replaces the load of the enum with a constant that is a valid
table index. Exactly six bytes, the same length as the instruction replaced:

    8b 86 4c 1c 00 00     mov eax,[esi+0x1c4c]
 -> b8 0f 00 00 00 90     mov eax,0x0F ; nop

The correct constant for this board is `0x0F`, not `0x12`:

    0x12 = 18 -> HLN4 / 3313 / 25032015   WRONG platform branch
    0x0F = 15 -> NZA3 / 3311 / 06012014  matches this board

Indices 0, 6 and 12 all land on the "Unknown platform type" stub -- and 6 is
what `PXA1802` produces.

USAGE
-----
Prefer the BLF edit. If you must patch:

    ./swdl-platform-patch.py swdl_linux -o swdl_linux_p298 --enum 0x0F

Always first run it against `p298_probe.blf`, which carries no image
payloads.
"""

import argparse
import os
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
    ap.add_argument("--enum", type=lambda s: int(s, 0), default=0x0F,
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

    # write_bytes creates a fresh file, so it does NOT inherit the exec bit
    # from the input. Without this the run dies with "Permission denied".
    os.chmod(args.output, (Path(args.input).stat().st_mode & 0o7777) | 0o111)

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
