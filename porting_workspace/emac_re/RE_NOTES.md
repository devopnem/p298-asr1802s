# EMAC RE Notes (ASR1802S vendor kernel 3.10.33)

Region: file 0x189600-0x18c300, VA 0xc0189600 (link base 0xC0008000).
Disassembly: `emac_dis2.txt` (r2, Thumb-2, base 0xc0189600, slice `emac2.bin`).

## String inventory (emac driver, VA c03cc500-c03ccf60)

- "asr_emac" (driver/module name)
- "IP175D_LINKUP"/"IP175D_LINKDW"/"LINKUP"/"LINKDW"/"PHY_CONNECT"/"DHCPCLIENT"/"DHCPSERVER" (uevent/notifier names)
- "%s link:%d speed:%dM duplex:%s" (KERN_INFO, emac_adjust_link)
- "eth0 port%d link up"/"eth0 port%d link down"
- "broken speed: %d" (KERN_ERR)
- "emac: force link speed:%dM duplex:%s" (forced link)
- "===> emac_reset_hw: MDIO clock div: 0x%x"
- "===> emac set tx dline 0x%x 0x%x", "===> emac set rx dline 0x%x 0x%x"
- "%s phase:%d direction:%s 0x%x 0x%x" (clk_phase_rgmii_set)
- "RMII"/"RGMII"/"Emac MII Interface : %s"/"Current rx clk config : %d"/"Current tx clk config : %d"
- "===> set eamc interface: rmii"/": rgmii"
- "===> emac set io to 3.3v"/"1.8v", "===> emac AIB read back: 0x%x"
- "DMA:0x%x:0x%x"/"MAC:0x%x:0x%x" (register dump labels)
- "===> dump emac register ====" / "----------%s-----------"
- "TX timeout"/"Packet length is zero"/"Collision detected"/"Descriptors are not free"
- "Could not acquire memory from pool"
- "sk_buff allocation failed"/"must be stopped to change its MTU"/"Invalid MTU setting"
- "Using random mac address"/"emac clock not found."/"failed to enable emac clock: %d"
- "Memory allocation failed for the Transmit descriptor buffer/ring" + Receive same
- "Error in setting up the Tx/Rx resources"/"Error in making the net intrface up"
- "register_netdev failed"
- "request_irq failed"/"request wakeup_irq failed"/"Could not attach to PHY"
- "%s:  %s: attached to PHY (UID 0x%x) Link = %d irq=%d addr=0x%x"
- "Not valid phy_id=0x%x"
- "find fixed link"/"no interface for fix-link, use RGMII"
- "no %s child node found" (mdio-bus child)
- "MD83X_N25" (HW version)/"the HW version is greater than MD83_N24..."
- "port_%s"/"clk_tuning"/"count must be less than 50."/"eg: echo rx 1 > clk_tuning"
- "wake_up irq not found"/"==> enter emac_suspend_noirq"/"==> enter emac_resume_noirq"
- "emac: reset-gpio=%d request failed"
- DT props: reset-gpio, reset-active-low, reset-delays-us, mdio-ldo, ldo-active-low,
  ldo-delays-us, mdio-reset, ldo-gpio, fixed-link, managed, mdio-clk-div, mdio-bus,
  in-band-status, full-duplex, asym-pause, clk-tuning-enable, tx-clk-config, rx-clk-config,
  phy-handle, phy-handle-2, 3v-enable, rgmii-pins, v3-enable(?)
- "error to ioremap APMU base" -> APMU at 0xd4282800
- "work error %d\n" + uevent env (HOME/PATH/SUBSYSTEM=ethernet/ACTION/ETH/PORT/SEQNUM)
- "Direct register access: read/write to phy 21 MII 22 Special tagging" (debugfs, mdio tools)
- "ster access: read/write to register (0-65535)" (debugfs reg access)
- "spec"/"clk_tuning" debugfs files

## Register map (base = EMAC reg block, DT reg 0xd4281800)

