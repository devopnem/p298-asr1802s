#!/usr/bin/env python3
"""Spam the P298 UART with keystrokes while logging everything received.

Why this exists
---------------
The P298's U-Boot has `bootdelay=1`, and the OBM hands over with
`get_quiet_from_obm params->quiet: 1`. With quiet set, the
"Hit any key to stop autoboot: 1" countdown is suppressed, so the one-second
window is invisible. Hand-tapping is a coin flip.

Worse, the OBM takes a long time to reach U-Boot: DDR calibration and the
SPI-NAND scan in `boot-oem-to-uboot.log` run for many seconds. An earlier
version of this script stopped sending keys after 15 s and simply missed the
window on a later boot. So by default it now keeps sending until the run ends,
and every received line is prefixed with the elapsed time so you can see
exactly when U-Boot came up relative to the keystrokes.

The prompt this is aiming for is `Marvell>> `, not `=>`.

Usage:
    sudo ./uart-spam.py /dev/ttyUSB0 --seconds 90
    sudo ./uart-spam.py /dev/ttyUSB0 --seconds 90 --log /tmp/p298-uart.log

Start it, THEN power the board on. Only writes to the serial port; never
touches the board's flash.
"""
from __future__ import annotations

import argparse
import os
import select
import sys
import termios
import time

# ispeed/ospeed take the B<n> *constants* (B115200 == 4098), never the literal
# rate: attrs[4] = 115200 gives cflag & CBAUD == 0, tcsetattr fails EINVAL, and
# the port stays at its default speed -- which looks exactly like the board
# spewing binary. This interpreter also does not export
# termios.cfsetispeed/cfsetospeed/cfsetspeed at all, so use the constants.
BAUD_CONSTANTS = {n: getattr(termios, "B" + str(n))
                  for n in (9600, 19200, 38400, 57600, 115200, 230400)
                  if hasattr(termios, "B" + str(n))}

# Rotate these rather than sending one character repeatedly: some autoboot
# implementations treat a bare newline as line noise and ignore it.
KEYS = (b" ", b"\r", b"\n", b"\x03")


def configure(fd: int, baud: int) -> int:
    speed = BAUD_CONSTANTS.get(baud)
    if speed is None:
        print(f"FATAL: no termios constant for {baud} baud. "
              f"Known: {sorted(BAUD_CONSTANTS)}", file=sys.stderr)
        return 0

    a = termios.tcgetattr(fd)
    a[0] &= ~(termios.BRKINT | termios.ICRNL | termios.INPCK |
              termios.ISTRIP | termios.IXON)
    a[1] &= ~termios.OPOST
    a[2] &= ~(termios.CSIZE | termios.PARENB)
    a[2] |= termios.CS8 | termios.CREAD | termios.CLOCAL
    a[3] &= ~(termios.ECHO | termios.ICANON | termios.IEXTEN | termios.ISIG)
    a[4] = speed                      # ispeed
    a[5] = speed                      # ospeed
    a[6][termios.VMIN] = 0
    a[6][termios.VTIME] = 1
    termios.tcsetattr(fd, termios.TCSANOW, a)

    actual = termios.tcgetattr(fd)[4] & termios.CBAUD
    if actual != speed:
        print(f"FATAL: asked for {baud} baud (const {speed:#x}), port reports "
              f"{actual:#x}. Something else (picocom?) may still hold the "
              f"device, or this adapter lacks that rate.", file=sys.stderr)
        return 0
    return speed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=int, default=90,
                    help="total run time")
    ap.add_argument("--spam", type=int, default=0,
                    help="seconds of keystrokes; 0 (default) = whole run")
    ap.add_argument("--interval", type=float, default=0.08,
                    help="seconds between keystrokes")
    ap.add_argument("--log", help="also append received data to this file")
    ap.add_argument("--no-timestamps", action="store_true")
    args = ap.parse_args()

    try:
        fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    except OSError as exc:
        print(f"FATAL: cannot open {args.port}: {exc}", file=sys.stderr)
        return 2

    if not configure(fd, args.baud):
        os.close(fd)
        return 2

    logfh = open(args.log, "ab", buffering=0) if args.log else None
    spam_for = args.seconds if args.spam == 0 else args.spam

    print(f"# {args.port} @ {args.baud} 8N1 verified. Sending keys every "
          f"{args.interval}s for {spam_for}s (total {args.seconds}s). "
          f"POWER THE BOARD ON NOW.", file=sys.stderr)

    start = time.time()
    next_send = start
    pending = b""
    try:
        while time.time() - start < args.seconds:
            now = time.time()
            if now - start < spam_for and now >= next_send:
                try:
                    os.write(fd, KEYS[int(now / args.interval) % len(KEYS)])
                except BlockingIOError:
                    pass
                next_send = now + args.interval

            r, _, _ = select.select([fd], [], [], 0.02)
            if not r:
                continue
            try:
                chunk = os.read(fd, 4096)
            except BlockingIOError:
                continue
            if not chunk:
                continue

            if logfh:
                logfh.write(chunk)
            if args.no_timestamps:
                sys.stdout.write(chunk.decode("latin1"))
                sys.stdout.flush()
                continue

            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                sys.stdout.write(f"[{time.time() - start:7.2f}s] "
                                 f"{line.decode('latin1')}\n")
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        if pending:
            sys.stdout.write(f"[{time.time() - start:7.2f}s] "
                             f"{pending.decode('latin1')}\n")
        if logfh:
            logfh.close()
        os.close(fd)

    print("\n# done. If you saw 'Marvell>>':", file=sys.stderr)
    print("#   setenv quiet 0", file=sys.stderr)
    print("#   printenv", file=sys.stderr)
    print("#   bdinfo", file=sys.stderr)
    print("#   mtdparts", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())