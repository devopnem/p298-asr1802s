#!/usr/bin/env python3
"""Drive the P298's WTPTP session ourselves, with full byte-level logging.

Every command format here was recovered from a usbmon capture of a working
vendor run, not guessed. See docs/recovery/WTPTP-WIRE.md.

The point is to be able to send something the vendor tool never does. It always
inserts a Preamble before each image; the board ACKs the first one and returns
nothing for the second. With --next select we skip the Preamble and ask
SelectImage directly, which is the one experiment the vendor tool structurally
cannot perform.

    sudo tools/wtp-host.py --next select --seconds 30

Board OFF, start this first, then power-cycle when it says it is waiting.
"""

import argparse
import ctypes
import fcntl
import os
import struct
import sys
import time

USBDEVFS_BULK = 0xC0185502
USBDEVFS_CLAIMINTERFACE = 0x80085514
EP_OUT, EP_IN = 0x01, 0x81

# --- recovered wire format -------------------------------------------------
PREAMBLE = bytes.fromhex("00 d3 02 2b")          # OUT 4,  reads up to 38
GET_WTP   = bytes.fromhex("2b00000000000000")    # OUT 8,  reads up to 262
GET_VER   = bytes.fromhex("2000000000000000")    # OUT 8,  reads 30
SELECT    = bytes.fromhex("2600000000000000")    # OUT 8,  reads 10
VERIFY    = bytes.fromhex("2700000001000000" + "00")   # OUT 9, reads 6
FINISH    = bytes.fromhex("3000000000000000")    # OUT 8,  reads 6


def dataheader(size, seq=1, flags=4):
    # 2a | seq | 00 | 04 | 04 | 00 00 00 | size as LE32
    return bytes([0x2A, seq, 0x00, flags, flags, 0, 0, 0]) + struct.pack("<I", size)


class Bulk(ctypes.Structure):
    _fields_ = [("ep", ctypes.c_uint), ("len", ctypes.c_uint),
                ("timeout", ctypes.c_uint), ("data", ctypes.c_void_p)]


class Host:
    def __init__(self, dev, timeout_ms):
        self.fd = os.open(dev, os.O_RDWR)
        buf = ctypes.create_string_buffer(64)
        fcntl.ioctl(self.fd, USBDEVFS_CLAIMINTERFACE, ctypes.byref(buf))
        self.timeout_ms = timeout_ms

    def xfer(self, ep, data, want):
        buf = ctypes.create_string_buffer(bytes(want), want)
        bt = Bulk()
        bt.ep, bt.len, bt.timeout = ep, want, self.timeout_ms
        bt.data = ctypes.cast(buf, ctypes.c_void_p)
        t0 = time.time()
        try:
            n = fcntl.ioctl(self.fd, USBDEVFS_BULK, ctypes.byref(bt))
        except OSError as e:
            print(f"    !! ioctl failed: {e.strerror}")
            return None
        dt = time.time() - t0
        if n <= 0:
            print(f"    IN  ep=0x{ep:02x}  ** {dt:.2f}s, 0 bytes -- SILENT **")
            return None
        got = buf.raw[:n]
        print(f"    IN  ep=0x{ep:02x}  {n:>4} B in {dt:.2f}s   {got.hex(' ')}")
        return got

    def cmd(self, label, out, want, note=""):
        print(f"  {label:<28} OUT {len(out):>3} B  {out.hex(' ')}  {note}")
        ok = self.xfer(EP_OUT, out, len(out))
        if ok is None:
            print(f"  {label:<28} ** host->board write not accepted **")
            return None
        return self.xfer(EP_IN, b"", want)

    def close(self):
        os.close(self.fd)


def find_board(wait, vid=0x2ECC, pids=(0x3001, 0x3002, 0x3003)):
    """Wait for the board to enumerate in download mode.

    Download mode is transient -- the module reverts to its normal USB identity
    within seconds unless a session holds it -- so poll sysfs rather than
    relying on lsusb at one instant.
    """
    deadline = time.time() + wait
    base = "/sys/bus/usb/devices"
    while time.time() < deadline:
        for entry in os.listdir(base):
            parts = entry.split("-")
            if len(parts) != 2:
                continue
            vid_p, pid_p = parts
            try:
                if int(vid_p, 16) != vid or int(pid_p, 16) not in pids:
                    continue
            except ValueError:
                continue
            node = f"/dev/bus/usb/{vid_p}/{pid_p}"
            if os.path.exists(node):
                return node
        time.sleep(0.2)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=60)
    ap.add_argument("--timeout", type=int, default=4000)
    ap.add_argument("--next", choices=("select", "getwtp", "preamble", "data"),
                    default="select",
                    help="what to try after the header: skip the Preamble and ask "
                         "SelectImage directly (select), poll (getwtp), behave "
                         "like the vendor tool (preamble), or send the payload (data)")
    ap.add_argument("--payload", default=None, help="file to send as image 1")
    ap.add_argument("--device", default=None)
    args = ap.parse_args()

    if os.geteuid() != 0:
        print("must run as root (usbfs needs it)", file=sys.stderr)
        return 2

    print(f"waiting up to {args.wait}s for the board in download mode...")
    dev = args.device or find_board(args.wait)
    if not dev:
        print("not found. power-cycle the board while this is waiting.", file=sys.stderr)
        return 2

    print(f"\nboard: {dev}\n")
    h = Host(dev, args.timeout)
    try:
        print("=== session start (reproduces the vendor tool exactly) ===")
        h.cmd("Preamble", PREAMBLE, 38)
        h.cmd("GetWtpMessage", GET_WTP, 262)
        h.cmd("GetVersion", GET_VER, 30)
        r = h.cmd("SelectImage", SELECT, 10)
        if r:
            print(f"      -> image ID = 0x{struct.unpack_from('<I', r, 6)[0]:08X}")
        h.cmd("Verify(0x27)", VERIFY, 6)

        payload = open(args.payload, "rb").read() if args.payload else None
        size = len(payload) if payload else 248
        r = h.cmd("DataHeader", dataheader(size), 10)
        if r:
            print(f"      -> return flag = 0x{r[4]:02x}, BufferSize = {r[6]}")

        if payload:
            print(f"\n=== sending image 1 ({size} B) ===")
            h.xfer(EP_OUT, payload, size)

        print(f"\n=== THE EXPERIMENT: next step = --next {args.next} ===")
        if args.next == "select":
            print("vendor tool would send a Preamble here and hang.")
            print("we ask SelectImage directly instead.")
            h.cmd("SelectImage (no preamble)", SELECT, 10)
        elif args.next == "getwtp":
            h.cmd("GetWtpMessage (poll)", GET_WTP, 262)
        elif args.next == "data":
            if payload:
                h.xfer(EP_OUT, payload, size)
            else:
                print("need --payload for --next data")
        else:
            h.cmd("Preamble (vendor behaviour)", PREAMBLE, 38)

        print("\ndone.")
    finally:
        h.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())