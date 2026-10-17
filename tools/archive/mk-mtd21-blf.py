#!/usr/bin/env python3
"""Generate a minimal SWDownloader .blf that writes ONLY mtd21 (U-Boot env).

WHY THIS EXISTS
---------------
The recovery goal is a U-Boot shell: patch mtd21 so `bootdelay=10` and
`autostart=no` give a real autoboot interrupt window.  It does not require
rewriting mtd0 (the OBM works -- it is what hands U-Boot `quiet=1`) or mtd7
(the DTIM, whose hashes cover only mtd13/14 and mtd15/16).

The previous config, `p298_mtd21.blf`, listed all three images with
`Enable = 1`, so the tool planned to rewrite 768 KiB of flash to change 32 KiB
of environment.  That is both unnecessary risk and unnecessary transfer.

THREE FINDINGS THAT SHRINK THE PACKAGE AND MAKE THE RUN WORK
--------------------------------------------------------------
0. `Processor_Type` MUST be `PXA1826`, not `PXA1802`.
   `CBlfParser::GetPlatFormType` maps `PXA1802` to ePlatForm 6, which is one of
   the three slots (0, 6, 12) whose dispatch handler is the "Unknown platform
   type" stub -- the run dies with "Get type of device failed" after a
   perfectly good handshake. `PXA1826` maps to ePlatForm 15, whose handler
   checks date `06012014` / processor `NZA3` / version `3311`, exactly what this
   board reports. `PXA1826` also prints "NEZHA3" while `PXA1802` prints
   "NEZHA"; the board's own processor string is NZA3.
   See findings/tooling/blf/swdl-platform-enum.md.

1. **`*_Image_Enable = 0` means "supply this file, do not write it to
   flash".**  It still feeds the DKB builder.  With TIMH and OBMI disabled,
   `FBF_h.bin` (the flash payload container) shrinks from 532,484 to 266,244
   bytes and contains exactly one image -- mtd21.  Nothing else is written.

2. **`Dkb.bin` is literally `b"IBKD" + <the OBMI image file>`, byte for
   byte.**  Verified: `Dkb[4:] == mtd0.bin`.  So the DKB size is the OBMI file
   size plus four bytes, and it is uploaded over the same 248-bytes-per-round
   -trip channel that the 1.58 s USB window constrains.  Because the OBMI no
   longer has to be a *flashable* OBM, any Nezha flasher can be wired in as
   the DKB source, and a smaller one is strictly better.

The mtd21 environment is 32 KiB; everything past 0x8000 in the partition is
0xFF.  `--env-size 32K` ships only the real block, cutting the post-DKB
transfer from 266,244 to 36,868 bytes.


(0 verified by reading `CBlfParser::GetPlatFormType` directly;
1 and 2 verified offline against the vendor's own `MakeDownloadPackage`
oracle.)

USAGE
-----
    ./tools/mk-mtd21-blf.py -o flashing_tools/p298-swd/p298_mtd21_only.blf
    ./tools/mk-mtd21-blf.py --dkb air720 --env-size 32K --validate
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SWD = REPO / "flashing_tools" / "p298-swd"
ORACLE = REPO / "flashing_tools" / "Marvell_SWDownloader_v4.8.8.2" / \
    "Utilities" / "MakeDownloadPackage" / "MakeDownloadPackage"

AIR720 = "Nezha_loader_MIFI_V5_SPI_NAND_Release.bin"

HEADER = f"""; =====================================================================
; mtd21-only recovery BLF -- WRITES NOTHING BUT THE U-BOOT ENVIRONMENT
; ---------------------------------------------------------------------
; Goal: a U-Boot shell.  mtd21 (bootargs, flash 0x06000000, 256 KiB) holds
; autostart=yes / bootdelay=1, which is why the board boots silently into
; `bootcmd=mrvlboot` and never returns.  Raising bootdelay opens a real
; interrupt window.  U-Boot 2014.01 autoboot_command() polls tstc() before
; run_command_list(); `autostart` is only read when bootcmd contains a ';',
; and `mrvlboot` does not, so the window exists -- it is just 1 s and silent.
;
; SAFE BY CONSTRUCTION:
;   * Only mtd21 is written (TIMH and OBMI are Enable = 0).
;   * mtd0's RSA signature covers the DTIM, not mtd21 -- verified in
;     docs/bootloader/bootloader_analyse.md.
;   * DTIM hashes cover mtd13/14 (kernel) and mtd15/16 (rootfs), never mtd21.
;
; DKB SOURCE: {AIR720 if True else ''}
;   The OBMI entry is the boot-ROM flasher uploaded to SRAM before any flash
;   write.  It is NOT written to flash (Enable = 0), so its only job is to be
;   a working flasher.  79,924 B against 262,144 B for our own OBM means ~3.3x
;   fewer round trips through the 248-byte channel.
;
; ENV SIZE: only the first 0x8000 of mtd21 is environment; the rest is 0xFF.
;   --env-size 32K ships just that block.
; =====================================================================

"""

TEMPLATE = """[TIM_Configuration]
Number_of_Images = 3
Number_of_Keys = 0
Boot_Flash_Signature = 0x5350490A
Processor_Type = PXA1826
OEM_UniqueID = 0x21796B53
Issue_Date = 0x20141006
Version = 0x00030400
Trusted = 0
ProductionMode = 0

[Flash_Properties]
Flash_Block_Size = 0x20000
Flash_Family = SPI-NAND
Erase_All_Flash = 0
Reset_BBT = 0

