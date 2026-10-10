# OBM / mtd0 "Bootloader" Analysis — and OBM vs U-Boot (mtd11)

Analysis date: 2026-10-06
Artifact: `mtd0.bin` (copied from `../oem_backup/dumps/mtd0.bin`, hash-verified identical)

| Property | Value |
|---|---|
| SHA-256 | `027efa61d29998bf8b58b42d903b81e816fd797dcda81eee695ec7bbfe54c675` |
| Size | 262,144 bytes = `0x40000` (exactly the `mtd0` partition size) |
| Magic | `0x00030400` then `HMIT` at offset `0x04` — **TIM-wrapped container** |
| Version banner | `OBM 4.9.0.0 for %s` |
| Download tool | `SWDownloader 4.9.0.5 for %s` |
| Build date | `-- Apr 11 2024 - 18:25:10 --` |
| Platform strings | `Falcon`, `Falcon A0 spi pinmux`, `NezhaC`, `M26H` |

Verified against `MANIFEST.sha256` in this folder.

## 1. Short answer: mtd0 is NOT U-Boot

They are **two completely different programs**, despite both being "bootloaders"
and both living on the same SPI-NAND. Confirmed by `cmp` — the files differ
completely.

| | **mtd0 = "bootloader"** | **mtd11/12 = "u-boot-a/b"** |
|---|---|---|
| What it really is | **Marvell OBM** (On-Board Manager / boot ROM stage) — a *minimal, freestanding* first-stage loader | **U-Boot** — a full-featured, Linux-aware bootloader with a command shell |
| Size | 262,144 B | 786,432 B |
| Compiler | Not GCC/Linux — bare-metal, `falcon` toolchain | `arm-openwrt-linux-uclibcgnueabi-gcc 4.8.3` (OpenWrt/Linaro) |
| Prompt | **none** — no console shell at all | `Marvell>> ` |
| Interactive commands | none | 30+ (`bootz`, `fastboot`, `setenv`, `mtdparts`, …) |
| RSA crypto | **yes** — 20 hits (`rsa key not right`, `check_notion_rsa`) | **no** — 0 hits |
| SHA-256 image hashing | **no** — 0 hits | **yes** — `Kernel Hash mismatch` |
| USB Fastboot | **no** — 0 `fastboot` hits | **yes** — `fastboot.c`, `gadget.c`, `dwc3-gadget` |
| USB gadget code | **no** — 0 `dwc3`/`gadget` hits | **yes** — 6 `gadget` + 9 `dwc3` hits |
| TFTP / network | none | none |
| Charger / fuel gauge | no (5 `pmic` hits only) | yes — 30 `charger`, 4 `fuelgauge` |
| RAM dump / crash log | minimal (1 `ramdump`) | full — 15 `ramdump`, `RAMDUMP.gz`, `.elf`, SD logging |
| LCD / logo support | no | yes — 11 `lcd`, `(LCD logo)lzma error` |
| MMC / SD | no — 0 hits | yes — 31 hits |
| mtd / partition layer | no (`mtd` = 0) | yes — 64 hits |
| SPI-NAND driver | `__spi_nand_read`, `spi_nand_erase`, QSPI (`QSPI_CLK_RES_CTRL`) | via mtd layer, `spi_flash` (20 hits) |
| Boot policy | **trust chain + USB download** | **DTIM + SHA-256 + A/B slots** |

### The division of labour

```
Power-on
   │
   ├─> mtd0  OBM ──── verifies RSA signature over DTIM ──┐
   │        (mtd0)    trusts TIM/DTIM metadata            │
   │        reads TIM, loads next stage per flash offsets │
   │        has USB download mode (SWDownloader)          │
   │                                                     ▼
   └─> mtd11/12  U-Boot ─── reads DTIM (mtd7/8) ──> SHA-256 verify ──> A/B slot select
                     exposes Marvell>> console
                     hosts USB Fastboot
                     runs mrvlboot -> bootz -> Linux
   │
   └─> Linux kernel (EMAC up, so networking finally exists here)
```

**Key point:** the RSA signature check that protects the flash layout lives in
mtd0, one stage *above* U-Boot. U-Boot itself does **no** signature
verification — only SHA-256, to detect corruption and drive A/B fallback.

That is why "edit the DTIM hashes" is blocked by mtd0, not by U-Boot.

## 2. mtd0 TIM structure

Same TIM format as the DTIMs (`HMIT` magic, version `0x00040300`). Entries
walked from offset `0x3C`:

| Offset | Tag | Meaning |
|---|---|---|
| `0x38` | `HMIT` | nested TIM header |
| `0x3C` | `IMBO` | OBM image itself |
| `0x9C` | `NASR` | RSA / signature area |
| `0x160` | `PYTD` | DTIM pointer |
| `0x16C` | `PMFD` | Product mode flag |
| `0x180` | `IATO` | OAT / OTA area |
| `0x190` | `ATOF` | ATOF flag |
| `0x194` | `TMBB` | BB marker |
| `0x1B4` | `CPSR` | CPS region |
| `0x1C4` | `IMSD` | IM signature |
| `0x1CC` | **`PROD`** | **production mode flag** |
| `0x1D4` | `PIPE` | pipeline / boot mode |
| `0x1DC` | `FAST` | fast boot |
| `0x1EC` | `CPBT` | CP boot |
| `0x1F4` | `MACA` | MAC address A slot |
| `0x1FC` | `MACB` | MAC address B slot |
| `0x204` | `RDUP` | ramdump upload |
| `0x2B8` | `IRBT` | |
| `0x2C1` | `RDDP` | ramdump |

The presence of a populated `PROD` entry is what puts the device in production
mode (see §3).

## 3. USB download mode exists in mtd0 — but is gated by the PROD flag

This is the important finding for your question *"can I get Fastboot over USB
without soldering?"*

### mtd0 has no Fastboot

```
strings mtd0.bin | grep -c fastboot   → 0
strings mtd0.bin | grep -c gadget     → 0
strings mtd0.bin | grep -c dwc3       → 0
```

What mtd0 has instead is Marvell's proprietary **`SWDownloader 4.9.0.5`**
protocol — a *flash-writing* transport, not a RAM-boot one.

### Its behaviour is explicitly conditional

```
0x37ec4  [Non-Prod]Wait for download...
0x37f10  [PROD]Enum USB port
0x37f28  [PROD]Don't enum USB port
0x37e54  User force to download
0x37e6c  Wait for download change timeout to true...
0x37e9c  <<<< Production_Mode_Flag =
0x37f80  isDownload=
0x37f74  bootMode=
0x38a54  <<<< OTA force set PROD to 0!!!!
0x37d1c  Falcon
0x37d18  NezhaC
0x37dc0  Trusted OBM without ProductBuild
0x37ec4  [Non-Prod]Wait for download...
```

In **Non-Prod** it waits for a download host. In **PROD** it explicitly chooses
*not* to enumerate the USB port (`[PROD]Don't enum USB port`). `PROD` is a
populated entry in the mtd0 TIM header, so this device is very likely in
production mode.

The only bypass is `User force to download` — the word **"force"** implies it is
not taken in normal operation. I searched for what hardware signal sets it and
found **no** GPIO/button/strap strings associated with it; mtd0's only pin-related
string is `Falcon A0 spi pinmux`. So the trigger mechanism is unresolved.

### Conclusion for your plan

| Route | UART needed? | Writes flash? | Assessment |
|---|---|---|---|
| **UART → `fastboot` → `bootz`** | Yes | **No** | Only RAM-boot route. Fully reversible. |
| USB `SWDownloader` from OBM | No | **Yes** | Gated by PROD flag; proprietary; **not Fastboot**; cannot RAM-boot. |

There is **no USB-only path to a RAM boot on this device.** USB download mode
would write flash, which is precisely what the RAM-boot approach is designed to
avoid.

Worth noting: this outcome is *safer* than it looks. `SWDownloader` would rewrite
flash over a tool we cannot easily audit, into A/B and RSA logic that is only
partly mapped. The 3-wire UART job buys the non-destructive path **and** the
only guaranteed recovery route (`bootcmd=mrvlboot`). Treat UART as mandatory, not
optional.

## 4. RSA in mtd0 — the real trust anchor

```
0x37e54  User force to download
0x37e20  rsa_flashaddr_get failed
0x37e3c  rsa_flashaddr_get ok
0x37ae0  RSA_UNRSA upgrade_mode
0x37af8  UNRSA_RSA upgrade_mode
0x37b10  RSA_RSA upgrade_mode
0x37b64  image rsa error
0x37b78  EraseFlash: / 0x37b8c WriteFlash:
```
Plus (from the earlier scan):
```
check_notion_rsa success / check_notion_rsa failed
Verify DTIM Signature Failed:
Verify Encrypted Key Failed:
rsa key not right
image rsa error
ENCK Key Not Found
OEMKeyHash
RSAN LZMA_Decompress / RSAN image skip rsa
OTA_Save_Config error
```

The four `*_upgrade_mode` strings look like an
`(OBM signature state, DTIM signature state)` state machine.

**What remains unresolved:** precisely what bytes the RSA signature covers, and
therefore whether a DTIM with edited SHA-256 fields still passes. Establishing
this requires disassembly of `check_notion_rsa` in mtd0 — **not yet done**.
Recall from `uboot_analyse.md` §4 that U-Boot performs no RSA check at all, so
mtd0 is the sole gate.

Also note mtd0's TIM has a `NASR` entry at `0x9C`, and `mtd20.bin` (256 KB,
partition name `rsa`) holds `NASRF` / `IMBO` / `IBRA` records — likely the RSA
public key material referenced by `rsa_flashaddr_get`.

