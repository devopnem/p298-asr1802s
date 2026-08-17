# M1 — QSPI SPI-NAND driver (`asr,qspi`) bring-up plan

> Workspace: /home/void/Downloads/Modems/Notion_R291_ASR1802S_P298_N13
> Parent milestone: BRINGUP_MILESTONES.md §M1 (MOST CRITICAL — blocks rootfs)
> Owner: this AI (M1 worker). M0 (clock) owned by same AI, lands first.
> Router for live RE: 192.168.1.1 (online during session 2026-08-17; saved captures in
> `live_trace/ROUTER_20260817_115949/`. Live ftrace NOT available. Exact SSH opts in STATE.md.)

## Objective
Kernel must see F35UQA001G SPI-NAND → MTD → `/dev/mtdblock15` → rootfs mount.
No driver → no mtdblock → kernel panic at root.

Deliverable:
- `drivers/spi/spi-asr1802s-qspi.c` — a standard `spi_controller` + `spi_mem_ops`
  driver (NOT a monolithic NAND driver). The generic `spi-nand` core
  (`CONFIG_MTD_SPI_NAND=y`, already in `config-6.12`) drives F35UQA001G.
- `Documentation/devicetree/bindings/spi/asr,asr1802s-qspi.yaml` DT binding.
- OpenWrt patch series in `target/linux/asr1802s/patches-6.12/`:
  - `0006-dt-bindings-spi-asr-qspi.yaml`
  - `0007-drivers-spi-spi-asr1802s-qspi.c` (+ `drivers/spi/Kconfig`, `Makefile`)
  - bump `config-6.12`: `CONFIG_SPI_ASR1802S_QSPI=y`
- checkpatch.pl --strict clean; dt_binding_check + dtbs_check clean.

## Confirmed facts (from vendor DTB / dmesg / clk_summary)
- QSPI node: `qspi@0xd420b000`, `compatible = "asr,qspi"`.
  - `reg = <0xd420b000 0x500>, <0x80000000 0x8000000>` (reg-names `reg-map`,`memory-map`).
  - IRQ 45 (ICU → Linux IRQ 77 = `d420b000.qspi` in /proc/interrupts).
  - `dma-tx-drcmr = <0x63>`, `dma-rx-drcmr = <0x61>`.
  - vendor props: `qspi-cs=0`, `qspi-txmode=0x04`, `qspi-rxmode=0x04`,
    `qspi-max_freq_mhz=0x34` (52 MHz), `marvell,ddrfreq-qos`.
- dmesg: `SPI-NAND: F35UQA001G is found.` mfr_id `cd`, dev_id `61 61`.
  `Set rx_pins: 4, tx_pins: 4, Read_CMD:0x6b` (quad read). `block_size=0x20000`,
  `page_size=0x800`, `bitflip_threshold=4`. `qspi: set qspi bus clock to 52MHz`.
  `use_intr=1 en_tx_dma=1 use_xip=1`.
- clk_summary: `qspi_fclk` 208 MHz → `qspi` 52 MHz.
- DTS already wired: `asr1802s.dtsi` has the node; `asr1826s-r291.dts` `&qspi`
  has 25 partitions + `spi-nand` child. `config-6.12` has SPI_MASTER/SPI_MEM/MTD_SPI_NAND=y.

## Open unknowns (the RE work)
1. Register map of `0xd420b000` — **RESOLVED (2026-08-17)** via objdump Thumb-2 of
   `Image.from_gzip` (see `RE_NOTES.md` §7). STRONG match to Freescale VF610
   QuadSPI (`spi-fsl-qspi.c`); only a few regs shifted (STATUS 0x15c, FR 0x160,
   trigger 0x164). Remaining TODO: pin the data FIFO reg (§7.4).
2. F35UQA001G support in mainline `drivers/mtd/nand/spi/` (mfr 0xcd) — may need a
   tiny device-table entry (M1.6).

## Decisions (from user)
- **Live kprobe/ftrace RE: deferred** until the router is physically reconnected.
  Harness scripts are prepared now and committed; executed later (non-destructive).
- **QSPI clock gate: deferred** until M0 (clock) lands. Driver uses
  `devm_clk_get_optional`; add `ASR1802S_CLK_QSPI` to M0's clk driver+header only
  after M0 is merged.

## Phased plan

### Phase 0 — Register-map RE
- **0a (NOW, no router):** dump-based RE.
  - Extract vmlinux from `oem_backup/kernel-a.bin` (zImage piggy) via
    `porting_workspace/qspi/extract_vmlinux.py`.
  - Pull `qspi_*` symbols from embedded kallsyms; confirm via `arm-linux-gnueabihf-objdump`.
  - Recover register offsets + read/erase/program sequencing from decompiled code.
  - Fetch a public Marvell 3.10 / MMP3 / PXA1928 tree for its `mv_qspi` reference
    (Technique A) to cross-check offsets. (Network download — dependency.)
  - Output: `porting_workspace/qspi/RE_NOTES.md` (mirror `clock_re/RE_NOTES.md`).