| Off  | Use | Notes |
|------|-----|-------|
| 0x00 | CTRL / soft-reset | =1 then delay ~1s, =0 delay, then 0x70020; read/write with dsb |
| 0x04 | ? | cleared on init |
| 0x08 | IRQ status/ack | bits 0-7, W1C write-back; bit0..7 mapped to events |
| 0x0c | TX/RX enable | |= 0x11 (bits 0,4) to start; &= ~0x11 to stop |
| 0x14 | ? | written 0xff |
| 0x100 | MAC config | init 0x18; adjust_link: bit0-1 speed (1=100M,2=1000M), bit2 duplex, bits 8-9 = 0x300 mask; enable 0x100/0x200 bits at 0x5e2 |
| 0x104 | ? | cleared |
| 0x108 | ? | cleared |
| 0x118 | ? | = 0x100 (init) |
| 0x11c | MDIO clock divider | = mdio-clk-div DT prop (0xfe); read back + print in reset_hw |
| 0x120/0x124/0x128 | MAC address (16-bit halves) | written by emac_set_mac_addr |
| 0x150-0x15c | ? | zeroed |
| 0x1c0 | ? | = 0x3f8 |
| 0x1c4 | speed config | 1000M:0x400, 100M:0x100, else:0x5ee |
| 0x1c8 | ? | = 0xc |
| 0x1e4 | ? | = 0 |
| 0x89f1 | MAC addr read (4 bytes LE) | via accessor fcn 0x189a18 (offset arg 0x89f1/0x89f2, base = [netdev,0x6a4]) |
| 0x89f2 | MAC addr write (4 bytes LE) | same accessor |

APMU: 0xd4282800, ioremap 0x1000, helper fcn 0x189f58 (set/clear bit by reg+bit pos).

## TX descriptor (32 bytes), ring base [netdev,0x63c], count [netdev,0x630]

- +0x00: skb pointer
- +0x04: halfword, bits 0-11 = buffer length
- +0x08/+0x0c: dma_addr (64-bit)
- +0x10: skb data ptr (non-frag)
- +0x14: jiffies snapshot
- +0x18: halfword length (buffer)
- +0x1a: halfword (ring wrap index?)
- +0x03 byte bit7: OWN bit (set for HW)
- +0x07 byte: bit5 = first?, bit6 = last (0xc0 = last+?), bit2 (0x4) = ring wrap, bit1 = ?

TX kick: fcn 0x18a6c6 writes [base+0x14] = 0xff (kick after tail update).

## RX path (fcn 0x18aae4, emac_irq-ish)

- desc[0] word bits: 0-13 = length, bits 6-7 / bit2 / bits 8-9 = status/error, bits 14-28 = status word
- buffer size check: (len + 0x3fc0 + 0x3b) & 0x3fff <= 0x7fb else drop
- [skb,0x64] bits 2-3 = checksum offload type (from rx status bits 8-9)
- [skb,0x66] = protocol; [skb,0xb8] = skb->data

## Priv/netdev layout (emac, netdev_priv)

- [netdev,0x624]: skb table (16-byte entries, skb ptr at +8)
- [netdev,0x630]: tx ring count
- [netdev,0x634]/[netdev,0x638]: tx head/tail index
- [netdev,0x63c]: tx descriptor ring base (32-byte)
- [netdev,0x65c]: tx lock (spinlock)
- [netdev,0x69c]: dma ops ptr (dma_pool ops: 0xc04a8328 default = swiotlb/dma direct)
- [netdev,0x6a4]: MMIO base (emac regs)
- [netdev,0x6b8]/[netdev,0x6bc]: cached link/duplex
- [netdev,0x794]: IRQ state flags (bit0 busy, bit1, bit3)
- [netdev,0x844]: link state (0/1)
- [netdev,0x848]: port link state; [netdev,0x849]: flag
- [netdev,0x84c]: work_struct (link work)
- [netdev,0x880]: switch port (IP175D check, 0x2430d80 phy id)
- [netdev,0x43c]: phy_device ptr; phy: +0x190 phy_id, +0x1cc duplex, +0x1d0 speed, +0x1dc link
- [priv,0xc4]: MMIO base (irq path), [priv,0xe4]: mdio_clk_div, [priv,0xdc]: forced speed
- [priv,0xf0]/[priv,0xf4]: reset-gpio / mdio-ldo gpio; [priv,0xf8]/[priv,0xfc]: active-low
- [priv,0x100]/[priv,0x104]: ldo delays (3 x u32)

## Functions identified (slice offsets = VA 0xc0189600 +)

