#!/usr/bin/env python3
"""Spam the P298 UART with keystrokes while logging everything received.

Why this exists
---------------
The P298's U-Boot has `bootdelay=1`, and the OBM hands over with
`get_quiet_from_obm params->quiet: 1`. With quiet set, the
"Hit any key to stop autoboot: 1" countdown is *suppressed*, so the one-second
window is invisible. Tapping a key by hand is a coin flip.

So: start this, THEN power on. It sends a space every 100 ms for the first
`--spam` seconds, which covers the window regardless of when the board boots,
and prints everything the board sends.

The prompt this is aiming for is `Marvell>> `, not `=>`.

Usage:
    sudo ./uart-spam.py /dev/ttyUSB0 --seconds 40
    sudo ./uart-spam.py /dev/ttyUSB0 --seconds 40 --log /tmp/p298-uart.log

Only writes to the serial port. Never touches the board's flash.
"""
import argparse
import os
import select
import sys
import termios
import time
import tty


# ispeed/ospeed take the B<n> *constants* (B115200 == 4098), never the
# literal rate: attrs[4] = 115200 gives cflag & CBAUD == 0 and tcsetattr
# fails EINVAL, leaving the port at its default speed, which looks like the
# board spewing binary. This interpreter also does not export
# termios.cfsetispeed/cfsetospeed/cfsetspeed at all, so use the constants.
BAUD_CONSTANTS = {n: getattr(termios, "B" + str(n))
                  for n in (9600, 19200, 38400, 57600, 115200, 230400)
                  if hasattr(termios, "B" + str(n))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=int, default=40,
                    help="total time to run")
    ap.add_argument("--spam", type=int, default=15,
                    help="how many seconds to keep sending keys")
    ap.add_argument("--key", default=" ", help="character to send")
    ap.add_argument("--log", help="also append received data to this file")
    args = ap.parse_args()

    fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        # termios ispeed/ospeed take the B<n> *constants* (B115200 == 4098),
        # not the literal rate. Passing 115200 yields cflag & CBAUD == 0 and
        # tcsetattr fails with EINVAL, leaving the port at its default speed --
        # which is exactly what produced unreadable garbage on the first run.
        speed = BAUD_CONSTANTS.get(args.baud)
        if speed is None:
            print(f"FATAL: no termios constant for {args.baud} baud. "
                  f"Known: {sorted(BAUD_CONSTANTS)}", file=sys.stderr)
            os.close(fd)
            return 2

        attrs = termios.tcgetattr(fd)
        attrs[0] &= ~(termios.BRKINT | termios.ICRNL | termios.INPCK |
                      termios.ISTRIP | termios.IXON)
        attrs[1] &= ~termios.OPOST
        attrs[2] &= ~(termios.CSIZE | termios.PARENB)
        attrs[2] |= termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[3] &= ~(termios.ECHO | termios.ICANON | termios.IEXTEN |
                      termios.ISIG)
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 1
        attrs[4] = speed                      # ispeed  (B<n> constant)
        attrs[5] = speed                      # ospeed  (B<n> constant)
        termios.tcsetattr(fd, termios.TCSANOW, attrs)

        # read it back and refuse to continue on a mismatch: a wrong baud
        # looks like the board spewing binary and wastes everyone's time
        back = termios.tcgetattr(fd)
        actual = back[4] & termios.CBAUD
        if actual != speed:
            print(f"FATAL: asked for {args.baud} baud (const {speed:#x}), "
                  f"port reports {actual:#x}. Something else (picocom?) may "
                  f"still hold the device, or this adapter lacks that rate.",
                  file=sys.stderr)
            os.close(fd)
            return 2
    except Exception as exc:      # noqa: BLE001
        print(f"FATAL: cannot configure {args.port} for {args.baud} baud: {exc}",
              file=sys.stderr)
        os.close(fd)
        return 2

    logfh = open(args.log, "ab", buffering=0) if args.log else None

    print(f"# {args.port} @ {args.baud} 8N1 — spamming '{args.key}' for "
          f"{args.spam}s, total {args.seconds}s. Power the board on NOW.",
          file=sys.stderr)

    start = time.time()
    next_send = start
    try:
        while time.time() - start < args.seconds:
            now = time.time()
            if now - start < args.spam and now >= next_send:
                try:
                    os.write(fd, args.key.encode())
                except BlockingIOError:
                    pass
                next_send = now + 0.1

            r, _, _ = select.select([fd], [], [], 0.05)
            if r:
                try:
                    data = os.read(fd, 4096)
                except BlockingIOError:
                    continue
                if data:
                    sys.stdout.write(data.decode("latin1"))
                    sys.stdout.flush()
                    if logfh:
                        logfh.write(data)
    except KeyboardInterrupt:
        pass
    finally:
        if logfh:
            logfh.close()
        os.close(fd)

    print("\n\n# done. If you saw 'Marvell>>', the shell is yours:",
          file=sys.stderr)
    print("#   setenv quiet 0", file=sys.stderr)
    print("#   printenv", file=sys.stderr)
    print("#   bdinfo", file=sys.stderr)
    print("#   mtdparts", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())