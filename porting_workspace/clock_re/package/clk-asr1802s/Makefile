include $(TOPDIR)/rules.mk

PKG_LICENSE:=GPL-2.0-only
PKG_LICENSE_FILES:=

include $(INCLUDE_DIR)/kernel.mk
include $(INCLUDE_DIR)/package.mk

define KernelPackage/clk-asr1802s
  SUBMENU:=other
  TITLE:=Marvell ASR1802S Clock Controller
  DEPENDS:=+kmod-of-reserved-memory
  FILES:= $(PKG_BUILD_DIR)/clk-asr1802s.ko
  AUTOLOAD:=1
  KCONFIG:=CONFIG_COMMON_CLK_ASR1802S
endef

define KernelPackage/clk-asr1802s/description
  Clock controller driver for the Marvell ASR1802S (PXA1826) SoC.
  Reverse-engineered from vendor firmware; programs CPU/DDR/AXI clock
  dividers and PLL selections.
endef

define Build/Prepare
	mkdir -p $(LINUX_DIR)/include/dt-bindings/clock
	cp $(PKG_BUILD_DIR)/include/dt-bindings/clock/marvell,asr1802s.h \
		$(LINUX_DIR)/include/dt-bindings/clock/
	mkdir -p $(LINUX_DIR)/Documentation/devicetree/bindings/clock
	cp $(PKG_BUILD_DIR)/marvell,asr1802s-clock.yaml \
		$(LINUX_DIR)/Documentation/devicetree/bindings/clock/
endef

define Build/Compile
	$(MAKE) -C $(LINUX_DIR) M=$$(pkgparentdir) \
		ARCH=$(ARCH) CROSS_COMPILE=$(TARGET_CROSS) \
		$(KERNEL_MAKE_FLAGS) modules
endef

$(eval $(call KernelPackage,clk-asr1802s))