- 0x000: emac_irq? tail (blx r4 trampoline) - partial
- 0x070: notifier name picker + queue (LINKDW/LINKUP/PHY_CONNECT/...)
- 0x154: emac_adjust_link (link/speed/duplex -> base+0x100; port loop x16; IP175D port logic)
- 0x458: wakeup/gpio irq helper (gpio->irq wake enable/disable, usleep 1000)
- 0x570/0x628: emac_irq/wakeup handlers (base+0xc |= / &= ~0x11, base+0x100 |= 0x100/0x200)
- 0x734: ddr_clk_scaling (tx rate limit calc, jiffies 0xc04a1370, delayed work +0x2c8)
- 0x850: emac_suspend_noirq-ish (priv+0x180 flags) [small, bit ops on 0x180]
- 0x90c/0x928/0x934: tiny (name copy "asr_emac", netdev_priv getters)
- 0x940: emac_gpio_init (reset-gpio/mdio-ldo parse + request, "reset-gpio=%d request failed")
- 0xa18: MAC addr accessor (reg 0x89f1/0x89f2, LE byte assembly, dsb)
- 0xa9a: copy 37 x 4 bytes from table 0xc037ece0 (init table)
- 0xacc: fixed-link/managed parsing ("fixed-link" 0xc03cc843, "managed" 0xc03cc84e, 0xc03bf3d0)
- 0xb1c: regmap-ish write (0xc04e9648) - debugfs "Direct register access" (phy 21 MII 22)
- 0xb74: uevent sender (kobject uevent with ETH/PORT env) - link change userspace notify
- 0xc8c: APMU ioremap check (0xd4282800, "error to ioremap APMU base")
- 0xcf4: dma_alloc/dma_pool wrapper (0xffe8966c dma_map, 0xffe7872c cache ops)
- 0xd20: dump emac registers ("DMA:0x%x:0x%x" 0x0-0x3c, "MAC:0x%x:0x%x" 0x100-0x1ec)
- 0xd64: TX timeout handler ("TX timeout", "===> dump emac register", bl 0xd20)
- 0xde0/0xdec: align helpers (8/4-byte rounding)
- 0xdf8: emac_reset_hw (lite: 0x100=0x18->0, 0x11c=mdio div, readback print)
- 0xe8c: emac_down (cancel work +0x26c, stop queue, reset_hw, phy_disconnect/detach, free_irq, cancel 3 delayed works, unmap?)
- 0xefc: emac_open HW init (0x108/0x104/0x118=0x100/0x150-0x15c/0x1c0=0x3f8/0x1c4=speed/0x1c8=0xc/0=1 delay ~1s,0,0x70020,0x11c=mdio div)
- 0x1038: set MAC addr regs (0x120/0x124/0x128)
- 0x1078: ndo_set_mac_address (reject multicast/zero, -EADDRNOTAVAIL)
- 0x10c6: TX kick ([base+0x14]=0xff)
- 0x10d4: emac_start_xmit (ARP/DHCP "CD" magic check, IP175D port2 redirect, frags + desc build)
- 0x14c8: [base+0xc] |= 0x11 (start rx/tx)
- 0x14e4: emac IRQ/NAPI handler (TX complete: dma_unmap, skb free via 0xaf560; RX: desc[0] status, checksum, netif_receive_skb)
- 0x1824: [base+0xc] &= ~0x11 (stop rx/tx)
- 0x183e: emac_irq_handler (read [base+8] status, ack write-back, event bits -> work)
- 0x1914: APMU mapped check
- 0x1958: APMU clrsetbits helper (set/clear bit at APMU base+[reg] by bit pos)
- 0x19b0-0x1b70: (see below)
- 0x1d18/0x1cc4/0x1da0: small funcs (gap region analysis pending)
- 0x25c4: emac_up / open (766 bytes, big) - ANALYSIS PENDING
- 0x2404 area: emac_mii (MDIO) - ANALYSIS PENDING

## FINAL CONSOLIDATED FINDINGS (session 2 - all cross-verified)

