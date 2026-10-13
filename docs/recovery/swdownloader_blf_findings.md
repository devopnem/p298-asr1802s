# SWDownloader `.blf` — findings for Notion P298 / ASR1802S (PXA1802)

Date: 2026-10-10 · Binary: `Marvell_SWDownloader_v4.8.8.2/swdl_linux` (ELF32 i386, static, not stripped, has `debug_info`)

## Status

| Stage | Result |
|---|---|
| `.blf` syntax / grammar | **SOLVED** — `p298_fixed.blf` parses and builds |
| DKB (boot-ROM download package) construction | **SOLVED 2026-10-13** — was a bug in our own `.blf`, not a missing vendor blob. See §4. |
| Linux USB transport understood | **SOLVED** — raw usbfs, no kernel module. See findings spec §8. |
| Live tool run to device detection | **DONE 2026-10-13** — package builds cleanly in `swdl_linux`, `Image_ID` hex confirmed. See §7. |
| Device handshake | **BLOCKED** — board enumerates as `2ecc:3002` for 1.58 s; `swdl_linux` 4.8.8.2 has **no `0x2ECC` immediate** and cannot open it |

---

## 1. Offline validator (no hardware required)

The toolchain ships Linux binaries that run the same `CBlfParser`:

```bash
cd Marvell_SWDownloader_v4.8.8.2
LC_ALL=C LANG=C ./Utilities/TimBuilder/TimBuilder -r <blf>          # prints full parse trace
LC_ALL=C LANG=C ./Utilities/MakeDownloadPackage/MakeDownloadPackage -r <blf> -o /tmp/pkg.zip
LC_ALL=C LANG=C ./Utilities/FBFMake/FBFMake -r <blf> -f /tmp/fbf
```

**`LC_ALL=C LANG=C` is mandatory** — without it they die with
`locale::facet::_S_create_c_locale name not valid` before opening the file.

`MakeDownloadPackage` reproduces `swdl_linux`'s full DKB failure chain, so it is
a faithful oracle for this bug.

Note: image paths and the `.blf` itself are resolved **relative to the
executor's directory**, not the cwd. Keep `.blf` and `mtd*.bin` next to the
binary.

**`swdl_linux` needs no kernel module.** It opens `/dev/bus/usb` and speaks raw
usbfs, parsing USB descriptors itself; no libusb is linked. The
`rmmod: ERROR: Module wtptp is not currently loaded` in its output is harmless
cleanup of a Marvell module shipped in some Android images. Root is needed only
for `/dev/bus/usb` permissions — **not** for the module. See
`../../findings/tooling/blf/swdownloader-blf-spec.md` §8, which also documents
the CLI, the handshake ordering, and the platform-ID table.

Trap 5 below overstates this. Corrected 2026-10-13.

---

## 2. BLF grammar (verified, not guessed)

Sections and keys, from `CBlfParser::ParseBlfFile` / `::ParseImageInfo`:

```ini
[TIM_Configuration]
Processor_Type     = PXA1802
Number_of_Images   = N
BLF_Version        = V3.0.0          ; V2.0.0 / V2.1.0 / V2.2.0 / V3.0.0
FlasherLoadAddress = 0x00000000
Trusted            = 0
ProductionMode     = 0
Version / Issue_Date / OEM_UniqueID

[Flash_Properties]
Flash_Family      = SPI-NAND        ; ONLY: NAND | eMMC | SPI-NOR | SPI-NAND
Flash_Block_Size  = 0x20000
Erase_All_Flash / Reset_BBT / Flash_Options / Flash_NandID / Data_Area_Size / Spare_Area_Size
```

Per-image keys are built by the parser as `snprintf("%d_Image_%s", n, key)`
with **n 1-based**:

```ini
[Image_List]
1_Image_Path                = mtd0.bin
1_Image_Type                = OBM
1_Image_ID_Name             = OBMI     ; magic tags, see §4
1_Image_Image_ID            = OBMI
1_Image_Next_Image_ID       = 2
1_Image_Load_Address        = 0x00000000
1_Image_Flash_Entry_Address = 0x00000000
1_Image_Partition_Number    = 0
1_Image_Erase_Size          = 0x20000
1_Image_Tim_Included        = 1
1_Image_Enable              = 1
```

