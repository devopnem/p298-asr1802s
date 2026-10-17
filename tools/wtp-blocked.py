#!/usr/bin/env python3
"""Report exactly which USB transfer fbfdownloader is blocked on.

The tools set `timeout = 0` on every WTPTP transfer, which usbfs reads as
"wait forever". That is why a stalled run never returns and cannot be timed
out from the outside: there is no deadline to miss. This reads the blocked
syscall directly instead.

Needs root, because the tool runs as root and /proc/PID/syscall is only
readable by a tracer or root:

    sudo tools/wtp-blocked.py

Direction matters more than anything else here. USBDEVFS_BULK packs the
endpoint in bit 7: clear means OUT (host writes, board must ACK), set means
IN (host reads, board must reply). Those are different failures, and we have
been asserting "it stops ACKing" without having measured which one this is.
"""

import os
import struct
import subprocess
import sys

USBDEVFS_BULK = 0xC0185502  # _IOWR('U', 2, struct usbdevfs_bulktransfer)

# struct usbdevfs_bulktransfer { __u32 ep; __u32 len; __u32 timeout; void *data; }
# 24 bytes with natural alignment on x86-64: data sits at offset 16.
BULK_FMT = "<III4xQ"

SYS_IOCTL = 16  # x86-64


def find_pid(name):
    try:
        out = subprocess.run(
            ["pgrep", "-x", name], capture_output=True, text=True, check=False
        ).stdout.split()
    except FileNotFoundError:
        sys.exit("pgrep not available")
    return int(out[-1]) if out else None


def read_syscall(pid):
    """Return (number, [arg0..arg5]) or None if the task is running."""
    try:
        with open(f"/proc/{pid}/syscall") as fh:
            raw = fh.read().split()
    except PermissionError:
        sys.exit(
            f"cannot read /proc/{pid}/syscall -- run under sudo.\n"
            "The tool runs as root, so only root or a tracer may inspect it."
        )
    except FileNotFoundError:
        return None
    if not raw or raw[0] in ("running", "-1"):
        return None
    return int(raw[0]), [int(a, 16) for a in raw[1:7]]


def main():
    pid = find_pid(sys.argv[1] if len(sys.argv) > 1 else "fbfdownloader")
    if pid is None:
        sys.exit("no such process running")

    args = read_syscall(pid)
    if args is None:
        sys.exit(f"pid {pid} is running, not blocked")

    number, a = args
    print(f"pid            {pid}")
    if number != SYS_IOCTL:
        print(f"syscall        {number}  (not ioctl)")
        return
    print("syscall        ioctl")
    print(f"fd             0x{a[0]:x}")
    print(f"request        0x{a[1]:08x}", end="")
    print("   USBDEVFS_BULK" if a[1] == USBDEVFS_BULK else "   (something else)")

    if a[1] != USBDEVFS_BULK:
        return
    ptr = a[2]
    try:
        with open(f"/proc/{pid}/mem", "rb") as mem:
            mem.seek(ptr)
            ep, length, timeout, data = struct.unpack(BULK_FMT, mem.read(24))
    except PermissionError:
        sys.exit("cannot read /proc/PID/mem -- run under sudo")

    direction = "IN  (host reads; board must reply)" if ep & 0x80 else "OUT (host writes; board must ACK)"
    print(f"endpoint       0x{ep:02x}  -> {direction}")
    print(f"length         {length}")
    print(f"timeout        {timeout}", end="")
    print("   INFINITE -- this is why it never returns" if timeout == 0 else "")
    print(f"data           0x{data:x}")

    print()
    if ep & 0x80:
        print("The host is waiting for the BOARD to speak.")
        print("A board that has gone quiet explains this; a host bug does not.")
    else:
        print("The host has bytes to give and the board is not taking them.")
        print("A board that has stopped ACKing explains this.")


if __name__ == "__main__":
    main()