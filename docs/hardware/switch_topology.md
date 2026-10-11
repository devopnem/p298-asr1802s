# Ethernet switch topology — which switch is actually fitted?

Established 2026-10-11 by decompiling the vendor DTB
(`findings/firmware-backup/vendor_dtb_extracted/vendor.dtb`, 2030 lines) and
cross-checking against a live kernel log
(`data/probes-raw/ssh_probe_2026_08_31/full_dmesg.txt`).

## Short answer

**Only the Motorcomm YT9215RB is present and active. The MxL862 is fitted on
the PCB but does nothing — it is never probed, and the mainline MxL862xx DSA
driver is not applicable to this board.**

This matters because it means patch `0010` (the reverse-engineered YT921x DSA
driver) is *necessary*, not redundant, and the upstream MxL862xx backports are
irrelevant to us.

## Evidence

### 1. The vendor DTB declares three candidate switch nodes

| Node | Compatible | Status | Runtime |
|---|---|---|---|
| `dsa@0` → `switch@0` | `marvell,dsa` | **`disabled`** | not used |
| `yt_switch` | `motorcomm,yt9215rb` | **`okay`** | **probed, active** |
| `rtk_switch@0` | `realtek,rtl8367rb` | **`okay`** | **never probes** |

Notes on each:

- **`dsa@0` is `disabled`.** It carries a complete DSA port description
  (`lan2`…`lan5`, `cpu` at `reg = <0x06>`, `dsa,ethernet = <0x30>`), but the
  vendor kernel does not use it — ASR used their own `yt_switch` driver
  instead. This node is the obvious template for our own DSA patch.

- **`yt_switch` is the live one.** It binds the same MDIO bus
  (`mii-bus = <0x31>`, i.e. the `mdio-bus` under `asr-eth`), with
  `PHY_ID = <0x00>` and a `reset-gpio` of GPIO 0x13.

- **`rtk_switch@0` claims `realtek,rtl8367rb` and shares the *same*
  `reset-gpio = <0x10 0x13 0x00>` as `yt_switch`.** Two switch nodes driving
  one reset line is not physically possible, so at most one can be real. And
  the string `rtl8367` appears **nowhere** in the kernel log — it is never
  probed. Treat it as vestigial.

### 2. The kernel log confirms only YT9215RB

```
[    2.372802] ==========yt9215rb_probe==========
[    2.372833] platform yt_switch.13: Driver yt9215rb requests probe deferral
[    2.373535] skbrb_init(0xc5200000): type: 0, slot size: 1600, slot cnt: 1000. Done.
...
[    3.044921] ==========yt9215rb_probe==========
[    3.636535] [yt9215rb_switch_init]
[    3.661987] ==========yt9215rb init success==========
...
[   10.686096] ytswitch: port 0 link up
[   11.958221] ytswitch port[1 2 3 ] link down/up
[   12.133789] ===>yt9215rb_sw_set_vlan_ports 250
[   12.134185] [yt9215rb_sw_set_vlan_ports] vid=1 , mem=20,untag=0,fid=0
[   12.139862] ===>yt9215rb_sw_set_vlan_ports 250
[   12.141662] [yt9215rb_sw_set_vlan_ports] vid=2 , mem=2f,untag=f,fid=0
```

Two VLANs are programmed: **VLAN 1** (untagged, membership `0x20` = ports 0
and 5) and **VLAN 2** (tagged, membership `0x2f` = ports 0–4).

### 3. No MxL862 activity anywhere

`mxl`, `sllu`, `gpy`, `862` return **no hits** in the kernel log. There is no
MxL862 probe, no tag-protocol registration, no PHY attach.

### 4. The `MxL SLLU3 / RPN42.08` chip marking

The marking is real — it is on the board photo — but nothing drives it. Two
possibilities:

- it is a populated-but-unused part, or
- it is the **MaxLinear SLIC** for VoIP, which *is* active under a different
  name (see below), and the `SLLU3` line on the PCB refers to that.

The kernel log does show an active SLIC:

```
[    2.288269] enter maxlinear_slic_probe.
[    2.36297] maxlinear-slic maxlinear-slic.12: slic chip powered on
[    8.467742] Telephony seems OK
```

`maxlinear-slic` is a **voice** IC, not an Ethernet switch. It is unrelated to
MxL862xx DSA. Do not confuse the two.

## Consequences for the OpenWrt port

