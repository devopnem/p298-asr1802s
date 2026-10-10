# M2 — EMAC Ethernet driver (asr,asr-eth-v2)

> Goal: eth0 up -> SSH observation channel (switch pass-through is M3).
> Status: ✅ DONE (code/config) — build verification & hardware deferred (see below)
> Owner: this AI session (parallel to M0/M1/DTIM workstreams)

## Facts verified (2026-08-17)

- DT node (vendor.dts:382): `reg <0xd4281800 0x200>`, `interrupts <10 11>`,
  `reset-delays-us <0 0x186a0 0x7a120>`, `clk-tuning-enable`,
  `tx-clk-config <0x203>`, `rx-clk-config <0x803>`, `mdio-clk-div <0xfe>`,
  `fixed-link { speed 1000, full-duplex, phy-mode rgmii }`,
  `mdio-bus { phy@0 ethernet-phy-id011a.c816, tx_rx_delay <0x0b 0x00> }`.
- Fork `0003` patch already contains eth0 skeleton (compatible/reg/interrupts
  + board-level fixed-link). Missing: driver, full node, mdio, config.
- IRQ mapping: mainline `mrvl,mmp-intc` maps DT values 1:1 (irq-mmp.c:263,
  virq_base=0). Vendor 42/43 = DT 10/11 + 32 (their domain base artifact).
  Use `<10 11>`.
- Switch link (M3 input): `yt_switch { compatible motorcomm,yt9215rb,
  mii-bus = <&mdio-bus>; PHY_ID 0 }` -> M2 MDIO bus is the switch access
  path. Probe deferral + "cannot get PHY at address 0" in vendor dmesg is
  expected (switch inits later).
- NOT pxa168-compatible: 0x200 reg block vs pxa168_eth 0x400+ offsets/0x1000
  block. MMP3 has MMC4 at 0xd4281800. Custom ASR MAC -> register map from RE.
- Router was OFFLINE (ping 192.168.1.1 failed) -> live kprobes deferred.
- M0 in-flight: untracked `0005-clk-asr1802s-add-clock-driver.patch` in fork.
  M2 patches get numbers 0006+.
- Tooling: radare2 present; `extract-vmlinux` in
  build_dir/.../linux-6.12.103/scripts/; old `kernel-decomp.bin` (clock RE)
  is gone -> re-extract. Link base 0xC0008000 (clock RE notes).
- Build .config already has PHYLIB/FIXED_PHY/OF_MDIO/MDIO_BUS as =m
  (build_dir .config:2230-2355) -> promote to =y for built-in driver.

## Phase 1 — Binary RE of kernel-a.bin

1. `scripts/extract-vmlinux findings/firmware-backup/kernel-a.bin > porting/reverse/emac_re/kernel-decomp.bin`
2. Locate emac code:
   - String xrefs (`r2` izz/axt): "emac_reset_hw", "emac set tx dline",
     "emac set rx dline", "clk_phase_rgmii_set", "emac mii", "find fixed
     link", "Using random mac address", "emac_up".
   - kallsyms table extraction for full asr_emac_* list (fallback: xrefs).
3. Decode per function: register offsets (base 0xd4281800 + off), constants
   (0xfe, 0x2310001, 0x2310831, 0x2007 MPMU phase, 0x203/0x803), TX/RX
   descriptor ring layout ("dline" regs), INT_CAUSE/MASK bits, MDIO
   addr/data/ctrl sequence, NAPI/IRQ handling.
4. Cross-check descriptor format vs mainline pxa168_eth.c (build tree).
5. Write porting/reverse/emac_re/RE_NOTES.md.

## Phase 2 — Driver

- drivers/net/ethernet/asr/{Kconfig,Makefile,asr-emac.c}
- platform driver, compatible "asr,asr-eth-v2", depends ARCH_ASR,
  select PHYLIB/FIXED_PHY/OF_MDIO.
- fixed-link (1000/full) for netdev + separate MDIO bus (DT mii-bus phandle)
  for the switch (M3 consumer).
- 2 IRQs, NAPI RX, mac-address/random fallback, asr,mdio-clk-div,
  reset delays, RGMII clock tuning (MPMU 0xc0100000 writes per RE).

## Phase 3 — DT binding + DTS

- Documentation/devicetree/bindings/net/asr,asr-eth-v2.yaml
  (asr,-prefixed vendor props).
- Extend asr1802s.dtsi eth0 + board dts (new patch, after driver patch).

## Phase 4 — Config, build, verify

- config-6.12: CONFIG_ASR_EMAC=y + promote phy symbols =y. ✅
- Build kernel; nm vmlinux | grep asr_emac; dtbs_check; checkpatch clean.
  - ⛔ DEFERRED: no ARM toolchain in fork staging_dir -> only C-stage (.s)
    verification possible (0 errors/warnings via gcc wrapper, -Werror).
    Real build must run in OpenWrt CI or after toolchain install.
    DTB builds clean; dtbs_check (dt-schema) not run.
  - ✅ checkpatch: 0 errors (0006: 3 benign warnings; 0007: 1 expected).
- Commit to fork PR branch (after M0 lands for stable numbering) + mirror
  to linux-asr1802s-rfc. ⛔ DEFERRED (0006/0007 still untracked in fork).

## Deferred items (outside M2 scope or blocked)

- APMU clock-phase writes (Phase 2 "RGMII clock tuning"): PARTIAL — driver
  parses/logs tx/rx clk-config (0x203/0x803) but APMU phase reg offsets not
  decoded (see RE_NOTES clk_phase_rgmii_set). Revisit in M5/live tracing.
- Hardware verification of eth0: M4 gate (per Risks below).

## Phase 5 — Optional live tracing (router back online)

- kprobe asr_emac_* on stock 3.10.33, log writel sequences, diff vs RE.

## Risks

- Register map RE-only (no public ASR Linux EMAC source found; Luat/RTOS
  repos irrelevant). Mitigated by string xrefs + constants + dual prints.
- Fixed-link + MDIO dual model is unusual but vendor does exactly this.
- No hardware feedback until M4; verification static only.
