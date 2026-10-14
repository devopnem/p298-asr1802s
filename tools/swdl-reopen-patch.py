#!/usr/bin/env python3
"""Third-stage patch: let OpenDev re-open a device it is already holding.

WHY
---
Once the DKB finishes uploading, the ROM hands control to the uploaded code.
The device stays enumerated -- dmesg shows `new high-speed USB device number 38`
and never a matching `USB disconnect` -- but the tool's hotplug thread decides
the device went away and re-detects it:

    |Completed DownLoad file: .../temp/DKB_ntimheader.bin
    |Begin DownloadImage...........
    remove DevName:/dev/bus/usb/001/038
    add DevName:/dev/bus/usb/001/038
    ERROR: n = -1, errno = 16 (Device or resource busy)      x ~700

errno 16 is EBUSY. The tool opens the very node it still holds open. usbfs
permits one open per device per process, so the second open fails forever and
the retry loop spins at `usleep(5000)` until the -T timeout expires. The FBF
never goes out and nothing is ever written.

    CWtpComm::CloseUsbPort        0x0816d2f0
      cb 8a 00 02 00 00           mov ecx,[edx+0x200]    ; handle->fd
      85 c9                       test ecx,ecx
      74 11                       je  +0x11              ; skip if fd == 0
      06 48 06 00 00              add eax,0x648          ; handle = this+0x648
      e8 79 e4 fc ff              call CloseDev          ; 0x0813b790
    CBulkDevNonDrv_Linux::CloseDev 0x0813b790   <- the ONLY caller of CloseDev

So the tool already owns the close logic; the re-detect path simply never calls
it. This patch makes `OpenDev` idempotent by calling `CloseDev` itself before
every open.

TWO EDITS
---------
1. Make CloseDev safe to call unconditionally. It currently guards with `js`
   (skip only when fd is negative), but `CWtpComm::CWtpComm` never initialises
   the handle -- it calls a 5-byte stub constructor -- so a first-time handle has
   fd == 0. `js` would let that through and close(0), i.e. stdin. Widening the
   guard to `jle` skips any fd <= 0, which is what "not open" means:

       813b7a7  85 d2     test edx,edx
       813b7a9  78 33     js  +0x33
    -> 813b7a9  7e 33     jle +0x33

2. Call it from OpenDev just before `__libc_open64` (0x0813b6b3). `ebx` already
   holds the handle (loaded at 0x0813b66f, not clobbered before this point), so
   it is pushed explicitly. Omitting that push is not a harmless no-op: CloseDev
   reads its argument from [ebp+0xc], and a bare call leaves stack junk there.
   That is exactly what the first attempt did, and it produced

       segfault at 200 ip 000000000813b7a1 error 4

   which is CloseDev's `mov edx,[ebx+0x200]` executing with ebx == 0.

   The 10-byte instruction replaced is dead: `GetPipeOfDev` writes all three of
   its out-params on success (0x813b432-0x813b44c) and OpenDev reads only two of
   them back (0x813b714, 0x813b720); `[ebp-0x428]` is the third and is never
   read on either path -- the failure path at 0x813b770 only prints and returns.

       813b69e  c7 85 d8 fb ff ff ff ff ff ff   mov DWORD PTR [ebp-0x428],-1
    -> 813b69e  53 e8 ec 00 00 00 90 90 90 90   push ebx ; call CloseDev ; nops

   rel32 = 0x0813b790 - 0x0813b6a4 = 0xEC.

RISK DIRECTION
--------------
CloseDev closes a file descriptor and zeroes 256 bytes of the handle; OpenDev
immediately repopulates both. No flash operation is reachable from here. The
DKB upload happens before any image is written, so a failure at this point
leaves the board exactly where it was. Run it against a probe .blf first.

    ./swdl-reopen-patch.py swdl_linux_p298_v3 -o swdl_linux_p298_v4
"""

import argparse
import os
import struct
import sys
from pathlib import Path

LOAD1_VA, LOAD1_END = 0x08048000, 0x34C404
LOAD2_VA, LOAD2_OFF = 0x08395404, 0x34C404

# site 1: CloseDev guard, js -> jle (the `test edx,edx` sits at 0x813b7a7,
# the jump itself at 0x813b7a9)
GUARD_VA = 0x0813B7A9
GUARD_EXPECT = bytes.fromhex("7833")
GUARD_REPLACE = bytes.fromhex("7e33")   # jle +0x33

