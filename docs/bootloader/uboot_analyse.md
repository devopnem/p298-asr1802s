# U-Boot (mtd11) Analysis — Notion R291 ASR1802S "Kagu"

Analysis date: 2026-10-06
Artifact: `mtd11.bin` (copied from `../findings/nand-dumps/mtd11.bin`, hash-verified identical)

| Property | Value |
|---|---|
| SHA-256 | `ef32bf6aa6f2b774e7b0b8e5241a7ccaee909e517b593163a3aaafd81b41f446` |
| Size | 786,432 bytes = `0xC0000` (exactly the `u-boot-a` partition size) |
| Meaningful code | ends at `0x751b4` (~472 KB); `0x76000`..end is `0xFF` padding |
| Base | ARM exception vector table at `0x00` → ARM32, little-endian |
| Compiler | `arm-openwrt-linux-uclibcgnueabi-gcc (OpenWrt/Linaro GCC 4.8-2014.04 r47068) 4.8.3` |
| Linker | `GNU ld (GNU Binutils) 2.22` |
| Prompt | `Marvell>> ` |
| Prompt string | `@ 0x5ce6f` |

Verified identical to `mtd12.bin` (`u-boot-b`) — both A/B slots hold the same bootloader.

## 1. Direct answers

### Is there a TFTP server? NO.

Exhaustive string search of the whole 768 KB image:

| Token | Hits |
|---|---|
| `tftp`, `tftpboot` | **0** |
| `bootp`, `dhcp` | **0** |
| `nfs` | **0** |
| `ipaddr`, `ethaddr`, `serverip` | **0** |
| `mii`, `ping`(as command) | **0** |
| `ethernet` | **0** |

The 3 `ping` hits are **false positives** — substrings of `"...mapping"` and
`"...skipping bad blocks"`. `phy` (6 hits) refers to the `88PM801` **PMIC**
fuel-gauge (`pm801_fg_check_battery`), not an Ethernet PHY.

**Conclusion: there is no network stack of any kind in this bootloader.** No TFTP,
no DHCP, no Ethernet driver, no ARP. This is not a configuration issue — the code
is not compiled in. It cannot be enabled by `setenv`.

This confirms and strengthens `REPORT.md` §6, which reached the same conclusion
independently.

### Is Fastboot available? YES — and it is the real transfer path.

This was **missed by the existing documentation**. The image contains a complete
USB Fastboot server:

```
0x63030  fastboot.c
0x62bdd  gadget.c
0x62e63  dwc3-gadget
0x59fbb  android fastboot client application
0x630a1  Fastboot serial no set as:%s
```

Supporting strings confirm a DesignWare USB3 DRD gadget stack:
`this is not a DesignWare USB3 DRD Core`, `dwc3_gadget_start_config: ep NULL`,
`failed to initialize gadget`, `gadget %s data soft-%s`.

Fastboot command table present at `0x59d00`–`0x59fc0`:
`download:` (`DATA`), `erase`, `oem`, `onfly`, `bootsp`, `setno`, `fb_serial`,
`fbenv`, `senddata`, `upload`, `senddata`, `go %x`, `booting linux...`.

### Can you transfer a file over UART? NO.

There is **no serial download protocol** compiled in:

| Command | Present? |
|---|---|
| `loadb` | **absent** |
| `loady` | **absent** |
| `ymodem` / `xmodem` | **absent** |
| `load` / `sload` | **absent** |

Absent too: `tftpboot`, `usbboot`, `booti`, `cdc_acm`, `protect`, `cmp`.

**Consequence:** it is *not possible* to push a 5.4 MB file over the serial
console. The USB Fastboot path is the only high-speed transfer route.

### Is Ethernet enabled in U-Boot? NO.

The Ethernet MAC on this SoC is initialized only by the **Linux kernel**
(`emac_up`, per `emac_re/RE_NOTES.md` in the project). U-Boot brings up the
DDR, SPI-NAND, PMIC, USB gadget and charger — but never the MAC.

## 2. Boot flow and the A/B hash gate

`bootcmd=mrvlboot` (custom Marvell command) drives boot. Relevant strings:

```
0x5796d  @@ DTIM@0x%x, ASR FLAG@0x%x
0x5798a  @@ Retrive image offset/size from DTIM.
0x57ccc  Kernel is not in DTIM_Primary
0x57ceb  Kernel Hash mismatch
0x57d01  PASS: Kernel verify.
0x57d17  @@@ System %s validation failed, try the other one...
0x57d4e  @@@ System %s validation failed either, no good system...
0x57d89  @@@ FATAL Error, two systems were illegal
0x57db4  @@@ System %s validation OK, rollback to it...
0x57a97  @@ Default AB flags: active_slot: %c, temp_active_slot: %c, reboot_cnt: %d, synced: %d
0x57b38  Got ASR Flag Offset: 0x%x.
```

Boot reads the DTIM (mtd7/mtd8) to obtain per-image offset+size, validates the
image **SHA-256**, and honours an A/B active-slot flag with automatic rollback.
A failed slot is abandoned for the other one.

Verified: the A/B flag structure lives in `mtd19.bin` (`asr_flag`), magic
`ATOF` at offset 0, with strings `OBMD`, `DLFGDLOK` ("DLFGDLOK" = **D**o**L**o**a**d
**F**la**G**s reverse-stamped), `NOCP`.

## 3. DTIM hash algorithm — SOLVED

