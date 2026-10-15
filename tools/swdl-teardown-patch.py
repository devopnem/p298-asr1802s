#!/usr/bin/env python3
"""Keep a removed device's CWtpComm usable by the download thread that still holds it.

WHY
---
Live run against the P298, 2026-10-15, `swdl_linux_p298_v6 -D p298_mtd21_latch.blf`.
The run completed the first image and then died at the stage handover:

    Completed DownLoad file: .../temp/FBF_Ntimheader.bin
    Begin DownloadImage...........
    remove DevName:/dev/bus/usb/001/064
    Thread 3 received signal SIGSEGV

gdb backtrace:

    #0  0x0816de56 in CWtpComm::GetTargetMessage(WTPSTATUS*)
    #1  0x08133167 in CWtptpDownLoad::DownloadImage(_DEVICE*, int, ...)
    #2  0x08134ce3 in CWtptpDownLoad::WTPTPDownLoad(_DEVICE*)
    #3  0x08135c8b in CWtptpDownLoad::BootLoaderIOThread(void*)

ROOT CAUSE
----------
`CWtptpDownLoad::SetAndWaitForThreadExit` @ 0x0812f950 is named as if it
synchronises. It does not. It sets two flags and sleeps:

    0812f979  mov DWORD PTR [ebx+0xc1c],0x1     /* device->m_bExit     */
    0812f983  mov DWORD PTR [eax+0x424],0x1     /* CWtpComm+0x424      */
    0812f995  mov DWORD PTR [esp],0x1e8480      /* usleep(2000000)    */
    0812f9a8  call RemoveEntryList

Two seconds of `usleep`, then `RemoveEntryList` @ 0x0812f840 tears the device
down. Nothing waits for the download thread to acknowledge the flag.

`DownloadImage` re-reads the comm pointer out of the device on every image:

    08133159  mov eax,DWORD PTR [ebx+0xc18]    /* dev->m_pComm, fresh */
    0813315f  mov DWORD PTR [esp],eax
    08133162  call CWtpComm::GetTargetMessage

and `RemoveEntryList` invalidates exactly that pointer, twice over:

    0812f91b  call CWtpComm::~CWtpComm()       destroys what thread 3 holds
    0812f923  call operator delete             frees the CWtpComm
    0812f928  mov DWORD PTR [esi+0xc18],0x0    dev->m_pComm = NULL
    0812f935  call operator delete             frees the _DEVICE

So at the second `DownloadImage` the comm pointer is either a freed pointer or
zero, and `GetTargetMessage` dereferences it immediately:

    0816de46  mov DWORD PTR [esp+0x8],0x8338d3d
    0816de4e  mov DWORD PTR [esp+0x4],0x1
    0816de56  mov eax,DWORD PTR [esi+0x638]    <-- CRASH: esi is 0 or freed
    0816de5c  mov DWORD PTR [esp],eax
    0816de5f  call __fprintf_chk               fprintf(this->m_fpLog, ...)

Note this loop never tests `this+0x424`, unlike `ReadUSB` and `WriteUSB`, which
both bail with "Thread is to be exit". It spins up to ~240 million times and
dereferences `this` on every pass.

HOW THIS WAS FOUND, AND WHAT WAS WRONG FIRST
-------------------------------------------
The first guess was use-after-free on the `operator delete` calls inside
`WtptpDeviceDetectThread`. Three real calls at 0x081377d9, 0x08137b64 and
0x08137e90 were neutralised, and the crash survived unchanged at the same
address. The frees are not in the detect thread; `SetAndWaitForThreadExit`
calls `RemoveEntryList` and that is where the objects actually go. The
device-detect sites are not touched by this tool.

WITH THE CALLS NOPPED
---------------------
v7 neutralised the three calls and still crashed at the same instruction,
which located the remaining half of the bug: 0x0812f928 still sets
`dev->m_pComm = NULL`. A freed pointer and a null pointer both read as garbage
into `fprintf`, so nopping the frees alone changes nothing. Both halves have
to go, and that is the difference between v7 and v8.

WHAT THIS PATCH DOES
--------------------
    0x0812f91b  e8 90 e0 03 00            call ~CWtpComm()  ->  5x nop
    0x0812f923  e8 18 6c 18 00            call _ZdlPv       ->  5x nop
    0x0812f928  c7 86 18 0c 00 00 00      mov [esi+0xc18],0 ->  7x nop
    0x0812f935  e8 06 6c 18 00            call _ZdlPv       ->  5x nop

Twenty-two bytes of instructions, 21 of which differ: the byte at 0x0812f91c
is already 0x90 in the stock binary. No instruction is moved, no relocation
changes, no stack frame is touched. Every site is a whole instruction, and
each is followed by alignment padding, so nothing is split.

`--undo` round-trips byte-identical to the input.

`RemoveEntryList`'s `CWtpComm::CloseUsbPort()` call is deliberately left in
place: closing the fd makes the download thread's next transfer fail cleanly,
which is the behaviour we want. The list-node frees earlier in the same
function are also left alone.

COST
----
One leaked `CWtpComm` plus one leaked `_DEVICE` per USB remove event, and a
`dev->m_pComm` that keeps pointing at a live object. A session sees one or
two remove events. That is irrelevant next to crashing.

HONEST LIMIT
------------
This stops the crash. It does not make the download resume. The device really
does go away between stages, and whether the tool can follow it to a new
device node is still unproven.

    ./swdl-teardown-patch.py swdl_linux_p298_v6 -o swdl_linux_p298_v8
    ./swdl-teardown-patch.py swdl_linux_p298_v8 --verify
    ./swdl-teardown-patch.py --describe
"""

