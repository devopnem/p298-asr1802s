#!/usr/bin/env python3
"""Measure the P298's real SWDownloader transfer budget, end to end.

The handoff brief claims the boot ROM's USB window is 1.58 s and that a
79,928-byte DKB does not fit while a 248-byte header does.  Those are the two
ends of a ladder with nothing in between, so nobody knows the actual budget
-- and the whole "can the transfer be made to fit?" question is unanswerable
without a number.

This script produces that number.  It:

  1. watches sysfs at 200 Hz for the `2ecc:3002` download-mode device and
     records appear/disappear to the millisecond;
  2. launches the vendor tool *before* you power-cycle (the tool must already
     be listening -- `usb-watch.py` showed it opens the device ~150 ms after
     enumeration, so starting it after the fact is the classic false negative);
  3. after the run, parses the per-device `wtp_dev_*.log` for progress markers
     and counts the protocol round trips that actually happened;
  4. prints window, rate, and the implied byte budget.

Read-only with respect to flash: use `p298_probe.blf` (both images
`Enable = 0`) which carries headers only.

    sudo tools/swdl-budget.py -D flashing_tools/p298-swd/p298_probe.blf \
         -b flashing_tools/p298-swd/swdl_linux_p298_v3

    # and to test a patched chunk size in the same command:
    sudo tools/swdl-budget.py -D flashing_tools/p298-swd/p298_probe_small.blf \
         -b flashing_tools/p298-swd/swdl_linux_p298_v2 --chunk 4096

Power-cycle the board when prompted.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SYS = Path("/sys/bus/usb/devices")
DEFAULT_VIDPID = "2ecc:3002"


def load_patcher():
    path = REPO / "tools" / "swdl-chunksize-patch.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("swdl_chunk_patch", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Watcher:
    """200 Hz sysfs poll for the download-mode device."""

    def __init__(self, vidpid: str):
        self.want = vidpid.lower()
        self.events: list[tuple[float, str, str]] = []
        self._stop = False

    def _snap(self) -> dict[str, str]:
        out = {}
        try:
            entries = sorted(SYS.iterdir())
        except OSError:
            return out
        for dev in entries:
            name = dev.name
            if not re.match(r"^\d+-[\d.]+$", name):
                continue
            try:
                vid = (dev / "idVendor").read_text().strip()
                pid = (dev / "idProduct").read_text().strip()
            except OSError:
                continue
            out[name] = f"{vid.lower()}:{pid.lower()}"
        return out

    def run(self):
        prev: set[str] = set()
        while not self._stop:
            now = time.time()
            cur = {k for k, v in self._snap().items() if v == self.want}
            for added in cur - prev:
                self.events.append((now, "appear", added))
            for gone in prev - cur:
                self.events.append((now, "disappear", gone))
            prev = cur
            time.sleep(0.005)

    def stop(self):
        self._stop = True

    def windows(self) -> list[tuple[float, float]]:
        """(appear, disappear) pairs, last one possibly open."""
        out = []
        open_at = None
        for ts, kind, _ in self.events:
            if kind == "appear" and open_at is None:
                open_at = ts
            elif kind == "disappear" and open_at is not None:
                out.append((open_at, ts))
                open_at = None
        if open_at is not None:
            out.append((open_at, float("inf")))
        return out


def parse_log(path: Path) -> dict:
    """Pull the progress markers out of one per-device wtp log."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return {}
    info: dict = {"path": str(path), "roundtrips": 0, "images": []}
    info["roundtrips"] = len(re.findall(r"GetWtpMessage\.\.\.", text))
    for name in re.findall(r"download file name is (\S+)", text):
        info["images"].append(Path(name).name)
    for name in re.findall(r"Completed DownLoad file: (\S+)", text):
        info.setdefault("completed", []).append(Path(name).name)
    m = re.search(r"BufferSize is (0x[0-9A-Fa-f]+)", text)
    if m:
        info["buffersize"] = int(m.group(1), 16)
    m = re.search(r"uiRemainingData size:(\d+)", text)
    if m:
        info["remaining_reported"] = int(m.group(1))
    info["dropped"] = "remove DevName" in text
    info["bytes"] = len(text.encode("utf-8", "replace"))
    return info


