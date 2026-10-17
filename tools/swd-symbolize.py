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
    (0x514200, "walks the image list at [+0x1ca8] -- big 0x698 frame"),
    (0x517ab0, "the log writer: appends the device name and newline, then writes"),
    (0x5181d0, "DownloadImage() -- ENTRY. Called from the image loop at 0x51a086. "
               "Returns int: 0 means stop."),
    (0x5181ec, "DownloadImage(): tests [rbx+0xd78]; ==1 branches to 0x5185e0 (no log)"),
    (0x518205, "DownloadImage(): builds \"Begin DownloadImage.........\" from movabs immediates"),
    (0x51825c, "log \"Begin DownloadImage\"  <-- last log line we ever see"),
    (0x518264, "call 0x514200 -- walks the image list at [+0x1ca8]"),
    (0x51827a, "call 0x6d9870 -- jump-table dispatch on al"),
    (0x518297, "call 0x5fded0 -- trivial setter, writes [rdi+0x658], returns 1"),
    (0x5182a8, "memset(buf, 0, 0x4006) -- 16 KB scratch"),
    (0x5182f2, "log \"Sending Preamble...\""),
    (0x5182fc, "cmpb $0,[r13+0x1c72]; jne 0x518b21 -- SKIPS the preamble+version block "
               "when already set. This is why GetVersion never fires per image."),
    (0x518319, "call 0x5ffef0 -- malloc(0x4006) then clears it"),
    (0x518337, "call 0x5fe860 -- GetWtpMessage: logs '\\n GetWtpMessage...\\n' then "
               "reads a WTPTP message. CANDIDATE for the 38-byte read that hangs."),
    (0x518376, "call 0x5ffdb0 -- GetVersion command (observed NEVER taken)"),
    (0x51838a, "call 0x6daef0 -- refcount/mutex, lock cmpxchg on (%fs:0x10)->0x8"),
    (0x51839e, "call 0x5ff970 -- SelectImage command"),
    (0x51843b, "log \"download file name is %s\""),
    (0x518445, "call 0x6d9a30 -- that log. Reached for image 1 only."),
    (0x518b21, "target of the [r13+0x1c72] branch: rebuilds and logs \"Sending Preamble\" "
               "from movabs immediates, then rejoins before SelectImage"),
    (0x51a086, "call 0x5181d0 -- the image loop calling DownloadImage"),
    (0x51a08b, "test %eax,%eax; je 0x51aa20 -- DownloadImage returned 0, stop looping"),
    (0x518e56, "log \"Download data finished\""),
    (0x518eaa, "log \"Completed DownLoad file: %s\""),
    (0x5fe210, "WTPTP command sender. Logs 'GetVersion command......' / "
               "'SelectImage command' then builds a 0x10/0x30 header and waits"),
    (0x5fe860, "GetWtpMessage -- logs \"\\n GetWtpMessage...\\n\", reads a message"),
    (0x5ffef0, "malloc(0x4006) + clear"),
    (0x5ff970, "wrapper: SelectImage command"),
    (0x5ffdb0, "wrapper: GetVersion command"),
    (0x5ff800, "wrapper called just before the file-name log"),
    (0x6daef0, "refcount/mutex: lock cmpxchg  <-- CAN BLOCK"),
    (0x6d9870, "jump-table dispatch (computes a target from al and jumps)"),
    (0x6db920, "log printf (variadic)"),
    (0x6d9a30, "log printf (variadic)"),
    (0x6918c0, "snprintf-family"),
    (0x7165b0, "glibc ioctl() wrapper: mov $0x10,%eax ; syscall. __NR_ioctl = 16. "
               "Break here to catch EVERY usbdevfs call with %rdi=fd, %rsi=code, "
               "%rdx=&usbdevfs_bulktransfer{ep,len,timeout}"),
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

    # swdl_linux is a non-PIE ET_EXEC: the lowest PT_LOAD vaddr IS the load
    # bias. maps.txt shows the text segment at 0x400000, but that is its link
    # address, not a relocation -- gdb reports absolute addresses that need no
    # adjustment. Subtracting 0x400000 pushed every address below the filter and
    # reported "0 addresses inside swdl_linux".
    base = 0
    etype = subprocess.run(["readelf", "-hW", SWDL], capture_output=True,
                           text=True).stdout
    m = re.search(r"Type:\s+(\S+)", etype)
    kind = m.group(1) if m else "?"
    if "DYN" in kind:
        if args.maps and os.path.exists(args.maps):
            lo = None
            for line in open(args.maps):
                if line.rstrip().endswith("swdl_linux"):
                    s0 = int(line.split("-")[0], 16)
                    lo = s0 if lo is None else min(lo, s0)
            base = lo or 0
    print(f"elf type  : {kind} -> base 0x{base:x}\n")

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