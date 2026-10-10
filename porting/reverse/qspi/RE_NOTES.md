# M1 — QSPI SPI-NAND RE NOTES (ASR1802S `asr,qspi`)

Recovered from the vendor `kernel-a.bin` (zImage, 3.10.33) by extracting the
embedded kernel `Image` (`porting/reverse/qspi/extract_vmlinux.py` →
`Image.from_gzip`) and mining its string table + disassembly. This is the
authoritative source until Ghidra decompile or live kallsyms/ftrace (router
reconnect) give exact register offsets.

## 1. Driver identity (CONFIRMED)
- Platform driver name `asr-qspi`; `compatible = "asr,qspi"` (matches our DTS).
- Procfs node `asr-qspi` ("asr-qspi: Failed to register with procfs." — procfs
  is optional, ignore in mainline driver).
- It is a **Marvell PXA3xx-derived QSPI SPI-NAND controller** driver. It pulls in
  the Marvell `pxa3xx_bbm` bad-block-management layer (strings:
  `pxa3xx_bbm`, `pxa3xx_bbm_mark_biterr`, `spi_nand_read_oob_bbm`,
  `spi_nand_write_oob_bbm`, `[abbt] relocation table at page:%d`,
  `[bbt] relocation table at page:%d`, `Max capacity of BBM is %d blocks!!`,
  `MRVL_BBM`). This matches the PXA3xx/MMP NAND lineage (ASR = Marvell mobile
  spin-off).

## 2. Controller architecture (CONFIRMED from strings/error flags)
- **Two register spaces** (matches DTB `reg-map` 0xd420b000+0x500 and
  `memory-map` 0x80000000+0x8000000):
  - MMIO control registers, dumped as `offset[0x%03x]:0x%08x`.
  - **LUT** (look-up table) registers, dumped as `lut_reg[0x%03x]:0x%08x`.
    → command sequences are programmed into a LUT (like Freescale/NXP QuadSPI).
- **AHB / XIP memory-mapped window**: `AHB memory-mapped base address: 0x%x`
  (printed as 0x80000000). `use_xip=1` in dmesg. Reads can go via the AHB
  window; `spi_controller->mem_ops.dirmap` is the mainline analog.
- **IP (instruction) command engine**: error flags reference
  `IP Command Usage Error`, `IP Command Trigger during AHB Access Error`,
  `IP Command Trigger could not be executed Error`, `IP Command Trigger during
  AHB Grant Error`. A software command is triggered (sets a bit / writes a
  command register) and the engine executes the SPI sequence.
- **Flag/Status registers** named in code as **`FR`** and **`SR`**:
  - `cmd 0x%.2x error, FR:0x%.8x, SR:0x%.8x`
  - `cmd 0x%.2x timeout, FR:0x%.8x, SR:0x%.8x`
  - `qspi: cmd trigger failed, fr=0x%x. restart...`
  - `qspi: cmd failed, fr=0x%x. restart...`
  - `qspi tx dma timeout, FR=0x%x, bytes=0x%x`
  - `Interrupt happen while no cmd sent, fr=0x%x`
  → `FR` = flag/interrupt-status register; `SR` = status/state register.
- **DMA via the Marvell PXA DMA controller** (NOT a private DMA):
  - register-name string `DRCMR:0x%x DCSR:0x%x DSADR:0x%x DTADR:0x%x DCMD:0x%x DDADR:0x%x`
    → DRCMR/DCSR/DSADR/DTADR/DCMD/DDADR are the standard PXA2xx/3xx DMA registers.
  - DTB `dma-tx-drcmr=<0x63>`, `dma-rx-drcmr=<0x61>` map to DRCMR entries
    (these are the DMA request-channel router registers).
  - `failed to request qspi tx dma`, `No property for tx channel map to register`,
    `!!!!qspi_start_dma_xfer: dma_mapping_error` → TX uses DMA; RX likely PIO or DMA.
  - The SoC has `CONFIG_MMP_PDMA=y` in our tree → reuse `pxa-dma` / `MMP_PDMA`
    (drivers/dma/pxa-dma.c) rather than a private DMA.

## 3. IRQ (CONFIRMED)
- `failed to get qspi irq: %d` → IRQ from DT (`interrupts = <45>`; maps to Linux
  IRQ 77 = `d420b000.qspi` in /proc/interrupts). `use_intr=1`.