[Image_List]
1_Image_Enable = 0
1_Image_Tim_Included = 1
1_Image_Image_ID = 0x54494D48
1_Image_Next_Image_ID = 0x4F424D49
1_Image_Path = mtd7.bin
1_Image_Flash_Entry_Address = 0x01000000
1_Image_Load_Address = 0xD1101000
1_Image_Type = RAW
1_Image_ID_Name = TIMH
1_Image_Erase_Size = 0x40000
1_Image_Partition_Number = 7
1_Image_Size_To_CRC_in_bytes = 0

2_Image_Enable = 0
2_Image_Tim_Included = 1
2_Image_Image_ID = 0x4F424D49
2_Image_Next_Image_ID = 0x52444348
2_Image_Path = {dkb_path}
2_Image_Flash_Entry_Address = 0x00000000
2_Image_Load_Address = 0x01C00000
2_Image_Type = RAW
2_Image_ID_Name = OBMI
2_Image_Erase_Size = {dkb_erase}
2_Image_Partition_Number = 0
2_Image_Size_To_CRC_in_bytes = 0

3_Image_Enable = 1
3_Image_Tim_Included = 0
3_Image_Image_ID = 0x52444348
3_Image_Next_Image_ID = 0xFFFFFFFF
3_Image_Path = {env_path}
3_Image_Flash_Entry_Address = 0x06000000
3_Image_Load_Address = 0x00000000
3_Image_Type = RAW
3_Image_ID_Name = ENV0
3_Image_Erase_Size = 0x40000
3_Image_Partition_Number = 21
3_Image_Size_To_CRC_in_bytes = 0
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", required=True, help=".blf to write")
    ap.add_argument("--dkb", choices=["air720", "p298"], default="air720",
                    help="which file supplies the DKB (default air720)")
    ap.add_argument("--env-size", choices=["256K", "32K"], default="32K")
    ap.add_argument("--env", help="env block to embed, relative to "
                    "flashing_tools/p298-swd. Overrides the default name for "
                    "--env-size and skips the derivation step.")
    ap.add_argument("--validate", action="store_true",
                    help="run the vendor MakeDownloadPackage oracle on the result")
    args = ap.parse_args()

    if args.dkb == "air720":
        dkb_path = AIR720
        dkb_erase = "0x20000"
    else:
        dkb_path = "mtd0.bin"
        dkb_erase = "0x40000"

    if args.env_size == "32K":
        env_path = args.env or "mtd21.env32k.bin"
        env_bytes = 0x8000
        # Derive it if absent so the .blf is always buildable in one step.
        # Skipped when --env names a file explicitly: that file is the point.
        src = SWD / "mtd21.unlocked.bin"
        dst = SWD / env_path
        if not args.env and src.exists():
            full = src.read_bytes()
            if not dst.exists() or dst.read_bytes() != full[:0x8000]:
                dst.write_bytes(full[:0x8000])
                print(f"derived {dst} from mtd21.unlocked.bin "
                      "(first 0x8000 B; the rest of the partition is 0xFF)")
    else:
        env_path = args.env or "mtd21.unlocked.bin"
        env_bytes = 0x40000

    # A short or long env block would be written at the wrong partition size.
    # Catch it here; the vendor oracle does not check it.
    env_file = SWD / env_path
    if env_file.exists():
        actual = env_file.stat().st_size
        if actual != env_bytes:
            print(f"error: {env_path} is {actual} bytes, but --env-size "
                  f"{args.env_size} means {env_bytes}. Refusing to build a "
                  f".blf that would write it at the wrong size.",
                  file=sys.stderr)
            return 1
    else:
        print(f"error: {env_path} not found in {SWD}", file=sys.stderr)
        return 1

    text = HEADER.replace("{AIR720 if True else ''}", "")
    text += TEMPLATE.format(dkb_path=dkb_path, dkb_erase=dkb_erase, env_path=env_path)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)

    dkb_size = (SWD / dkb_path).stat().st_size + 4
    fbf = env_bytes + 4100
    print(f"wrote {out}")
    print(f"  DKB to upload   : Dkb.bin {dkb_size:,} B  "
          f"({dkb_size / 248:.0f} round trips at 248 B)")
    print(f"  + DKB TIM header: DKB_ntimheader.bin 248 B (1 round trip)")
    print(f"  flash payload   : FBF_h.bin ~{fbf:,} B (after the DKB is running)")
    print(f"  total           : ~{dkb_size + 248 + fbf + 496:,} B")
    if args.env_size == "32K":
        print("  note: --env-size 32K writes 0x8000 at 0x06000000; the erase "
              "clears the\n        whole 0x40000 region and the remainder is "
              "already 0xFF.")

    if args.validate:
        if not ORACLE.exists():
            print("oracle not found:", ORACLE, file=sys.stderr)
            return 1
        # NEVER run the oracle in p298-swd: it overwrites mtd7.bin in place.
        # Work in a scratch copy of every file the .blf references.
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            for name in ("mtd7.bin", "mtd0.bin", "mtd21.unlocked.bin",
                         AIR720):
                src = SWD / name
                if src.exists():
                    dst = work / name
                    dst.write_bytes(src.read_bytes())
                    if name == "mtd21.unlocked.bin":
                        (work / "mtd21.env32k.bin").write_bytes(
                            src.read_bytes()[:0x8000])
            shutil.copy2(ORACLE, work / ORACLE.name)
            shutil.copy2(out, work / out.name)
            r = subprocess.run(
                ["env", "LC_ALL=C", "LANG=C", str(work / ORACLE.name),
                 "-r", str(work / out.name), "-o", str(work / "pkg.zip")],
                cwd=work, capture_output=True, text=True)
            tail = (r.stdout + r.stderr).strip().splitlines()[-4:]
            print("\noracle:", "\n  ".join(tail))
            ok = "Make Download Package successfully" in r.stdout + r.stderr
            print("oracle result:", "PASS" if ok else "FAIL")
            return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