### MDIO block (regs 0x1a0/0x1a4, bus ops)
- 0x1a0 = MDIO command: bit15 = start/busy (poll until clear), bit10 = read op, bits9-5 = phy addr, bits4-0 = reg num
- 0x1a4 = MDIO data
- bus->read  = 0xc01914a2 (file 0x1894a2): [0x1a4]=0; [0x1a0]=0x8400|phy<<5|reg; poll bit15@0x1a0; return [0x1a4]
- bus->write = 0xc019142c (file 0x18942c): [0x1a4]=val; [0x1a0]=0x8000|phy<<5|reg; poll bit15@0x1a0
- both: spinlock [priv+8], dsb barriers, schedule/cancel delayed_work [priv+0x210] (0x7fffffff/-1)
- bus->reset = 0xc0191f40 (file 0x189f40 = slice 0x940, NOT gpio-init as previously guessed):
  parses "reset-gpio"(0xc03cb4f5)->[priv,0xf0]+active-low[priv,0xfc], "reset-delay-us"->[priv,0x10c],
  "mdio-reset"(0xc03cb500)->[priv,0xf4]+[priv,0xf8], "ldo-gpio"(0xc03c08fb); gpio_request; then bl 0x458
- mii_bus setup (probe): mdiobus_alloc_size(0) @0xffffd0e2 -> [priv,0x118]; name "emac mii"(0xc03ccddc)@+0;
  priv@+0x18; read@+0x1c=0xc01914a2; write@+0x20=0xc019142c; reset@+0x24=0xc0191f40; parent&pdev->dev@+0x44;
  irq[0]@+0x25c = &[priv,0x11c]; irq=-1@+0x258; of_mdiobus_register @0x5df98(bus, "mdio-bus" child node)

### emac_up (fcn.000025c4 @0x18bbc4, 766 bytes) - complete
- arg = priv; [priv,0x8c] = netdev; prints "----------%s-----------" with "emac_up"(0xc0361f3e)
- HW ver global [0xc04a393c]; strcmp "MD83X_N25"(0xc03ccea8) -> "phy-handle-2"(0xc03cceb2) else "phy-handle"(0xc03cceed)
- phy: of_phy_connect @0x5df10(netdev, node, 0xc0191755=emac_adjust_link, 0, iface); fail: "Could not attach to PHY"
- interface [netdev,0x6c0] (default 6=RGMII); set_interface fcn 0x1d18; pinctrl_select_state(rgmii-pins) if 6
- clk_phase_rgmii_set = fcn 0x1cc4 (arg2 = phydev->interrupts>0?1:0)
- phy_id check: (id-1)<=3 else "Not valid phy_id=0x%x"; attach print "%s:  %s: attached to PHY (UID 0x%x)..."
- [netdev,0x43c] = phydev; if phy_id==0x2430d80 -> bl 0x70(4,0) (PHY_CONNECT notifier)
- [priv,0xe8]==0 -> pm_runtime_enable(&pdev->dev) @0xfffaa9ce
- mod_delayed_work @0xffeab304(priv+0x1c0, [priv,0x260]); bl 0x1958(priv,1) then 0x1958(priv,0) (APMU bits)
- HW init (base=[priv,0xc4]): [0x104]=(x&~0x70)|0x9; [0x10]=0; [0x4]|=1; [0x20]=[priv,0x64];
  [0x108]|=0x49; [0x4]|=2; phy_start @0xffffbf1c(netdev->phydev)
- request_threaded_irq @0xffeb9e34([priv,0xd0]=irq10, 0xc0192e3f=emac_irq, 0, 0x80=IRQF_FORCE_RESUME, netdev, netdev)
  fail: "request_irq failed"; [priv,0xd4]=irq11 if set: (0xc019228d,0,0x80,...) fail: "request wakeup_irq failed" + free_irq
- [priv,0xcc] wakeup flags -> bl 0xfffffd50(priv) (wakeup enable)
- [base+0x1e4]=0; [base+0xc]=0xd5 (TX/RX enable full value); napi_enable: [priv,0x98]&=~1
- phy_id==0x2430d80 -> 0x70(6,0) else 0x70(1,0) (LINKUP notifiers)
- [netdev,0x1d0]+0x4c &=~1 (netif_start_queue)