Other accepted sub-keys: `ImageNumber`, `Hash_Algorithm_ID`,
`Size_To_CRC_in_bytes`, `Image_Size_To_Hash_in_bytes`.

---

## 3. Traps found (all empirically confirmed)

1. **`Processor_Type` takes SoC names, not platform names.**
   `GetPlatFormType()` compares against `PXA688 / PXA1202 / PXA2128 / PXA1802`
   and prints `MMP2`/`NEZHA` as the *result*. `NEZHA` and `Falcon` are rejected.
   `strings mtd0.bin` contains `Falcon` and `NezhaC` — those are build names
   inside the OBM, not blf tokens.

2. **There is no `FlashType` key.** The key is `[Flash_Properties] Flash_Family`.

3. **`Trusted` must be `0`.** With `Trusted = 1` the parser enters
   `ParseDSAInfo` and aborts `unknown DSAID in ParseDSAInfo` unless a
   `DSA_Algorithm` is declared — i.e. it wants to re-sign the TIM. We must not:
   `mtd7`/`mtd8` are already vendor RSA-signed and are pushed verbatim.

4. **All `;` comments must sit before the first `[Section]`.** Comments
   interleaved between sections make the parser lose section context and it
   later fails with the misleading `unknown DSAID in ParseDSAInfo`.

5. **`swdl_linux` needs root, but not because of `wtptp`.** ~~it `rmmod`s the
   `wtptp` module and touches USB~~ — that was wrong. It opens `/dev/bus/usb`
   (raw usbfs, in-tree) and needs root for the permissions. `rmmod wtptp` is
   tolerated-if-missing cleanup. Run non-root it exits silently with no
   banner. That is why `MakeDownloadPackage` / `TimBuilder` are the right
   oracles.

---

## 4. `OBMImage is NULL in prepareDKB list` — SOLVED, 2026-10-13

> **This section previously concluded the route was dead. That was wrong.**
> The blocker was a bug in our own `.blf`, not a missing vendor blob.

```
Platform is NEZHA.....
Prepare FBF list..... / Prepare FBF list return.....
Preparing NEZHA DKBlist
IFLSWD exception: OBMImage is NULL in prepareDKB list
```

Raised by `CIFL_SWD::PrepareTwoStagDKBlist()` at `swdl_linux:0x81039ec`:

```
CTimDescriptor::ImagesList()   // of  this + 0x3804  (the DKB TimDescriptor)
if (list.empty()) throw "OBMImage is NULL in prepareDKB list"
```

### 4a. Root cause: `Image_ID` is an integer, not a string

Our `flash_recovery.blf` carried the ID as a bare token:

```ini
1_Image_Image_ID = OBMI        ; parses as 0
```

`*_Image_Image_ID` is read as a **number**. `"OBMI"` → `0`, so the DKB builder
never matches the `OBMI` entry, the list comes back empty, and the error is
thrown. The vendor form is the ASCII hex of the tag:

```ini
1_Image_Image_ID = 0x4F424D49  ; 'O' 'B' 'M' 'I'
2_Image_Image_ID = 0x54494D48  ; 'T' 'I' 'M' 'H'
```

`*_Image_ID_Name` may stay a plain string. Confirmed by bisection: changing only
that one key flips FAIL → OK, with the vendor payload in place.

This also explains why the earlier gdb work was misleading: the setter *was*
called with `OBMI`, but the matching field is a different member.

### 4b. There is no `WTMI` and no `TZII` requirement

The four literals exist in `swdl_linux` near `%s/temp/TZII.bin`,
`%s/temp/WTM_h.bin`, `%s/temp/OBM_h.bin` — all of which are **temp files the
tool generates**, not blobs you supply. Decisive evidence: run the tool on a
known-good vendor `.blf` and read its own output.

`DKB_ntimheader.bin` (744 B) contains **one** nested entry, `IBKD`, and zero
`WTMI`/`TZII` literals. `Dkb.bin` is the `OBMI` payload wrapped in a 4-byte TIM
header — with our own images, 262,148 = 262,144 + 4.

Empirically, on a working package: `TIMH` alone → fails, `OBMI` alone → fails,
`TIMH` + `OBMI` → **succeeds**. Two entries is the requirement, not four.

