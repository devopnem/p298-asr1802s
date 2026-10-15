#!/usr/bin/env python3
"""Stop the hotplug thread from freeing a device the download thread is still using.

WHY
---
Live run against the P298, 2026-10-15, `swdl_linux_p298_v6 -D p298_mtd21_latch.blf`.
The run reached the stage handover and then died:

    Completed DownLoad file: .../temp/FBF_Ntimheader.bin
    Begin DownloadImage...........
    remove DevName:/dev/bus/usb/001/064
    Thread 3 received signal SIGSEGV

gdb backtrace:

    #0  0x0816de56 in CWtpComm::GetTargetMessage(WTPSTATUS*)
    #1  0x08133167 in CWtptpDownLoad::DownloadImage(...)
    #2  0x08134ce3 in CWtptpDownLoad::WTPTPDownLoad(...)
    #3  0x08135c8b in CWtptpDownLoad::BootLoaderIOThread(void*)

ROOT CAUSE
----------
`CWtptpDownLoad::SetAndWaitForThreadExit` @ 0x0812f950 is named as if it
synchronises. It does not. It sets two flags and sleeps:

    0812f979  mov DWORD PTR [ebx+0xc1c],0x1     /* device->m_bExit        */
    0812f983  mov DWORD PTR [eax+0x424],0x1     /* CWtpComm+0x424         */
    0812f995  mov DWORD PTR [esp],0x1e8480      /* usleep(2000000)       */
    0812f9a8  call RemoveEntryList

Two seconds of `usleep`, then the list entry is dropped and the object is
freed. Nothing waits for the download thread to acknowledge the flag.

The download thread does notice the flag -- `ReadUSB` and `WriteUSB` both
test `this+0x424` and bail with "Thread is to be exit". But
`GetTargetMessage` never tests it:

    0816de38  cmp edi,0xe4e1bff       /* loop bound, ~240M iterations */
    0816de40  cmp BYTE PTR [ebx+0x3],0
    0816de46  mov [esp+0x8],fmt
    0816de56  mov eax,DWORD PTR [esi+0x638]    <-- CRASH: the log FILE*  */
    0816de5f  call __fprintf_chk

so it keeps spinning, dereferencing `this` each pass. Two seconds later the
hotplug thread frees the `_DEVICE` and the `CWtpComm` it points at, and the
next `mov eax,[esi+0x638]` reads freed memory. A garbage `FILE*` into
`__fprintf_chk` is an immediate SIGSEGV.

This is a use-after-free that only became reachable once the transfer timeout
made the failure paths live; with the original infinite timeout the ioctl
never returned and the process just parked instead.

WHAT THIS PATCH DOES
--------------------
Neutralises the three `operator delete` calls in the detect thread. The object
survives the remove event, so `esi` stays valid and the download thread runs
its loop to completion and fails cleanly on the timeout instead of crashing.

    0x081377d9  e8 62 ed 17 00   call _ZdlPv   ->   90 90 90 90 90
    0x08137b64  e8 d7 e9 17 00   call _ZdlPv   ->   90 90 90 90 90
    0x08137e90  e8 ab e6 17 00   call _ZdlPv   ->   90 90 90 90 90

Fifteen bytes. No instruction is moved, no relocation changes, no stack frame
is touched.

COST
----
One leaked `_DEVICE` per USB remove event. A session sees one or two. That is
irrelevant next to crashing.

HONEST LIMIT
------------
This stops the crash. It does not make the download resume. The device really
does go away between stages, and whether the tool can follow it to a new
device node is still unproven.

    ./swdl-teardown-patch.py swdl_linux_p298_v6 -o swdl_linux_p298_v7
    ./swdl-teardown-patch.py swdl_linux_p298_v7 --verify
    ./swdl-teardown-patch.py --describe
"""

import argparse
import shutil
import struct
import subprocess
import sys
from pathlib import Path

LOAD1_VA, LOAD1_END = 0x08048000, 0x34C404
LOAD2_VA, LOAD2_OFF = 0x08395404, 0x34C404

# va of each `call operator delete(void*)` in WtptpDeviceDetectThread
DELETE_CALLS = [0x081377D9, 0x08137B64, 0x08137E90]

NOP5 = b"\x90" * 5
EXPECT = {
    0x081377D9: bytes.fromhex("e8 62 ed 17 00"),
    0x08137B64: bytes.fromhex("e8 d7 e9 17 00"),
    0x08137E90: bytes.fromhex("e8 ab e6 17 00"),
}


def v2f(va: int) -> int:
    off = va - LOAD1_VA
    if 0 <= off < LOAD1_END:
        return off
    return LOAD2_OFF + (va - LOAD2_VA)


def describe() -> None:
    print("neutralise 3 `call operator delete` in WtptpDeviceDetectThread")
    print("(use-after-free: download thread still holds the freed CWtpComm)")
    print()
    for va in DELETE_CALLS:
        print(f"  {va:#010x}  {EXPECT[va].hex(' ')}  ->  {NOP5.hex(' ')}")


def patched(buf: bytes, va: int) -> bool:
    return bytes(buf[v2f(va):v2f(va) + 5]) == NOP5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?")
    ap.add_argument("-o", "--output")
    ap.add_argument("--undo", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--describe", action="store_true")
    args = ap.parse_args()

    if args.describe:
        describe()
        return 0
    if not args.input:
        ap.error("input required (or use --describe)")

    buf = bytearray(Path(args.input).read_bytes())
    changed = 0

    for va in DELETE_CALLS:
        off = v2f(va)
        cur = bytes(buf[off:off + 5])
        if args.undo:
            if cur == EXPECT[va]:
                print(f"{va:#010x}: already original")
                continue
            if cur != NOP5:
                print(f"{va:#010x}: neither patched nor original: {cur.hex(' ')}",
                      file=sys.stderr)
                return 1
            buf[off:off + 5] = EXPECT[va]
            print(f"{va:#010x}: restored  call _ZdlPv")
        else:
            if cur == NOP5:
                print(f"{va:#010x}: already neutralised")
                continue
            if cur != EXPECT[va]:
                print(f"{va:#010x}: bytes are {cur.hex(' ')}, expected "
                      f"{EXPECT[va].hex(' ')} -- wrong binary?", file=sys.stderr)
                return 1
            buf[off:off + 5] = NOP5
            print(f"{va:#010x}: call _ZdlPv -> 5x nop")
        changed += 1

    if args.verify:
        ok = True
        for va in DELETE_CALLS:
            p = patched(buf, va)
            want = not args.undo
            good = (p == want)
            print(f"  {'ok ' if good else 'BAD'} {va:#010x} "
                  f"{'nopped' if p else 'call _ZdlPv'}")
            ok &= good
        return 0 if ok else 1

    if args.output:
        shutil.copyfile(args.input, args.output)
        Path(args.output).write_bytes(bytes(buf))
        Path(args.output).chmod(
            (Path(args.input).stat().st_mode & 0o7777) | 0o111)
        print(f"wrote {args.output}  ({changed} call(s) changed)")
    else:
        sys.stdout.buffer.write(bytes(buf))
    return 0


if __name__ == "__main__":
    sys.exit(main())