- ISR decodes FR error flags (see §2). `err: receive tx interrupt while no cmd sent`.

## 4. Clocks (CONFIRMED)
- `failed to get io qspi clock` → driver does `clk_get` for a clock (likely named
  "qspi" / "qspi_fclk"). clk_summary: `qspi_fclk` 208 MHz → `qspi` 52 MHz.
- `qspi: set qspi bus clock to %dMHz` → sets SCLK to 52 MHz (matches
  `qspi-max_freq_mhz=0x34`). Driver programs a baud/divider; honor
  `spi-max-frequency` (50 MHz in DTS).
- **M0 dependency**: our M0 clock driver currently has NO QSPI clock id. Plan:
  add `ASR1802S_CLK_QSPI` (gate) after M0 lands; until then
  `devm_clk_get_optional` + rely on bootloader-enabling the domain.

## 5. DT properties consumed (CONFIRMED — from string table)
| DT prop | meaning |
|---|---|
| `asr,qspi` (compatible) | driver match |
| `reg` `reg-map` / `memory-map` | MMIO + AHB window |
| `interrupts` | IRQ |
| `dma-tx-drcmr` (0x63) | TX DMA request router reg |
| `dma-rx-drcmr` (0x61) | RX DMA request router reg |
| `qspi-cs` (0) | chip select |
| `qspi-txmode` (0x04) | TX bus mode |
| `qspi-rxmode` (0x04) | RX bus mode |
| `qspi-max_freq_mhz` (0x34=52) | SCLK max |
| `marvell,ddrfreq-qos` | DDR QoS (ignore in mainline) |
| `qspi-nand` | marks child as SPI-NAND |

Boot line: `use_intr=%d en_tx_dma=%d use_xip=%d flags=0x%x` (all enabled).

## 6. SPI-NAND device (CONFIRMED)
- Detect: `SPI-NAND: %s is found.`, `SPI-NAND type mfr_id: %x, dev_id: %x%x`.
  F35UQA001G = mfr `0xcd`, dev `0x61 0x61`.
- `Set rx_pins: %d, tx_pins: %d, Read_CMD:0x%x` → quad read `0x6b`, 4 rx / 4 tx pins.
- `block_size=0x%x page_size=0x%x bitflip_threshold=%d` → block 0x20000, page 0x800,
  ECC threshold 4. `spi_nand_detect_onfi` present → ONFI auto-detect supported.
- `spi-nand: WEL not ready, status=0x%x` → WEL (write-enable-latch) polling.
- Command flow strings: `error %d read page 0x%x to cache`, `error %d waiting page
  0x%x to cache`, `error %d program page 0x%x`, `erase block 0x%012llx failed`,
  `attempt to erase a bad block at 0x%012llx` (BBM hook).
- Stats: `qspi_erase_times(block/sector)`, `qspi_write_times(page)`.

## 7. Register map — VERIFIED (Thumb-2 disassembly of `Image.from_gzip`)
Extraction technique that actually worked (NO Ghidra needed, low CPU): from the
live `/proc/kallsyms` take each `qspi_*`/`spi_nand_*` address, convert to a file
offset as `fileoff = addr - 0xc0008000` (kernel load base = PAGE_OFFSET 0xc0000000
+ TEXT_OFFSET 0x8000), then `arm-linux-gnueabihf-objdump -EL -b binary -m arm
--disassembler-options=force-thumb -D --start-address=<foff-0x20>
--stop-address=<foff+0x700>`. Disassembling each function individually (objdump
has no symbol names) gives clean Thumb-2. Output saved in
`porting/reverse/qspi/qspi_funcs.disasm` + `qspi_exec.disasm`.

Register window: two spaces — MMIO `0x00`–`0x190` (4-byte step, emitted by
`qspi_dump_reg` as `offset[0x%03x]`) and LUT `0x310`–`0x40c` (emitted as
`lut_reg[0x%03x]`). `regs` base = driver struct field `#12` (`[r4,#12]`).

