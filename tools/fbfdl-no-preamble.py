#!/usr/bin/env python3
"""Patch fbfdownloader so it never sends a WTPTP Preamble.

Diagnostic only. Produces a patched copy beside the original; the vendor
binary is never modified.

    python3 tools/fbfdl-no-preamble.py

Why
---
The board accepts image 1 (the 248-byte FBF TIM header), replies
`Platform ready status: 0`, and then stops answering. The host's next call is
SendPreamble, and that is where it blocks forever.

Inside DownloadImage (FUN_00409c10, image base 0x400000):

    409d48:  test   %esi,%esi        ; per-image flag
    409d4a:  jne    0x40a080         ; non-zero  =>  skip SendPreamble
    409d50:  mov    0x1c64(%r13),%esi
    409d57:  mov    0xd70(%rbx),%rdi
    409d5e:  call   0x403810         ; SendPreamble

which matches the device log exactly. Image 1 takes the branch and never sends
a Preamble; image 2 falls through into it and stalls.

Turning the conditional into an unconditional jump makes every image take the
path image 1 takes: straight to SelectImage, an exchange already observed to
succeed. This is the Linux equivalent of the old `--force-no-preamble` switch
that moved the stall on swdl_linux.

What it does NOT prove
----------------------
Skipping the Preamble may simply desynchronise the host from the board. The
WTPTP board drives the session, and a Preamble between images may be required.
If the run stalls at SelectImage instead, that is a real result and not a
failure of the patch: it localises the fault to "the board answers no command
after image 1", whichever command it is.

Run it the same way, then read the device log:

    sudo env LC_ALL=C LANG=C ./fbfdownloader-nopreamble -b BinFile.bin
    cat wtp_dev_bus_usb_001_*.log
"""

import hashlib
import os
import shutil
import sys

BINARY = "fbfdownloader"
PATCHED = "fbfdownloader-nopreamble"

IMAGE_BASE = 0x400000  # ELF EXEC, LOAD offset 0 -> vaddr 0x400000

# jne rel32 0x330 at vaddr 0x409d4a
SITE_VADDR = 0x409D4A
ORIGINAL = bytes.fromhex("0f8530030000")  # jne rel32 0x330
# jmp rel32 is ONE BYTE SHORTER than jcc rel32: the opcode is e9, not 0f 8x.
# The displacement is measured from the end of the instruction, which therefore
# moves from 0x409d50 to 0x409d4f, so the same destination needs rel32 = 0x331,
# not 0x330. Keeping 0x330 lands on 0x40a07f, one byte short -- which objdumps
# as a jump into the middle of whatever is there.
PATCHED_BYTES = bytes.fromhex("e93103000090")  # jmp rel32 0x331 + nop


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
    data = bytearray(open(src, "rb").read())
    off = SITE_VADDR - IMAGE_BASE

    actual = bytes(data[off : off + len(ORIGINAL)])
    if actual != ORIGINAL:
        sys.exit(
            f"UNEXPECTED BYTES at vaddr 0x{SITE_VADDR:x} (file offset 0x{off:x})\n"
            f"  found    {actual.hex(' ')}\n"
            f"  expected {ORIGINAL.hex(' ')}\n"
            "This build is not the one the analysis was done against.\n"
            "Refusing to patch. Re-run the disassembly first."
        )

    data[off : off + len(PATCHED_BYTES)] = PATCHED_BYTES

    # Verify we landed on the same destination, not merely on "a" destination.
    # jcc rel32 and jmp rel32 differ in length, so a displacement copied across
    # unchanged silently moves the target. Decode both and compare.
    orig_target = SITE_VADDR + 6 + int.from_bytes(ORIGINAL[2:6], "little")
    new_target = SITE_VADDR + 5 + int.from_bytes(PATCHED_BYTES[1:5], "little")
    if orig_target != new_target:
        sys.exit(
            f"BUG: patch would jump to 0x{new_target:x}, not 0x{orig_target:x}.\n"
            "jcc rel32 is 6 bytes and jmp rel32 is 5, so the displacement\n"
            "must be recomputed for the new instruction end."
        )

    dst = os.path.join(os.path.dirname(src), PATCHED)
    with open(dst, "wb") as fh:
        fh.write(data)
    os.chmod(dst, 0o755)

    changed = [
        (a, b)
        for a, b in zip(open(src, "rb").read(), data)
        if a != b
    ]
    print(f"source   {src}")
    print(f"         sha256 {hashlib.sha256(open(src, 'rb').read()).hexdigest()}")
    print(f"patched  {dst}")
    print(f"         sha256 {hashlib.sha256(bytes(data)).hexdigest()}")
    print(f"\n1 instruction changed at vaddr 0x{SITE_VADDR:x}, {len(changed)} byte(s) differ")
    print("\n  before  jne 0x40a080   ; esi != 0 skips SendPreamble")
    print("  after   jmp 0x40a080   ; SendPreamble is never called")
    print("\nThe original binary is untouched.")
    print("Run:  sudo env LC_ALL=C LANG=C ./%s -b BinFile.bin" % PATCHED)


if __name__ == "__main__":
    main()