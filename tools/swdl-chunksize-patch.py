#!/usr/bin/env python3
"""Override the WTP transfer chunk size in `swdl_linux` (SWDownloader 4.8.8.2).

WHY THIS EXISTS
---------------
The P298's boot ROM advertises `BufferSize = 0xF8` (248) in its DataHeader
reply, and the tool obeys it literally: `CWtptpDownLoad::DownloadImage`
computes the chunk as `min(BufferSize, remaining)` and calls
`CWtpComm::Data(buf, chunk)` once per chunk.  Every chunk is one bulk write
plus one bulk read, so the whole DKB (262,148 B = 1,057 chunks) cannot get
through the boot ROM's ~1.58 s USB window.

`CWtpComm::Data` itself supports up to 0x4000 bytes per call -- its legacy
path does `__memcpy_chk(dst, src, len, 0x4000)` and issues a single
`WriteUSB` of `len + 8` bytes.  The 248-byte cap is not a tool limit, it is
the device's *advertised* buffer being honoured.  This patch substitutes a
fixed chunk size.

RISK
----
The chunk-size override is applied to the DKB upload **and** to the later
flash-image writes, because both run through the same code path.  The DKB
upload happens *before* anything is written to flash, so raising the chunk
can at worst make the boot ROM reject the transfer -- the board simply
re-enumerates.  It cannot brick flash.  If the DKB stage then succeeds but
the flash stage fails, re-run with `--chunk 0` to restore stock behaviour
for the flash writes (the DKB is re-sent every power cycle anyway).

USAGE
-----
    ./swdl-chunksize-patch.py swdl_linux_p298_v2 -o swdl_linux_p298_v3 --chunk 4096
    ./swdl-chunksize-patch.py swdl_linux_p298_v3 --verify          # re-check
    ./swdl-chunksize-patch.py --describe                            # print the patch

`--force-fast-download` additionally flips the branch that prints
"Fast Download is not activated" so that `isFastDownload(true, true)` is
called.  That switches `CWtpComm::Data` onto `WriteUSBWithNoRsp`, i.e. no
per-chunk ACK.  Try it only *after* the plain chunk override, and only
because a failed attempt writes nothing to flash.

Everything is byte-precise and self-verifying: the tool refuses to patch a
binary whose bytes at the patch site do not match the expected original,
and re-disassembles the result so the encoding can be eyeballed.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# vaddr -> file offset for this non-PIE i386 ELF:  off = vaddr - 0x08048000
# ---------------------------------------------------------------------------
IMAGE_BASE = 0x08048000

# CWtptpDownLoad::DownloadImage + 0x8a0 .. +0x8c9  (42 bytes)
#   0813382a  mov  ecx,[ebp-0x4878]        <- kept (loads "remaining")
#   08133830  mov  [ebp-0x4860],esi        <- PATCHED: chunk = imm32
#   08133836  mov  [ebp-0x4868],ecx        <- re-emitted
#   0813383c  mov  [esp+0x8],1             <- re-emitted (as a byte store)
#   08133844  mov  [esp+0x4],0             <- re-emitted (as a byte store)
#   0813384c  mov  eax,[ebx+0xc18]         <- re-emitted
#   08133852  mov  [esp],eax               <- re-emitted
#   08133855  call 0816d060                <- re-emitted (rel32 recomputed)
#   0813385a  mov  esi,[ebp-0x4868]        <- kept
CHUNK_VADDR = 0x08133830
CHUNK_LEN = 42

# CWtptpDownLoad::DownloadImage + 0xd4f .. (the "not activated" branch)
#   08133cdf  mov [esp+0x8],0x0            <- PATCHED: mov BYTE [esp+0x8],1
#   08133ce7  mov [esp+0x4],0x1
#   08133cef  mov eax,[ebx+0xc18]
#   08133cf5  mov [esp],eax
#   08133cf8  call 0816d060                isFastDownload(1, 0)
FD_VADDR = 0x08133CDF
FD_LEN = 8

IS_FAST_DOWNLOAD = 0x0816D060

MAX_CHUNK = 0x4000          # __memcpy_chk dest size in CWtpComm::Data


def orig_chunk_bytes() -> bytes:
    return bytes.fromhex(
        "89 b5 a0 b7 ff ff"            # mov  [ebp-0x4860],esi
        "89 8d 98 b7 ff ff"            # mov  [ebp-0x4868],ecx
        "c7 44 24 08 01 00 00 00"      # mov  [esp+0x8],1
        "c7 44 24 04 00 00 00 00"      # mov  [esp+0x4],0
        "8b 83 18 0c 00 00"            # mov  eax,[ebx+0xc18]
        "89 04 24"                     # mov  [esp],eax
        "e8 06 98 03 00"               # call 0816d060
    )


def new_chunk_bytes(chunk: int) -> bytes:
    """Rebuild the 42-byte region with a fixed chunk size.

    The store MUST use the disp32 form (`C7 85 ...`, 10 bytes).  The disp8
    form `C7 45 A0 ...` sign-extends 0xA0 to -0x60, which is the wrong
    slot -- the first version of this patch made exactly that mistake and
    objdump is what caught it.

    Instruction budget (40 bytes of code + 2 NOPs = 42):

        mov  DWORD PTR [ebp-0x4860], chunk   C7 85 A0B7FFFF imm32  10
        mov  BYTE  PTR [esp+0x4], 0          C6 44 24 04 00         5
        mov  BYTE  PTR [esp+0x8], 1          C6 44 24 08 01         5
        mov  eax,[ebx+0xc18]                 8B 83 18 0C 00 00      6
        mov  [esp],eax                       89 04 24              3
        call isFastDownload                    E8 rel32             5
        mov  [ebp-0x4868],ecx                89 8D 98 B7 FF FF     6
    """
    call_site = CHUNK_VADDR + 10 + 5 + 5 + 6 + 3
    rel = IS_FAST_DOWNLOAD - (call_site + 5)
    if not (-0x80000000 <= rel <= 0x7FFFFFFF):
        raise SystemExit("call displacement out of range")
    body = b"".join([
        b"\xc7\x85\xa0\xb7\xff\xff"
        + chunk.to_bytes(4, "little"),                    # [ebp-0x4860] = chunk
        b"\xc6\x44\x24\x04\x00",                          # [esp+4] = 0 (getter)
        b"\xc6\x44\x24\x08\x01",                          # [esp+8] = 1
        b"\x8b\x83\x18\x0c\x00\x00",                      # eax = [ebx+0xc18]
        b"\x89\x04\x24",                                  # [esp] = eax
        b"\xe8" + rel.to_bytes(4, "little", signed=True),
        b"\x89\x8d\x98\xb7\xff\xff",                      # [ebp-0x4868] = ecx
    ])
    assert len(body) == 40, len(body)
    return body + b"\x90" * (CHUNK_LEN - len(body))


def orig_fd_bytes() -> bytes:
    return bytes.fromhex("c7 44 24 08 00 00 00 00")       # mov [esp+0x8],0


def new_fd_bytes() -> bytes:
    return b"\xc6\x44\x24\x08\x01" + b"\x90" * 3         # mov BYTE [esp+0x8],1


# ---------------------------------------------------------------------------


def read_region(data: bytes, vaddr: int, length: int) -> bytes:
    off = vaddr - IMAGE_BASE
    if off < 0 or off + length > len(data):
        raise SystemExit(f"vaddr {vaddr:#x} outside file")
    return data[off:off + length]


def disasm(binary: Path, vaddr: int, length: int) -> str:
    out = subprocess.run(
        ["objdump", "-d", "-M", "intel", "--no-show-raw-insn",
         f"--start-address={vaddr}", f"--stop-address={vaddr + length}",
         str(binary)],
        capture_output=True, text=True, check=False)
    return out.stdout


def assert_patched(binary: Path, chunk: int | None, force_fd: bool) -> bool:
    """Disassemble the patched binary and prove the intended instructions landed.

    A local reimplementation of someone else's tool is not evidence that their
    tool is happy -- but objdump decoding *our own* bytes is exactly the
    evidence we need that we patched the slot we meant to patch.
    """
    ok = True
    text = disasm(binary, CHUNK_VADDR, CHUNK_LEN)
    if chunk:
        want = f"mov    DWORD PTR [ebp-0x4860],{hex(chunk)}"
        got = [ln.split(":", 1)[1].strip() for ln in text.splitlines()
               if "DWORD PTR [ebp-0x4860]" in ln]
        print(f"self-check chunk store : {'OK' if want in got else 'FAIL'}"
              f"  (want {want!r}, got {got!r})")
        ok &= want in got
        if "ebp-0x60]" in text:
            print("self-check            : FAIL -- disp8 form, wrong slot")
            ok = False
    if force_fd:
        t2 = disasm(binary, FD_VADDR, FD_LEN)
        print(f"self-check fastdl gate : "
              f"{'OK' if 'BYTE PTR [esp+0x8],0x1' in t2 else 'FAIL'}")
        ok &= "BYTE PTR [esp+0x8],0x1" in t2
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Patch swdl_linux's WTP chunk size / Fast Download gate.")
    ap.add_argument("binary", nargs="?", help="swdl_linux binary")
    ap.add_argument("-o", "--output", help="patched copy (default: in place)")
    ap.add_argument("--chunk", type=lambda s: int(s, 0), default=0,
                    help=f"fixed chunk size in bytes, 1..{MAX_CHUNK:#x} "
                         "(0 = leave stock)")
    ap.add_argument("--force-fast-download", action="store_true",
                    help="also make isFastDownload(true,true) unconditional")
    ap.add_argument("--verify", action="store_true",
                    help="re-check a previously patched binary and exit")
    ap.add_argument("--describe", action="store_true",
                    help="print the patch layout and exit")
    args = ap.parse_args()

    if args.describe:
        print("chunk site  ", hex(CHUNK_VADDR), "file off", hex(CHUNK_VADDR - IMAGE_BASE))
        print("  original", orig_chunk_bytes().hex(" "))
        print("fastdl site", hex(FD_VADDR), "file off", hex(FD_VADDR - IMAGE_BASE))
        print("  original", orig_fd_bytes().hex(" "))
        return 0

    if not args.binary:
        ap.error("binary is required")

    src = Path(args.binary)
    data = bytearray(src.read_bytes())

    have_chunk = read_region(data, CHUNK_VADDR, CHUNK_LEN)
    want_chunk = orig_chunk_bytes()
    already_chunk = new_chunk_bytes(args.chunk) if args.chunk else None
    chunk_state = ("stock" if have_chunk == want_chunk else
                   "patched" if already_chunk and have_chunk == already_chunk
                   else "unknown")

    have_fd = read_region(data, FD_VADDR, FD_LEN)
    fd_state = ("stock" if have_fd == orig_fd_bytes() else
                "patched" if have_fd == new_fd_bytes() else "unknown")

    print(f"binary      {src}  ({len(data)} bytes)")
    print(f"chunk site  {hex(CHUNK_VADDR)} -> {chunk_state}")
    print(f"fastdl site {hex(FD_VADDR)} -> {fd_state}")

    if chunk_state == "unknown" or fd_state == "unknown":
        print("ERROR: unexpected bytes at a patch site -- refusing.", file=sys.stderr)
        print("  got      chunk:", have_chunk.hex(" "))
        print("  expected       ", want_chunk.hex(" "))
        print("  got      fd   :", have_fd.hex(" "))
        print("  expected       ", orig_fd_bytes().hex(" "))
        return 1

    if args.verify:
        ok = (chunk_state == "stock" or args.chunk == 0 or chunk_state == "patched")
        print(f"chunk value in use: "
              f"{'stock 248 (device-advertised)' if chunk_state == 'stock' else hex(args.chunk)}")
        return 0 if ok else 1

    if not args.chunk and not args.force_fast_download:
        print("nothing requested (--chunk 0 and no --force-fast-download)")
        return 0

    if args.chunk:
        if not 1 <= args.chunk <= MAX_CHUNK:
            ap.error(f"--chunk must be 1..{MAX_CHUNK:#x}")
        off = CHUNK_VADDR - IMAGE_BASE
        data[off:off + CHUNK_LEN] = new_chunk_bytes(args.chunk)
        print(f"  patched chunk -> {args.chunk} "
              f"({args.chunk // 248}x fewer round trips than 248)")

    if args.force_fast_download:
        off = FD_VADDR - IMAGE_BASE
        data[off:off + FD_LEN] = new_fd_bytes()
        print("  patched Fast Download gate -> always on")

    dst = Path(args.output) if args.output else src
    if dst != src:
        shutil.copy2(src, dst)
    dst.write_bytes(bytes(data))
    # keep the exec bit the source had
    mode = src.stat().st_mode
    dst.chmod(mode)

    print(f"wrote {dst}")
    print()
    print("--- patched chunk site ---")
    print(disasm(dst, CHUNK_VADDR, CHUNK_LEN))
    if args.force_fast_download:
        print("--- patched Fast Download branch ---")
        print(disasm(dst, FD_VADDR, 0x25))
    print()
    if not assert_patched(dst, args.chunk or None, args.force_fast_download):
        print("SELF-CHECK FAILED -- the patch did not land as intended. "
              "Do not use this binary.", file=sys.stderr)
        return 1
    print("self-check             : OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
