#!/usr/bin/env python3
"""wtp-probe.py -- talk to a board in WTPTP download mode without swdl_linux.

Why this exists
---------------
swdl_linux stalls with an unanswered request and `timeout = 0`, so it can never
fail and never returns the device. That leaves us unable to ask the only
question that matters now: is the board still alive after file 1, or has it gone
quiet?

This speaks the same protocol directly, with a deadline the tool does not have,
and closes the fd on the way out so the device is free afterwards.

Observed from the tool's own trace, which is what this reproduces:

  ioctl #2  ep=0x01 OUT  len=4     the Preamble, 00 D3 02 2B
  ioctl #3  ep=0x81 IN   len=0x26  38-byte reply -- succeeds at session start

The same two transfers fail for the second file. Sending them by hand tells us
whether the board is still answering, which distinguishes "the target went
quiet" from "the tool is confused".

Usage
-----
  sudo tools/wtp-probe.py                       # find the board, probe it
  sudo tools/wtp-probe.py --raw                 # just try to read
  sudo tools/wtp-probe.py --bytes "00 d3 02 2b"  # send something else
  sudo tools/wtp-probe.py --wait 30             # wait for the board to appear

Exit status: 0 if the board answered, 1 if it did not, 2 on setup trouble.
"""

import argparse
import ctypes
import glob
import os
import struct
import sys
import time

# _IOWR('U', 2, 24) -- the size is 24 because the tool's kernel headers describe
# struct usbdevfs_bulktransfer as {u32 ep; u32 len; u32 timeout; void *data;}
# and the ioctl returns the transferred count directly, so no actual_length.
USBDEVFS_BULK = 0xC0185502
# _IOR('U', 15, int) -- matches the first ioctl the tool makes after opening.
USBDEVFS_CLAIMINTERFACE = 0x8004550F

EP_OUT = 0x01
EP_IN = 0x81

# The 4-byte Preamble, read out of swdl_linux at 0x5fff52:
#   movb $0xd3,0x1(%rsp) / movb $0x02,0x2(%rsp) / movb $0x2b,0x3(%rsp)
PREAMBLE = bytes((0x00, 0xD3, 0x02, 0x2B))


class BulkTransfer(ctypes.Structure):
    _fields_ = [
        ("ep", ctypes.c_uint32),
        ("len", ctypes.c_uint32),
        ("timeout", ctypes.c_uint32),
        ("data", ctypes.c_void_p),
    ]


def ioc(code, arg):
    buf = ctypes.create_string_buffer(struct.pack("I", arg))
    fcntl_buf = ctypes.create_string_buffer(
        ctypes.addressof(buf), ctypes.sizeof(buf))
    rc = fcntl.ioctl(fd, code, fcntl_buf)
    return rc, struct.unpack("I", buf.raw)[0]


def find_board(wait=0):
    deadline = time.time() + wait
    while True:
        for path in sorted(glob.glob("/dev/bus/usb/*/*")):
            try:
                with open(path, "rb") as fh:
                    fh.seek(0x1000)
                    if fh.read(2) == b"\xec\x86":
                        return path
            except OSError:
                continue
        if time.time() >= deadline:
            return None
        time.sleep(0.5)


import fcntl  # noqa: E402  (after find_board so the docstring reads first)

fd = None


def bulk(ep, buf, timeout_ms):
    """One USBDEVFS_BULK transfer. Returns (ok, nbytes_or_errno, message)."""
    cbuf = ctypes.create_string_buffer(bytes(buf), len(buf))
    bt = BulkTransfer()
    bt.ep = ep
    bt.len = len(buf)
    bt.timeout = timeout_ms
    bt.data = ctypes.cast(cbuf, ctypes.c_void_p)
    try:
        n = fcntl.ioctl(fd, USBDEVFS_BULK, ctypes.byref(bt))
    except OSError as exc:
        return False, -1, f"ioctl failed: {exc.strerror}"
    if n < 0:
        return False, n, f"ioctl returned {n}"
    return True, n, cbuf.raw[:n].hex(" ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=0,
                    help="seconds to wait for the board to appear")
    ap.add_argument("--timeout", type=int, default=3000,
                    help="per-transfer timeout in ms")
    ap.add_argument("--bytes", help="hex bytes to send instead of the Preamble")
    ap.add_argument("--raw", action="store_true",
                    help="only attempt a read, send nothing")
    ap.add_argument("--device", help="explicit /dev/bus/usb/BBB/DDD")
    args = ap.parse_args()

    global fd
    if os.geteuid() != 0:
        print("must run as root (usbfs needs it)", file=sys.stderr)
        return 2

    dev = args.device or find_board(args.wait)
    if not dev:
        print("board not found on /dev/bus/usb -- power-cycle it into "
              "download mode, or pass --wait", file=sys.stderr)
        return 2

    print(f"device : {dev}")
    fd = os.open(dev, os.O_RDWR)
    try:
        rc, iface = ioc(USBDEVFS_CLAIMINTERFACE, 0)
        print(f"claim  : rc={rc} interface={iface}")

        if not args.raw:
            payload = PREAMBLE
            if args.bytes:
                payload = bytes.fromhex(args.bytes.replace(" ", ""))
            print(f"\nsending {len(payload)} bytes: {payload.hex(' ')}")
            ok, n, msg = bulk(EP_OUT, payload, args.timeout)
            print(f"  OUT ep=0x{EP_OUT:02x}: {'ok' if ok else 'FAILED'} "
                  f"n={n} {msg}")
            if not ok:
                print("\nThe board did not accept the command. Either it is "
                      "already past this stage, or it has stopped answering.")
                return 1

        print(f"\nreading (ep=0x{EP_IN:02x}, timeout {args.timeout} ms)...")
        t0 = time.time()
        ok, n, msg = bulk(EP_IN, bytes(args.timeout), args.timeout)
        dt = time.time() - t0
        if ok and n > 0:
            print(f"  IN  ep=0x{EP_IN:02x}: {n} bytes in {dt:.3f}s")
            print(f"  data: {msg}")
            return 0
        print(f"  IN  ep=0x{EP_IN:02x}: NO DATA after {dt:.3f}s "
              f"(n={n}) {msg}")
        print("\nThe board is silent. This is the same condition swdl_linux "
              "hangs in, but\nhere it is bounded: the transfer returned instead "
              "of waiting forever.")
        return 1
    finally:
        os.close(fd)
        print("\ndevice closed")


if __name__ == "__main__":
    sys.exit(main())