import argparse
import shutil
import sys
from pathlib import Path

LOAD1_VA = 0x08048000
LOAD1_END = 0x34C404
LOAD2_VA = 0x08395404
LOAD2_OFF = 0x34C404

# (va, original bytes) -- each a single whole instruction, nopped with
# len(original) nops. See the module docstring for the disassembly.
SITES = [
    (0x0812F91B, bytes.fromhex("e8 90 e0 03 00")),  # call CWtpComm::~CWtpComm()
    (0x0812F923, bytes.fromhex("e8 18 6c 18 00")),  # call operator delete  (CWtpComm)
    (0x0812F928, bytes.fromhex("c7 86 18 0c 00 00 00")),  # dev->m_pComm = NULL
    (0x0812F935, bytes.fromhex("e8 06 6c 18 00")),  # call operator delete  (_DEVICE)
]

WHAT = {
    0x0812F91B: "call CWtpComm::~CWtpComm()",
    0x0812F923: "call operator delete  (CWtpComm)",
    0x0812F928: "mov  [esi+0xc18],0     dev->m_pComm = NULL",
    0x0812F935: "call operator delete  (_DEVICE)",
}


def v2f(va: int) -> int:
    off = va - LOAD1_VA
    if 0 <= off < LOAD1_END:
        return off
    return LOAD2_OFF + (va - LOAD2_VA)


def nops(n: int) -> bytes:
    return b"\x90" * n


def describe() -> None:
    print("CWtptpDownLoad::RemoveEntryList @ 0x0812f840 -- 4 sites, 22 bytes")
    print("keep the removed device's CWtpComm alive for BootLoaderIOThread")
    print()
    for va, orig in SITES:
        print(f"  {va:#010x}  {orig.hex(' ')}"
              f"  ->  {nops(len(orig)).hex(' ')}")
        print(f"             {WHAT[va]}")


def is_nopped(buf, va, orig) -> bool:
    off = v2f(va)
    return bytes(buf[off:off + len(orig)]) == nops(len(orig))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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

    for va, orig in SITES:
        off = v2f(va)
        cur = bytes(buf[off:off + len(orig)])
        if args.undo:
            if cur == orig:
                print(f"{va:#010x}: already original")
                continue
            if cur != nops(len(orig)):
                print(f"{va:#010x}: neither patched nor original: "
                      f"{cur.hex(' ')}", file=sys.stderr)
                return 1
            buf[off:off + len(orig)] = orig
            print(f"{va:#010x}: restored  {WHAT[va]}")
        else:
            if cur == nops(len(orig)):
                print(f"{va:#010x}: already neutralised")
                continue
            if cur != orig:
                print(f"{va:#010x}: bytes are {cur.hex(' ')}, expected "
                      f"{orig.hex(' ')} -- wrong binary?", file=sys.stderr)
                return 1
            buf[off:off + len(orig)] = nops(len(orig))
            print(f"{va:#010x}: {WHAT[va]}  ->  {len(orig)}x nop")
        changed += 1

    if args.verify:
        ok = True
        for va, orig in SITES:
            p = is_nopped(buf, va, orig)
            good = (p == (not args.undo))
            print(f"  {'ok ' if good else 'BAD'} {va:#010x} "
                  f"{'nopped' if p else 'original'}")
            ok &= good
        return 0 if ok else 1

    if args.output:
        shutil.copyfile(args.input, args.output)
        Path(args.output).write_bytes(bytes(buf))
        Path(args.output).chmod(
            (Path(args.input).stat().st_mode & 0o7777) | 0o111)
        print(f"wrote {args.output}  ({changed} site(s) changed)")
    else:
        sys.stdout.buffer.write(bytes(buf))
    return 0


if __name__ == "__main__":
    sys.exit(main())