#!/usr/bin/env python3
"""Send commands to the P298 U-Boot console and log the replies.

Why this instead of uart-spam.py
--------------------------------
The U-Boot environment contains `autostart=yes`. In U-Boot's
`autoboot_command_autostart()`:

    static int autoboot_command_autostart(const char *s)
    {
            if (!autostart)
                    autoboot_command(s);
            return 1;
    }

With `autostart` set, `autoboot_command()` is never called, so the
"Hit any key to stop autoboot" countdown never runs and `tstc()` is never
polled. **No keypress can interrupt the boot, and no length of key-spamming
will help.** `bootdelay=1` is irrelevant on this unit.

What that implies is more useful: `bootcmd=mrvlboot` runs immediately and
fails silently under `quiet=1`, and control then falls through to U-Boot's
command loop. The CLI prints its banner and prompt through code paths that
`quiet` suppresses, so the prompt is invisible -- but the console is still
live and still accepts input.

So we do not need to interrupt anything. We just need to talk to it.

Usage:
    sudo ./uart-exec.py /dev/ttyUSB0 echo HELLO printenv bootdelay
    sudo ./uart-exec.py /dev/ttyUSB0 --settle 3 printenv bdinfo mtdparts

Only sends commands. Reads nothing but the serial port; touches no flash.
"""
from __future__ import annotations

import argparse
import os
import select
import sys
import termios
import time

BAUD_CONSTANTS = {n: getattr(termios, "B" + str(n))
                  for n in (9600, 19200, 38400, 57600, 115200, 230400)
                  if hasattr(termios, "B" + str(n))}

# Deliberately read-only / display-only. Nothing here writes to the board.
DEFAULT_COMMANDS = [
    "version",
    "echo P298_UART_ALIVE",
    "printenv bootcmd",
    "printenv bootdelay",
    "printenv autostart",
    "printenv loadaddr",
]


def configure(fd: int, baud: int) -> bool:
    speed = BAUD_CONSTANTS.get(baud)
    if speed is None:
        print(f"FATAL: no termios constant for {baud} baud", file=sys.stderr)
        return False
    a = termios.tcgetattr(fd)
    a[0] &= ~(termios.BRKINT | termios.ICRNL | termios.INPCK |
              termios.ISTRIP | termios.IXON)
    a[1] &= ~termios.OPOST
    a[2] &= ~(termios.CSIZE | termios.PARENB)
    a[2] |= termios.CS8 | termios.CREAD | termios.CLOCAL
    a[3] &= ~(termios.ECHO | termios.ICANON | termios.IEXTEN | termios.ISIG)
    a[4] = a[5] = speed
    a[6][termios.VMIN] = 0
    a[6][termios.VTIME] = 1
    termios.tcsetattr(fd, termios.TCSANOW, a)
    actual = termios.tcgetattr(fd)[4] & termios.CBAUD
    if actual != speed:
        print(f"FATAL: wanted {baud} ({speed:#x}), port has {actual:#x}",
              file=sys.stderr)
        return False
    return True


def drain(fd: int, seconds: float, quiet: bool) -> bytes:
    """Read and print whatever arrives for `seconds`. Returns the raw bytes."""
    end = time.time() + seconds
    start = end - seconds
    got = bytearray()
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.05)
        if not r:
            continue
        try:
            data = os.read(fd, 4096)
        except BlockingIOError:
            continue
        if not data:
            continue
        got += data
        if not quiet:
            sys.stdout.write(f"[{time.time() - start:6.2f}s] "
                             f"{data.decode('latin1')}")
        sys.stdout.flush()
    return bytes(got)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", default="/dev/ttyUSB0")
    # Repeated --cmd rather than a bare nargs="*": with a leading positional
    # port, argparse cannot tell the port from the first command, and it
    # silently swallows "echo" as the device name.
    ap.add_argument("--cmd", action="append", dest="commands", metavar="CMD",
                    help="command to send; repeat for several. "
                         "Default is a read-only probe set.")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--settle", type=float, default=1.5,
                    help="seconds to listen before sending the first command")
    ap.add_argument("--gap", type=float, default=1.5,
                    help="seconds to listen after each command")
    ap.add_argument("--seconds", type=float, default=0,
                    help="total run time; 0 = one pass (default). For a COLD "
                         "BOARD, set this and --every so the probe is resent "
                         "until U-Boot is actually up.")
    ap.add_argument("--every", type=float, default=8.0,
                    help="seconds between repeat passes when --seconds > 0")
    ap.add_argument("--stop-on-reply", default="P298_UART_ALIVE",
                    help="end early once this string is seen; empty to disable")
    ap.add_argument("--log", help="also append raw received data here")
    args = ap.parse_args()

    cmds = args.commands or DEFAULT_COMMANDS

    try:
        fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    except OSError as exc:
        print(f"FATAL: cannot open {args.port}: {exc}", file=sys.stderr)
        return 2
    if not configure(fd, args.baud):
        os.close(fd)
        return 2

    logfh = open(args.log, "ab", buffering=0) if args.log else None

    print(f"# {args.port} @ {args.baud} verified. Listening {args.settle}s "
          f"(board may already be sitting at an invisible prompt), then "
          f"sending {len(cmds)} command(s).", file=sys.stderr)

    deadline = time.time() + args.seconds if args.seconds else None
    seen = b""
    try:
        drain(fd, args.settle, quiet=False)

        while True:
            for cmd in cmds:
                sys.stdout.write(f"\n>>> {cmd}\n")
                sys.stdout.flush()
                try:
                    os.write(fd, (cmd + "\r").encode())
                except BlockingIOError:
                    pass
                got = drain(fd, args.gap, quiet=False)
                seen += got
                if args.stop_on_reply and args.stop_on_reply.encode() in seen:
                    print(f"\n# got {args.stop_on_reply!r} - the console is "
                          f"live. Stopping.", file=sys.stderr)
                    raise KeyboardInterrupt

            if deadline is None or time.time() >= deadline:
                break
            wait = min(args.every, max(0.0, deadline - time.time()))
            if wait <= 0:
                break
            sys.stdout.write(f"\n# --- no reply yet; retrying in {wait:.0f}s "
                             f"(power the board on now if you have not) ---\n")
            sys.stdout.flush()
            time.sleep(wait)

    except KeyboardInterrupt:
        pass
    finally:
        if logfh:
            logfh.close()
        os.close(fd)

    print("\n# done.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())