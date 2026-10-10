# WiFi Research: RTL8192FR (2.4GHz) & RTL8812FR (5GHz)

## Hardware Overview (VERIFIED from live router)

| Chip | Band | Interface | PCI ID | Standard | MMIO Base |
|------|------|-----------|--------|----------|-----------|
| RTL8192FR | 2.4GHz | PCIe | `10ec:818c` | 802.11n (WiFi 4) | `0xe0100000` |
| RTL8812FR | 5GHz | PCIe | `10ec:f812` | 802.11ac (WiFi 5) | `0xd8200000` |

Both are Realtek PCIe WiFi chips. The stock firmware uses proprietary `rtl8192cd.ko` (compiled against kernel 3.10.33 ABI), which **cannot load on kernel 6.12**.

---

## Live Router PCI Topology (from dmesg)

```
Bus 0000:00 (root — ASR1802S)
├── 00:01.0 [1e5d:7846] PCIe Root Port 1 (kagu-pcie1, base d4220000)
│   └── 01:00.0 [1e5d:3002] PCIe Switch Port
│       └── 02:00.0 [10ec:f812] RTL8812FR (5GHz WiFi)
│           BAR0: io 0x10000-0x100ff (I/O port)
│           BAR2: mem 0xd8200000-0xd820ffff (64bit MMIO registers)
│           MSI IRQ 250 (wlan0)
│
└── 00:02.0 [1e5d:7846] PCIe Root Port 2 (kagu-pcie2, base d4288000)
    └── 03:00.0 [1e5d:3001] PCIe Switch Port
        └── 04:00.0 [10ec:818c] RTL8192FR (2.4GHz WiFi)
            BAR0: io 0x20000-0x200ff (I/O port)
            BAR2: mem 0xe0100000-0xe010ffff (64bit MMIO registers)
            MSI IRQ 26 (wlan1)
```

