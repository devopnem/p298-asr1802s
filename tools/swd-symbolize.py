#!/usr/bin/env python3
"""swd-symbolize.py -- interpret a swdl_linux backtrace.

swdl_linux is a 4.8 MB statically linked, *stripped*, non-PIE ELF, so gdb can
only hand back bare addresses. Two things make them readable anyway:

  1. The load base is 0 and vaddr == file_offset + 0x400000, so an address
     converts to a file offset exactly.

  2. The binary hides most of its log strings, assembling them at runtime from
     movabs immediates -- "Begin DownloadImage........." does not exist in
     .rodata at all. So plain `strings` proximity is weak. Instead this tool
     carries a landmark table derived by static analysis (see
     docs/recovery/SWD-v5-status.md), which pins the interesting functions.

The landmark table was obtained without running anything: the log lines that DO
appear in .rodata were resolved, then their xrefs into .text were found by
scanning for the 4-byte little-endian address, and the control flow between
consecutive log prints was read out of objdump.

Usage:
    swd-symbolize.py <gdb.txt> [maps.txt] [--disasm]
"""

import argparse
import os
import re
import subprocess

SWDL = ("/home/void/Downloads/Modems/Notion_P298_ASR1802S/flashing_tools/"
        "SWDownloader_5_0_0_2/binlinux/swdl_linux")

ELF_BIAS = 0x400000          # vaddr == file_offset + ELF_BIAS, base 0

# ---------------------------------------------------------------------------
# Landmarks, derived by static analysis of swdl_linux 5.0.0.2.
# addr -> (what it is, how we know)
# ---------------------------------------------------------------------------
LANDMARKS = [
    (0x5181e0, "DownloadImage() -- prologue; entry for one image transfer"),
    (0x5181ec, "DownloadImage(): tests [rbx+0xd78]; ==1 branches to 0x5185e0 (no log)"),
    (0x518205, "DownloadImage(): builds \"Begin DownloadImage.........\" on the stack"),
    (0x51825c, "DownloadImage(): log write  -> LAST LOG LINE WE SEE"),
    (0x518269, "DownloadImage(): call 0x514200 (walks image list @+0x1ca8)"),
    (0x51827a, "DownloadImage(): call 0x6d9870 (jump-table dispatch)"),
    (0x518297, "DownloadImage(): call 0x5fded0 (trivial setter, +0x658)"),
    (0x5182a8, "DownloadImage(): memset(0x4006) -- 16 KB scratch"),
    (0x518319, "DownloadImage(): call 0x5ffef0"),
    (0x518337, "DownloadImage(): call 0x5fe860"),
    (0x51834e, "log \"Getting Version...\"  <-- stall window opens here"),
    (0x518357, "WTPTP GetVersion  -> 0x5ffdb0 -> helper 0x5fe210"),
    (0x518376, "WTPTP SelectImage -> 0x5ffdb0/0x5ff970 -> helper 0x5fe210"),
    (0x51838a, "mutex / refcount  -> 0x6daef0 (lock cmpxchg)  <-- CAN BLOCK"),
    (0x51839e, "WTPTP SelectImage command issued here"),
    (0x518416, "snprintf 0x6918c0 (formats into [rsp+0x4470])"),
    (0x518426, "call 0x5ff800"),
    (0x51843b, "log \"download file name is %s\"  <-- stall window closes"),
    (0x518445, "never reached in our runs -> payload never opened"),
    (0x518e56, "log \"Download data finished\""),
    (0x518eaa, "log \"Completed DownLoad file: %s\""),
    (0x5fe210, "WTPTP command sender. Called with \"GetVersion command......\" "
               "and \"SelectImage command\". Builds 0x10/0x30 header then waits"),
    (0x6daef0, "refcount/mutex: lock cmpxchg on (%fs:0x10)->0x8  <-- CAN BLOCK"),
    (0x5ffdb0, "wrapper: GetVersion command"),
    (0x5ff970, "wrapper: SelectImage command"),
    (0x5ff800, "wrapper called just before the file-name log"),
    (0x6db920, "log printf (variadic)"),
    (0x6d9a30, "log printf (variadic)"),
    (0x6918c0, "snprintf-family, the %m return fixup runs inline before it"),
]
LANDMARKS.sort()


def sec_of(addr, sections):
    for name, lo, hi in sections:
        if lo <= addr < hi:
            return name
    return "?"


def load_sections():
    out, cur = [], None
    try:
        res = subprocess.run(["readelf", "-SW", SWDL], capture_output=True, text=True)
    except Exception:                                        # noqa: BLE001
        return out
    for line in res.stdout.splitlines():
        m = re.search(r"\]\s+(\.\S+)\s+\S+\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)", line)
        if m:
            cur = (m.group(1), int(m.group(2), 16),
                   int(m.group(2), 16) + int(m.group(4), 16))
            out.append(cur)
    return out


def nearest_landmark(addr):
    best = None
    for a, desc in LANDMARKS:
        if a <= addr:
            best = (a, desc, addr - a)
        else:
            break
    return best


def disasm(addr, span=0x50):
    try:
        res = subprocess.run(
            ["objdump", "-d", f"--start-address={addr - 0x30}",
             f"--stop-address={addr + span}", SWDL],
            capture_output=True, text=True)
        return "\n".join(res.stdout.splitlines()[-28:])
    except Exception as exc:                                   # noqa: BLE001
        return f"(disassembly failed: {exc})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gdb")
    ap.add_argument("maps", nargs="?")
    ap.add_argument("--disasm", action="store_true")
    args = ap.parse_args()

    sections = load_sections()
    print(f"swdl_linux: base 0, vaddr = file_offset + 0x{ELF_BIAS:x}")
    print(f"landmarks : {len(LANDMARKS)}\n")

    base = 0
    if args.maps and os.path.exists(args.maps):
        for line in open(args.maps):
            if line.rstrip().endswith("swdl_linux"):
                start = int(line.split("-")[0], 16)
                base = min(base, start) if base else start
    print(f"load base : 0x{base:x} (0 = non-PIE, expected)\n")

    text = open(args.gdb).read()
    addrs, seen = [], set()
    for m in re.finditer(r"0x([0-9a-f]{6,16})", text):
        v = int(m.group(1), 16) - base
        if v not in seen and v >= 0x400000:
            seen.add(v)
            addrs.append(v)

    print(f"--- {len(addrs)} addresses inside swdl_linux ---\n")
    for v in sorted(addrs):
        sec = sec_of(v, sections)
        hit = nearest_landmark(v) if sec == ".text" else None
        print(f"  0x{v:x}  [{sec}]  file 0x{v - ELF_BIAS:x}")
        if hit:
            a, desc, delta = hit
            print(f"      +0x{v - a:x} past landmark 0x{a:x}")
            print(f"      {desc}")
        else:
            print("      (before first landmark)")
        if args.disasm and hit and hit[2] < 0x200:
            print(disasm(v))
        print()


if __name__ == "__main__":
    main()