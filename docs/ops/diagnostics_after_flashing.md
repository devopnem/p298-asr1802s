lspci -v
dmesg | grep -iE "pcie|rtl8xxxu|wlan"
iw dev
iw phy0 info    # RTL8192FR (2.4 GHz)

# Network
ip link show
brctl show
