# M1 QSPI — current state (saved 2026-08-17, updated after register-map RE)

## Where we are
- M1 plan + milestones: `porting/reverse/qspi/M1_PLAN.md` (M1.3 register map DONE)
- RE notes: `porting/reverse/qspi/RE_NOTES.md` (architecture + VERIFIED register map §7)
- Vendor kernel extracted: `extract_vmlinux.py` → `Image.from_gzip` (5 MB ARM/Thumb-2 Image)
- Per-function Thumb-2 disassembly: `qspi_funcs.disasm`, `qspi_exec.disasm`, `qspi_core.disasm`
- Live router captures: `live_trace/ROUTER_20260817_115949/` (kallsyms 42671 ln, iomem,
  interrupts, cmdline, dmesg, procfs stats). Router was online 2026-08-17.

## What is DONE
- [x] Extracted vendor Image from `kernel-a.bin` (zImage piggy = gzip at off 17500)
- [x] Identified driver: **Marvell PXA3xx-derived QSPI SPI-NAND** (`asr,qspi`) + `pxa3xx_bbm`
- [x] Documented architecture: IP-command engine (FR/SR regs), LUT table, AHB/XIP window,
      PXA-DMA (DRCMR/DCSR/DSADR/DTADR/DCMD/DDADR), IRQ 45, qspi clock 208→52 MHz,
      full DT-prop table, F35UQA001G params (mfr 0xcd, quad 0x6b, blk 0x20000, pg 0x800, ecc 4)
- [x] **Register map EXTRACTED** via objdump Thumb-2 per-function disassembly (NO Ghidra needed).
      Reg base = struct field #12; MMIO `0x00`–`0x190`, DATA port `0x1e0`, LUT `0x310`–`0x418`.
      Key regs:
      - `0x08` cmd/opcode, `0x0c` FLSHCR(0x202), `0x10/0x14` BUF timings(14),
        `0x44–0x50` AHB window bases (0x80000000..0x98000000), `0x54/0x60` enable,
      - `0x100` SFAR, `0x104` reset/busy-clear (write0 poll0), `0x108` mode, `0x110` RBCT,
      - `0x150/0x154/0x158` IP-cmd words, `0x15c` STATUS(bit0 busy), `0x160` FR(bit6 0x40),
        `0x164` IP trigger, `0x180/0x184/0x188/0x18c` SFAxAD (VF610 match), `0x1e0` DATA port.
      - **STRONG match to Freescale VF610 QuadSPI (`spi-fsl-qspi.c`)** → model driver on it,
        overriding shifted regs (STATUS 0x15c, FR 0x160, trigger 0x164, DATA 0x1e0) + LUT range.
- [x] **M1.3b DONE** — data FIFO / TX-RX buffer reg PINNED = `0x1e0` (RE_NOTES §7.4).
      Full register set verified.

## Remaining RE TODO
- (none outstanding — register map complete; proceed to driver writing M1.4)

## Live RE notes (router was online 2026-08-17)
- SSH (works): `sshpass -p <pw> ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no
  -o KexAlgorithms=diffie-hellman-group14-sha1 -o HostKeyAlgorithms=+ssh-rsa -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null root@192.168.1.1`. NOTE: `-o StrictHostKeyAlgorithms=+ssh-rsa` is
  INVALID for this ssh client — do NOT reuse it; the negotiation above still succeeded.
  (Password not stored here; it was provided in-session. Update harness if reused.)
- ftrace NOT compiled in (no /sys/kernel/tracing, no /proc/sys/kernel/ftrace_enabled) → live
  trace harness is non-functional; disassembly is the authoritative offset source.
- `/dev/mem` reads of 0xd420b000 blocked by STRICT_DEVMEM ("Bad address"); procfs `asr-qspi`
  exposes only stats (qspi_erase_times/qspi_write_times), not a register dump.

## Next after M1.3b (FIFO reg) — driver writing
- M1.4 write `drivers/spi/spi-asr1802s-qspi.c` (spi_controller + spi_mem exec_op, PIO first;
      model on `spi-fsl-qspi.c`), use `devm_clk_get_optional` for QSPI gate (added in M0 later)
- M1.5 DT binding YAML (`asr,asr1802s-qspi.yaml`)
- M1.6 add F35UQA001G spi-nand entry if mfr 0xcd missing in mainline
- M1.7 QSPI clock gate (after M0): add `ASR1802S_CLK_QSPI` to M0 clk driver+header
- M1.8 OpenWrt patches 0006/0007 + config-6.12; build + checkpatch + dtc clean
- M1.9 hand off to M4 boot test (rootfs mount = success)