### 4c. Two more bugs, found the same way

| what | error | fix |
|---|---|---|
| `Erase_Size = 0x20000` for a 256 KiB image | `ImageFileSize is larger than ImageEraseSize,ImageID: OBMI` | `0x40000` for `mtd0`/`mtd7` |
| two enabled images sharing `Flash_Entry_Address` | `Images TIMH and OBMI overlap in flash` | distinct addresses |

`Erase_Size` in a `.blf` is the **region the image occupies**, not the NAND
block size. The real block is `0x20000` per `fw_env.config`.

### 4d. Status

`findings/tooling/blf/p298_fixed.blf` builds a complete download package from
our **own** `mtd0.bin` + `mtd7.bin`:

```
LC_ALL=C LANG=C ./Utilities/MakeDownloadPackage/MakeDownloadPackage \
    -r p298_fixed.blf -o pkg.zip
# Make Download Package successfully....   exit 0
```

Output `cfg.ini`: `PlatFormType = 6` (NEZHA), `FlashFamilyType = 4`
(SPI-NAND) — both correct for this board.

Verified non-issues, each tested individually and all still building:
comments between sections, `BLF_Version` V2.0.0 vs V3.0.0, presence of
`FlasherLoadAddress`, dropping `[EraseOnly_Option]` / `[Reserved_Data]` /
`[Extended_Reserved_Data]` / `[Flash_Options]` / `[UE_Options]` /
`[BLF_Version]`, `Image_Type` `OBM`/`PRIMARY` instead of `RAW`, index-style
`Next_Image_ID`, and omitting `Size_To_CRC_in_bytes`.

**Still open, and unchanged by the above:**

- No USB transfer has been exercised against hardware.
- `swdl_linux -U` still segfaults in `CUploadCfgParser::ParseUploadCfgFile` (§6b), unexplained.
- `-D` needs **root**, and `swdl_linux` 4.8.8.2 vs the OBM's advertised `4.9.0.5`.
- Device appears then drops — `USB Enum timeout` in mtd0, `NoEnumerationResponseTimeOutError` in the tool. See `§8b` of the findings spec: **start the tool before power-cycling**.
- `PROD` flag may gate USB enumeration entirely (`[PROD]Don't enum USB port`).
- `VID_1286&PID_8130` is the expected WTPTP identity per driver databases — **unconfirmed**, needs a live `lsusb`.

---

## 5. Flash map (still valid, still useful)

From `findings/probes/proc_partitions.txt`; the 25 partitions sum to
exactly 128 MiB = `0x8000000`, so the layout is contiguous:

```
mtd0  0x0000000   256K   OBM
mtd1  0x040000    128K   mtd2  0x060000  mtd3 0x080000  mtd4 0x0A0000
mtd5  0x0C0000    128K   mtd6  0x0E0000
mtd7  0x0100000   256K   DTIM-A      mtd8  0x0140000  256K  DTIM-B
mtd9  0x0180000  15360K  mtd10 0x1080000
mtd11 0x01F80000  768K   u-boot-a   mtd12 0x02040000  768K  u-boot-b
mtd13 0x02100000  5120K  kernel-a   mtd14 0x02600000 5120K kernel-b
mtd15 0x02B00000 20480K  rootfs-a    mtd16 0x03F00000
mtd17 0x05300000  6144K              mtd18 0x05900000  6144K
mtd19 0x05F00000   768K              mtd20 0x05FC0000   256K  rsa
mtd21 0x06000000   256K  u-boot env  mtd22 0x06040000   256K
mtd23 0x06080000 25344K              mtd24 0x07940000  6912K  MRVL_BBM
                                  end 0x08000000 = 128 MiB
```

> The original `findings/tooling/blf/flash_recovery.blf` draft had `FlashAddr=0x000C0000` for U-Boot. That
> lands **inside `mtd7` (DTIM)** and would destroy the TIM tables. Correct value
> is `0x01F80000`.
>
> `flash_recovery.blf` itself has been deleted, superseded by `p298_fixed.blf`.

---

## 6. Live USB read attempt — 2026-10-12 (NEW)

Ran for real, against the board, with a read-only upload config.

