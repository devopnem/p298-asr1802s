#!/usr/bin/env python3
"""Give the usbdevfs bulk transfers a bounded timeout instead of 'wait forever'.

WHY THIS EXISTS
---------------
Live run against the P298 on 2026-10-15, `swdl_linux_p298_v5`, got past the
platform gate and completed the first image:

    Version: 3311  Date: 06012014  Processor: NZA3
    Get type of device successfully
    Completed DownLoad file: .../temp/FBF_Ntimheader.bin
    Begin DownloadImage...........
    remove DevName:/dev/bus/usb/001/059

and then hung forever. The process sat in state D (uninterruptible I/O):

    $ ps -eo pid,stat,cmd | grep swdl
    24990 Sl+  ./swdl_linux_p298_v5 -D p298_mtd21_only.blf -T 300 -N

`-T 300` did eventually rescue the run -- `main()` does enforce it on a
`pthread_cond_timedwait`, and after the full 300 s the tool printed
"swdl_linux timeout exit / TerminateBL" and exited cleanly. But that means
losing the whole 300 s to a transfer that will never return, and the device
sits there unanswered for all of it. Meanwhile `lsusb` showed the board the
entire time:

    Bus 001 Device 059: ID 2ecc:3002 ASR KSTR

So the device was present and the tool was waiting on a transfer the device
had stopped answering.

ROOT CAUSE
----------
Both bulk-transfer paths pass `timeout = 0` to the usbdevfs ioctl:

    CBulkDevNonDrv_Linux::Write   0x0813b55b
        c7 45 e0 00 00 00 00      mov DWORD PTR [ebp-0x20],0x0

    CWtpComm::ReadUSB             0x0816d51b
        c7 44 24 10 00 00 00 00   mov DWORD PTR [esp+0x10],0x0

In `struct usbdevfs_bulktransfer` the field at that offset is:

    unsigned int timeout;   /* milliseconds; 0 = no timeout, wait forever */

Zero means block indefinitely. The tool's own retry loops cannot help,
because they sit *above* the ioctl and never get to run:

    ReadUSB        10 retries, usleep(1000)   between them
    WriteUSB       20 retries, usleep(1000)
    ...Read        6 retries,  usleep(10000)

Every one of those is dead code while the kernel call below it is blocked.

WHAT THIS PATCH DOES
--------------------
Sets both timeouts to a finite value. The ioctl then returns ETIMEDOUT,
the existing retry loops take over, and the tool fails cleanly or recovers
instead of hanging. Two 4-byte immediate edits; no instruction changes.

    ./swdl-timeout-patch.py swdl_linux_p298_v5 -o swdl_linux_p298_v6
    ./swdl-timeout-patch.py swdl_linux_p298_v6 --verify
    ./swdl-timeout-patch.py --describe

SAFETY
------
The timeout is per bulk transfer, not per file. 2000 ms is ~40x what a
4096-byte high-speed transfer needs, so it will not fire on a healthy link.
It only fires when the device has genuinely stopped responding, which is
exactly the case we want to escape.

The board re-enumerating between stages is normal and is NOT what this
fixes. It makes the hang recoverable so the hotplug thread can run and
re-detect the device; whether the download then resumes is a separate
question, answered by the run.
"""

import argparse
import shutil
import struct
import subprocess
import sys
from pathlib import Path

LOAD1_VA, LOAD1_END = 0x08048000, 0x34C404
LOAD2_VA, LOAD2_OFF = 0x08395404, 0x34C404

# (name, va of the `mov ..., 0` instruction, file offset of its 4-byte
#  immediate, opcode bytes that must immediately precede it)
SITES = [
    ("CBulkDevNonDrv_Linux::Write  struct.timeout",
     0x0813B55B, 0x000F355E, bytes.fromhex("c7 45 e0")),
    ("CWtpComm::ReadUSB            transfer timeout arg",
     0x0816D51B, 0x0012551F, bytes.fromhex("c7 44 24 10")),
]

DEFAULT_MS = 2000
WILDCARD = 0xFFFFFFFF      # written back when the patch is undone


def v2f(va: int) -> int:
    off = va - LOAD1_VA
    if 0 <= off < LOAD1_END:
        return off
    return LOAD2_OFF + (va - LOAD2_VA)


def describe() -> None:
    print("usbdevfs bulk-transfer timeout: 0 (infinite) -> %d ms" % DEFAULT_MS)
    print()
    for name, va, imm_off, _ in SITES:
        print(f"  {va:#010x}  {name}")
        print(f"              immediate at file {imm_off:#010x}  "
              f"(mov ..., 0x00000000)")


def current(buf: bytes, imm_off: int) -> int:
    return struct.unpack_from("<I", buf, imm_off)[0]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="bound the usbdevfs bulk-transfer timeout")
    ap.add_argument("input", nargs="?")
    ap.add_argument("-o", "--output")
    ap.add_argument("--ms", type=lambda s: int(s, 0), default=DEFAULT_MS,
                    help=f"timeout in milliseconds (default {DEFAULT_MS})")
    ap.add_argument("--undo", action="store_true",
                    help="write 0xFFFFFFFF back, i.e. usbdevfs 'no timeout'")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--describe", action="store_true")
    args = ap.parse_args()

    if args.describe:
        describe()
        return 0
    if not args.input:
        ap.error("input required (or use --describe)")

    buf = bytearray(Path(args.input).read_bytes())
    new = WILDCARD if args.undo else args.ms
    changed = 0

    for name, va, imm_off, want in SITES:
        got = bytes(buf[imm_off - len(want):imm_off])
        if got != want:
            print(f"{va:#010x}: opcode is {got.hex(' ')}, expected "
                  f"{want.hex(' ')} -- wrong binary?", file=sys.stderr)
            return 1
        old = current(buf, imm_off)
        if old == new:
            print(f"{va:#010x}: already {new} ms")
            continue
        if old not in (0, WILDCARD) and not args.undo:
            print(f"{va:#010x}: unexpected existing value {old:#x}",
                  file=sys.stderr)
            return 1
        struct.pack_into("<I", buf, imm_off, new)
        print(f"{va:#010x}: timeout {old} -> {new}"
              f"{' ms' if new != WILDCARD else ' (no timeout)'}")
        changed += 1

    if args.verify:
        ok = True
        for name, va, imm_off, _ in SITES:
            v = current(buf, imm_off)
            good = (v == WILDCARD) if args.undo else (v == args.ms)
            print(f"  {'ok ' if good else 'BAD'} {va:#010x} = {v:#x} ms  {name}")
            ok &= good
        return 0 if ok else 1

    if args.output:
        shutil.copyfile(args.input, args.output)
        Path(args.output).write_bytes(bytes(buf))
        Path(args.output).chmod(
            (Path(args.input).stat().st_mode & 0o7777) | 0o111)
        print(f"wrote {args.output}  ({changed} site(s) changed)")
    else:
        Path(args.output or "swdl_linux.timeout-patched").write_bytes(bytes(buf))

    out = subprocess.run(
        ["objdump", "-d", "-M", "intel",
         f"--start-address={SITES[0][1]:#x}",
         f"--stop-address={SITES[0][1] + 10:#x}",
         args.output or args.input],
        capture_output=True, text=True)
    print("\n".join(l for l in out.stdout.splitlines() if ":" in l))
    return 0


if __name__ == "__main__":
    sys.exit(main())