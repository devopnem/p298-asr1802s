# Notion P298 ASR1802S — OpenWrt Flash & Failsafe Guide

> **Consolidated guide** for flashing OpenWrt onto the Notion P298 (ASR1802S/ASR1826s).
> Replaces `flashing_guide.md` and `FLASH_TEST_PLAN.md`.
>
> **Rev 2026-09-11:** SSH-only findings incorporated — live unit boots `system=b`
> (not `a`), `fw_printenv` has **no `system` variable** (bank select likely via
> `asr_flag` mtd19, unverified), unit exposes **mtd0–mtd24 incl. `MRVL_BBM`**,
> `initramfs-kernel.bin` (5,473,240 B) **does not fit** the 5 MiB kernel
> partition, padding must be **0xFF** (not `truncate` zeros) or DTIM hashes
> mismatch, `flash_slot_a.sh` has scp/`basename` bugs (use §5b inline instead),
> `openwrt_r291` password via `uci-defaults` unverified, UART level likely
> **1.8 V not 3.3 V** (measure before driving pins).
>
> **Rev 2026-10-10 — read this first.** Path references were updated during the
> workspace reorganisation, but the *technical* content below pre-dates a month
> of further work and some of it is now known to be wrong or superseded. Known
> corrections and additions:
>
> | Section | Status |
> |---|---|
> | §3 "Prepare Flash Images", §5 "Flash Slot A" | The stated hashes only match if DTIM in mtd7/mtd8 is rebuilt. That rebuild is still **unsolved**. See [`../bootloader/REPORT.md`](../bootloader/REPORT.md) §2. |
> | §5 "Flash Slot A" | Assumes a **booted** unit with SSH. The unit is now bricked; this route is unavailable until the flash is restored. |
> | §7 "Failsafe Mode" | Still accurate, including that failsafe is UART-only here. |
> | §10 "MTD Partition Reference" | Superseded by the verified map in [`../../findings/tooling/blf/flash-map.md`](../../findings/tooling/blf/flash-map.md), which also records that **all A/B slots are byte-identical** on a factory unit and that mtd5/mtd6 are zero length. |
> | §11 (RAM boot / TFTP) | TFTP is impossible on this bootloader — see [`../bootloader/TFTP_AND_FAILSAFE.md`](../bootloader/TFTP_AND_FAILSAFE.md). |
> | — | **U-Boot does have Fastboot**, over USB via DWC3 gadget. It needs no TFTP and bypasses the DTIM hash problem entirely, but only once U-Boot is running. See [`../bootloader/bootloader_analyse.md`](../bootloader/bootloader_analyse.md). |
> | — | The SWDownloader USB write path is analysed in [`swdownloader_blf_findings.md`](swdownloader_blf_findings.md) and is currently **blocked**. |
>
> The stock `mtd7.stock` referred to in §1 is byte-identical to `mtd7.bin`; it is
> a convenience name, not a distinct template.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Build OpenWrt](#2-build-openwrt)
3. [Prepare Flash Images](#3-prepare-flash-images)
4. [Backup Stock Firmware](#4-backup-stock-firmware)
5. [Flash Slot A](#5-flash-slot-a)
6. [Verify Boot](#6-verify-boot)
7. [Failsafe Mode](#7-failsafe-mode)
8. [Slot Switching (A/B)](#8-slot-switching-ab)
9. [Rollback & Recovery](#9-rollback--recovery)
10. [MTD Partition Reference](#10-mtd-partition-reference)

---

## 1. Prerequisites

| Item | Notes |
|------|-------|
| Host PC connected to P298 LAN | Via Ethernet switch port (lan1–lan4) |
| Router stock firmware running | SSH accessible at `192.168.1.1` |
| `sshpass` installed on host | `sudo xbps-install sshpass` (Void Linux) |
| Python 3 | For `dtim-rebuild.py` |
| `dtim-rebuild.py` | In `porting/delivery/` |
| `mtderase` static ARM binary | In `porting/delivery/` |
| Stock mtd7 template | `porting/delivery/mtd7.stock` |

### SSH Options (stock firmware)

```bash
SSHOPT="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -o LogLevel=ERROR -o ConnectTimeout=6 -o BatchMode=yes \
  -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa \
  -o KexAlgorithms=diffie-hellman-group14-sha1"

# Stock passwords (from U-Boot env mtd21): 19222019, 16953087, 83099569, 79476268, 85719364
sshpass -p '79476268' ssh $SSHOPT root@192.168.1.1 'cat /proc/cmdline'
```

**Verify before proceeding:**
- Record live slot: `grep -o "system=[ab]" /proc/cmdline` — **flash the idle
  slot, keep the running slot untouched.** The reference unit currently boots
  `system=b` (`root=/dev/mtdblock16`), so slot A (`mtd7/13/15`) is the test
  target. (Earlier revs assumed `system=a` — do not assume, measure.)
- `bootcmd=mrvlboot`, `bootfile=zImage` present.
- `/proc/mtd` shows 25 partitions (mtd0 through mtd24, incl. `MRVL_BBM` at the
  end — do not touch it). Older notes saying "24 partitions mtd0–mtd23" are
  outdated for this unit.
- `fw_printenv` currently shows **no `system` variable** and a stale
  `bootargs=root=/dev/mtdblock11` while live cmdline is `root=/dev/mtdblock16
  system=b` — i.e. `mrvlboot` patches cmdline at boot. `fw_setenv system a/b`
  (§8) is therefore **unverified** on stock; bank selection may live in
  `asr_flag` (mtd19). Resolve with `hexdump -C /dev/mtd19 | head` before
  relying on slot-switch commands.

### UART console (optional but strongly recommended)

| Item | Notes |
|------|-------|
| USB-TTL adapter with **1.8 V support or external level shifter** | SoC IO is likely **1.8 V, not 3.3 V** (PXA/MMP heritage, 88PM801 PMIC has 1.8 V rails; EMAC IO is the 3.3 V exception, not the rule). A 3.3 V-only adapter showing nothing is expected — and driving 3.3 V into a 1.8 V RX can damage the pin. |
| Multimeter | Measure TX idle level **with board powered, adapter disconnected**: ~1.8 V → 1.8 V logic, ~3.3 V → 3.3 V logic. |
| Wiring | GND common, cross RX/TX, **do not connect VCC**. Try 115200n8 on ttyS0 first (`pxa2xx-uart @ d4017000`); 57600/ttyS1 is an unconfirmed old string note. |
| U-Boot | 1.1.3 with `tftpboot`, `bootdelay=1`, `loadaddr=0x8000`, `bootcmd=mrvlboot` — see §11 for RAM-boot without flashing. |

---

## 2. Build OpenWrt

### 2a. Clone and configure

```bash
cd /path/to/openwrt-fork
make defconfig
```

### 2b. Required config changes

The `image/Makefile` must produce separate `kernel.bin` + `rootfs.bin` files. Verify it contains:

```makefile
IMAGES := kernel.bin rootfs.bin
IMAGE/kernel.bin := append-kernel | check-size $$(KERNEL_SIZE)
IMAGE/rootfs.bin := append-rootfs | check-size $$(IMAGE_SIZE)
KERNEL_SIZE := 5120k
IMAGE_SIZE := 20480k
FILESYSTEMS := squashfs
```

### 2c. Build

```bash
# Full build (kernel + packages + images)
make -j$(nproc) V=s

# Or just compile kernel to test patches apply
make target/linux/compile TARGET=asr1802s -j$(nproc) V=s
```

Output appears in `bin/targets/asr1802s/generic/`:
- `openwrt-...-asr1826s_p298-squashfs-kernel.bin` (~3.2 MiB, raw zImage + DTB) → NAND `kernel` partition (5 MiB, fits)
- `openwrt-...-asr1826s_p298-squashfs-rootfs.bin` (~2.5 MiB, squashfs) → NAND `rootfs` partition (20 MiB, fits)
- `openwrt-...-asr1826s_p298-initramfs-kernel.bin` (~5.2 MiB / 5,473,240 B, kernel + rootfs in RAM) → **RAM-boot only via UART+TFTP (§11), NEVER `mtd write`**: it is larger than the 5,242,880 B kernel partition and would truncate.

`CONFIG_TARGET_ROOTFS_INITRAMFS=y` is already enabled — no `menuconfig` change needed for initramfs output.

### 2d. Minimal package set for working system

The following packages are enabled in the defconfig for a working system:

| Feature | Package | Status |
|---------|---------|--------|
| Base | `busybox`, `dropbear`, `uci`, `ubus`, `dnsmasq`, `firewall4` | ✅ default |
| LuCI | `luci`, `luci-base`, `luci-mod-admin-full`, `luci-theme-bootstrap` | ✅ enabled |
| Ethernet | `kmod-asr-emac`, `kmod-y921x`, `kmod-phy-yt9215` | ✅ patches 0006, 0007, 0010, 0011 |
| PCIe | `kmod-pcie-asr-kagu`, `kmod-pcie-dw-host` | ✅ patches 0013, 0014 |
| WiFi | `kmod-rtl8xxxu`, `rtl8xxxu-firmware` | ✅ patch 0012 |
| PCI | `pciutils` (lspci) | ✅ enabled |
| LED/Trigger | `kmod-leds-gpio`, `kmod-ledtrig-*` | ✅ default |

> ⚠️ The `kmod-asr-emac` / `kmod-y921x` / `kmod-phy-yt9215` /
> `kmod-pcie-asr-kagu` / `kmod-rtl8xxxu` names above are aspirational — verify
> against `bin/targets/asr1802s/generic/*.manifest` after build; actual OpenWrt
> kmod package names may differ (e.g. in-tree vs out-of-tree). Do not treat
> this table as proof the drivers are packaged.

All patches are included in `target/linux/asr1802s/patches-6.12/` and applied automatically.

---

## 3. Prepare Flash Images

### 3a. Locate build output

```bash
cd bin/targets/asr1802s/generic/
ls -la openwrt-*-asr1826s_p298-squashfs-*.bin
```

You need:
| File | Purpose |
|------|---------|
| `openwrt-...-squashfs-kernel.bin` | Raw zImage + appended DTB → mtd13 |
| `openwrt-...-squashfs-rootfs.bin` | Squashfs rootfs → mtd15 |

### 3b. Verify images before flash

```bash
# Kernel: must NOT start with uImage magic 0x27051956
hexdump -C openwrt-*-squashfs-kernel.bin | head -1
# Expected: ARM boot header (0x016f2818 or similar), NOT 27 05 19 56

# Rootfs: must start with squashfs magic "hsqs" (68 73 71 73)
hexdump -C openwrt-*-squashfs-rootfs.bin | head -1
```

### 3c. Pad images to partition sizes (0xFF — NOT truncate zeros)

> ⚠️ **Do not use `truncate -s`** (it zero-fills). `dtim-rebuild.py` hashes
> `data.rstrip(b'\xff')`, so zero-padded images produce wrong SHA256 → DTIM
> reject → "two systems were illegal". Pad with **0xFF**:

```bash
python3 - <<'EOF'
def pad_ff(src, dst, size):
    d = open(src, 'rb').read()
    assert len(d) <= size, (src, len(d), size)
    open(dst, 'wb').write(d + b'\xff' * (size - len(d)))
    print(dst, hex(len(d)), '->', hex(size))
pad_ff('openwrt-asr1802s-generic-asr1826s_p298-squashfs-kernel.bin',
       '/tmp/openwrt-zImage-dtb', 5 * 1024 * 1024)
pad_ff('openwrt-asr1802s-generic-asr1826s_p298-squashfs-rootfs.bin',
       '/tmp/openwrt-rootfs.bin', 20 * 1024 * 1024)
EOF
```

### 3d. Rebuild DTIM (mtd7) with new hashes

```bash
cd /path/to/Notion_P298_ASR1802S

python3 porting/delivery/dtim-rebuild.py \
  porting/delivery/mtd7.stock \
  /tmp/openwrt-zImage-dtb \
  /tmp/openwrt-rootfs.bin \
  /tmp/dtim-a.rebuilt.bin
```

### 3e. Verify DTIM

```bash
hexdump -C /tmp/dtim-a.rebuilt.bin | head -1
# Expected: TIM header magic
```

---

## 4. Backup Stock Firmware

**MANDATORY before flashing.** The running slot is your safety net (on the
reference unit that is slot B — confirm yours via `/proc/cmdline`).

```bash
sshpass -p '79476268' ssh $SSHOPT root@192.168.1.1 '
  mkdir -p /tmp/bak
  for p in 7 8 13 14 15 16 19 21 22; do
    dd if=/dev/mtd${p}ro of=/tmp/bak/mtd${p}.bin bs=1M 2>/dev/null
  done
  ls -la /tmp/bak/'
```

> Note: `porting/delivery/mtd*.bin` copies are dated 2026-09-05 — re-run
> this backup live, don't rely on the old copies alone. `mtd22 cust_info`
> added to the loop; `mtd23 rootfs_data` (UBI) and `mtd24 MRVL_BBM` are left
> untouched.

Pull to host:

```bash
mkdir -p porting/delivery/backup_stock
sshpass -p '79476268' scp $SSHOPT \
  root@192.168.1.1:/tmp/bak/*.bin \
  porting/delivery/backup_stock/
```

**Verify sha256 after pull:**
```bash
cd porting/delivery/backup_stock
sha256sum *.bin
```

---

## 5. Flash Slot A

**Only 3 partitions are written: dtim-a (mtd7), kernel-a (mtd13), rootfs-a (mtd15).**
**Slot B (mtd8, mtd14, mtd16) stays untouched** — it is the hardware fallback.

> Slot rule: this section assumes you are **running slot B** (reference unit:
> `system=b`) and therefore flashing idle slot A. If your unit boots
> `system=a`, mirror the steps to slot B instead — never flash the running
> slot. Prefer the inline §5b sequence below over `flash_slot_a.sh`, which has
> known bugs (missing scp destination on line 15, non-expanding `basename`
> inside single-quoted ssh).

### 5a. Upload files to router

```bash
sshpass -p '79476268' scp $SSHOPT \
  /path/to/porting/delivery/mtderase \
  /tmp/openwrt-zImage-dtb \
  /tmp/openwrt-rootfs.bin \
  /tmp/dtim-a.rebuilt.bin \
  root@192.168.1.1:/tmp/
```

### 5b. Flash (order matters: DTIM → kernel → rootfs)

```bash
sshpass -p '79476268' ssh $SSHOPT root@192.168.1.1 '
  chmod +x /tmp/mtderase

  echo "=== [1/3] Flashing dtim-a (mtd7) ==="
  /tmp/mtderase /dev/mtd7 /tmp/dtim-a.rebuilt.bin || { echo "FAIL: mtd7"; exit 1; }

  echo "=== [2/3] Flashing kernel-a (mtd13) ==="
  /tmp/mtderase /dev/mtd13 /tmp/openwrt-zImage-dtb || { echo "FAIL: mtd13"; exit 1; }

  echo "=== [3/3] Flashing rootfs-a (mtd15) ==="
  /tmp/mtderase /dev/mtd15 /tmp/openwrt-rootfs.bin || { echo "FAIL: mtd15"; exit 1; }

  echo "=== Verifying ==="
  hexdump -C /dev/mtd7ro | head -1
  hexdump -C /dev/mtd13ro | head -1
  hexdump -C /dev/mtd15ro | head -1

  echo "=== Rebooting in 3 seconds ==="
  sleep 3
  reboot'
```

### 5c. Magic byte verification

| Partition | Expected magic | Bytes |
|-----------|---------------|-------|
| mtd7 (dtim-a) | TIM header | `00 04 03 00 54 49 4d 48` |
| mtd13 (kernel-a) | ARM zImage | NOT `27 05 19 56` (that is uImage!) |
| mtd15 (rootfs-a) | squashfs | `68 73 71 73` ("hsqs") |

---

## 6. Verify Boot

1. Wait **3–5 minutes** (first boot generates dropbear keys + builds overlay)
2. `ping 192.168.1.1`
3. SSH in:

```bash
# OpenWrt default password: openwrt_r291 (set via uci-defaults)
# ⚠️ UNVERIFIED: no password setter was found in target/linux/asr1802s/
# (only base-files/etc/board.d/02_network sourcing uci-defaults.sh).
# Confirm the uci-defaults fragment exists in your image before reboot,
# or you may be locked out with no UART. First-login fallback: try empty
# password / failsafe (§7) before assuming the password took.
sshpass -p 'openwrt_r291' ssh $SSHOPT root@192.168.1.1 '
  echo "=== Kernel ==="
  uname -r
  echo "=== MTD ==="
  cat /proc/mtd
  echo "=== Dmesg highlights ==="
  dmesg | grep -iE "asr1802s|qspi|emac|yt921x|mmc|pcie"
  echo "=== Network ==="
  ip link show
  bridge link show 2>/dev/null || brctl show'
```

**Expected results:**
- Kernel: `6.12.x`
- `dmesg` shows: `asr1802s`, `qspi`, `emac`, `yt921x`, `pcie-kagu`, `rtl8xxxu`
- Network: `lan1`–`lan4`, `wan`, `eth0`, `wlan0` (RTL8812FE), `wlan1` (RTL8192FR) interfaces present
- LuCI accessible at http://192.168.1.1

### 6b. WiFi Testing

After verifying basic boot, test PCIe/WiFi:

```bash
sshpass -p 'openwrt_r291' ssh $SSHOPT root@192.168.1.1 '
  echo "=== PCIe ==="
  lspci -v
  echo "=== WiFi ==="
  dmesg | grep -iE "pcie|rtl8xxxu|wlan"
  iw dev
  iw phy0 info
  iw phy1 info'
```

**Expected:**
- `lspci` shows two root ports (bus 00) + two WiFi endpoints (RTL8812FE = 10ec:f812, RTL8192FR = 10ec:818c)
- `iw dev` shows `wlan0` (phy0) and `wlan1` (phy1)
- `iw phy0 info` shows RTL8812FE capabilities (2.4/5 GHz)
- `iw phy1 info` shows RTL8192FR capabilities (2.4 GHz only)

---

## 7. Failsafe Mode

### 7a. How OpenWrt failsafe works (built-in)

OpenWrt has a preinit-based failsafe system:

1. `/etc/preinit` runs early in boot
2. `30_failsafe_wait` checks for `failsafe_wait` in `/proc/cmdline`
3. If present, waits N seconds for user to press `f` on serial console
4. If triggered: drops to root ash shell on UART, blinks LED

**Limitation on P298:** `pi_ifname=` and `fs_failsafe_ifname=` are empty — failsafe only works via UART serial console, NOT over LAN. The reset button does NOT trigger failsafe.

### 7b. Enabling failsafe via bootargs (⚠️ DANGEROUS — skip on SSH-only units)

> ⛔ This rewrites the `bootargs` env (mtd21), contradicting §9 ("do not touch
> mtd21"). A typo here bricks boot with no UART to fix it. Only use with UART
> attached and a known-good backup of `mtd21`. SSH-only users: skip to §7c/§7d.

```bash
sshpass -p 'openwrt_r291' ssh $SSHOPT root@192.168.1.1 '
  fw_setenv bootargs "mem=128M@0x0 cpmem=32M@0x6000000 console=ttyS0,115200 root=/dev/mtdblock15 rootfstype=squashfs failsafe_wait=10"
  reboot'
```

After reboot, during the first 10 seconds of boot, press `f` on UART console to enter failsafe.

### 7c. Custom failsafe for no-UART scenario (recommended)

Since you have no UART, create a custom rescue system that works over LAN.

**Create the init.d script on the router:**

```bash
sshpass -p 'openwrt_r291' ssh $SSHOPT root@192.168.1.1 '
cat > /overlay/etc/init.d/rescue-network << "SCRIPT"
#!/bin/sh /etc/rc.common
START=99
STOP=10

start() {
    # Check if rescue mode is enabled via U-Boot env or bootargs
    if grep -q "rescue=1" /proc/cmdline 2>/dev/null || \
       [ "$(fw_printenv -n rescue 2>/dev/null)" = "1" ]; then
        logger -t rescue "Rescue mode active — starting dropbear on port 22"
        /usr/sbin/dropbear -F -p 22 &
    fi
}
SCRIPT
chmod +x /overlay/etc/init.d/rescue-network
/etc/init.d/rescue-network enable'
```

**To activate rescue mode later (if system is partially working):**

```bash
sshpass -p 'openwrt_r291' ssh $SSHOPT root@192.168.1.1 '
  fw_setenv rescue 1
  reboot'
```

### 7d. dmesg watchdog + auto-failsafe to slot B

This script captures dmesg after 7 minutes and failsafe-reboots to slot B if health checks fail.

```bash
sshpass -p 'openwrt_r291' ssh $SSHOPT root@192.168.1.1 '
cat > /overlay/etc/init.d/dmesg-watchdog << "SCRIPT"
#!/bin/sh /etc/rc.common
START=99
STOP=10

HEALTH_TIMEOUT=420  # 7 minutes

health_check() {
    # Check 1: LAN interface up
    ip link show lan1 >/dev/null 2>&1 || return 1
    # Check 2: DSA switch present
    [ -d /sys/class/net/lan1 ] || return 1
    # Check 3: dropbear running
    pgrep -x dropbear >/dev/null 2>&1 || return 1
    # Check 4: no kernel oops in dmesg
    dmesg | grep -qi "oops\|panic\|bug:" && return 1
    return 0
}

capture_and_check() {
    sleep $HEALTH_TIMEOUT

    # Capture dmesg
    dmesg > /overlay/dmesg-$(cat /proc/cmdline | grep -o "system=[ab]" | cut -d= -f2)-$(date +%s).log 2>/dev/null

    if health_check; then
        logger -t watchdog "Health check PASSED after ${HEALTH_TIMEOUT}s"
    else
        logger -t watchdog "Health check FAILED after ${HEALTH_TIMEOUT}s — failsafe to slot B"
        # Get current slot
        CURRENT=$(grep -o "system=[ab]" /proc/cmdline | cut -d= -f2 | tr -d '\n')
        if [ "$CURRENT" = "a" ]; then
            fw_setenv system b
            logger -t watchdog "Switched to slot B, rebooting"
            sync
            reboot
        else
            logger -t watchdog "Already on slot B, not rebooting"
        fi
    fi
}

start() {
    capture_and_check &
}
SCRIPT
chmod +x /overlay/etc/init.d/dmesg-watchdog
/etc/init.d/dmesg-watchdog enable'
```

**How it works:**
1. At boot, starts a background timer (7 minutes)
2. After 7 min, runs health checks (network, services, kernel errors)
3. If **healthy**: saves dmesg to `/overlay/dmesg-a-*.log`, does nothing
4. If **unhealthy** and on slot A: saves dmesg, switches to slot B via `fw_setenv system b`, reboots
5. On slot B: reads the dmesg log from `/overlay/` (shared UBI rootfs_data)

**Reading dmesg from slot B:**

```bash
# After slot B boots, SSH in and check:
sshpass -p 'openwrt_r291' ssh $SSHOPT root@192.168.1.1 '
  ls -la /overlay/dmesg-*.log
  cat /overlay/dmesg-a-*.log'
```

### 7e. Critical limitation

If slot A **kernel panics** before init.d scripts run, the watchdog never executes. In that case, only the bootloader's built-in A/B rollback can save you — and that requires valid DTIM hashes in both dtim-a and dtim-b.

---

## 8. Slot Switching (A/B)

> ⚠️ **Unverified on stock:** reference `fw_printenv` output contains **no
> `system` variable**, and the stored `bootargs=root=/dev/mtdblock11` disagrees
> with live cmdline (`root=/dev/mtdblock16 system=b`), so `mrvlboot` patches
> cmdline at boot — bank selection may live in `asr_flag` (mtd19), not env.
> Before relying on these commands: `hexdump -C /dev/mtd19 | head`,
> `fw_printenv system`, and a harmless `fw_setenv`/`fw_printenv` round-trip
> test. If `system` doesn't exist, creating it may be a no-op for the
> bootloader.

### Check current slot

```bash
sshpass -p 'openwrt_r291' ssh $SSHOPT root@192.168.1.1 '
  grep -o "system=[ab]" /proc/cmdline'
```

### Switch to slot B

```bash
sshpass -p 'openwrt_r291' ssh $SSHOPT root@192.168.1.1 '
  fw_setenv system b
  reboot'
```

### Switch back to slot A

```bash
sshpass -p 'openwrt_r291' ssh $SSHOPT root@192.168.1.1 '
  fw_setenv system a
  reboot'
```

### Bootloader A/B rollback

The U-Boot bootloader has built-in rollback:
- `reboot_cnt` counts consecutive failed boots
- If DTIM hash verification fails on the active slot, it tries the other slot
- "FATAL Error, two systems were illegal" = both slots rejected

---

## 9. Rollback & Recovery

| Scenario | Recovery |
|----------|----------|
| Boot hangs, no SSH | **Slot B is untouched.** Power cycle — U-Boot A/B logic should fall back to slot B automatically |
| Slot B also broken | Restore from host backups (Step 4) via NAND clip |
| Need to re-flash slot A | Boot from slot B, SSH in, run Steps 3–5 again targeting slot A |
| Both slots broken, no SSH | NAND clip restore from `factory/clip_ready/` (last resort) |

### What was NOT touched

| Partition | Content | Why safe |
|-----------|---------|----------|
| mtd0 | Bootloader (OBM) | Never flash this |
| mtd11/12 | U-Boot A/B | Never flash this |
| mtd8 | dtim-b (stock) | Untouched fallback |
| mtd14 | kernel-b (stock) | Untouched fallback |
| mtd16 | rootfs-b (stock) | Untouched fallback |
| mtd19 | asr_flag | Do not touch |
| mtd21 | bootargs (U-Boot env) | Do not touch — `system=a` stays |
| mtd23 | rootfs_data (UBI) | Do not touch — overlay builds automatically |

---

## 10. MTD Partition Reference

```
mtd0   bootloader    0x0000000 - 0x040000   (256K)   [DO NOT TOUCH]
mtd1   cp_reliab     0x040000  - 0x060000   (128K)
mtd2   ap_reliab     0x060000  - 0x080000   (128K)
mtd3   cp_reliab_bak 0x080000  - 0x0a0000   (128K)
mtd4   ap_reliab_bak 0x0a0000  - 0x0c0000   (128K)
mtd5   mep-ota       0x0c0000  - 0x0e0000   (128K)
mtd6   mep-ota_bak   0x0e0000  - 0x100000   (128K)
mtd7   dtim-a        0x100000  - 0x140000   (256K)   [FLASH - TIM table slot A]
mtd8   dtim-b        0x140000  - 0x180000   (256K)   [DO NOT TOUCH - stock fallback]
mtd9   cpimage-a     0x180000  - 0x1080000  (14.5M)  [DO NOT TOUCH]
mtd10  cpimage-b     0x1080000 - 0x1f80000  (15M)    [DO NOT TOUCH]
mtd11  u-boot-a      0x1f80000 - 0x2040000  (768K)   [DO NOT TOUCH]
mtd12  u-boot-b      0x2040000 - 0x2100000  (768K)   [DO NOT TOUCH]
mtd13  kernel-a      0x2100000 - 0x2600000  (5M)     [FLASH - zImage+DTB]
mtd14  kernel-b      0x2600000 - 0x2b00000  (5M)     [DO NOT TOUCH - stock fallback]
mtd15  rootfs-a      0x2b00000 - 0x3f00000  (20M)    [FLASH - squashfs]
mtd16  rootfs-b      0x3f00000 - 0x5300000  (20M)    [DO NOT TOUCH - stock fallback]
mtd17  oem_data-a    0x5300000 - 0x5900000  (6M)
mtd18  oem_data-b    0x5900000 - 0x5f00000  (6M)
mtd19  asr_flag      0x5f00000 - 0x5fc0000  (768K)   [DO NOT TOUCH]
mtd20  rsa           0x5fc0000 - 0x6000000  (256K)
mtd21  bootargs      0x6000000 - 0x6040000  (256K)   [DO NOT TOUCH]
mtd22  cust_info     0x6040000 - 0x6080000  (256K)
mtd23  rootfs_data   0x6080000 - 0x8000000  (32M)    [DO NOT TOUCH - UBI overlay]
mtd24  MRVL_BBM      (bad-block table area)                  [DO NOT TOUCH - present on live unit, absent from older notes]
```

### Flash layout visual

```
0x0000000 ┌──────────────────┐
          │ bootloader (256K) │  mtd0
0x0400000 ├──────────────────┤
          │ reliable data     │  mtd1-4 (512K total)
0x0c00000 ├──────────────────┤
          │ mep-ota           │  mtd5-6 (256K total)
0x1000000 ├──────────────────┤
          │ dtim-a (256K)     │  mtd7  ← FLASH (TIM hashes)
0x1400000 ├──────────────────┤
          │ dtim-b (256K)     │  mtd8  [stock]
0x1800000 ├──────────────────┤
          │ cpimage-a (14.5M) │  mtd9
0x1080000 ├──────────────────┤
          │ cpimage-b (15M)   │  mtd10
0x1f80000 ├──────────────────┤
          │ u-boot-a (768K)   │  mtd11
0x2040000 ├──────────────────┤
          │ u-boot-b (768K)   │  mtd12
0x2100000 ├──────────────────┤
          │ kernel-a (5M)     │  mtd13 ← FLASH (zImage+DTB)
0x2600000 ├──────────────────┤
          │ kernel-b (5M)     │  mtd14 [stock]
0x2b00000 ├──────────────────┤
          │ rootfs-a (20M)    │  mtd15 ← FLASH (squashfs)
0x3f00000 ├──────────────────┤
          │ rootfs-b (20M)    │  mtd16 [stock]
0x5300000 ├──────────────────┤
          │ oem_data-a (6M)   │  mtd17
0x5900000 ├──────────────────┤
          │ oem_data-b (6M)   │  mtd18
0x5f00000 ├──────────────────┤
          │ asr_flag (768K)   │  mtd19
0x5fc0000 ├──────────────────┤
          │ rsa (256K)        │  mtd20
0x6000000 ├──────────────────┤
          │ bootargs (256K)   │  mtd21
0x6040000 ├──────────────────┤
          │ cust_info (256K)  │  mtd22
0x6080000 ├──────────────────┤
           │ rootfs_data (32M) │  mtd23 (UBI overlay)
           ├──────────────────┤
           │ MRVL_BBM          │  mtd24 [DO NOT TOUCH]
0x8000000 └──────────────────┘
           Total: 128 MiB SPI-NAND
```

---

## 11. UART Console & initramfs RAM-Boot (no NAND write)

UART is strictly safer than SSH-only flashing: interrupt `bootdelay=1`, inspect
`printenv`, TFTP-boot test images without touching NAND, see early 6.12 boot
logs and DTIM hash errors, use the `f` failsafe key, and recover when both
slots disagree.

### 11a. Voltage — 1.8 V likely, NOT 3.3 V

- A 3.3 V-only USB-TTL showing nothing is the expected symptom, not proof of
  wrong pins/baud. SoC IO on this PXA/MMP-derived platform is likely **1.8 V**
  (88PM801 PMIC exposes 1.8 V rails; the 3.3 V AIB setting in the EMAC patch
  is the Ethernet exception, not the rule).
- **Stop driving 3.3 V into the pins until measured** — 3.3 V TX into a 1.8 V
  RX can damage the pin. Procedure: board powered, adapter disconnected,
  multimeter TX-to-GND on idle: ~1.8 V → 1.8 V logic, ~3.3 V → 3.3 V logic.
- Use an adapter with 1.8 V support (or VIO pin / external TXB0108-type
  shifter), GND common, RX/TX crossed, **VCC unconnected**. Then try 115200n8
  on ttyS0 (`pxa2xx-uart @ d4017000`); 57600/ttyS1 is an unconfirmed old note.
- Pinout is not yet documented — candidate is the unpopulated 3–4 pin header
  near the SoC/edge (see `hardware/pictures/PXL_20260727_*`). Confirm with
  continuity (GND) + idle-high (TX) before soldering.

### 11b. initramfs RAM-boot (zero flash risk)

```
# On host: serve bin/targets/asr1802s/generic/
#   openwrt-asr1802s-generic-asr1826s_p298-initramfs-kernel.bin via TFTP.
# At mrvlboot prompt (hit key during bootdelay=1):
tftpboot 0x8000 openwrt-asr1802s-generic-asr1826s_p298-initramfs-kernel.bin
bootz 0x8000
```

- No `mtd write`, no DTIM rebuild (DTIM gates NAND slots, not a RAM image),
  nothing persists — reboot returns to stock. This is the correct first boot
  test for the 6.12 kernel; only flash §5 after RAM-boot shows UART, DTB,
  QSPI/NAND probe, and network alive.
- There is intentionally **no `initramfs-rootfs`**: initramfs = kernel +
  rootfs in one RAM image. Do not create one.
- Without UART this path is unavailable (no `kexec` proven on vendor 3.10
  kernel) — hence §5 NAND flashing is the SSH-only fallback, with §7c/7d
  installed only after a successful boot.
