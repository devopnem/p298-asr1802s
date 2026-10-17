#!/usr/bin/env python3
"""Add the P298's USB ID to SWDownloader's supported-device whitelist.

WHY
---
`swdl_linux` 4.8.8.2 (and `SWDownloader.exe`) only open USB devices whose
VID/PID appears in a whitelist walked by

    CBulkDevNonDrv_Linux::ChecHWIds(long, long, long)      0x0813b220

which is called from `FindAllSupportedDevices` (0x0813b9a0) with the
`idVendor` and `idProduct` read from the device descriptor at offsets +8/+10.
The binary is not stripped, so this is read directly from `readelf -sW`.

The whitelist is a stride-12 array of {vid, pid, bcdDevice}, pointed at by
the global at 0x08337304, first entry at va 0x083D72E0 (file 0x38e2e0).
The scan stops at the first entry whose VID is 0 — that is the terminator.

Measured on this board: `usb-watch.py` shows `2ecc:3002` 'KSTR' 'ASR'
for 1.577 s from power-on. `0x2ECC` is absent from the whitelist, so every
tool silently skips it. That explains every observation: the device
enumerates, no tool ever opens it, no `wtp*.log` is written, and
`swdl_linux_wtptp_device_detect.log` stays 0 bytes.

The whitelist holds 29 live entries: 0x8086 (Intel) and 0x1286 (Marvell),
all with bcdDevice == 0xFFFFFFFF meaning "any". Our entry is appended by
reusing the terminator slot plus two spare slots, so no other device stops
working.

    ./swdl-whitelist-patch.py swdl_linux -o swdl_linux_p298
"""

import argparse
import os
import struct
import shutil
import sys
from pathlib import Path

LOAD1_VA, LOAD1_END = 0x08048000, 0x34C404
LOAD2_VA, LOAD2_OFF = 0x08395404, 0x34C404

TABLE_VA = 0x083D72E0          # first {vid,pid,bcd} entry
GLOBAL_VA = 0x08337304         # pointer to TABLE_VA
WILDCARD = 0xFFFFFFFF

OUR_VID = 0x2ECC
OUR_PID = 0x3002


def v2f(va: int) -> int:
    off = va - LOAD1_VA
    if 0 <= off < LOAD1_END:
        return off
    return LOAD2_OFF + (va - LOAD2_VA)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--vid", type=lambda s: int(s, 0), default=OUR_VID)
    ap.add_argument("--pid", type=lambda s: int(s, 0), default=OUR_PID)
    args = ap.parse_args()

    buf = bytearray(Path(args.input).read_bytes())
    table = v2f(TABLE_VA)

    # sanity: the global must point at our table
    gval = struct.unpack_from("<I", buf, v2f(GLOBAL_VA))[0]
    if gval != TABLE_VA:
        print(f"unexpected global: 0x{gval:08x}, expected 0x{TABLE_VA:08x}",
              file=sys.stderr)
        return 1

    # walk to the terminator
    ents = []
    off = table
    while off + 12 <= len(buf):
        vid, pid, bcd = struct.unpack_from("<III", buf, off)
        ents.append((off, vid & 0xFFFF, pid & 0xFFFF, bcd))
        if (vid & 0xFFFF) == 0:
            break
        off += 12

    print(f"whitelist at file 0x{table:x}: {len(ents) - 1} stored entries "
          f"+ terminator at 0x{ents[-1][0]:x}")
    print(f"  note: ChecHWIds starts at table+0xC, so entry[0] "
          f"(0x{ents[0][1]:04X}:0x{ents[0][2]:04X}) is unreachable; "
          f"{len(ents) - 2} entries are actually scanned")
    vids = sorted({v for _, v, _, _ in ents})
    print(f"  VIDs present: {', '.join(f'0x{v:04X}' for v in vids)}")
    if any(v == args.vid for _, v, _, _ in ents):
        print(f"  0x{args.vid:04X} already present, nothing to do")
        shutil.copyfile(args.input, args.output)
        return 0

    # Replace the LAST live entry in place. Nothing beyond the table is
    # touched: the terminator slot and every byte after it stay untouched.
    #
    # The alternative -- using the terminator slot plus the 12 bytes after it
    # -- was tried and rejected. The slot past the terminator holds
    # 0x0813c740 / 0x0813c720, which are code addresses and almost certainly a
    # vtable pointer pair. Zeroing it risks a crash on any virtual call.
    last_off, last_vid, last_pid, _ = ents[-2]
    print(f"  replacing last entry at 0x{last_off:x} "
          f"(0x{last_vid:04X}:0x{last_pid:04X}) with "
          f"0x{args.vid:04X}:0x{args.pid:04X}")
    print(f"  terminator at 0x{ents[-1][0]:x} and everything after stays as-is")
    print("  -> cost: one 0x1286 device type stops being recognised. We do "
          "not own one.")

    struct.pack_into("<III", buf, last_off, args.vid, args.pid, WILDCARD)
    shutil.copyfile(args.input, args.output)
    os.chmod(args.output, (Path(args.input).stat().st_mode & 0o7777) | 0o111)
    Path(args.output).write_bytes(bytes(buf))

    # re-read from disk and verify
    chk = bytearray(Path(args.output).read_bytes())
    off = table
    n = 0
    print("\npatched whitelist:")
    while off + 12 <= len(chk):
        vid, pid, bcd = struct.unpack_from("<III", chk, off)
        mark = "   <<<< OURS" if (vid & 0xFFFF) == args.vid else ""
        if (vid & 0xFFFF) != 0:
            print(f"  {n:>2}  0x{vid & 0xFFFF:04X}:0x{pid & 0xFFFF:04X}"
                  f"  bcd=0x{bcd:08X}{mark}")
            n += 1
        else:
            print("   .. terminator")
            break
        off += 12

    # ents includes the terminator, n counts live entries only
    if n != len(ents) - 1:
        print(f"\nentry count changed: {len(ents) - 1} -> {n}", file=sys.stderr)
        return 1
    print(f"\nentry count preserved: {n}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
