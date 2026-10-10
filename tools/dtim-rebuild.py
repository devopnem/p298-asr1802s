#!/usr/bin/env python3
"""
dtim-rebuild.py — rebuild mtd7/dt im-a TIM table with new kernel/rootfs hashes.

Template: stock mtd7.bin (256 KiB) from dumps.
Input: new kernel (zImage+DTB, padded to 5 MiB with 0xFF) and rootfs (20 MiB padded)
Output: new mtd7 with size+sha256 replaced at the two entries.

Entry layout (little-endian):
  magic 8B at 0x218 (kernel): 47 4d 49 5a 4a 53 59 53 ("GMIZJSYS")
           at 0x278 (rootfs): 4a 53 59 53 44 4d 45 4f ("JSYSDMEO")
  +0x10: size LE32
  +0x14: size2 LE32 (duplicate for kernel, maybe offset for rootfs — we sync both)
  +0x1c: sha256 (32B) of image.rstrip(b'\xff')
"""
import hashlib, struct, sys, pathlib

MAGIC_KERNEL = b"\x47\x4d\x49\x5a\x4a\x53\x59\x53"
MAGIC_ROOTFS = b"\x4a\x53\x59\x53\x44\x4d\x45\x4f"

def rstrip_len(data: bytes) -> int:
    return len(data.rstrip(b"\xff"))

def sha_rstrip(data: bytes) -> bytes:
    return hashlib.sha256(data.rstrip(b"\xff")).digest()

def patch(img: bytes, new_kernel: bytes, new_rootfs: bytes) -> bytes:
    out = bytearray(img)
    # find magics
    k_off = out.find(MAGIC_KERNEL)
    r_off = out.find(MAGIC_ROOTFS)
    if k_off < 0 or r_off < 0:
        raise SystemExit("magic not found")
    for off, data, name in [(k_off, new_kernel, "kernel"), (r_off, new_rootfs, "rootfs")]:
        sz = rstrip_len(data)
        dg = sha_rstrip(data)
        # size fields at +0x10 and +0x14
        # kernel: both fields = rstrip len (stock 0x2c3320 dup)
        # rootfs: first = partition size 0x1400000, second = rstrip len (stock 0x1400000 / 0xba2a5e)
        if name == "rootfs":
            struct.pack_into("<I", out, off+0x10, 0x1400000)
            struct.pack_into("<I", out, off+0x14, sz)
        else:
            struct.pack_into("<I", out, off+0x10, sz)
            struct.pack_into("<I", out, off+0x14, sz)
        out[off+0x1c:off+0x1c+32] = dg
        print(f"{name}: off {hex(off)} size {hex(sz)} sha {dg.hex()[:16]}...")
    return bytes(out)

def main():
    if len(sys.argv) !=5:
        print(f"usage: {sys.argv[0]} <template-mtd7> <kernel-bin> <rootfs-bin> <out-mtd7>")
        sys.exit(1)
    tpl = pathlib.Path(sys.argv[1]).read_bytes()
    k = pathlib.Path(sys.argv[2]).read_bytes()
    r = pathlib.Path(sys.argv[3]).read_bytes()
    out = patch(tpl, k, r)
    pathlib.Path(sys.argv[4]).write_bytes(out)
    print("written", sys.argv[4])

if __name__ == "__main__":
    main()