### NAPI/IRQ identity
- netif_napi_add(netdev, napi@netdev+0x670=priv+0x90, 0xc0192ae4, 0x20) in probe @0x24a2
- emac_poll = 0xc0192ae4 (slice 0x14e4, file 0x18aae4) - the big IRQ/NAPI handler
- emac_irq = 0xc0192e3e (slice 0x183e, file 0x18ae3e) - reads [base+0x8] status, ack write-back
- wakeup irq handler = 0xc019228d (file 0x18928c)
- fcn 0x570 = emac_suspend (enable-suspend gate; wakeup bit2: 0x458+wakeup irq off [priv,0xd4] via 0xffeb9458;
  [base+0x100] &=~0x100/0x200 = magic/unicast wake bits; else netif_running -> napi dis [priv,0x98]&=~1)
- fcn 0x628 = emac_resume (mirror; gpio_set_value [priv,0xf0]/[priv,0xf4], [priv,0x98]|=2/|=1, 0xffe98c48(1))
- [priv,0x1b4] bit0 = suspend state flag (cpsid i guarded)

### RX ring (refill fcn file 0x189564 -> continues at slice 0x0)
- [priv,0x60] skb table (16-byte: +4 len bfi bits0-11, +8 dma), [priv,0x6c] count, [priv,0x70] idx,
  [priv,0x78] ring base; buf size [priv,0x0]=0x800 (probe: [netdev,0x5e0]=0x800)
- refill: skb = alloc 0x842 (2048+66 headroom); [desc+0]=skb; data+=0x42; [desc+0x10]=data; [desc+0x18]=0x800;
  dma@[desc+8] (64-bit); idx==count -> [desc+7]|=4 (wrap); [desc+3]|=0x80 (OWN, SW-set)

### Fixed-link parse (probe 0x2254 -> fcn 0xacc, complete)
- "managed"=="in-band-status"(0xc03ccd5d) -> skip; "fixed-link"(0xc03cc843) -> "full-duplex"(0xc03ccd6c)
  [sp,0x18]=1, "speed"(0xc03dc271)->[sp,0x20], "asym-pause"->[sp,0x24], "pause"->[sp,0x28]
- iface [netdev,0x6c0]: of_phy... fail -> "no interface for fix-link, use RGMII" [netdev,0x6c0]=6
- [netdev,0x6bc]=duplex, [netdev,0x6b8]=speed, fixed_phy_register @0xfffffd50(priv), "find fixed link", [netdev,0x6ac]=1

### Probe misc (final)
- 0xa2e7c = register_netdev; 0xfff67f90 = dev_set_name; 0xffffd146 = mdiobus_free
- watchdog setup fcn 0x1da0: [netdev,0x50]=0xc8, [netdev,0x6c]=0x5dc (gated on global [0xc0504590]>=0x8000)
- netdev ops/work: [netdev,0x858]=0xc019171d (work fn, file 0x18971c=slice 0x11c); [netdev,0x86c]=0xc0030f91;
  init work @netdev+0x848 (list head 0x850/0x854), fcn 0xffe98c5c(x, 2, 0xc0191e51)
- [netdev,0x618]/[0x61c] self-list; [netdev,0x614]=-0x20
- 0x2480: dma_set_mask path: [sl,0x150] of_node, ops 0xc04a8328 -> dma ops ptr (swiotlb/dma-direct)

## Open questions (resolved)
- MDIO read/write register details: 0x1a0 cmd (bit15 busy, bit10 read), 0x1a4 data - RESOLVED
- emac_up ring alloc/IRQ/phy start: complete above - RESOLVED
- set_io 3v3/1v8: AIB reg 0xd401e804 bit2 (0=3.3V,1=1.8V), unlock 0xd4015050 0xbaba/0xeb10 - RESOLVED
- clk_phase_rgmii_set APMU offsets: values tx-clk-config 0x203/rx-clk-config 0x803 via [netdev,0x788]/[0x78c],
  clk-tuning-enable -> [netdev,0x790]; reg writes still in fcn 0x1cc4 (APMU phy phase) - PARTIAL
- IP175D: phy id 0x2430d80, port redirect logic in start_xmit - noted (not needed for clean driver)

================================================================================
M2 DRIVER COMPLETION (2026-08-17 session)
================================================================================