```
sudo env LC_ALL=C LANG=C ./swdl_linux -U read.cfg -T 120
SWDL Version: 4.8.8.2   /  SWDL Date: 2015-8-3
rmmod: ERROR: Module wtptp is not currently loaded
Doing Upload...............
Parsing UploadCfg file: read.cfg
Number of Area in UploadCfg file is 1
Segmentation fault
```

Three findings.

### 6a. The recovered upload grammar is CORRECT

`Number of Area in UploadCfg file is 1` means `CUploadCfgParser` accepted the
config, including the `Upload_Area_Nums` placement trap and the comment rule
from §1. Every key was then confirmed against the binary's own string statics
by reading them through gdb:

| config key | C++ static | literal |
|---|---|---|
| `Upload_Property` | `pszUPLOAD_PROPERTY` | `Upload_Property` |
| `Upload_Area_Nums` | `pszUPLOADAREA_NUM` | `Upload_Area_Nums` |
| `Upload_Areas_List` | `pszUPLOADAREA_LIST` | `Upload_Areas_List` |
| `Blf_Version` | `pszBLFVERSION` | `Blf_Version` |
| `Flash_Family` | `pszFLASH_FAMILY_PRO` | `Flash_Family` |
| `Max_Upload_Size` | `pszMAX_UPLOAD_SIZE` | `Max_Upload_Size` |
| `ResetUE_AfterUpload` | `pszUPLOAD_RESETUE` | `ResetUE_AfterUpload` |
| `Reset_DelayTime` | `pszUPLOAD_TIMEDELAY_RESET` | `Reset_DelayTime` |
| `Area_Type` | `pszUPLOADAREA_TYPE` | `Area_Type` |
| `Area_SubType` | `pszUPLOADAREA_SUBTYPE` | `Area_SubType` |
| `Area_Offset` | `pszUPLOADAREA_OFFSET` | `Area_Offset` |
| `Area_DataSize` | `pszUPLOADAREA_DATATSIZE` | `Area_DataSize` |
| `Area_Partition` | `pszUPLOADAREA_PARTITION` | `Area_Partition` |
| `Area_UploadWithSpareArea` | `pszUPLOADAREA_SPAREAREA` | `Area_UploadWithSpareArea` |
| `Area_UploadData_SaveFile` | `pszUPLOADAREA_SAVEFILE` | `Area_UploadData_SaveFile` |

Note `Area_Partition` is a real string at `0x8330af3` even though
`strings | grep -x` misses it — do not conclude a key is absent from that test
alone. Accepted `Blf_Version` literals are `V2.0.0`/`V2.1.0`/`V2.2.0`/`V3.0.0`.
Accepted flash tokens are `SPI-NAND`/`SPI-NOR`/`eMMC` — **bare `NAND` is NOT
accepted**, despite `GetPlatFormType()` comparing against it elsewhere.

### 6b. The crash is in the parser, before any USB access

```
#0  std::_List_node_base::hook(std::_List_node_base*)
#1  CUploadCfgParser::ParseUploadCfgFile(char const*, _InstanceParams*)
#2  CIFL_SWD::PreforUpload(char const*)
#3  PrepareUpload(_InstanceParams*, char const*)
#4  main() at SWDTool.cpp:343
```

Disassembly at the fault site: it `operator new(12)`, tests the result against
`0xfffffff8` (the `std::bad_alloc` magic), then calls `hook()` with an element
pointer loaded from offset `0x4c` of another object. The crash means that
element pointer is garbage, so the per-area record was not populated even
though the *count* parsed. With every key name verified correct, this looks
like a defect in a 2015 binary running on a current kernel rather than a
config error — but that is not yet proven.

This happens before `Begin to detect wtptp device`, so nothing about the board
was learned. It is **not** evidence that the board is reachable.

### 6c. The tool's `mtd*.bin` inputs are symlinks into the NAND dumps

```
mtd0.bin -> ../../findings/nand-dumps/mtd0.bin
mtd7.bin -> ../../findings/nand-dumps/mtd7.bin
mtd8.bin -> ../../findings/nand-dumps/mtd8.bin
mtd11.bin -> ../../findings/nand-dumps/mtd11.bin
```

Running `-D` would have written through these symlinks and overwritten the
primary-source dumps. Use an upload config with a distinct
`Area_UploadData_SaveFile`, and never point a write blf at that directory.

