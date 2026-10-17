#!/usr/bin/env python3
"""Capture the full USB byte stream of a download session with usbmon.

We have never seen a single byte the board sends. The vendor tool logs its own
interpretation -- "Version: 3311", "Platform ready status: 0", "can not get
ACK" -- but not the bytes behind them. That has made every conclusion an
inference from somebody else's parser.

This records the raw traffic instead, so the WTPTP exchange can be read
directly: every command the host sends, every reply the board returns, and
crucially what happens in the moment after image 1 completes.

Needs the usbmon module and debugfs:

    doas modprobe usbmon
    doas mount -t debugfs debugfs /sys/kernel/debug

Then, in one terminal:

    sudo tools/usbmon-capture.py --seconds 120

and in another, start the download and power-cycle the board. Stop the capture
with Ctrl-C, or let --seconds expire.

Output is raw usbmon text plus a decoded summary. The text is the record of
truth; the summary is only a convenience and can be wrong.

    usbmon text format, per line:
      <type><status> <bus> <dev> <ep> <status> <timestamp> [payload]
    type is S submit, C complete, E error; the endpoint character says
    direction (i = device to host, o = host to device); payload appears as
    trailing hex, possibly continued on following lines.
"""

import argparse
import os
import re
import subprocess
import sys
import time

MON_ROOT = "/sys/kernel/debug/usb/usbmon"
DEFAULT_VID = 0x2ECC
DEFAULT_PIDS = (0x3001, 0x3002, 0x3003)


def check_prereqs():
    missing = []
    if not os.path.exists(MON_ROOT):
        missing.append(
            f"{MON_ROOT} not present -- is debugfs mounted?\n"
            "  doas mount -t debugfs debugfs /sys/kernel/debug"
        )
        if not os.path.exists("/sys/module/usbmon"):
            missing.append(
                "usbmon module not loaded\n"
                "  doas modprobe usbmon"
            )
    for m in missing:
        print(m, file=sys.stderr)
    return not missing


def busnum_for(vid, pids):
    """Which usbmon bus node corresponds to our device."""
    try:
        out = subprocess.run(["lsusb", "-d", f"{vid:04x}:%04x" % pids[0]],
                             capture_output=True, text=True, check=False).stdout
    except FileNotFoundError:
        return None
    if not out.strip():
        return None
    m = re.search(r"Bus (\d+)", out)
    return int(m.group(1)) if m else None


def decode(line):
    """Best-effort one-line summary. Never trust this over the raw text."""
    parts = line.split()
    if len(parts) < 7:
        return None
    kind, direction, ts = parts[0], parts[1], parts[5] if len(parts) > 5 else ""
    if direction not in ("Bo", "Bi", "Co", "Ci"):
        return None
    ep = parts[4]
    arrow = "host->board" if direction.endswith("o") else "board->host"
    payload = line.split(None, 7)[7] if len(parts) > 7 else ""
    return f"  {ts:>14}  ep{ep:<3} {arrow:<12} {payload}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--out", default=None)
    ap.add_argument("--vid", type=lambda s: int(s, 0), default=DEFAULT_VID)
    args = ap.parse_args()

    if not check_prereqs():
        return 2

    bus = busnum_for(args.vid, DEFAULT_PIDS)
    if bus is None:
        print("board is not enumerated on the host -- start the download, then "
              "capture while it is still present.", file=sys.stderr)
        bus = 1

    node = f"{MON_ROOT}/{bus}u"
    if not os.path.exists(node):
        print(f"{node} does not exist; listing what is there:", file=sys.stderr)
        for n in sorted(os.listdir(MON_ROOT)):
            print(f"  {n}", file=sys.stderr)
        return 2

    out = args.out or f"/tmp/usbmon-{time.strftime('%H%M%S')}.txt"
    print(f"capturing {node} for {args.seconds}s -> {out}")
    print("start the download now, and power-cycle the board when prompted.")
    print("Ctrl-C to stop early.\n")

    deadline = time.time() + args.seconds
    captured = 0
    with open(node, errors="replace") as src, open(out, "w") as dst:
        while time.time() < deadline:
            line = src.readline()
            if not line:
                time.sleep(0.05)
                continue
            dst.write(line)
            dst.flush()
            captured += 1
            if args.seconds and (captured % 50 == 0 or "Bo" in line or "Co" in line):
                d = decode(line.rstrip("\n"))
                if d and captured < 4000:
                    print(d)

    print(f"\ncaptured {captured} lines -> {out}")
    print("raw text is the record; the summary above may drop continuation "
          "lines of split payloads.")
    return 0


if __name__ == "__main__":
    sys.exit(main())