def newest_log(directory: Path, since: float) -> Path | None:
    best = None
    for p in sorted(directory.glob("wtp_dev_*.log")):
        if p.stat().st_mtime < since:
            continue
        if best is None or p.stat().st_mtime > best.stat().st_mtime:
            best = p
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-D", "--blf", required=True, help=".blf to run")
    ap.add_argument("-b", "--binary", required=True, help="swdl_linux binary")
    ap.add_argument("--chunk", type=lambda s: int(s, 0), default=0,
                    help="patch a copy of --binary to this chunk size first")
    ap.add_argument("-T", "--timeout", default="120", help="tool -T seconds")
    ap.add_argument("--wait", type=int, default=300,
                    help="seconds to wait for the board to enumerate")
    ap.add_argument("--vidpid", default=DEFAULT_VIDPID)
    args = ap.parse_args()

    if os_euid() != 0:
        print("NOTE: not running as root; the tool and sysfs reads may fail.",
              file=sys.stderr)

    binary = Path(args.binary).resolve()
    if not binary.exists():
        ap.error(f"no such binary: {binary}")

    if args.chunk:
        patcher = load_patcher()
        if patcher is None:
            ap.error("--chunk needs tools/swdl-chunksize-patch.py")
        target = binary.with_name(binary.name + f".budget{args.chunk}")
        rc = subprocess.run([sys.executable,
                             str(REPO / "tools" / "swdl-chunksize-patch.py"),
                             str(binary), "-o", str(target),
                             "--chunk", str(args.chunk)]).returncode
        if rc != 0:
            ap.error("patch failed")
        binary = target
        print(f"using patched binary {binary} (chunk {args.chunk})")

    blf = Path(args.blf).resolve()
    vidd = binary.parent / "temp"
    dkb = vidd / "Dkb.bin"
    dkb_size = dkb.stat().st_size if dkb.exists() else None

    watcher = Watcher(args.vidpid)
    import threading
    th = threading.Thread(target=watcher.run, daemon=True)
    th.start()

    cmd = ["env", "LC_ALL=C", "LANG=C", str(binary), "-D", str(blf),
           "-T", args.timeout, "-N"]
    print("\nstarting:", " ".join(cmd))
    print(">>> POWER-CYCLE THE BOARD NOW <<<\n")
    started = time.time()
    proc = subprocess.Popen(cmd, cwd=str(binary.parent))

    deadline = started + args.wait
    appeared = None
    while time.time() < deadline:
        w = watcher.windows()
        if w:
            appeared = w[-1][0]
            break
        if proc.poll() is not None:
            break
        time.sleep(0.05)

    if appeared is None:
        print("no enumeration observed within the wait window.")
        print("checklist: board powered? USB cable? tool already running?")
        watcher.stop()
        return 2

    print(f"device appeared at t+{appeared - started:.3f} s")
    # wait for it to go away or the tool to exit
    while time.time() < deadline:
        if watcher.windows() and watcher.windows()[-1][1] != float("inf"):
            break
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
    watcher.stop()
    th.join(timeout=2)

    wins = watcher.windows()
    print()
    for a, b in wins:
        if b == float("inf"):
            print(f"USB window : device NEVER disappeared "
                  f"(appeared t+{a - started:.3f} s, still present now)")
            print("             -> the 'USB Enum timeout' / 1.58 s window premise "
                  "is NOT what\n                is stopping us. See handoff §11h.")
        else:
            span = (b - a) * 1000
            print(f"USB window : {span:8.1f} ms  "
                  f"(appear t+{a - started:.3f} s, "
                  f"disappear t+{b - started:.3f} s)")

    log = newest_log(binary.parent, started - 2)
    info = parse_log(log) if log else {}
    if info:
        print(f"\nper-device log : {info['path']}")
        print(f"  round trips  : {info['roundtrips']}")
        print(f"  images seen  : {info['images']}")
        if info.get("completed"):
            print(f"  completed    : {info['completed']}")
        print(f"  BufferSize   : {info.get('buffersize', 'not logged')}")
        print(f"  device gone  : {info['dropped']}")

    if dkb_size and wins:
        span = (wins[-1][1] - wins[-1][0]) if wins[-1][1] != float("inf") else None
        chunk = 248
        # chunk actually used, if we patched it
        if args.chunk:
            chunk = args.chunk
        elif info.get("buffersize"):
            chunk = info["buffersize"]
        done = info.get("roundtrips", 0)
        if span and done:
            rate = done * chunk / span
            budget = rate * span
            print(f"\nassumptions   : chunk={chunk} B, round trips counted from the log")
            print(f"measured rate : ~{rate / 1024:.1f} KiB/s over the window")
            print(f"implied budget: ~{budget / 1024:.1f} KiB per power cycle")
            print(f"                        ({budget:.0f} bytes)")
            print(f"DKB to move   : {dkb_size} B ({dkb_size / 1024:.1f} KiB)")
            if dkb_size > budget:
                print(f"VERDICT       : DKB does NOT fit -- need the chunk up by "
                      f"{dkb_size / budget:.1f}x, or a DKB "
                      f"{dkb_size / budget:.1f}x smaller.")
            else:
                print(f"VERDICT       : DKB fits with {dkb_size / budget:.0%} "
                      f"of the budget used.")
    return 0


def os_euid() -> int:
    try:
        import os
        return os.geteuid()
    except AttributeError:
        return -1


if __name__ == "__main__":
    sys.exit(main())