# site 2: OpenDev dead init -> call CloseDev
CALL_VA = 0x0813B69E
CALL_EXPECT = bytes.fromhex("c785d8fbffffffffffff")
CLOSEDEV_VA = 0x0813B790


def v2f(va: int) -> int:
    off = va - LOAD1_VA
    if 0 <= off < LOAD1_END:
        return off
    return LOAD2_OFF + (va - LOAD2_VA)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args()

    src = Path(args.input).read_bytes()
    buf = bytearray(src)

    guard_off = v2f(GUARD_VA)
    call_off = v2f(CALL_VA)

    got_guard = bytes(buf[guard_off:guard_off + 2])
    if got_guard != GUARD_EXPECT:
        print(f"unexpected bytes at va {GUARD_VA:#x} (file {guard_off:#x}): "
              f"{got_guard.hex(' ')}", file=sys.stderr)
        print("wrong binary, or already patched", file=sys.stderr)
        return 1

    got_call = bytes(buf[call_off:call_off + len(CALL_EXPECT)])
    if got_call != CALL_EXPECT:
        print(f"unexpected bytes at va {CALL_VA:#x} (file {call_off:#x}): "
              f"{got_call.hex(' ')}", file=sys.stderr)
        print("wrong binary, or already patched", file=sys.stderr)
        return 1

    # call CloseDev: the handle lives in ebx. rel32 is measured from the end of
    # the call instruction, which now sits one byte later because of the push.
    rel = CLOSEDEV_VA - (CALL_VA + 1 + 5)
    if not -(1 << 31) <= rel < (1 << 31):
        print("CloseDev is out of rel32 range", file=sys.stderr)
        return 1
    call_patch = bytes.fromhex("53") + bytes.fromhex("e8") + struct.pack("<i", rel) + b"\x90" * 4
    assert len(call_patch) == len(CALL_EXPECT), "patch must be same length"

    # Decode our own output the way the CPU would and insist it lands on
    # CloseDev. A call with the wrong rel32 compiles, links, looks plausible in
    # a hex dump and crashes at run time -- this is the check that catches it.
    call_at = CALL_VA + 1
    decoded_target = (call_at + 5) + struct.unpack("<i", call_patch[2:6])[0]
    if decoded_target != CLOSEDEV_VA:
        print(f"encoded call lands on {decoded_target:#x}, "
              f"not CloseDev {CLOSEDEV_VA:#x}", file=sys.stderr)
        return 1

    buf[guard_off:guard_off + 2] = GUARD_REPLACE
    buf[call_off:call_off + 10] = call_patch

    Path(args.output).write_bytes(bytes(buf))

    # write_bytes creates a fresh file, so it does NOT inherit the exec bit
    # from the input. Without this the run dies with "Permission denied".
    os.chmod(args.output, (Path(args.input).stat().st_mode & 0o7777) | 0o111)

    # verify by re-reading from disk
    chk = Path(args.output).read_bytes()
    ok_guard = chk[guard_off:guard_off + 2] == GUARD_REPLACE
    ok_call = chk[call_off:call_off + 10] == call_patch
    changed = [i for i, (a, b) in enumerate(zip(src, chk)) if a != b]
    windows = [(guard_off, guard_off + 2), (call_off, call_off + 10)]
    inside = all(any(lo <= i < hi for lo, hi in windows) for i in changed)

    print(f"va {GUARD_VA:#x}  file {guard_off:#x}")
    print(f"  before: {GUARD_EXPECT.hex(' ')}   (js  +0x33)")
    print(f"  after : {GUARD_REPLACE.hex(' ')}   (jle +0x33)")
    print(f"va {CALL_VA:#x}  file {call_off:#x}")
    print(f"  before: {CALL_EXPECT.hex(' ')}")
    print(f"  after : {call_patch.hex(' ')}")
    print(f"  call rel32 = {rel:#x} -> lands on {decoded_target:#x} "
          f"(CloseDev is {CLOSEDEV_VA:#x})")
    print(f"bytes differing: {len(changed)} (all inside the windows: {inside})")
    print(f"size unchanged: {len(chk) == len(src)}")

    if not ok_guard or not ok_call or not inside:
        print("FAILED verification", file=sys.stderr)
        return 1
    print(f"wrote {args.output}")
    print("OpenDev now releases a stale fd before every open")
    return 0


if __name__ == "__main__":
    sys.exit(main())