- **0b (router connected LATER):** run prepared `ftrace`/`kprobe` harness on
  `qspi_*` during a real read/erase to log exact register writes; fold into RE_NOTES.
  - Harness: `porting_workspace/qspi/live_trace/` (ftrace set_ftrace_filter +
    kprobe on qspi register accesses + a trigger that reads a NAND partition).

### Phase 1 — Driver `drivers/spi/spi-asr1802s-qspi.c`
- `probe`: ioremap `reg-map`+`memory-map`; `devm_clk_get_optional` (QSPI gate TBD
  post-M0); request IRQ 45; PIO first, PDMA (`CONFIG_MMP_PDMA=y`) later.
- `spi_controller->mem_ops.exec_op`: opcode+addr+dummy+data in/out, 1/2/4-line
  (quad `0x6b`), honor `spi-max-frequency` 52 MHz.
- Optional `spi_controller->mem_ops.dirmap` over the `memory-map` window for fast reads.

### Phase 2 — DT binding + clock
- YAML binding `asr,asr1802s-qspi.yaml`.
- QSPI clock gate: add `ASR1802S_CLK_QSPI` to M0 clk driver+header AFTER M0 lands.

### Phase 3 — Package + verify (after M0 green)
- Patches 0006/0007 + `config-6.12` bump as above.
- Verify: `make -j$(nproc)`; `nm vmlinux | grep asr1802s_qspi_probe`;
  `checkpatch.pl --strict` clean; `dt_binding_check`/`dtbs_check` clean.
- Hand off to M4 (blind slot-a boot; rootfs mount = success).

## Sub-milestones (checklist)
- [x] M1.0  vmlinux extracted from kernel-a.bin (`extract_vmlinux.py` → `Image.from_gzip`)
- [x] M1.1  Driver lineage identified: Marvell PXA3xx-derived QSPI SPI-NAND +
           `pxa3xx_bbm`; web cross-check done (no public exact register map)
- [x] M1.2  `RE_NOTES.md` architecture captured (IP-cmd + LUT + AHB/XIP + FR/SR,
            PXA-DMA DRCMR/DCSR/DSADR/DTADR/DCMD/DDADR, IRQ, clocks, DT props,
            F35UQA001G params). See §7/§8.
- [x] M1.3  **Register map EXTRACTED** (2026-08-17) via objdump Thumb-2 per-function
            disassembly of `Image.from_gzip` (`qspi_funcs.disasm`, `qspi_exec.disasm`);
            no Ghidra needed. Map in RE_NOTES §7 + VF610-similarity note §7.3.
- [x] M1.3b data FIFO / TX-RX buffer reg PINNED = `0x1e0` (RE_NOTES §7.4). Full
            register set now verified.
- [x] M1.3c live-trace harness committed (`live_trace/trace_qspi.sh`, sshpass present)
- [x] M1.4  `spi-asr1802s-qspi.c` written (probe + spi_mem exec_op PIO + AHB dirmap,
            modelled on `spi-fsl-qspi.c`; compiled clean vs 6.12). As OpenWrt patch
            `target/linux/asr1802s/patches-6.12/0009-drivers-spi-spi-asr1802s-qspi.c.patch`.
            NOTE: IP command trigger (0x164) + descriptor words (0x150/0x154/0x158)
            are reconstructed from disasm — need HW bring-up tuning.
- [x] M1.5  DT binding `asr,asr1802s-qspi.yaml` written. As OpenWrt patch
            `0008-dt-bindings-spi-asr1802s-qspi.yaml.patch`.
- [ ] M1.6  F35UQA001G spi-nand entry: likely handled by generic spi-nand core via ONFI
            autodetect (vendor has `spi_nand_detect_onfi`); verify on first boot, add
            `drivers/mtd/nand/spi/core.c` mfr 0xcd entry only if needed.
- [ ] M1.7  QSPI clock gate added to M0 clk driver (post-M0) — driver uses
            `devm_clk_get_optional` so it builds/boots without it.
- [x] M1.8  OpenWrt patches **COMMITTED to the openwrt fork** (branch `asr1802s-kagu-wip`,
            commit `b3a50fae`): `0008-dt-bindings-spi-asr1802s-qspi.yaml.patch` +
            `0009-drivers-spi-spi-asr1802s-qspi.c.patch`. config-6.12 has
            `CONFIG_SPI_ASR1802S_QSPI=y` appended but is still uncommitted (mixed with the
            clock/EMAC target edits) — commit it with the target config so the driver builds.
            checkpatch + dtc: TODO (run before pushing PR #24614).
- [ ] M1.9  hand off to M4 boot test (rootfs mount = success)

## Dependency graph (relevant)
```
M0 (clock+build) ──┐ (provides QSPI gate + build base)
M1 (qspi) ─────────┼──> M4 (boot test, rootfs mount = success)
DTIM hash RE (parallel, AI #3) ──> M4
```
