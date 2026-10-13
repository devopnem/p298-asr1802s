#!/usr/bin/env python3
"""Capture the P298's transient USB download-mode enumeration.

The OBM enumerates and then drops within seconds ("USB Enum timeout"), which is
faster than `watch -n1 lsusb` can resolve. This polls sysfs at ~50 Hz, records
every device that appears or disappears with a timestamp, and tails the kernel
log for the matching enumeration messages.

Read-only: touches nothing but /sys and the kernel log.

    sudo tools/usb-watch.py                  # 60 s
    sudo tools/usb-watch.py --seconds 180    # longer
    sudo tools/usb-watch.py --out /tmp/usb.log

Then power-cycle the board while it runs.
"""

import argparse
import re
import os
import subprocess
import sys
import time
from pathlib import Path

SYS = Path("/sys/bus/usb/devices")
DURATION_DEFAULT = 60

# sysfs names three kinds of entry:
#   usb1                root hub          (starts with "usb", no colon)
#   1-10                a device          (bus-port, no colon)
#   1-10:1.0            an interface      (bus-port:config.interface)
# Only devices and interfaces carry idVendor/idProduct; we key on the
# bus-port prefix so an interface is not counted as a separate device.
RE_ROOT = re.compile(r"^usb\d+$")
RE_DEV = re.compile(r"^\d+-[\d.]+$")
RE_IFACE = re.compile(r"^\d+-[\d.]+:\d+\.\d+$")


def bound_drivers(bus_port: str) -> list[str]:
    """Kernel drivers that have claimed this device's interfaces.

    A non-empty result is the thing to look for: if the kernel binds, say,
    cdc_acm or usb-storage to the board's download-mode device, the vendor
    tool can no longer talk to it. Documented as a real failure mode for
    Yuge ASR module upgrades ("Linux driver conflict").
    """
    out = []
    try:
        for dev in SYS.iterdir():
            if not RE_IFACE.match(dev.name):
                continue
            if dev.name.split(":")[0] != bus_port:
                continue
            drv = dev / "driver"
            if drv.exists():
                out.append(drv.resolve().name)
    except OSError:
        pass
    return sorted(set(out))


def snapshot() -> dict[str, tuple]:
    """bus-port -> (vid_pid, product, manufacturer, busnum)."""
    out: dict[str, tuple] = {}
    try:
        entries = sorted(SYS.iterdir())
    except OSError:
        return out
    for dev in entries:
        name = dev.name
        if RE_ROOT.match(name) or RE_DEV.match(name):
            key = name
        elif RE_IFACE.match(name):
            key = name.split(":")[0]
        else:
            continue
        try:
            vid = (dev / "idVendor").read_text().strip()
            pid = (dev / "idProduct").read_text().strip()
        except OSError:
            continue

        def rd(f: str) -> str:
            try:
                return (dev / f).read_text(errors="replace").strip()
            except OSError:
                return "?"

        out[key] = (
            f"{vid}:{pid}",
            rd("product"),
            rd("manufacturer"),
            rd("busnum"),
        )
    return out


def is_interesting(vid_pid: str, product: str, manufacturer: str) -> bool:
    blob = f"{vid_pid} {product} {manufacturer}".lower()
    needles = ("1286", "8130", "marvell", "asr", "kagu", "nezha", "mifi", "wtp")
    return any(n in blob for n in needles)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=DURATION_DEFAULT)
    ap.add_argument("--interval", type=float, default=0.02,
                    help="poll period, default 0.02 s (~50 Hz)")
    ap.add_argument("--out", default=None, help="also write the transcript here")
    args = ap.parse_args()

    lines: list[str] = []

    def emit(text: str) -> None:
        stamp = time.strftime("%H:%M:%S") + f".{int(time.time() % 1 * 1000):03d}"
        line = f"[{stamp}] {text}"
        print(line, flush=True)
        lines.append(line)

    # dmesg baseline, so we only show what is new
    try:
        dmesg_mark = subprocess.run(
            ["dmesg"], capture_output=True, text=True, check=False
        ).stdout.count("\n")
    except OSError:
        dmesg_mark = 0

    emit(f"baseline: {len(snapshot())} usb device(s); "
         f"watching {args.seconds}s at {1 / args.interval:.0f} Hz")

    prev = snapshot()
    interesting_seen = False
    deadline = time.time() + args.seconds

    while time.time() < deadline:
        time.sleep(args.interval)
        cur = snapshot()

        for name in cur.keys() - prev.keys():
            vid_pid, product, maker, bus = cur[name]
            hot = is_interesting(vid_pid, product, maker)
            if hot:
                interesting_seen = True
            emit(f"APPEARED  {name}  {vid_pid}  "
                 f"'{product}'  '{maker}'  bus={bus}"
                 + ("   <<< CANDIDATE" if hot else ""))
            # re-read interfaces: a driver may bind a moment after enumeration
            time.sleep(0.15)
            drv = bound_drivers(name)
            if drv:
                emit(f"  !! driver(s) bound to {name}: {', '.join(drv)}"
                     f"   <<< likely blocks the vendor tool")
            elif hot:
                emit(f"  -- no driver bound to {name} (good)")

        for name in prev.keys() - cur.keys():
            vid_pid, product, maker, _ = prev[name]
            hot = is_interesting(vid_pid, product, maker)
            emit(f"GONE      {name}  {vid_pid}  '{product}'  '{maker}'"
                 + ("   <<< CANDIDATE" if hot else ""))

        prev = cur

    emit("---- new dmesg lines ----")
    try:
        after = subprocess.run(
            ["dmesg"], capture_output=True, text=True, check=False
        ).stdout.splitlines()
        for row in after[dmesg_mark:]:
            if any(k in row.lower() for k in
                   ("usb", "asr", "kagu", "marvell", "nezha", "1286", "8130",
                    "gadget", "dwc3", "otg")):
                emit("dmesg: " + row.strip())
    except OSError:
        emit("dmesg unavailable")

    emit(f"done. candidate device seen: {'YES' if interesting_seen else 'NO'}")

    if args.out:
        Path(args.out).write_text("\n".join(lines) + "\n")
        emit(f"transcript written to {args.out}")

    return 0


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("warning: not root, /sys reads may be incomplete", file=sys.stderr)
    sys.exit(main())