**Key corrections from live probe (our initial guesses were wrong):**
- RTL8812FR PCI ID is `10ec:f812` (we didn't have this before)
- MMIO is on **BAR2** (64bit memory), not BAR0 — BAR0 is I/O port space
- MMIO size is 64KB (0x10000), not 16KB as initially assumed
- Two separate PCIe root ports, each with a switch chip (1e5d:3001/3002)
- Both chips use MSI interrupts (IRQ 250 and 26)

### OEM Driver Identification (from dmesg)

The OEM `rtl8192cd` driver identifies chips by reading register 0x08:
```
IS_RTL8812F_SERIES value8 = 14  → RTL8812FE (5GHz)
IS_RTL8192F_SERIES value8 = d   → RTL8192F  (2.4GHz)
```

4 × `rtl8192cd_init_one` calls (2 per chip — possibly dual-interface or MAC/PHY split).
Hardware init via `rtl8192cd_init_hw_PCI` takes ~800ms per chip.

### IRQs (from /proc/interrupts)

| IRQ | Name | Chip | Count |
|-----|------|------|-------|
| 26 | PCI-MSI | wlan1 (RTL8192FR) | 156362 |
| 50 | icu_irq | kagu-pcie2 (root port) | 157180 |
| 51 | icu_irq | kagu-pcie1 (root port) | 156362 |
| 250 | PCI-MSI | wlan0 (RTL8812FR) | 157180 |

---

## Mainline Driver Search Results

### rtw88 (drivers/net/wireless/realtek/rtw88/)

| Chip Family | PCIe | USB | SDIO | Status |
|-------------|------|-----|------|--------|
| RTL8822B | Yes | — | — | Supported |
| RTL8822C | Yes | — | — | Supported |
| RTL8821C | Yes | Yes | Yes | Supported |
| RTL8703B | — | — | — | Supported |
| RTL8723D | — | Yes | — | Supported |
| **RTL8192F** | **No** | **No** | **No** | **Not present** |
| **RTL8812F** | **No** | **No** | **No** | **Not present** |

**Neither RTL8192FR nor RTL8812FR are in rtw88.**

### rtl8xxxu (drivers/net/wireless/realtek/rtl8xxxu/)

| Chip | USB | PCIe | Status |
|------|-----|------|--------|
| RTL8192F | Yes (rtl8192fu) | **No** | USB-only in mainline |
| RTL8812AU | Yes | No | Supported |
| RTL8188EU | Yes | No | Supported |
| RTL8723BU | Yes | No | Supported |

Kconfig line: `depends on MAC80211 && USB` — PCIe not supported.

### rtw89 (drivers/net/wireless/realtek/rtw89/)

RTL8852A/B/C, RTL8832A, RTL8922A — **RTL8812FR not listed.**

### Stock vendor driver

`rtl8192cd.ko` — proprietary, ~30k lines, targets kernel 3.10. USB vs PCIe question is moot for this driver; it already supports PCIe (R291 uses it over PCIe). However, it **cannot be loaded on 6.12** due to ABI incompatibility.

---

## USB vs PCIe Driver Architecture Analysis

### rtw88 bus abstraction

rtw88 uses a clean two-layer abstraction:

1. **`struct rtw_hci_ops`** (hci.h:9-34) — bus transport layer (16 function pointers):
   - `tx_write`, `tx_kick_off`, `flush_queues`, `setup`, `start`, `stop`
   - `deep_ps`, `link_ps`, `interface_cfg`, `dynamic_rx_agg`
   - `read8/16/32`, `write8/16/32`
   - `write_firmware_page`, `write_data_rsvd_page`, `write_data_h2c`

2. **`struct rtw_chip_ops`** (main.h:843-902) — chip MAC/PHY/RF layer (~25 function pointers):
   - `mac_init`, `phy_set_param`, `set_channel`, `read_rf`, `write_rf`
   - `set_tx_power_index`, `phy_calibration`, `pwr_track`
   - All bus-agnostic

### Bus-specific vs shared code ratio

| Layer | Code | % of total |
|-------|------|-----------|
| Shared core (main.c, fw.c, mac80211.c, phy.c, mac.c, tx.c, rx.c, coex.c) | ~10k lines | ~65% |
| Chip-specific (e.g., rtw8821c.c) | ~2k lines | ~15% |
| Bus-specific (pci.c, usb.c, sdio.c) | ~1.5k lines | ~12% |

**Within rtw88**, adding PCIe for an already-supported USB chip = trivial (35-line glue file like `rtw8821ce.c`).

### Why this DOESN'T help RTL8192F

RTL8192F is **not in rtw88 at all**. It's in `rtl8xxxu`, which has a completely different architecture:
- `rtl8xxxu` uses `struct rtl8xxxu_fileops` with USB-specific methods (`.usb_quirks`, `.writeN_block_size`, URB transfers)
- Kconfig hardcodes `depends on MAC80211 && USB`
- The PCIe variant (RTL8192FR) uses different silicon than the USB variant (RTL8192FU)
- Adapting `rtl8xxxu` to PCIe = major rewrite (PCIe DMA rings, MMIO, NAPI vs URBs)

### Chip silicon difference

| Feature | RTL8192F (USB) | RTL8192FR (PCIe) |
|---------|---------------|-------------------|
| Standard | 802.11n | 802.11n |
| Bus | USB | PCIe |
| Register layout | USB control messages | MMIO at BAR2 (64bit) |
| TX/RX | URB bulk transfers | DMA ring buffers |
| Interrupt | USB interrupt IN endpoint | MSI IRQ |
| Power save | USB selective suspend | PCIe L1/ASPM |
| **Same silicon?** | **Possibly same MAC/PHY core, but different bus interface and potentially different register maps** |

---

## Feasible Paths to WiFi on R291

### Path 1: Port OEM rtl8192cd.ko to kernel 6.12 (Best chance of working)

**Effort:** Major (weeks to months)

The OEM `rtl8192cd.ko` source code exists (GPL, Realtek Jungle SDK). Porting steps:

1. **Obtain source**: Realtek Jungle SDK rtl8192cd driver (GPL, CVE-2026-36355 filed against it)
2. **Analyze API surface**: Map all kernel API calls (3.10 → 6.12 changes):
   - `struct net_device` changes
   - `pci_*` API changes
   - `ieee80211` / `netif_rx` / `napi_*` changes
   - `timer_list` API changes
   - `work_struct` / `tasklet` API changes
   - `request_irq` → `request_threaded_irq` changes
3. **Fix compilation errors**: Typically 100-300 call sites need updating
4. **Build as out-of-tree module**: Create `package/kernel/rtl8192cd/` with Makefile
5. **Test**: Load on hardware, verify PCIe enumeration, scan, associate, transmit

**Pros**: Known-working driver for this exact hardware, already supports PCIe
**Cons**: Large vendor codebase, significant porting effort, not upstreamable

### Path 2: Write new RTL8192FR driver for rtw88

**Effort:** Very major (months, requires datasheet)

1. Obtain Realtek RTL8192FR datasheet or reverse-engineer from `rtl8192cd` source
2. Write `rtw8192f.c` implementing `rtw_chip_ops` (~25 functions)
3. Write `rtw8192fr.c` glue file (PCIe ID table, ~35 lines)
4. Submit to linux-wireless mailing list

**Pros**: Clean mainline driver, upstreamable
**Cons**: Requires datasheet, very large effort

### Path 3: Adapt rtl8xxxu to support PCIe (IN PROGRESS)

**Effort:** Major (significant restructuring)
**Status:** Tasks 1-4 complete — 2026-08-31

Implemented as patch `0012-net-wireless-rtl8xxxu-add-PCIe-bus-support-for-RTL81.patch`:

1. **Bus ops abstraction** (`rtl8xxxu.h`): Added `struct rtl8xxxu_bus_ops` with read8/16/32, write8/16/32, writeN function pointers. Core reg access functions (`rtl8xxxu_read8` etc.) check `priv->bus_ops` first — if set, dispatches through MMIO; if NULL, falls back to USB control messages (unchanged).
2. **PCIe transport** (`rtl8xxxu_pcie.c`): PCI probe/remove, BAR2 MMIO mapping, DMA TX/RX descriptor rings (256 entries each), NAPI polling, MSI interrupt handling. PCI IDs `10ec:818c` and `10ec:f812`.
3. **PCIe header** (`rtl8xxxu_pcie.h`): Ring descriptor structs (8-byte TX/RX), per-queue TX ring, RX ring, `struct rtl8xxxu_pcie_priv`.
4. **Kconfig/Makefile**: `depends on MAC80211 && (USB || PCI)`, conditional `rtl8xxxu_pcie.o` on `CONFIG_PCI`.
5. **mac80211 integration** (2026-08-31):
   - `struct ieee80211_ops rtl8xxxu_pcie_ops` — reuses all shared callbacks from core.c (add_interface, config, bss_info_changed, configure_filter, set_key, etc.), with PCIe-specific `tx`, `start`, `stop`
   - `struct device *dev` added to `rtl8xxxu_priv` for bus-agnostic logging (replaces `priv->udev->dev` everywhere)
   - All shared core.c functions (`rtl8xxxu_add_interface`, `rtl8xxxu_config`, `rtl8xxxu_watchdog_callback`, etc.) made non-static with declarations in `rtl8xxxu.h`
   - `ieee80211_register_hw()` called in PCIe probe with proper band setup (2.4GHz HT40), interface modes, hw flags
   - PCIe `start` callback: calls `fops->enable_rf()`, sets RX filter masks, starts RA watchdog, enables NAPI
   - PCIe `stop` callback: disables NAPI, calls `fops->disable_rf()`
   - PCIe `tx` callback: maps skb for DMA, fills TX descriptor, rings doorbell

**What works now:** Register read/write via MMIO (PCIe bus), chip identification, EFUSE read, firmware load, DMA ring init, mac80211 registration (`phy0` appears in `iw phy`).

**What does NOT work:** No WiFi connectivity. Laptops/phones cannot connect. The TX/RX descriptor format in the DMA rings is a generic 8-byte placeholder — the RTL8192F hardware expects a chip-specific descriptor layout (32+ bytes with rate info, AMPDU fields, etc.). Without the correct format, the card cannot send or receive WiFi frames. Scanning (`iw scan`) may partially work for beacon frames, but association, DHCP, and all data traffic will fail.

### What is NOT working yet (detailed)

#### 5. TX path — wrong descriptor format (BLOCKS ALL WiFi connectivity)
- PCIe `tx` callback fills 8-byte descriptors, but RTL8192F hardware expects its native TX descriptor format (32+ bytes, `struct rtl8xxxu_txdesc32` from `rtl8xxxu.h`)
- Need to use `priv->fops->tx_desc_size` and fill the RTL8192F TX descriptor fields (txdw0-4 with rate, queue, security, first/last segment bits)
- Without this: **no frames leave the card** — no association, no DHCP, no data

#### 6. RX path — wrong descriptor format (BLOCKS ALL WiFi connectivity)
- NAPI poll reads 8-byte descriptors, but RTL8192F hardware writes its native RX descriptor format
- `parse_rx_desc` in8192f.c expects the RTL8192F-specific RX descriptor layout (rxdesc32)
- Without this: **no frames received** — can't see beacons, can't receive data

#### 7. No hardware testing
- PCI BAR addresses verified on live OEM firmware
- MMIO register map verified (chip ID, version registers)
- DMA ring addresses/offsets are educated guesses based on similar Realtek chips
- **No OpenWrt build + flash + test yet**

#### 8. No OpenWrt kmod package
- Need `package/kernel/kmod-rtl8xxxu-pcie/Makefile` to build and install the module
- Kconfig symbol `CONFIG_RTL8XXXU` needs to be set in `config-6.12`

### Remaining work (priority order)

| # | Task | Effort | Blocks | Status |
|---|------|--------|--------|--------|
| 1 | Fix BAR number (0→2) | 5 min | Probe | ✅ Done |
| 2 | Add `10ec:f812` to PCI ID table | 5 min | RTL8812FR | ✅ Done |
| 3 | Fix `eth_type_trans` | 10 min | RX | ✅ Done |
| 4 | Write `struct ieee80211_ops` for PCIe | 2-3 hours | Everything | ✅ Done |
| 5 | Wire band/channel/capabilities setup | 2-3 hours | Scan/assoc | ✅ Done |
| 6 | Wire power_on, RF init, PHY init | 2-3 hours | Hardware | ⏳ Next |
| 7 | Fix TX descriptor format for RTL8192F | 4-8 hours | TX data | ⏳ Next |
| 8 | Fix RX descriptor format for RTL8192F | 4-8 hours | RX data | ⏳ Next |
| 9 | Build + flash + test on hardware | 1-2 days | All | ⏳ After 6-8 |
| 10 | Create kmod-rtl8xxxu-pcie package | 1 hour | Deployment | ⏳ After 9 |

**Blocks 6-8** are independent — they can be done in any order or in parallel.
**Block 9** (build + flash + test) requires 6, 7, and 8 to be done first.

**Estimated total to get basic WiFi scanning:** 1 day
**Estimated total to get WiFi connection + traffic:** 1-2 weeks

### Fallback: Path 1 (Port rtl8192cd.ko)

If rtl8xxxu PCIe proves too difficult to complete (e.g., RTL8192FR register map differs significantly from USB variant), the OEM driver port remains available as a fallback.

### Short-term (current OpenWrt port)
**Path 4 (wired-only) + Path 5 (USB adapter if WiFi needed)**

The current OpenWrt port is focused on getting basic networking working. WiFi is a secondary concern. Ship wired-only first, document WiFi limitations.

---

## What can be probed from live router (with original firmware + SSH)

**YES** — we already have significant data from `probe_read_from_live_router/`. Additional probes possible with SSH access:

| Data | Available? | Source | Useful for |
|------|------------|--------|------------|
| PCI topology + BAR addresses | ✅ YES | dmesg.txt, proc_iomem.txt | BAR number, MMIO base |
| PCI device IDs | ✅ YES | dmesg.txt | ID table |
| IRQ numbers | ✅ YES | proc_interrupts.txt | MSI handler |
| OEM driver init sequence | ✅ YES | modem_wifi_dmesg.txt | Chip identification |
| PCIe PHY config | ✅ YES | proc_iomem.txt (pcie1-phy, pcie2-phy) | PCIe setup |
| DT nodes | ✅ YES | live_ssh_session/registers_and_dt.txt | Device tree |
| MMIO register dumps | ❌ Partial | /dev/mem reads failed (permission) | Register map verification |
| Full dmesg with WiFi | ✅ YES | dmesg.txt (912 lines) | Full boot sequence |

### What we still CAN'T get from live probe
- **MMIO register map** — `/dev/mem` access denied, need kernel driver or JTAG
- **EFUSE contents** — requires driver loaded
- **RF calibration data** — requires driver loaded
- **TX/RX descriptor format** — requires reading OEM driver source or datasheet

### Recommended additional probes (if SSH available)
```bash
# Full PCI config space dump (all registers)
lspci -vvv -s 02:00.0  # RTL8812FR
lspci -vvv -s 04:00.0  # RTL8192FR

# IO memory maps
cat /proc/iomem | grep -i "realtek\|wlan\|pcie"

# PCIe link status
cat /sys/bus/pci/devices/*/link_speed
cat /sys/bus/pci/devices/*/link_width

# Module parameters (if rtl8192cd loaded)
cat /sys/module/rtl8192cd/parameters/*

# WiFi interfaces
iw dev
iw phy
```

---

## References

- Stock driver: `Notion_R291_ASR1802S_P298_N13/oem_backup/extracted_rootfs/lib/modules/3.10.33/rtl8192cd.ko`
- Realtek Jungle SDK: GPL source (CVE-2026-36355)
- rtw88: `drivers/net/wireless/realtek/rtw88/`
- rtl8xxxu: `drivers/net/wireless/realtek/rtl8xxxu/`
- rtw89: `drivers/net/wireless/realtek/rtw89/`
- OpenWrt wireless packages: `package/kernel/mac80211/`
- Live router probe: `probe_read_from_live_router/`
- OEM dmesg: `probe_read_from_live_router/modem_wifi_dmesg.txt`
