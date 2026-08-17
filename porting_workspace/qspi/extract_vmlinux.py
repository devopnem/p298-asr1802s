#!/usr/bin/env python3
"""Extract the uncompressed vmlinux image from a ARM zImage (vendor kernel-a.bin).

Mirrors the logic of the kernel tree's scripts/extract-vmlinux: scan the file for
a known compression magic, decompress, and repeat until the result is an ELF
(vmlinux). Supports gzip and xz/lzma (the compressors used by 3.10-era kernels).
"""
import sys
import os
import gzip
import lzma

MAGICS = [
    (b"\x1f\x8b", "gzip", lambda d: gzip.decompress(d)),
    (b"\xfd\x37\x7a\x58\x5a\x00", "xz", lambda d: lzma.decompress(d)),
    (b"\x28\xb5\x2f\xfd", "zstd", None),   # needs zstandard module; detected only
    (b"\x89\x4c\x5a\x4f", "lzo", None),     # needs lzo; detected only
    (b"\x02\x21\x4c\x18", "lz4", None),     # needs lz4; detected only
]


# Compressed piggy in a zImage is the raw ARM Image (NOT ELF). Accept any
# decompressed blob >= 1 MiB as the kernel Image. Also re-decompress if the
# result is itself another compressed stream (nested payloads).
MIN_IMG = 1024 * 1024


def try_decompress(data, decompress):
    for magic, name, fn in MAGICS:
        if fn is None:
            continue
        idx = data.find(magic)
        while idx != -1:
            try:
                out = fn(data[idx:])
                if len(out) >= MIN_IMG:
                    return out
                # result may itself be compressed (nested) - try one level
                nested = try_decompress(out, None)
                if nested and len(nested) >= MIN_IMG:
                    return nested
            except Exception:
                pass
            nxt = data.find(magic, idx + 1)
            if nxt == -1:
                break
            idx = nxt
    return None


def main():
    if len(sys.argv) != 3:
        sys.stderr.write("usage: extract_vmlinux.py <in.zImage> <out.vmlinux>\n")
        sys.exit(2)
    inp, outp = sys.argv[1], sys.argv[2]
    with open(inp, "rb") as f:
        blob = f.read()

    data = blob
    for _ in range(20):
        if data[:4] == b"\x7fELF" or len(data) >= MIN_IMG:
            with open(outp, "wb") as o:
                o.write(data)
            print("extracted kernel Image -> %s (%d bytes)" % (outp, len(data)))
            return
        nxt = try_decompress(data, None)
        if not nxt or nxt == data:
            break
        data = nxt

    # Fallback: search whole blob for an ELF that may already be present.
    idx = blob.find(b"\x7fELF")
    if idx != -1:
        # Find ELF end heuristically: decompress not needed; dump from first ELF.
        print("NOTE: no compressed piggy decoded; raw ELF found at offset %d" % idx)
        sys.exit(1)
    print("ERROR: could not extract vmlinux (no gzip/xz piggy found)")
    sys.exit(1)


if __name__ == "__main__":
    main()
