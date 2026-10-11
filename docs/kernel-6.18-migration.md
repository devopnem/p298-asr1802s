# Kernel 6.12 → 6.18 migration — status

Started 2026-10-11. Branch: `asr1802s-kernel-6.18` in the OpenWrt fork.

## Why

OpenWrt's default kernel is **6.18** (`target/linux/generic/kernel-6.18`,
currently `.55`, verified against `upstream/master` @ `baf6e53`). The
asr1802s target was pinned to 6.12.

There was also a concrete defect forcing the move: patch `0010` (the
reverse-engineered YT921x DSA driver) **could not apply on 6.12**, because its
`include/net/dsa.h` context expects `DSA_TAG_PROTO_MXL862`, which only exists
once OpenWrt's MxL862xx backports are applied — and OpenWrt ships those only
under `backport-6.18/`, not `backport-6.12/`.

> The MxL862xx backports do **not** mean this board has an MxL862 switch. See
> [`switch_topology.md`](switch_topology.md): only the Motorcomm YT9215RB is
> fitted and active. The backports matter only because they define the DSA tag
> numbers that 0010's context lines sit next to.

## How it was validated

Applied, in order, exactly as the real build does:

1. pristine `linux-6.18.55.tar.xz` (sha256 verified against upstream's
   `LINUX_KERNEL_HASH-6.18.55`)
2. `target/linux/generic/backport-6.18/*.patch` — 136/139 apply; the 3 failures
   are upstream's own already-applied patches (`706` mhi, `751` qca8k, `942`
   rtl8365mb) and are unrelated to this target
3. `target/linux/asr1802s/patches-6.18/*.patch`

21 hunks needed re-anchoring (17 exact-match, 4 with upstream context drift).
No `+`/`-` payload was altered — only `@@` headers — so no semantic difference
could be absorbed silently.

## Result: 13 of 14 patches apply

| # | Patch | Status |
|---|---|---|
| 0001 | vendor prefixes (`asr`, `notion`) | ✅ re-anchored |
| 0002 | SoC + board bindings | ✅ |
| 0003 | SoC dtsi + board DTS | ✅ |
| 0004 | `ARCH_ASR` + MAINTAINERS | ✅ re-anchored |
| 0005 | clock controller | ✅ re-anchored |
| 0006 | EMAC | ✅ |
| 0007 | EMAC pinctrl/MDIO wiring | ✅ |
| 0008 | QSPI binding | ✅ |
| 0009 | QSPI driver | ✅ re-anchored |
| 0010 | YT921x DSA | ✅ **previously broken on 6.12** |
| 0011 | YT9215 switch DTS | ✅ |
| 0012 | rtl8xxxu PCIe | ❌ **3 of 78 hunks** |
| 0013 | PCIe binding | ✅ |
| 0014 | PCIe host controller | ✅ re-anchored |

Changes made along the way:

- **0010** — `DSA_TAG_PROTO_MXL862_8021Q` exists in neither 6.12 nor
  6.18.55+backports; `MXL862` does after the backports. Dropped the
  non-existent context line from both hunks.
- **0001** — 6.18 added `"^nothing,.*"` between `nordic` and `novatek`, so the
  `notion` entry must be anchored after it.
- **0005** — upstream changed `obj-y += clk-of-pxa1928.o` to
  `obj-$(CONFIG_ARCH_MMP) +=` and added a PXA1908 block.
- **0004** — the `aspeed-video.txt` MAINTAINERS anchor became
  `aspeed,video-engine.yaml`.
- **0014** — 6.18 added `CONFIG_PCIE_STM32_HOST` at the anchor.

## The one blocker: 0012 (rtl8xxxu PCIe)

This is **not** line drift and cannot be mechanically re-anchored. 6.18 added
a `radio_idx` argument to several mac80211 callbacks, which changes the
function signatures patch 0012 has to de-`static` and export:

| callback | 6.12 | 6.18 |
|---|---|---|
| `get_antenna` | `(hw, u32 *tx, u32 *rx)` | `(hw, int radio_idx, u32 *tx, u32 *rx)` |
| `config` | `(hw, u32 changed)` | `(hw, int radio_idx, u32 changed)` |

Failing hunks: **#37** (`get_antenna` — upstream dropped the stray bare
`static` we were removing), **#62** (`remove_interface` + `config`, whose
signatures gained `radio_idx`), **#65** (`configure_filter`).

Fixing this means editing the patch body: thread `radio_idx` through the
exported wrappers and update the `ieee80211_ops` table in `rtl8xxxu_pcie.c`
to the 6.18 signature. That is a code change and should be done deliberately,
not by another automated pass.

## Also still to do

- `config-6.18` is the renamed `config-6.12`; it has not been re-validated
  against the 6.18 Kconfig (new/renamed symbols may be needed).
- No compile has been attempted yet — this is patch-application validation
  only. A real `make target/linux/compile` is the next step once 0012 is fixed.
- The `asr1802s-kagu-wip` branch (6.12) is untouched and still tracks PR
  #24614, so the PR is unaffected while this branch is in progress.