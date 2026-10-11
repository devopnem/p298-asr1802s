# Notion P298 — ASR1802S (P298_N13, KAGU)

Linux mainlining, OpenWrt port, and primary-source hardware findings for the
**Notion P298** router — hardware version `P298_N13`, board codename
**KAGU / ASR1826s**, **ASR1802S** SoC (ARM Cortex-A7, Marvell-MMP-derived),
128 MB RAM, 128 MiB SPI-NAND, 25 MTD partitions.

The name used throughout this project is **P298**. It is the platform code the
hardware actually carries: it is on the board silkscreen, in the U-Boot banner
(`ASR KAGU EVB P298`), in ASR's own kernel build string
(`BB14.07_asr1826sP298_...`), and it is the prefix of the device's TR-069 model
(`P298M22I_Ooredoo_Tuni_R2921_1G`).

> **Why not R291?** The firmware's `EXTERNAL_VERSION` says `Ooredoo-R291-V2`,
> which is the operator's retail SKU for the same board. But an unrelated
> **MediaTek MT7621A** product is also sold as "Notion R291", so the string is
> ambiguous across two completely different devices. P298 is not. See
> [`findings/README.md`](findings/README.md).

---

## Where things are

| path | what |
|---|---|
| **`findings/`** | **Primary-source device data** — probes, NAND dumps, firmware backup, PCB photos, flash tooling. Its **own git repository**, tracked at [devopnem/p298-asr1802s-findings](https://github.com/devopnem/p298-asr1802s-findings). Read [`findings/README.md`](findings/README.md). |
| **`docs/`** | All written documentation, by subject (see below) |
| **`porting/`** | Mainline porting work — `reverse/` (hardware reverse engineering), `delivery/` (flashing and bring-up scripts) |
| **`ops/`** | Work performed against a live unit — `api/` (TR-069/ACS), `sim-unlock/` |
| **`hardware`** | → `findings/board` (chip markings, PCB photos) |
| **`recovery`** | → `flashing_tools/` — vendor flashing tools and the current recovery working set |
| **`data/`** | **Local only, never pushed.** A second physical unit, unsanitised probes, extracted rootfs, and one file containing live IMEI/IMSI/MAC. Read [`data/README.md`](data/README.md). |
| **`tools/`** | Standalone helper scripts |
| **`archive/`** | Finished snapshots kept for reference |

Cloning this repository alone is not enough: `findings/` is a separate
repository, and several paths here are symlinks into it.

```bash
git clone git@github.com:devopnem/notion-p298.git
git clone git@github.com:devopnem/p298-asr1802s-findings.git   # sibling
```

### Sync

`findings/` is the single source of truth for the findings repository, so
local and GitHub cannot drift:

```bash
git -C findings pull
git -C findings push
```

### Disk layout is de-duplicated

Every MTD dump, kernel, rootfs and probe used by this repository is a
**symlink into `findings/`** rather than a second copy. `findings/nand-dumps/`
and `findings/firmware-backup/` are the only real copies.

---

## Documentation index

| file | subject |
|---|---|
| [`docs/hardware/asr_and_marvell.md`](docs/hardware/asr_and_marvell.md) | ASR's acquisition of Marvell's modem division, and the PXA1802 / ASR1802S lineage |
| [`docs/hardware/info_on_board.md`](docs/hardware/info_on_board.md) | What is physically on the board |
| [`docs/hardware/wifi_RTL8812FR_RTL8192FR.md`](docs/hardware/wifi_RTL8812FR_RTL8192FR.md) | The RTL8812FR / RTL8192FR PCIe Wi-Fi pair |
| [`docs/bootloader/REPORT.md`](docs/bootloader/REPORT.md) | **Start here.** OBM, DTIM, U-Boot, A/B, RSA secure boot, the full boot chain |
| [`docs/bootloader/uboot_analyse.md`](docs/bootloader/uboot_analyse.md) | U-Boot internals, TIM/DTIM structure, verified hashes |
| [`docs/bootloader/bootloader_analyse.md`](docs/bootloader/bootloader_analyse.md) | Where Fastboot lives (it does — over USB/DWC3), why TFTP does not |
| [`docs/bootloader/TFTP_AND_FAILSAFE.md`](docs/bootloader/TFTP_AND_FAILSAFE.md) | Why TFTP is impossible on this bootloader, and how failsafe really behaves |
| [`docs/recovery/flashing_and_failsafe_guide.md`](docs/recovery/flashing_and_failsafe_guide.md) | Flashing OpenWrt, failsafe, A/B slot switching *(pre-dates the reorganisation; some paths were rewritten, some statements are superseded — see its header)* |
| [`docs/recovery/swdownloader_blf_findings.md`](docs/recovery/swdownloader_blf_findings.md) | How far the SWDownloader route got and why it stopped |
| [`findings/tooling/blf/swdownloader-blf-spec.md`](findings/tooling/blf/swdownloader-blf-spec.md) | The recovered `.blf` format, as a reference spec |
| [`findings/tooling/blf/flash-map.md`](findings/tooling/blf/flash-map.md) | Verified 128 MiB SPI-NAND map |
| [`docs/porting/mainlin.md`](docs/porting/mainlin.md) | Mainlining status |
| [`docs/porting/BRINGUP_MILESTONES.md`](docs/porting/BRINGUP_MILESTONES.md) | Milestones |
| [`docs/porting/PCIe_PHY_DRIVER_PLAN.md`](docs/porting/PCIe_PHY_DRIVER_PLAN.md) | PCIe PHY driver |
| [`docs/porting/BUILDCI.md`](docs/porting/BUILDCI.md) | CI and build rules |
| [`docs/ops/api-rgw.md`](docs/ops/api-rgw.md), [`docs/ops/ssh_open.md`](docs/ops/ssh_open.md) | Remote management / SSH access |
| [`docs/ops/confirmed.md`](docs/ops/confirmed.md) | What is confirmed versus assumed |

---

## External work

| | |
|---|---|
| Linux RFC series | [devopnem/linux-asr1802s-rfc](https://github.com/devopnem/linux-asr1802s-rfc) |
| OpenWrt port | [openwrt/openwrt#24614](https://github.com/openwrt/openwrt/pull/24614), branch `asr1802s-kagu-wip` |
| Device data | [devopnem/p298-asr1802s-findings](https://github.com/devopnem/p298-asr1802s-findings) |

The OpenWrt fork is a separate checkout at `~/Downloads/openwrt/openwrt-fork`
(symlinked here as `openwrt-fork`, gitignored). Target is
`target/linux/asr1802s/` — kernel 6.12, musl.

---

## Recovering a bricked unit

The P298 has no dedicated recovery button and cannot be rescued from a running
system once it fails to boot. These are the documented routes, in the order
worth trying.

* **UART over the test points — try this first.** It is read-only, costs
  nothing, and tells you immediately whether the flash is intact: if the
  `Marvell>>` prompt appears, the bootloader survived and most of the recovery
  work is unnecessary. 1.8 V, 115200 baud, GND, cross TX/RX, **do not connect
  VCC**. See [`docs/recovery/flashing_and_failsafe_guide.md`](docs/recovery/flashing_and_failsafe_guide.md).
* **USB ROM-boot + SWDownloader read** — the unit enumerates as `2ecc:3002`
  (ASR ROM boot mode) when the `USB_BOOT` test point is asserted, dropping off
  the bus after ~1.5 s if the host does not handshake. This gives a read-only
  flash dump; config templates are in
  [`findings/tooling/blf/`](findings/tooling/blf/).
* **USB ROM-boot + SWDownloader write — blocked.** The DKB image list needs
  Marvell-internal `WTMI` and `TZII` blobs that are not any MTD partition and
  are not obtainable from the hardware. Analysis in
  [`findings/tooling/blf/swdownloader-blf-spec.md`](findings/tooling/blf/swdownloader-blf-spec.md) §6.
* **UART fastboot** — U-Boot exposes a USB fastboot gadget over DWC3, so once
  you have a UART shell this is a viable write path that avoids SWDownloader
  entirely.
* **NAND clip / programmer** — the last resort if the bootloader is gone.

⚠️ Whatever the route, **do not write a raw uImage + DTB to `mtd7`
(`0x0100000`) or `mtd8` (`0x0140000`)**. Those are the DTIM/bootloader slots;
overwriting them with a kernel image is what turns a recoverable unit into a
dead one.

## ⚠️ Privacy

`findings/` is public. Its **text files are sanitised** (`[REDACTED]` for
IMEI, IMSI, MACs, passwords) but the **binary dumps ship as read** and contain
this unit's NVM/calibration data. Treat them as private unit data.

`data/` is **never** pushed and contains the unsanitised originals, including
a file with this unit's live IMEI, IMSI and MAC addresses.