> **Update 2026-10-13 — this is worse than it looked.** The **offline**
> utility triggers it too. `MakeDownloadPackage` rewrites the **`TIMH` image in
> place** with a 248-byte generated TIM header, no hardware needed:
>
> ```
> before:  mtd7.bin  262144 B  7de63ddc29453b0a...
> after:   mtd7.bin    248 B  f4e1b35d7e74e84c...
> ```
>
> `mtd0.bin` (the `OBMI` image) is untouched. So **never** run any of these
> binaries from `flashing_tools/Marvell_SWDownloader_v4.8.8.2/`, where
> `mtd7.bin` is that symlink. Always run in a scratch directory with real
> copies. `flashing_tools/p298-swd/` is prepared for this. Details in the
> findings spec §6d-bis.
>
> Also note `flash_recovery.blf` targeted mtd0 (OBM), mtd7/mtd8 (DTIM A/B) and
> mtd11 (u-boot-a) — the entire trust chain, with **no kernel or rootfs image**.
> It was never usable for recovering the board, and has been deleted in favour
> of `p298_fixed.blf`.

### Still blocking a write

- `WTMI`/`TZII` absent from every dump (§4).
- Tool is `4.8.8.2`; the board's OBM advertises `SWDownloader 4.9.0.5`. None of
  the four available products is 4.9.

---

## 7. Live Linux run — 2026-10-13

The package pipeline now runs end to end in the **live** tool, not just the
oracle. `swdl_linux -D p298_fixed.blf -T 120 -N` reached the device-detection
stage with no errors:

```
Platform is NEZHA.....
Preparing NEZHA DKBlist
complete to prepare NEZHA DKBlist
Tim file name is .../temp/DKB_ntimheader.bin
Generating image bin ....  GenerateTim Successfully
image->Image_ID = 0x54494d48        <- TIMH, hex form now correct
image->Flash_erase_size = 0x00040000
image->Image_ID = 0x4f424d49        <- OBMI
Successfully to prepare temp folder file for wtptp download
Begin to detect wtptp device....
Please plug your USB device
```

This independently confirms §4: `Image_ID` came through as hex, `Erase_Size`
was accepted at `0x40000`, and the NEZHA/SPI-NAND path completed. It also
confirms the §6c hazard live — `GenerateTim` rewrote `mtd7.bin` down to 248 B
mid-run.

**It then stalled at `Please plug your USB device`.** `tools/usb-watch.py`
(polls sysfs at ~50 Hz, `watch -n1 lsusb` is far too slow) captured it:

```
[15:37:29.239] APPEARED  1-2  2ecc:3002  'KSTR'  'ASR'  bus=1   <<< CANDIDATE
[15:37:30.816] GONE      1-2  2ecc:3002  'KSTR'  'ASR'            <<< CANDIDATE
```

**1.577 seconds.** Two facts fall out, and the first is good news:

1. **The board does enumerate in USB download mode.** It is not `PROD`-gated
   after all — mtd0's `[PROD]Don't enum USB port` did not prevent this. The
   device appears at power-on and drops when the OBM's `USB Enum timeout`
   expires, which is exactly the `[Non-Prod]Wait for download...` behaviour.
2. **The tool cannot see it.** `swdl_linux` 4.8.8.2 contains **no `0x2ECC`
   immediate anywhere** — verified by decoding every occurrence of the byte
   pair and classifying it as instruction-immediate versus coincidence:

   | value | immediates | coincidental byte pairs |
   |---|---|---|
   | `0x2ECC` | **0** | 3 (all inside `call` rel32) |
   | `0x3002` | **0** | 16 |
   | `0x1286` | 0 (one apparent hit is also a `call`) | 41 |
   | `0x8130` | **0** | 25 |

   A binary with no `0x2ECC` literal cannot open a `2ecc:3002` device. This is
   not a flag, a permission or a timing problem. **The 4.8.8.2 route is closed.**

**Correction to §8d:** the `USB\VID_1286&PID_8130` "Marvell R WTP driver for
Nezha" lead is **wrong for this board**. Those are Monahans/PXA-era IDs from
the module lineage; the P298 router enumerates as `2ecc:3002`. Do not chase
that ID. The real identity is now known from observation, not inference.