### 7.1 MMIO control registers (offset : observed use / confidence)
Verified offsets and how the vendor code uses them (reg base `0xd420b000`):
| off | observed in | meaning (confidence) |
|----|----|----|
| `0x00` | qspi_write_sfar, qspi_start_cmd | Ctrl reg; bit `0x4000` toggled (enable/clear). (HIGH) |
| `0x08` | qspi_start_cmd `str.w r9,[r3,#8]` | **Command/opcode register** — opcode byte written here once per op. (HIGH) |
| `0x0c` | qspi_host_init `str #0x202` | Flash config (FLSHCR-like); value `0x202`. (MED) |
| `0x10` | setup_memmap_read `str #14` | BUF0CR-like timing/baud window (set 14). (MED) |
| `0x14` | setup_memmap_read `str #14` | BUF1CR-like (set 14). (MED) |
| `0x30/0x34/0x38` | setup_memmap_read `str #0` | Buffer/window thresholds cleared. (MED) |
| `0x40` | qspi_start_cmd/setup | Controller field; written 0 / used. (MED) |
| `0x44/0x48/0x4c/0x50` | qspi_host_init `str 0x80000000/0x88000000/0x90000000/0x98000000` | **AHB/XIP window base address regs** (map flash into 0x80000000+0x8000000). (HIGH) |
| `0x54` | qspi_host_init `str #1` | Enable (1). (MED) |
| `0x60` | qspi_host_init `str #1` | Enable (1). (MED) |
| `0x68/0x6c` | qspi_host_init / start_cmd | Config fields. (MED) |
| `0x100` | qspi_write_sfar; qspi_start_cmd | **SFAR** (Serial Flash Address Reg) — write addr, poll until written. (HIGH) |
| `0x104` | qspi_host_init `str #0`; read-back poll | **Reset/busy-clear**: write 0, wait until read==0. (HIGH) |
| `0x108` | qspi_host_init `str #0` or `str #32` | Mode reg (0 or 0x20). (MED) |
| `0x10c` | qspi_start_cmd `ldr [r3,#268]` | Read (status/state). (MED) |
| `0x110` | qspi_write_rbct; start_cmd | **RBCT** (read-buffer/burst count) — write, poll. (HIGH) |
| `0x150/0x154/0x158` | qspi_start_cmd | IP-command word registers (seq low/mid/high). (HIGH) |
| `0x15c` | qspi_start_cmd/ahb_read/wait_cmd_done `ldr [r3,#348]`, poll bit0 | **STATUS** — busy wait until bit0 clears. (HIGH) |
| `0x160` | qspi_write_sfar/rbct/wait_cmd_done `ldr/str [r3,#352]`, bit `0x40` | **FR** flag/int-status reg (bit6 = cmd done/err). (HIGH) |
| `0x164` | qspi_start_cmd (heavy R/W) | **IP command trigger / data-config reg** — assembled cmd written here. (HIGH) |
| `0x16c` | qspi_start_cmd `ldr/str [r3,#364]` | SPTRCLR-like / pointer-clear. (MED) |
| `0x180` | qspi_host_init `str 0x88000000` | AHB window base (2nd). (MED) |
| `0x304` | qspi_dump_reg prologue `str [r3,#772]` | Control/trigger (uncertain). (LOW) |
| `0x118` | qspi_start_cmd/ahb_read | Config / timeout reg. (MED) |
| `0x140` | qspi_start_cmd | Config reg. (MED) |
| `0x180/0x184/0x188/0x18c` | qspi_host_init/start_cmd | **SFA1AD/SFA2AD/SFB1AD/SFB2AD** (AHB window flash-address regs) — exact VF610 match. (HIGH) |
| `0x1c8`/`0x1dc` | qspi_start_cmd/ahb_read | Unknown config. (LOW) |
| `0x1e0` | qspi_ahb_read, spi_nand_do_write_ops `ldrd [..,#480]` | **DATA port (TBDR/RBDR)**: PIO RX read / TX write. (HIGH) |

### 7.2 LUT registers
`0x310`–`0x40c` (4-byte steps): command-sequence LUT table. Programmed by
`qspi_config_lookup_tbl` (`qspi_kallsyms.txt` @ `0xc015b388`). Mainline driver can
either reuse the vendor LUT programming or implement sequence in the IP regs.

### 7.3 STRONG similarity to Freescale/NXP Vybrid VF610 QuadSPI
Offsets `0x00`(MCR), `0x08`(IPCR/cmd), `0x0c`(FLSHCR), `0x10`(BUF0CR),
`0x14`(BUF1CR), `0x100`(SFAR), `0x110`(RBCT), AHB window bases `0x44–0x50`,
`0x180/0x184/0x188/0x18c`(SFA1AD/SFA2AD/SFB1AD/SFB2AD), and the LUT region all match
the upstream `drivers/spi/spi-fsl-qspi.c` VF610 register layout almost 1:1. Only a
few regs are shifted/added vs VF610:
- STATUS is `0x15c` (VF610 FR is `0x140`), FR flag is `0x160` (VF610 RSER `0x148`),
  IP trigger `0x164`, SPTRCLR `0x16c`, DATA port `0x1e0` (VF610 TBDR `0x1c0`).
