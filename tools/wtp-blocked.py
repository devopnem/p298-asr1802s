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

SYS_IOCTL = 16      # x86-64
SYS_FUTEX = 202     # x86-64
SYS_READ = 0
SYS_WRITE = 1
SYS_NANOSLEEP = 35


def find_pid(name):
    try:
        out = subprocess.run(
            ["pgrep", "-x", name], capture_output=True, text=True, check=False
        ).stdout.split()
    except FileNotFoundError:
        sys.exit("pgrep not available")
    return int(out[-1]) if out else None


def read_syscall(path):
    """Return (number, [arg0..arg5]) or None if the task is running."""
    try:
        with open(path) as fh:
            raw = fh.read().split()
    except PermissionError:
        sys.exit(
            "cannot read a task's syscall -- run under sudo.\n"
            "The tool runs as root, so only root or a tracer may inspect it."
        )
    except (FileNotFoundError, ProcessLookupError):
        return None
    if not raw or raw[0] in ("running", "-1"):
        return None
    return int(raw[0]), [int(a, 16) for a in raw[1:7]]


def syscall_name(number):
    return {
        SYS_IOCTL: "ioctl",
        SYS_FUTEX: "futex",
        SYS_READ: "read",
        SYS_WRITE: "write",
        SYS_NANOSLEEP: "nanosleep",
    }.get(number, f"syscall {number}")


def describe_bulk(pid, tid, ptr):
    try:
        with open(f"/proc/{pid}/task/{tid}/mem", "rb") as mem:
            mem.seek(ptr)
            ep, length, timeout, _data = struct.unpack(BULK_FMT, mem.read(24))
    except (OSError, struct.error) as exc:
        return f"USBDEVFS_BULK (struct unreadable: {exc})"
    direction = "IN, board must reply" if ep & 0x80 else "OUT, board must ACK"
    tail = ", timeout INFINITE" if timeout == 0 else ""
    return f"USBDEVFS_BULK ep=0x{ep:02x} ({direction}) len={length}{tail}"


def main():
    pid = find_pid(sys.argv[1] if len(sys.argv) > 1 else "fbfdownloader")
    if pid is None:
        sys.exit("no such process running")

    tasks = sorted(os.listdir(f"/proc/{pid}/task"))
    print(f"pid {pid}: {len(tasks)} thread(s)\n")

    for tid in tasks:
        try:
            with open(f"/proc/{pid}/task/{tid}/status") as fh:
                state = next(
                    (l.split()[1] for l in fh if l.startswith("State:")), "?"
                )
            with open(f"/proc/{pid}/task/{tid}/comm") as fh:
                comm = fh.read().strip()
        except OSError:
            continue

        args = read_syscall(f"/proc/{pid}/task/{tid}/syscall")
        if args is None:
            note = "running, not blocked"
        else:
            number, a = args
            note = syscall_name(number)
            if number == SYS_IOCTL and a[1] == USBDEVFS_BULK:
                note += "  ->  " + describe_bulk(pid, tid, a[2])

        # D is uninterruptible: parked in the kernel, no signal will move it.
        flag = "   <== uninterruptible, this is the one" if state == "D" else ""
        print(f"  tid {tid:<7} {state}  {comm:<16} {note}{flag}")

    print(
        "\nD state is the thread that matters. S on a main thread usually just\n"
        "means it is joining the worker: futex is a userspace lock, not USB."
    )


if __name__ == "__main__":
    main()