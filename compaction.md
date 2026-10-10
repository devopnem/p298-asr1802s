Port OpenWrt to Notion R291 ASR1802S/ASR1826s LTE gateway by adding PCIe host controller driver (asr,pcie-kagu) for dual-port DesignWare PCIe to enable WiFi (RTL8812FE + RTL8192FR) and complete flashable image with minimal system (LuCI + SSH + Ethernet + WiFi)
Important Details
Device: Notion R291 ASR (ASR1802S SoC = ASR1826s P298 board) — ARMv7 Cortex-A7, 128 MiB RAM, 128 MiB SPI-NAND
PCIe: Dual-port DesignWare (asr,pcie-kagu) — Gen1 x1, ports at PHY 0xd4220000/0xd4210000, config 0xd428c000/0xd4288000, ICU IRQ 51/50
WiFi: RTL8812FE (5GHz, port 0) + RTL8192FR (2.4GHz, port 1) behind ASR bridges (1e5d:3002/1e5d:3001)
Build environment: distrobox Debian (openwrt-ci), NOT Void Linux — host toolchain issues fixed
Architecture: SoC = ASR1802S (same as ASR1826s), board = ASR1826s-r291 (P298); "1806s" was typo, correct is 1826s
Clock driver: Patch 0005 provides ASR1802S_CLK_PERIPH (9), ASR1802S_CLK_AXI (11)
Minimal test goal: SSH + Ethernet + WiFi (2.4GHz RTL8192FR) + kernel working; LuCI later
Work State
Completed
All 14 patches created and applying cleanly: DT bindings (0001, 0002, 0008, 0013), DTS (0003, 0007, 0011), clock (0005), EMAC (0006), QSPI (0009), DSA/YT9215 (0010, 0011), rtl8xxxu PCIe (0012), PCIe host driver + DT binding (0013, 0014)
Kernel compiles successfully with all drivers built-in: ASR EMAC, YT921X, PHY YT9215, RTL8XXXU (RTL8192FR), PCIe ASR KAGU, PCIe DW Host, MAC80211
Kernel config: CONFIG_ASR_EMAC=y, CONFIG_YT921X=y, CONFIG_PHY_YT9215=y, CONFIG_RTL8XXXU=y, CONFIG_PCIE_ASR_KAGU=y, CONFIG_PCIE_DW_HOST=y, CONFIG_MAC80211=y, CONFIG_WLAN_VENDOR_REALTEK=y
PCIe driver pcie-asr-kagu.c implemented as thin DW wrapper with PHY init, clock/reset handling, INTx/MSI interrupt handling
DT binding asr,pcie-kagu.yaml created with proper interrupt-map, clock references, child port nodes
Architecture clarification: target-aarch64_cortex-a53_musl in build_dir is host toolchain (host tools), NOT target — actual target is target-arm_cortex-a7_musl_eabi (32-bit ARMv7)
Active
make target/linux/install TARGET=asr1802s failing: rootfs directory root-asr1802s not created during package installation phase
Rootfs directory not populated — package installation step not running before target/linux/install
rtl8xxxu-firmware package doesn't exist as separate package; firmware is in linux-firmware package (rtlwifi/rtl8192fufw.bin present)
All kmod-* packages unnecessary since drivers are built-in (=y, not =m)
Blocked
make target/linux/install fails: root-asr1802s directory not created → rootfs not populated → squashfs generation fails
Need to ensure package installation populates root-asr1802s before target/linux/install runs
Full image generation blocked until rootfs builds successfully
Next Move
Build rootfs by running package installs first: make package/base-files/compile package/dropbear/compile package/uci/compile package/luci/compile package/luci-base/compile package/luci-theme-bootstrap/compile package/dropbear/compile package/rtl8xxxu-firmware/compile (note: rtl8xxxu-firmware may not exist as separate package; use linux-firmware instead)
Run make target/linux/install TARGET=asr1802s V=s to generate DTIM + rootfs + flashable images
If still failing, run make target/linux/install TARGET=asr1802s -j$(nproc) V=s to let dependency resolution handle order
For production: use openwrt-ci (distrobox/Debian) for reproducible builds
Relevant Files
target/linux/asr1802s/patches-6.12/0014-pci-asr-kagu-add-pcie-host-controller-driver.patch — PCIe driver + Kconfig + Makefile
target/linux/asr1802s/patches-6.12/0013-dt-bindings-pci-asr,pcie-kagu.yaml.patch — DT binding
target/linux/asr1802s/patches-6.12/0003-ARM-dts-asr-Add-ASR1802S-SoC-and-ASR1826s-R291-board.patch — DTS with PCIe node, clocks, interrupt-map
target/linux/asr1802s/config-6.12 — kernel config (PCI options enabled)
target/linux/asr1802s/image/Makefile — image build (needs pad-rootfs)
package/firmware/linux-firmware/ — contains rtlwifi/rtl8192fufw.bin for RTL8192FR
docs/flashing_and_failsafe_guide.md — updated with architecture note, build commands, failsafe plan
