# PCIe PHY Driver Development Plan — ASR1802S (pcie-asr-kagu)

## Objective
Write a DesignWare PCIe host controller driver for `asr,pcie-kagu` to enable WiFi (RTL8812FE + RTL8192FR) on Notion R291 ASR1802S.

## Hardware Summary (from OEM probes)
| Resource | PCIe Port 1 | PCIe Port 2 |
|---|---|---|
| PHY base (0x800) | 0xd4220000 | 0xd4210000 |
| DBI/Config base (0x1000) | 0xd428c000 | 0xd4288000 |
| MEM window | 0xd8050000-0xd8ffffff | 0xe0100000-0xe201ffff |
| IO window | 0x10000-0x10fff | 0x20000-0x20fff |
| ICU IRQ (INTx) | 51 (kagu-pcie1) | 50 (kagu-pcie2) |
| MSI IRQ | 250 (wlan0) | 26 (wlan1) |
| WiFi chip | RTL8812FE (10ec:f812) via bridge 1e5d:3002 | RTL8192FR (10ec:818c) via bridge 1e5d:3001 |
| Reset GPIOs | GPIO 72 (pcie-rst-gpio) | GPIO 80 (pcie-rst-gpio2) |

## Clocks (from patch 0005)
- `ASR1802S_CLK_AXI` (11) — AXI bus clock
- `ASR1802S_CLK_PERIPH` (9) — Peripheral bus clock (pclk)

## Current Patches Status
| Patch | Component | Status |
|---|---|---|
| 0003 | DTS node with `compatible = "asr,pcie-kagu"` | ✅ Exists |
| 0005 | Clock driver (AXI, PERIPH) | ✅ Exists |
| 0012 | rtl8xxxu PCIe endpoint support | ✅ Exists |
| **NEW** | **PCIe host controller driver** | ❌ **Missing** |
| **NEW** | **DT binding YAML** | ❌ **Missing** |
| **NEW** | **Kconfig/Makefile** | ❌ **Missing** |
| **NEW** | **config-6.12 PCI enable** | ❌ **Missing** |

## Milestones

### M1: DT Binding & Build Infrastructure (Day 1)
- [ ] `Documentation/devicetree/bindings/pci/asr,pcie-kagu.yaml`
- [ ] `drivers/pci/controller/dwc/Kconfig` addition
- [ ] `drivers/pci/controller/dwc/Makefile` addition
- [ ] Validate: `make kernel_oldconfig` picks up new symbol

### M2: Core Driver Skeleton (Day 1-2)
- [ ] `drivers/pci/controller/dwc/pcie-asr-kagu.c` — probe, remove, dw_pcie_ops
- [ ] Standard DWC wrapper pattern (like pcie-qcom.c, pcie-kirin.c)
- [ ] Clock handling (AXI + PERIPH)
- [ ] Reset GPIO handling (per-port)
- [ ] PHY register map (0x800 per port) — standard DWC PHY offsets
- [ ] DBI base mapping (0x1000 per port) — standard DWC config space
- [ ] LTSSM polling for L0 (PCIE_PORT_DEBUG0 at 0x728)

### M3: IRQ & MSI Support (Day 2)
- [ ] Legacy INTx: chained IRQ handler for ICU IRQ 50/51
- [ ] MSI: `dw_pcie_msi_init()` + ICU MSI routing
- [ ] interrupt-map in DTS for INTx routing to ICU

### M4: PHY Init Sequence (Day 2-3)
- [ ] Power up sequence: clocks → reset GPIOs → PHY registers
- [ ] PHY registers (reverse-engineered from standard DWC + OEM strings):
  - PLL enable & wait for lock
  - LTSSM enable
  - Link width (x1) and speed (Gen1) config
  - Wait for LTSSM == L0 (0x11)
- [ ] Add register dump debugfs for first-boot iteration

### M5: DTS & Config Updates (Day 3)
- [ ] Patch 0003: Add `clocks`, `clock-names`, `interrupt-map` to PCIe node
- [ ] Patch 0003: Add child nodes `pcie@1,0` and `pcie@2,0` with interrupt-map
- [ ] config-6.12: Add `CONFIG_PCI=y`, `CONFIG_PCI_MSI=y`, `CONFIG_PCIE_DW_HOST=y`, `CONFIG_PCIE_ASR_KAGU=y`, `CONFIG_PCI_REALTEK=y`