`REPORT.md` §2 listed this as unresolved open work (*"needs disassembling
mrvlboot to know the exact hash equation — our direct SHA-256 of the region did
not fully match"*). **It is plain SHA-256.** Confirmed empirically against the
real dumps:

```
sha256( mtd13.bin[0 : 0x2C3320] )  ==  stored SYSJ hash in dtim-a   ✅ EXACT MATCH
```

That is: SHA-256 over the **first `size` bytes** of the partition, where `size`
is the DTIM entry's size field. No padding, no OOB/spare interleaving, no
canonicalisation.

### DTIM entry map (mtd7 = dtim-a)

Each entry is a Marvell TIM record. Layout confirmed as:
`tag(4) | flags/attrs | size(4) | loadaddr(4) | hashlen(4) | hash(N)`

| Tag | Partition | Size field | Hash stored at | Meaning |
|---|---|---|---|---|
| `ARBI` | mtd9 / mtd10 | `0x75A8DC` | `0x0B8` | CP / Arbel (modem fw) |
| `RFBI` | mtd9 / mtd10 | `0x20000` | `0x170` | RF |
| `OSLO` | mtd11 / mtd12 | `0x751B8` | `0x1D0` | U-Boot |
| `ZIMG` | mtd13 / mtd14 | `0x2C3320` | `0x230` | **Kernel** |
| `SYSJ` | mtd15 / mtd16 | `0xBA2A5E` | `0x290` | **Rootfs** |
| `OEMD` | mtd17 / mtd18 | `0x1E0000` | `0x2F0` | oem_data |

Hashes verified to match `sha256(partition[0:size])` for every row above.

**This means the DTIM tables are regenerable** — a custom image can be made
bootable by patching size + SHA-256 into the right DTIM entries.

### DTIM primary/backup relationship

`mtd7.bin` and `mtd8.bin` are **identical** from `0x000` to `0x201EC`, then
diverge: `mtd7` has an RSA-signature/encrypted block at `0x201ED`–`0x20833`
(~1.6 KB of high-entropy data) where `mtd8` has `0xFF`.

`mtd7` structure: TIM header at `0x00` (`HMIT` magic, version `0x00040300`),
entries from `0x3C` onward, used length 133,172 bytes of 262,144.

## 4. Does U-Boot verify the DTIM signature? NO

```
strings mtd11.bin | grep -ci "Verify DTIM Signature|check_notion_rsa|rsa key not right"
→ 0
```

`rsa` appears **0 times** in the whole U-Boot image. U-Boot only does SHA-256
hashing, never RSA. **All RSA verification lives in the OBM (mtd0)** — see
`bootloader_analyse.md` §3.

## 5. Environment (`mtd21.bin`)

Stored as plain `key=value` NUL-separated text at offset `0x00`, backed by
`env_spi_flash.c` ("Erasing SPI flash at 0x%08x", "Writing to SPI flash...0x%x").

```
0x00  .C)-apn_update=0
0x11  autostart=yes
0x1f  baudrate=115200
0x2f  bootargs=root=/dev/mtdblock11 rootfstype=squashfs init=/etc/preinit
      noinitrd console=ttyS0,115200 panic_debug crashkernel=4k@0x00A00000
      RDCA=0x00A00400 rootsize=0xF00000 force_pm80x_fg
0xe8  bootcmd=mrvlboot
0xf9  bootdelay=1
0x105 bootfile=zImage
0x115 cdc_connect_timeout=60
0x12c dropbear_key_type=99
0x141 dropbear_mode=1
0x151 dropbear_password=85719364     <-- plaintext credential
0x16c loadaddr=0x00008000
0x180 mtdids=nand0=nand_mtd
0x1b3 stderr=serial
0x1c1 stdin=serial
0x1ce stdout=serial
0x1dc verify=no
0x1e6 wifi_cal=1
```

### `setenv` vs `fw_setenv` — persistence

- `setenv bootdelay 10` at the U-Boot console changes the **RAM copy only**. It
  is lost on reboot unless followed by `saveenv`.
- `fw_setenv bootdelay 10` over SSH writes **directly to flash** (`mtd21`,
  the env partition) and **persists**.
- `saveenv` **does exist** in this image (`0x5b742`, "save environment variables
  to persistent storage").

`bootdelay=1` is why the autoboot window is only one second.

**Recommendation:** use `fw_setenv`, not console `setenv`+`saveenv`. It touches
only `mtd21` — never `mtd0` (OBM), `mtd11` (bootloader), or the DTIMs — and
avoids an erase/rewrite cycle on a flash sector.

### Security note

`dropbear_password` is stored in **plaintext** in `mtd21` and is also published
in plaintext in `TFTP_AND_FAILSAFE.md`. If this repo is ever shared publicly,
rotate that credential and scrub the doc.

## 6. Command inventory

Confirmed as registered commands:

```
bootm      bootz      bootd      run        imxtract   iminfo
reset      printenv   setenv     saveenv    mtdparts   erase
sleep      echo       help       version    coninfo    base
bdinfo     itest      crc32      i2c        gpio       fastboot
mrvlboot   ddr0       ramdump    ramdump2   ubi        ubifs*
ubi write / ubi read / ubi remove
ubifsmount ubifsumount ubifsload ubifsloadnvm ubifsls
```

`bootz` (`0x59878`, "boot Linux zImage image from memory") is the key command
for RAM-booting a raw zImage. Note `booti` is **absent**, and `bootz` rejects
an Android boot image (`FAILNot zImage, use bootsp oem cmd to boot special app`).

## 7. RAM topology

From the vendor DTB (`../findings/firmware-backup/vendor_dtb_extracted/vendor.dtb`):

```
memory { reg = <0x4000000 0x8000000>; };    /* base 64 MB, size 128 MB */
```

U-Boot also prints `mem=512M@0x%x`, `mem=256M@0x%x`, `mem=128M@0x%x`,
`mem=64M@0x%x` and warns `Unsupport DDR size` — so the DTB and U-Boot's own
tables disagree on total size. **Read `bdinfo` at the console to get the truth**
rather than trusting either source.

`0x8000000` appears in U-Boot as `reserve 4KB for ramdump boot`.

## 8. USB port role

```
dwc31@c0000000 {
    compatible       = "snps,dwc3";
    dr_mode          = "peripheral";        /* USB DEVICE mode */
    maximum-speed    = "super-speed";
    usb-phy          = <0x02>;               /* asr,asr-usb3-phy @ 0xc0030000 */
    vbus-gpio        = <0xff>;               /* invalid */
    id-gpadc         = <0xff>;               /* invalid */
};
```

The port is a **USB gadget/device** port, not a host port. It is **not** the
modem: both PCIe ports are occupied by WiFi (RTL8812FE `10ec:f812` and
RTL8192FR `10ec:818c`), per this project's own `docs/porting/PCIe_PHY_DRIVER_PLAN.md`.

The `marvell,88pm80x-usb` nodes in the PMIC subtree are charger/VBUS-detect
logic (`vbus-detect`, `get-vbus`, `vchg-from-exton`) and that node is
`status = "disabled"`.

**Operational caveats:** with `vbus-gpio`/`id-gpadc` = `0xff`, software cannot
detect cable presence, so "plugged in" must not be used as a "ready" signal. And
because this is a charge port, a **charge-only USB cable will not work** for
Fastboot — that is the first thing to rule out.

## 9. Practical procedure: RAM-boot a custom kernel, writing nothing to flash

Because nothing is written, **neither the DTIM hash gate nor the OBM RSA check
applies.** Every reboot simply returns to normal factory boot.

```
# --- on the Linux host (SSH), phase 1 ---
ssh root@192.168.1.1 'fw_printenv bootdelay'      # expect: bootdelay=1
ssh root@192.168.1.1 'fw_setenv bootdelay 10'     # persists, touches mtd21 only
ssh root@192.168.1.1 'reboot'

# --- phase 2: serial console, 115200 8N1, 3.3V TTL ---
#   expect: "Hit any key to stop autoboot: 10"
#   press any key -> "Marvell>> "
Marvell>> printenv          # confirm bootdelay=10
Marvell>> bdinfo            # get authoritative RAM base/size
Marvell>> fastboot          # UNCONFIRMED whether it takes no arguments

# --- phase 3: host, Fastboot ---
fastboot devices
fastboot download 0x8000000 5473240    # 5473240 = size of initramfs-kernel.bin
Marvell>> md 0x8000000 20              # sanity-check received bytes
Marvell>> bootz 0x8000000              # NOT `fastboot boot` (expects bootimg)
```

### Open risks

1. **`fastboot` invocation form is unverified.** The command name exists at
   `0x630d8`, but whether it accepts zero arguments (or wants a subcommand)
   could not be determined statically. Only observable at runtime.
2. **Load address `0x8000000` is provisional** — confirm against `bdinfo`.
3. **Fastboot requires reaching the U-Boot console**, i.e. the TTL adapter. No
   automatic, `bootcmd`-driven, or USB-triggered Fastboot entry exists in this
   image. The USB download path (`SWDownloader`) lives one stage earlier, in the
   OBM, and is gated by the production flag — see `bootloader_analyse.md` §3.
4. **UART is the only recovery path.** If a RAM boot wedges the router,
   `bootcmd=mrvlboot` from the console is how to get back in. There is no
   equivalent USB fallback.

## 10. Image size — hard constraint on any flash-based approach

Partition sizes from `fw_env_full.txt`:

| Image | Bytes | Target partition | Capacity | Fits? |
|---|---|---|---|---|
| `initramfs-kernel.bin` | 5,473,240 | `kernel-a` (mtd13) | 5,242,880 (`0x500000`) | **NO — over by 230,360 B (225 KB)** |
| `squashfs-kernel.bin` | 3,267,416 | `kernel-a` | 5,242,880 | yes |
| `squashfs-rootfs.bin` | 2,621,444 | `rootfs-a` (mtd15) | 20,971,520 (`0x1400000`) | yes |

The `-initramfs-kernel.bin` is **inherently too large to persist**; it is built
to be booted from RAM. Any durable install must use the squashfs pair.

DDR headroom for the RAM boot is comfortable:

```
openwrt-...-initramfs-kernel.bin   5,473,240 B on flash
  XZ payload at 0x6C87             5,434,865 B compressed
  decompresses to                 18,397,120 B = 17.5 MB
  DDR available                                128 MB
  headroom                                     ~110 MB
```

Image layout: ARM zImage header + XZ payload, with the DTB appended at
`0x535A78` (10,592 bytes) — not an Android boot image.

## 11. Corrections to existing documentation

| Document | Claim | Correction |
|---|---|---|
| `REPORT.md` §6 | "No TFTP line at all" | ✅ Confirmed. |
| `REPORT.md` §6 | TFTP only possible by replacing bootloader with a TFTP-enabled `uboot.bin` | Still true, but the doc omits that **USB Fastboot already exists** and needs no bootloader replacement. |
| `REPORT.md` §2 | DTIM hash algorithm unknown / open work | ❌ **Now solved** — plain `sha256(partition[0:size])`, verified against all 6 entries. |
| `TFTP_AND_FAILSAFE.md` | Failsafe reachable without UART | ⚠️ The doc itself notes `pi_ifname=` is empty, so network failsafe does not work. Not re-tested here. |
| `TFTP_AND_FAILSAFE.md` | Publishes `dropbear_password` in plaintext | ⚠️ Credential exposure; rotate and scrub if shared. |
| both | UART used for file transfer | ❌ Impossible — no `loadb`/`loady`/ymodem. UART is console-only; USB Fastboot is the transfer path. |

## 12. Method / reproducibility

```bash
sha256sum mtd11.bin
binwalk mtd11.bin                       # CRC32 tables + one LZMA blob at 0x565F3
strings -a -t x mtd11.bin | grep -i <token>
python3 -c "import hashlib;print(hashlib.sha256(open('mtd13.bin','rb').read()[:0x2C3320]).hexdigest())"
```

The single LZMA blob at `0x565F3` decodes to 40,960 bytes of repeating
`0x3D` — **padding, not code or data of interest**.