Patch set for the clean-room EMAC driver (asr,asr-eth-v2):

  0006-net-ethernet-asr-Add-ASR1802S-EMAC-driver.patch  (34KB, new in fork)
     - drivers/net/ethernet/asr/{Kconfig,Makefile,asr-emac.c} (driver ~1044 lines)
     - wires drivers/net/ethernet/{Kconfig,Makefile} (after airoha)
     - includes DT binding yaml: Documentation/devicetree/bindings/net/asr,asr-eth-v2.yaml
     - checkpatch: 0 errors / 3 warnings (MAINTAINERS, binding-split convention,
       vendor help boilerplate - all benign)
     - Kconfig: NET_VENDOR_ASR (bool, depends ARCH_ASR || COMPILE_TEST),
       ASR_EMAC (tristate, selects PHYLIB/FIXED_PHY/OF_MDIO)
  0007-ARM-dts-asr-Wire-up-EMAC-pinctrl-MDIO-bus-and-vendor-props.patch
     - dtsi: pinctrl node -> pinctrl-single (#pinctrl-cells=2, register-width 32,
       function-mask 0x7), 5 vendor EMAC pin groups func0..func4; eth0 vendor props
     - r291 board: mdio-bus phy@0 ethernet-phy-id011a.c816
     - checkpatch: 0 errors, only expected generic-phy warning; dtc builds clean
  config-6.12: + CONFIG_NET_VENDOR_ASR=y, CONFIG_ASR_EMAC=y, CONFIG_PHYLIB=y,
     CONFIG_FIXED_PHY=y, CONFIG_OF_MDIO=y, CONFIG_MDIO_BUS=y,
     CONFIG_PINCTRL_SINGLE=y (lines 270-276)

Driver design (v1, register map from vendor 3.10.33 RE):
  - 1 TX + 1 RX ring, 64 desc each; 16-byte desc {status,len,flags,dma_lo,dma_hi};
    dma_lo/dma_hi split (bus = AXI DMA 40-bit); asr_emac_desc_dma() helper
  - NAPI weight 32; RX buf 0x800 + 0x42 headroom; OWN bit31, wrap bit2, first/last
    bit5/6; RX status bits 0-13 len, 14-28 status
  - fixed-link via phy_connect_direct or of_phy_connect; MDIO via mdiobus +
    of_mdiobus_register on "mdio-bus" child, optional reset-gpios (fsleep(10))
  - irq10 main + irq11 wakeup (both request_irq); IRQ disable during poll
  - io-sync helper uses dsb(sy) after every readl/writel (MAC on AXI, no posted
    writes tolerated per RE)
  - APMU/AIB IO level only when "asr,3v-enable" in DT (unlock 0xd4015050)
  - clk devm_clk_get_optional("emac"), pinctrl state "rgmii-pins" on RGMII
  - asr,mdio-clk-div default 0xfe; asr,reset-delays-us defaults [1]=100000
    [2]=500000; tx/rx clk-config 0x203/0x803 parsed+logged only (APMU phase
    regs still PARTIAL - see line "clk_phase_rgmii_set" above)

Verification status:
  - Patch 0006 applies clean (patch -p1) to linux-6.12.103; old kernel-tree git
    apply is unreliable (tree .git is a gitdir link to the fork repo -> "Skipped")
  - C stage verified: make ARCH=arm CC=gcc-arm-strip drivers/net/ethernet/asr/
    asr-emac.s -> 0 errors/warnings (-Werror). NOTE: only the .s (C) stage can be
    checked this way; the x86-64 assembler cannot assemble ARM inline asm (io.h
    readl/writel, dsb) so a full .o build is impossible without a real ARM
    cross-gcc. A previous "COMPILE-OK" with asr-emac.o was a false positive
    (make had nothing to do after an rm -rf).
  - DTB builds clean; content verified via dtc decompile (pinctrl phandles,
    asr props, fixed-link 1000/full, mdio-bus phy@0)
  - NOT yet done on hardware: real build + boot (no ARM toolchain in fork
    staging_dir; wrapper-built include/generated headers are x86-64-wrong and
    the tree must be re-prepared by OpenWrt before a real build)

Scratch: canonical driver at /tmp/opencode/kern3 (git repo base+1 commit;
base = pristine Kconfig/Makefile only). Patch regeneration: commit files,
git format-patch -1. The 0006 rebuild had a pitfall: if new files end up in
the BASE commit, format-patch loses them - keep base to only the two wiring
files.
