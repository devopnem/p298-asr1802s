#!/usr/bin/env bash
# RAM-boot a P298 with the OpenWrt image built from this tree.
#
# Writes NOTHING to flash. The kernel and DTB are pushed into DRAM over the
# board's USB gadget port and started with U-Boot's bootz.
#
# Prerequisites on the board (already done via SSH on a healthy unit):
#     fw_setenv autostart no
#     fw_setenv bootdelay 10
# then reboot and stop autoboot at the "Marvell>> " prompt, and from that
# prompt run:  fastboot
#
# This script is the HOST side: it waits for the device and pushes the image.
#
# Usage:
#   ./tools/ramboot.sh                     # default image and load address
#   ./tools/ramboot.sh --addr 0x0080000 IMAGE
set -euo pipefail

FORK=/home/void/Downloads/openwrt/openwrt-fork
IMAGE="$FORK/bin/targets/asr1802s/generic/openwrt-asr1802s-generic-asr1826s_p298-initramfs-kernel.bin"
ADDR=0x00008000

while [ $# -gt 0 ]; do
  case "$1" in
    --addr) ADDR="$2"; shift 2 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) IMAGE="$1"; shift ;;
  esac
done

[ -f "$IMAGE" ] || { echo "no image at $IMAGE" >&2; exit 1; }

SIZE=$(stat -c%s "$IMAGE")
printf 'image : %s\n' "$IMAGE"
printf 'size  : %d bytes\n' "$SIZE"
printf 'load  : %s  (end %s)\n' "$ADDR" "$(printf '0x%x' $((ADDR + SIZE)))"

# The appended DTB starts where the zImage ends; bootz wants that as the size.
DTB_OFF=$(python3 - "$IMAGE" <<'PY'
import struct, sys
d = open(sys.argv[1], 'rb').read()
print(d.rfind(struct.pack('>I', 0xd00dfeed)))
PY
)
printf 'dtb   : offset 0x%x (bootz size)\n\n' "$DTB_OFF"

echo "waiting for the board in fastboot mode (Ctrl-C to abort)..."
for i in $(seq 1 60); do
  if fastboot devices | grep -q fastboot; then
    fastboot devices
    break
  fi
  sleep 1
  [ "$i" = 60 ] && { echo "no fastboot device appeared" >&2; exit 1; }
done

echo
echo "downloading... (this is RAM only)"
fastboot download "$ADDR" "$IMAGE"

cat <<EOF

Now, at the U-Boot "Marvell>>" prompt:

    setenv bootargs "console=ttyS0,115200"
    md $ADDR 20
    bootz $ADDR $DTB_OFF

Do NOT use "fastboot boot" - it expects a boot image, and this is a raw
zImage with an appended DTB.

"md" should show the zImage header, not zeroes. If it shows zeroes the
transfer did not land and bootz will fail.
EOF