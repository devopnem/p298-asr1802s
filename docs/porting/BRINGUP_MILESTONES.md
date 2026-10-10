# R291 ASR1802S (Notion R291 / KAGU) — OpenWrt + kernel bring-up milestones

> Workspace: /home/void/Downloads/Modems/Notion_R291_ASR1802S_P298_N13
> Findings (mirror): https://github.com/devopnem/r291-asr1802s-findings
> OpenWrt fork: /home/void/Downloads/openwrt/openwrt-fork  (branch asr1802s-kagu-wip @ 74a3dc6b = PR #24614)
> Kernel RFC: https://github.com/devopnem/linux-asr1802s-rfc
> Strict rule: `AGENTS.md` — target completeness check before any `push --force`.

## Context
- PR #24614 was pushed from our local fork → local `b9880b51` IS the PR content. No `git fetch` needed.
- ASR1802S = Marvell-MMP lineage (ASR acquired Marvell's mobile division; Cortex-A7 + CP = PXA1088/PXA1920 generation). Vendor kernel is Marvell 3.10.33 fork (closed source).
- We DO have: full 25-partition NAND dumps, vendor DTB + decompiled DTS, live router SSH, full dmesg, /proc/interrupts, kallsyms, Marvell public 3.10 trees for reference.
- Ethernet reality: LAN = SoC internal ASR EMAC (`asr,asr-eth-v2` @ 0xd4281800, RGMII) → **Motorcomm YT9215RB** 5-port switch → RJ45. Realtek chips (RTL8812FR / 8192FR) are **WiFi**, not Ethernet. No mainline/OpenWrt driver exists for EMAC or switch.

## Critical constraints (from bootloader_analysis/REPORT.md)
1. mrvlboot (U-Boot) verifies SHA-256 of kernel/rootfs against Marvell TIM tables in mtd7/8. Custom image with no TIM update → rejected → falls back to slot-b (safe, but our image never boots). Writing a raw DTB into mtd7 DESTROYS the TIM tables + RSA signature → OBM refuses boot (the old router brick). A/B rollback (`reboot_cnt`+`temp_active_slot`) is the secure rescue.
2. No TFTP in the bootloader (zero network code). Failsafe is UART-only (preinit gives no LAN IP). No UART on this unit.
3. The DTB is APPENDED INSIDE the zImage (stock kernel-a.bin layout) — mrvlboot does `bootz` on a raw zImage + appended DTB. Build must produce raw zImage (+ appended DTB), NOT uImage.

## M0 — Push clock driver to PR + fresh build  [DONE ✅ 2026-08-22 @ 74a3dc6b]
1. ✅ `clk-asr1802s.c` `of_device_id` aligned: `asr,asr1802s-clock` + `marvell,asr1802s-clock`.
2. ✅ Patch `0005` (clk driver, 869→868 lines after 2026-08-22 header trim): driver + Kconfig + Makefile + dt-bindings.
3. ✅ `config-6.12`: `CONFIG_COMMON_CLK_ASR1802S=y`, cleaned 7 unreachable lines (`SND_*`/`VIDEO`/`ARM_APPENDED_DTB`), moved to `430fb917` so bisect passes (430fb917..74a3dc6b all have config).
4. ✅ `.config` device symbol fixed (`notion_r291`). `0001-0004` subjects normalized to bare `[PATCH]`, `0008` maintainer + `unevaluatedProperties`, `0009` distinct hash.
5. ⏳ Local build: toolchain NOT installed → **build via CI** (CI `Build asr1802s` now runs again after 74a3dc6b).
6. ✅ PR branch at `74a3dc6b` (forced from `8bd7c651`), 4 review nits fixed, target completeness verified (`AGENTS.md` strict rule added).
7. ⏳ Mirror series to `linux-asr1802s-rfc` (pending).

## M1 — QSPI SPI-NAND driver (asr,qspi) — MOST CRITICAL (blocks rootfs)  [RE DONE, OFFSETS BLOCKED]
Goal: kernel sees F35UQA001G → MTD → /dev/mtdblock15 → rootfs mount. No driver → no mtdblock → kernel panic at root.
- ✅ RE (Technique C, binary): vmlinux extracted (`qspi/extract_vmlinux.py` → `Image.from_gzip`); driver = **Marvell PXA3xx-derived QSPI** + `pxa3xx_bbm`; architecture confirmed in `qspi/RE_NOTES.md` (IP-cmd + LUT + AHB/XIP + FR/SR regs, PXA-DMA DRCMR 0x63/0x61, IRQ 45, qspi_fclk 208→52 MHz, F35UQA001G mfr 0xcd quad 0x6b blk 0x20000 pg 0x800 ecc 4).
- ✅ Live-trace harness ready: `qspi/live_trace/trace_qspi.sh` (Technique B — run when router reconnects).
- ⛔ **BLOCKED: exact register offsets** — Image is Thumb-2; Ghidra headless script `qspi/ExtractQspi.java` written, run aborted (CPU load). Decision: prefer **live tracing** first, Ghidra as offline fallback (~6 min CPU).
- Detailed sub-milestones M1.0–M1.9: `porting_workspace/qspi/M1_PLAN.md` (+ `STATE.md`).
- Deliverable: `drivers/spi/spi-asr1802s-qspi.c` (spi-mem + spi-nand) + DT binding; checkpatch/dtc clean.

## M2 — EMAC Ethernet (asr,asr-eth-v2)  [RE COMPLETE ✅, DRIVER NEXT]
Goal: eth0 up → SSH observation channel.
- ✅ **Binary RE complete** — `emac_re/RE_NOTES.md` (223 lines): register map (base 0xd4281800: CTRL 0x00, IRQ 0x08, TX/RX enable 0x0c, MAC cfg 0x100, MDIO div 0x11c, MAC addr 0x120-0x128, speed 0x1c4, MAC accessor 0x89f1/0x89f2), MDIO (0x1a0 cmd bit15/b10 + 0x1a4 data), TX desc 32B + ring, RX path, `emac_up` full (phy connect/fixed-link/IRQs), APMU 0xd4282800, AIB 0xd401e804 3v3/1v8, NAPI/IRQ identities (emac_poll 0xc0192ae4, emac_irq 0xc0192e3e). Partial: APMU phase in `clk_phase_rgmii_set` (fcn 0x1cc4).
- Deliverable: `drivers/net/ethernet/asr/asr-emac.c` (fixed-link + MDIO bus for switch) + DT binding. Plan: `emac_re/PLAN_M2.md`.

## M3 — YT9215RB switch  [PRE-WORK DONE ✅]
Goal: LAN ports pass traffic.
- ✅ Pre-work: `yt_code.bin` + `mdio.bin` slices extracted from kernel image (in `emac_re/`).
- Next: RE switch MDIO protocol → "forward-all" via MDIO poke first; proper DSA later.
- Deliverable: LAN SSH working.

## M4 — Blind slot-a boot test (needs M1+M2+M3 + DTIM workstream)
- **Parallel workstream (RE, not a driver)**: RE mrvlboot hash formula (Ghidra on `mtd11.bin`) → dtim-rebuild tool.
- Steps: backups (mtd7,8,13,14,15,16,19,21) → rebuild dtim-a with new-image hashes → write mtd7, kernel-a (zImage+DTB), rootfs-a → reboot.
- Secure rescue: untouched stock slot-b + mrvlboot A/B rollback.
- Verify via SSH: `uname -r`=6.12.103, dmesg (asr1802s/qspi/emac), `clk_summary` (312/533/208), `/proc/mtd` 24 parts, ping/LuCI.

## M5 — Follow-ups
WiFi (RTL8812FR), USB3/PCIe, DSA switch, DTIM doc, kernel-ML + OpenWrt upstreaming.

## Dependency graph
```
M0 (clock+build) ──┐
M1 (qspi) ─────────┼──> M4 (boot test)
M2 (emac) ──> M3 ──┘
DTIM hash RE (parallel) ──> M4
```

## Parallel-job division (to run another AI concurrently)
- **AI #2 → M1 (QSPI)**: RE phase DONE (vmlinux extracted, architecture confirmed — `qspi/RE_NOTES.md`). Blocked on register offsets: run Ghidra `qspi/ExtractQspi.java` (~6 min CPU) or wait for live trace. Then: `drivers/spi/spi-asr1802s-qspi.c` + DT binding.
- **AI #3 → DTIM hash RE**: Ghidra analysis of `mtd11.bin` (u-boot) to derive the TIM SHA-256 formula; goal: a `dtim-rebuild` tool. This gates M4 independently of all drivers.
- **AI #2/3 → M2 (EMAC)**: binary RE **complete** (`emac_re/RE_NOTES.md`); next job = write `drivers/net/ethernet/asr/asr-emac.c` from the recovered register map.
- **You (this AI) → M0 done ✅; next: M1 integration + M2 driver + M3 RE.**

## Risks
- Blind dev until M4 (no live feedback) — mitigated by live kprobes on stock router + Marvell public sources + full dumps.
- DTIM hash formula is the hard gate for M4.
- DELETE old delivery scripts (`flash_r291_slot_a.sh`, `install_openwrt_r291.sh`) — they write uImage + raw DTB to mtd7 = brick method.