1. **Patch `0010` (YT921x DSA) is required.** There is no upstream or
   OpenWrt-supplied driver for the Motorcomm YT9215RB; a search of
   `upstream/master` finds no `yt921x` driver anywhere. Our
   reverse-engineered driver is the only option.

2. **The MxL862xx backports do not help us.** OpenWrt ships 27 MxL862xx
   patches under `target/linux/generic/backport-6.18/`, but they target a
   different chip that is not wired up on this board.

3. **⚠️ Patch 0011's port labelling disagrees with the vendor DTB.** Our
   `0011-ARM-dts-add-YT9215-switch.patch` describes the switch as:

   | | ours (patch 0011) | vendor DTB `dsa@0` |
   |---|---|---|
   | labels | `lan1`,`lan2`,`lan3`,`lan4`,`wan`,`cpu` | `lan5`,`lan4`,`lan3`,`lan2`,`cpu` |
   | CPU port | `port@8` | `port@6` |
   | numbering | contiguous 0-4, plus 8 | 0-3, plus 6 (4 and 5 absent) |

   The vendor's numbering skips 4 and 5; ours invents a contiguous 0-4. **This
   should be reconciled against real hardware before the DSA driver is called
   working.**

   ### On the MDIO address — an earlier claim here was wrong

   An earlier revision of this note asserted that patch 0011's `switch@1d` /
   `reg = <0x1d>` was wrong, and that the vendor's `PHY_ID = <0x00>` proved the
   switch sits at MDIO address 0. **That does not follow.** Corrected:

   - `yt_switch` is **not a DSA node** in the vendor tree. It carries
     vendor-specific properties (`PHY_ID`, `wlan-port`) read only by ASR's own
     driver, and has **no `reg` at all** — it reaches the bus through
     `mii-bus = <0x31>`, the same MDIO bus as the `phy@0` node. Its
     `PHY_ID = <0x00>` is therefore not comparable to a DSA `reg`.
   - The vendor `phy@0` node is a different thing entirely: a generic
     `ethernet-phy-id011a.c816` RGMII PHY. At runtime the kernel reports
     `mdio_bus ...: cannot get PHY at address 0` — nothing answered there.
   - `skbrb_init(0xc5200000)` in the boot log is a **RAM** address, not an MDIO
     address; it belongs to the driver's packet-slot allocator.
   - The EMAC MDIO command register does encode a 5-bit PHY address (bits 9-5,
     i.e. 0-31), so `0x1d` is representable and is a plausible real address for
     a YT9215RB — it is the address the common upstream-style YT921x DSA
     bindings use.

   So **`0x1d` is not disproven**; it is simply **unverified** in our own data,
   because we never captured the switch's MDIO response. Settling it needs one
   MDIO read of the switch's ID registers on live hardware. Do not change it on
   the strength of the vendor DTB alone.

4. **The `mdio_bus ... cannot get PHY at address 0`** message in the log is a
   red herring for our purposes: the vendor binds its switch through its own
   driver on the same MDIO bus rather than through a generic PHY node, and
   does not care that the generic probe fails.

## How to settle the two open items on hardware

Both need a live unit and a serial console; neither needs a full flash dump.

**1. Confirm the switch's MDIO address.** Scan the bus rather than trusting
either source. From a root shell on the stock firmware:

```sh
# the vendor EMAC exposes an MDIO bus; brute-force the ID registers.
# YT921x family reports its chip id in SMI registers 0x0000-0x0003,
# reachable via the standard phy_mii_read path.
for a in $(seq 0 31); do
  id=$(mdio-read "$a" 0x2 2>/dev/null)
  [ -n "$id" ] && echo "addr $a  id=0x${id}"
done
```

Expect the YT9215RB to answer on a single address (0x1d is the value our patch
assumes). Anything else means 0011 needs correcting.

**2. Confirm port labels and the CPU port index.** The vendor's own DSA node
says ports 0-3 = `lan5..lan2` and CPU = port 6. Verify by watching link events
per port:

```sh
cat /proc/net/dev          # or: ip -br link
# then, from the stock firmware's own logs:
dmesg -w | grep -i ytswitch
```

`ytswitch: port N link up/down` gives the authoritative mapping. Bring each
physical port up in turn and note which `N` it reports.

Until both are measured, patch 0011's DSA description is a best-effort guess
and should be presented as such upstream.

## Open question

Whether the unused MxL862 is fitted on *all* P298 variants or only some. The
board photo and DTB agree it exists, but nothing uses it. Not blocking.