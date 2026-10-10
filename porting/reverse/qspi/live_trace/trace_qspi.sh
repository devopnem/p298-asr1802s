#!/bin/sh
# trace_qspi.sh — capture the ASR1802S QSPI register-access sequence from the
# LIVE stock router (vendor 3.10.33) via ftrace/kprobes. Non-destructive:
# read-only tracing + a NAND read/erase trigger. Run AFTER the router is
# physically reconnected (192.168.1.1, root/19222019).
#
# Technique B from docs/porting/BRINGUP_MILESTONES.md M1. Highest-confidence RE source for
# the exact QSPI register offsets + IP-command program order.
#
# Output: trace_qspi_<timestamp>.log saved locally (scp'd back).
#
# NOTE: requires root SSH with the legacy ciphers the dropbear on the box uses.

set -u

ROUTER=192.168.1.1
USER=root
PASS=19222019
SSH_OPTS="-o StrictHostKeyAlgorithms=+ssh-rsa -o KexAlgorithms=diffie-hellman-group14-sha1 -o HostKeyAlgorithms=+ssh-rsa -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o PreferredAuthentications=password -o PubkeyAuthentication=no"
SSH="sshpass -p $PASS ssh $SSH_OPTS $USER@$ROUTER"
SCP="sshpass -p $PASS scp $SSH_OPTS"

OUT="trace_qspi_$(date +%Y%m%d_%H%M%S).log"

run() { echo "# $*" >> "$OUT"; $SSH "$@" >> "$OUT" 2>&1; }

echo "=== QSPI live trace started $(date) ===" | tee "$OUT"

# --- 1. Capture kallsyms (gives exact qspi_* function addresses) ----------
echo "## /proc/kallsyms qspi_*" >> "$OUT"
$SSH "grep -E ' qspi|_qspi|spinand|pxa3xx_bbm' /proc/kallsyms" >> "$OUT" 2>&1

# --- 2. Enable ftrace on the qspi driver functions -------------------------
echo "## ftrace function_graph on qspi_*" >> "$OUT"
$SSH '
  ROOT=/sys/kernel/debug; TRACE=$ROOT/tracing
  if [ ! -d "$TRACE" ]; then echo "NO debugfs/tracefs"; exit 1; fi
  echo function_graph > $TRACE/current_tracer
  echo "qspi_*" > $TRACE/set_ftrace_filter
  echo "spi_nand_*" >> $TRACE/set_ftrace_filter
  echo "pxa3xx_bbm*" >> $TRACE/set_ftrace_filter
  echo 1 > $TRACE/tracing_on
'
sleep 1

# --- 3. Trigger a real SPI-NAND access (read a partition, then erase+rewrite
#        a harmless scratch block) so the trace captures the command flow. ---
echo "## trigger: read mtd0 (bootloader) + read NAND page via mtdchar" >> "$OUT"
$SSH 'dd if=/dev/mtd0 of=/dev/null bs=4096 count=8 2>&1; nanddump --bb=/dev/null /dev/mtd15 2>/dev/null | head -c 4096 >/dev/null; echo trigger-done' >> "$OUT" 2>&1
sleep 2

# --- 4. Stop trace + dump ---------------------------------------------------
$SSH 'ROOT=/sys/kernel/debug/tracing; echo 0 > $ROOT/tracing_on; cat $ROOT/trace' >> "$OUT" 2>&1

# --- 5. Also dump the controller register window via the vendor procfs ------
#     (driver prints "dump qspi register:" through procfs if available) ------
$SSH 'cat /proc/asr-qspi/dump 2>/dev/null || echo "no procfs dump"' >> "$OUT" 2>&1

echo "=== done; saved to $OUT ===" | tee -a "$OUT"
echo "Copy this file into porting/reverse/qspi/live_trace/ for analysis."
