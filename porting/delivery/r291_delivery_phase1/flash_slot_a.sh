#!/bin/sh
# Flash slot-a only (mtd7, mtd13, mtd15) via SSH + mtderase
# Usage: ./flash_slot_a.sh <mtd7.rebuilt> <zImage> <rootfs>
set -e
if [ $# -ne 3 ]; then
  echo "Usage: $0 <mtd7.rebuilt> <zImage> <rootfs>"
  exit 1
fi
MTD7="$1"; ZIMAGE="$2"; ROOTFS="$3"
ROUTER="root@192.168.1.1"
SSHPASS="79476268"
SSHOPT="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o KexAlgorithms=diffie-hellman-group14-sha1 -o HostKeyAlgorithms=+ssh-rsa -o ConnectTimeout=5"
echo "=== Uploading to /tmp ==="
sshpass -p "$SSHPASS" scp $SSHOPT "$MTD7" "$ZIMAGE" "$ROOTFS" "$ROUTER:/tmp/"
sshpass -p "$SSHPASS" scp $SSHOPT /home/void/Downloads/Modems/Notion_R291_ASR1802S_P298_N13/r291_delivery_phase1/mtderase 2>&1 | head
if [ ! -f /home/void/Downloads/Modems/Notion_R291_ASR1802S_P298_N13/r291_delivery_phase1/mtderase ]; then
  echo "mtderase not found in delivery, using /tmp/mtderase on router if exists"
fi
echo "=== Flashing slot-a (mtd7, mtd13, mtd15) ==="
sshpass -p "$SSHPASS" ssh $SSHOPT "$ROUTER" '
  chmod +x /tmp/mtderase 2>/dev/null || true
  echo "mtd7..."
  /tmp/mtderase /dev/mtd7 /tmp/$(basename $MTD7) && echo "mtd7 ok" || { echo "mtd7 fail"; exit 1; }
  echo "mtd13..."
  /tmp/mtderase /dev/mtd13 /tmp/$(basename $ZIMAGE) && echo "mtd13 ok" || { echo "mtd13 fail"; exit 1; }
  echo "mtd15..."
  /tmp/mtderase /dev/mtd15 /tmp/$(basename $ROOTFS) && echo "mtd15 ok" || { echo "mtd15 fail"; exit 1; }
  sync
  echo "=== Verifying ==="
  hexdump -C /dev/mtd7ro | head -1
  hexdump -C /dev/mtd13ro | head -1
  hexdump -C /dev/mtd15ro | head -1
  echo "reboot in 3s..."
  sleep 3
  reboot
'
