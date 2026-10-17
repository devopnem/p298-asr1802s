#!/usr/bin/env python3
"""Patch fbfdownloader so it does not send a WTPTP Preamble.

Diagnostic only. Writes a patched copy beside the original; the vendor binary is
never modified.

    python3 tools/fbfdl-no-preamble.py

Why
---
Measured, with tools/wtp-blocked.py, on a hung run:

    tid 9321  D  ioctl -> USBDEVFS_BULK ep=0x81 (IN, board must reply)
                     len=38, timeout INFINITE

`ep=0x81` is an IN endpoint and `len=38` (0x26) is exactly the Preamble reply
size. So the board accepted our 4-byte Preamble on the OUT endpoint -- it is
ACKing -- and then sent nothing back. The board answers exactly one Preamble
per session: image 1's succeeds, image 2's does not.

This patch removes the Preamble from both images, so image 2 asks for its next
image the same way image 1 does.

The site
-------
Inside DownloadImage, image base 0x400000:

    409d48:  test   %esi,%esi        ; per-image flag
    409d4a:  jne    0x40a080         ; non-zero => log "Sending Preamble..."
    409d50:  mov    0x1c64(%r13),%esi
    409d57:  mov    0xd70(%rbx),%rdi
    409d5e:  call   0x403810         ; SendPreamble   <-- patched here
    409d63:  test   %eax,%eax
    409d65:  jne    0x409e00         ; failure path

An earlier attempt patched 0x409d4a instead, on the assumption that the `jne`
guarded the call. It does not. 0x40a080 is an out-of-line block that builds the
"Sending Preamble" string, prints it, and then jumps back:

    40a0d0:  je     0x409d50         ; back into the call

So `esi` controls only the message. SendPreamble runs either way, and patching
the branch just made the message unconditional. Verified against the board:
the patched binary behaved identically and still printed "Sending Preamble...".

Replacing the call with `xor %eax,%eax` plus nops is the same length, so there
is no jump displacement to recompute -- the failure mode that bit the first
attempt.

What a stall here means
-----------------------
A stall at SelectImage instead of SendPreamble is a result, not a failed patch.
The board drives WTPTP and may require a Preamble between images. Either way
the fault is localised to "the board answers no command after image 1", and the
patch tells us which command.

Run it, then read the device log:

    sudo env LC_ALL=C LANG=C ./fbfdownloader-nopreamble -b BinFile.bin
    cat wtp_dev_bus_usb_001_*.log
"""

import hashlib
import os
import sys

BINARY = "fbfdownloader"
PATCHED = "fbfdownloader-nopreamble"

IMAGE_BASE = 0x400000  # ELF EXEC, LOAD offset 0 -> vaddr 0x400000

SITE_VADDR = 0x409D5E
ORIGINAL = bytes.fromhex("e8ad9affff")  # call 0x403810
# xor %eax,%eax + 3 nops. Same length, so no displacement arithmetic, and a
# zero return takes the success branch at 0x409d63.
PATCHED_BYTES = bytes.fromhex("31c0909090")


def find_binary():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (
        os.path.join(here, "..", "flashing_tools", "SWDownloader_5_0_0_2", "binlinux", BINARY),
        os.path.join(here, BINARY),
        BINARY,
    ):
        if os.path.isfile(cand):
            return os.path.abspath(cand)
    sys.exit(f"cannot find {BINARY}; run it from the tool directory")


def main():
    src = find_binary()
    original_bytes = open(src, "rb").read()
    data = bytearray(original_bytes)
    off = SITE_VADDR - IMAGE_BASE

    actual = bytes(data[off : off + len(ORIGINAL)])
    if actual != ORIGINAL:
        sys.exit(
            f"UNEXPECTED BYTES at vaddr 0x{SITE_VADDR:x} (file offset 0x{off:x})\n"
            f"  found    {actual.hex(' ')}\n"
            f"  expected {ORIGINAL.hex(' ')}\n"
            "This build is not the one the analysis was done against.\n"
            "Refusing to patch."
        )
    if len(PATCHED_BYTES) != len(ORIGINAL):
        sys.exit("patch must be the same length as the original instruction")

    data[off : off + len(PATCHED_BYTES)] = PATCHED_BYTES

    dst = os.path.join(os.path.dirname(src), PATCHED)
    with open(dst, "wb") as fh:
        fh.write(data)
    os.chmod(dst, 0o755)

    print(f"source   {src}")
    print(f"         sha256 {hashlib.sha256(original_bytes).hexdigest()}")
    print(f"patched  {dst}")
    print(f"         sha256 {hashlib.sha256(bytes(data)).hexdigest()}")
    print(f"\n{sum(1 for a, b in zip(original_bytes, data) if a != b)} byte(s) differ, "
          f"all within one instruction at vaddr 0x{SITE_VADDR:x}")
    print("\n  before  call 0x403810    ; SendPreamble")
    print("  after   xor %eax,%eax    ; skipped, returns success")
    print("\nThe 0x409d4a branch is left alone: it only guards the log line.")
    print("The original binary is untouched.")
    print("Run:  sudo env LC_ALL=C LANG=C ./%s -b BinFile.bin" % PATCHED)


if __name__ == "__main__":
    main()