**Plan: model `spi-asr1802s-qspi.c` on `spi-fsl-qspi.c`, overriding the shifted
regs (STATUS 0x15c, FR 0x160, trigger 0x164, DATA 0x1e0) and the LUT range
0x310–0x418.**

### 7.4 Data FIFO / TX-RX buffer register — RESOLVED (2026-08-17)
**Data port = `0x1e0`** (offset 480). Confirmed referenced as the data register in
both `qspi_ahb_read` and `spi_nand_do_write_ops`
(`ldrd r2, r3, [r1, #480]!  @ 0x1e0`). PIO RX reads from it; PIO TX writes to it
(VF610 counterpart is TBDR 0x1c0 / RBDR 0x200+ — this IP relocates the port to 0x1e0,
just past the `qspi_dump_reg` MMIO window which ends at 0x190). AHB/XIP reads use the
memory-mapped window (0x80000000+) and bypass this port.
- Full verified register set now (offsets relative to `0xd420b000`):
  `0x00` MCR, `0x08` IPCR/cmd, `0x0c` FLSHCR(0x202), `0x10` BUF0CR(14), `0x14`
  BUF1CR(14), `0x30/0x34/0x38` buf thresholds, `0x40` cfg, `0x44/0x48/0x4c/0x50`
  AHB window bases, `0x54/0x60` enable, `0x68/0x6c` cfg, `0x100` SFAR, `0x104`
  reset/busy(w0 poll0), `0x108` mode(0/0x20), `0x10c` state, `0x110` RBCT, `0x118`
  cfg/timeout, `0x140` cfg, `0x150/0x154/0x158` IP-cmd words, `0x15c` STATUS(bit0
  busy), `0x160` FR(bit6 0x40), `0x164` IP trigger, `0x16c` SPTRCLR, `0x180/0x184/
  0x188/0x18c` SFA1AD/SFA2AD/SFB1AD/SFB2AD, `0x1c8`/`0x1dc` (unknown), `0x1e0` DATA
  port, `0x300/0x304` trigger/cfg, LUT `0x310–0x418`.

## 8. RE status — Technique (objdump Thumb-2) SUCCEEDED
Ghidra is abandonable for offset extraction. The low-CPU objdump-per-function
Thumb-2 method (§7) already recovered the full control-register map. Remaining
TODO: (a) pin the data FIFO reg (§7.4) by disassembling `spi_nand_do_read_ops` /
`spi_nand_do_write_ops` RX/TX loops; (b) recover LUT sequence programming from
`qspi_config_lookup_tbl` if mainline needs it. Live ftrace is NOT available
(no ftrace in kernel); `/dev/mem` reads blocked by STRICT_DEVMEM — so disassembly
is the authoritative source.

## 9. Files produced in this RE pass
- `porting/reverse/qspi/extract_vmlinux.py` — zImage → Image extractor.
- `porting/reverse/qspi/Image.from_gzip` — decompressed vendor kernel Image.
- `porting/reverse/qspi/Image.disasm` — objdump -D (ARM-view; partial, superseded).
- `porting/reverse/qspi/qspi_core.disasm` — objdump Thumb-2 of qspi cluster.
- `porting/reverse/qspi/qspi_funcs.disasm` — objdump Thumb-2 per-function (qspi_*+spi_nand_*).
- `porting/reverse/qspi/qspi_exec.disasm` — objdump of qspi_start_cmd/do_read_ops/do_write_ops.
- `porting/reverse/qspi/live_trace/ROUTER_20260817_115949/` — kallsyms.txt (42671 ln),
  qspi_kallsyms.txt (77 syms), iomem/interrupts/cmdline/dmesg/procfs (stats only).
- `porting/reverse/qspi/RE_NOTES.md` — this file.
- `porting/reverse/qspi/M1_PLAN.md` — M1 plan/checklist.
- `porting/reverse/qspi/live_trace/trace_qspi.sh` — live trace harness (run later).