### M6: Validation & Build (Day 3-4)
- [ ] Patch validation: hunk count + dry-run against clean kernel
- [ ] Build: `make -j$(nproc) target/linux/compile`
- [ ] Test: flash, `lspci`, verify WiFi probe

## PHY Register Map (Assumed — Standard DWC PHY + Iteration)

Based on Synopsys DesignWare PCIe PHY common layout and OEM dmesg strings:

```
PHY_BASE (0xd4210000 / 0xd4220000), size 0x800

Offset   Name                    Description
0x000    PHY_CTRL                PHY control: reset, power-down, enable
0x004    PHY_STATUS              PHY status: PLL lock, PHY ready
0x010    PLL_CTRL                PLL configuration (feedback div, refclk)
0x014    PLL_STATUS              PLL lock status
0x020    LTSSM_CTRL              LTSSM state machine control
0x024    LTSSM_STATUS            LTSSM current state (read)
0x030    LANE_CTRL               Lane configuration (x1 = 0x1)
0x040    PIPE_CTRL               PIPE interface control
0x100-0x1FC  SerDes lanes        Per-lane registers (1 lane = x1)
```

OEM dmesg confirms:
- "PCIe PLL isn't ready in time" → PLL_CTRL/STATUS at offset ~0x10-0x14
- "PCIe Ltssm enter L0 done" → LTSSM_STATUS at offset ~0x24
- "PCIe Ltssm does not enter L0, ltssm:0x%x" → LTSSM state readable

Standard DWC DBI (config space) at 0xd4288000/0xd428c000 (0x1000 each):
- PCIE_PORT_DEBUG0 (0x728) → LTSSM state bits [5:0]
- PCIE_PORT_LINK_CONTROL (0x710) → Link control
- PCIE_LINK_WIDTH_SPEED_CONTROL (0x80C) → Width/speed

## Files to Create/Modify

### New Files
1. `Documentation/devicetree/bindings/pci/asr,pcie-kagu.yaml`
2. `drivers/pci/controller/dwc/pcie-asr-kagu.c`

### Modified Files (in openwrt-fork)
1. `target/linux/asr1802s/patches-6.12/0003-ARM-dts-asr-Add-ASR1802S-SoC-and-ASR1826s-R291-board.patch` — DTS updates
2. `target/linux/asr1802s/patches-6.12/000X-pci-asr-add-kagu-pcie-host-driver.patch` — NEW patch for driver + Kconfig + Makefile + DT binding
3. `target/linux/asr1802s/config-6.12` — PCI config symbols

### Kernel Tree Files (upstream locations)
- `drivers/pci/controller/dwc/Kconfig`
- `drivers/pci/controller/dwc/Makefile`
- `Documentation/devicetree/bindings/pci/asr,pcie-kagu.yaml`

## Risk Mitigation

| Risk | Mitigation |
|---|---|
| PHY register map wrong | Add debugfs register dump; iterate on hardware |
| PLL never locks | Try multiple PLL configs; log register values |
| LTSSM stuck | Verify reset GPIO polarity; check clock enable order |
| MSI not working | Fall back to INTx only first; MSI later |
| Build breaks | Each commit independently buildable; test `make kernel_oldconfig` |

## Testing Checklist

- [ ] `make kernel_oldconfig CONFIG.targets=asr1802s` succeeds
- [ ] `make -j$(nproc) target/linux/{clean,compile}` succeeds
- [ ] Boot: `dmesg | grep -i pcie` shows "ASR Kagu PCIe Host Bridge"
- [ ] `lspci` shows two root ports + two WiFi endpoints
- [ ] `dmesg | grep -i rtl8xxxu` shows WiFi probe
- [ ] `iw dev` shows wlan0, wlan1

---

## Progress Log

| Date | Milestone | Status | Notes |
|---|---|---|---|
| 2026-09-02 | M1-M2 | In Progress | Starting implementation |