## 5. Storage and memory details in mtd0

```
0x37bbc  BBT Exhausted Error
0x37c38  BBT are exhausted!!!
0x37c64  BBT Write Error!!!
0x37c9c  Fatal Error Code:
0x37d64  -- Apr 11 2024 - 18:25:10 --
0x37df4  SecurityInitialization
0x37e0c  Flash Init Done
0x37de4  MMU Enabled
0x37f44  Trusted OS
0x37f50  OS-loader
0x37fa4  Jump to %s at 0x%x (size 0x%x)
0x37fd0  Trusted OS in TIM
0x37fe4  Uboot in TIM
0x37ff4  No Next Image to transfer to
0x38038  HandleDisconnect
0x3804c  Shutdown
```

NAND driver evidence (mtd0 talks to the SPI-NAND directly, not via an mtd layer):
`__spi_nand_read`, `__spi_nand_write`, `spi_nand_erase`, `spi_nand_fill_oob`,
`spi_nand_read_oob`, `spi_nand_transfer_oob`, vendor ECC-status routines for
`generic`/`micron`/`gd`, and QSPI controller strings
(`Bus clock: %dMHz QSPI_CLK_RES_CTRL: 0x%x`, `qspi: cmd trigger failed`).

`Jump to %s at 0x%x (size 0x%x)` confirms mtd0's job: read the next stage's
address+size from TIM and jump. It does not load a kernel itself.

## 6. Boot-time sequence implications

1. mtd0 runs first, from SPI-NAND. It initialises MMU, security and flash.
2. It resolves the next image from TIM (`Uboot in TIM`, `Trusted OS in TIM`) and
   jumps — that's U-Boot from `mtd11`/`mtd12`.
3. U-Boot runs `mrvlboot`, reads DTIM from `mtd7`/`mtd8`, verifies SHA-256,
   picks an A/B slot, and `bootz`es the kernel.
4. Linux initialises the EMAC — the first point at which the device has
   networking.

Consequence for recovery: because the chain is serial and verified, a failure at
step 1–2 is invisible from software. **UART at step 2 is the only practical
inspection and recovery point.**

## 7. Artifacts saved to this folder

Copied from `../oem_backup/dumps/` and verified byte-identical:

| File | Size | SHA-256 (first 16) | Role |
|---|---|---|---|
| `mtd0.bin` | 262,144 | `027efa61d29998bf` | OBM — first stage, RSA + USB download |
| `mtd11.bin` | 786,432 | `ef32bf6aa6f2b774` | U-Boot `u-boot-a` (already present) |
| `mtd7.bin` | 262,144 | `7de63ddc29453b0a` | DTIM primary (hash table) |
| `mtd8.bin` | 262,144 | `cb9d38db0b6a11ba` | DTIM backup (differs only in signature block) |
| `mtd21.bin` | 262,144 | `d9b9ce55d42922b5` | U-Boot environment (plaintext `key=value`) |

All five are covered by `MANIFEST.sha256` in this folder.

## 8. Summary

- **mtd0 is a Marvell OBM, not U-Boot.** Minimal freestanding stage: no shell, no
  commands, no Fastboot. It verifies RSA, reads TIM, and jumps.
- **mtd11 is U-Boot**: interactive `Marvell>>` console, USB Fastboot, SHA-256
  image validation, A/B slot logic, charger/LCD/ramdump support.
- **Neither has any network stack** — no TFTP, no DHCP, no Ethernet. So the
  "TFTP bootloader" route discussed in `TFTP_AND_FAILSAFE.md` is still the only
  way to get TFTP, and it means replacing the bootloader. Unnecessary: USB
  Fastboot in U-Boot already provides fast transfer.
- **USB alone cannot reach a RAM boot.** mtd0's `SWDownloader` is gated by the
  PROD flag and writes flash; U-Boot's Fastboot needs the console. **UART is
  required for the safe test.**
- **The DTIM SHA-256 algorithm is solved** (plain `sha256(partition[0:size])`),
  but whether mtd0's RSA signature tolerates edited hashes is still open and
  needs mtd0 disassembly. Irrelevant for RAM boot; essential before any durable
  flash install.

### Suggested next steps

1. Zero-risk USB check (no soldering): plug the router into the host USB and run
   `lsusb` / `dmesg -w` during power-on. If nothing enumerates, that confirms
   UART is the only route. Use a **data** cable — the port is also a charger.
2. Attach the TTL adapter (115200 8N1, 3.3V), interrupt autoboot, and collect
   `printenv` + `bdinfo`. That settles the Fastboot invocation form and the real
   RAM layout.
3. Only then: `fastboot download` + `bootz` for the RAM boot.

For a durable install later, tackle the mtd0 RSA question in §4 before writing
any DTIM.

