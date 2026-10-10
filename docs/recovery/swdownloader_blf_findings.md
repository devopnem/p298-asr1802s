# SWDownloader `.blf` — findings for Notion R291 / ASR1802S (PXA1802)

Date: 2026-10-10 · Binary: `Marvell_SWDownloader_v4.8.8.2/swdl_linux` (ELF32 i386, static, not stripped, has `debug_info`)

## Status

| Stage | Result |
|---|---|
| `.blf` syntax / grammar | **SOLVED** — `flash_recovery.blf` parses cleanly |
| DKB (boot-ROM download package) construction | **BLOCKED** — needs vendor-only flasher blobs |

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

5. `swdl_linux` needs root (it `rmmod`s the `wtptp` module and touches USB);
   run non-root it exits silently with no banner. That is why
   `MakeDownloadPackage` / `TimBuilder` are the right oracles.

---

## 4. Current blocker: `OBMImage is NULL in prepareDKB list`

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

So the list it walks is **not** the blf image list. It is a DKB TimDescriptor
populated by `CIFL_SWD::GenerateDKBTim()`, and the DKB stage expects exactly
four specially-tagged entries, matched by `CImageDescription::ImageId()`
against these literals:

| literal | meaning | do we have it? |
|---|---|---|
| `TIMH` | TIM/DTIM header binary | yes — `mtd7.bin` |
| `OBMI` | boot-ROM flasher | maybe — `mtd0.bin` (OBM contains `Wait for download` / `User force to download`) |
| `WTMI` | WTM manager | **no** |
| `TZII` | TrustZone init image | **no** |

plus a two-stage TIM descriptor and an `Next_Image_ID` chain.

Verified with gdb that the parser *does* store our IDs correctly
(`CImageDescription::ImageId()` lives at `this+0x44`; setter called with
`OBMI`/`TIMH`/`TIMH`/`UBOOT_A`). Adding `WTMI` + `TZII` entries pointing at
`mtd0.bin`, toggling `BLF_Version` across `V2.0.0`–`V3.0.0`, toggling
`Tim_Included`, and toggling `Enable` all leave the error unchanged.

### Conclusion

`SWDownloader` does not flash "a list of mtd dumps". It builds a
**boot-ROM download package** out of Marvell-internal support blobs that are
not part of any MTD partition and are not present in any backup we hold.
The syntax problem is solved; the missing piece is **binary content we cannot
synthesise**. Without the vendor's original `.blf` + `WTMI`/`TZII` blobs this
route is closed.

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
