#!/usr/bin/env bash
# One command, one action: start this, then power the board.
#
#   sudo tools/wtp-session.sh            # our own host, asks SelectImage directly
#   sudo tools/wtp-session.sh --tool host      # (default) same
#   sudo tools/wtp-session.sh --tool nopreamble
#   sudo tools/wtp-session.sh --tool vendor
#
# It does all of it: loads usbmon, starts a byte-level capture, waits for
# download mode, claims it inside the ~1.5 s window, runs the session, stops the
# capture, and prints both transcripts together. Nothing else for you to type.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLDIR="$REPO/flashing_tools/SWDownloader_5_0_0_2/binlinux"
BLF_BIN="$REPO/flashing_tools/p298-swd/BinFile.bin"
STAMP="$(date +%H%M%S)"
CAPTURE="/tmp/usbmon-$STAMP.txt"
SESSION="/tmp/session-$STAMP.txt"
TOOL="host"
NEXT="select"

while [ $# -gt 0 ]; do
  case "$1" in
    --tool) TOOL="$2"; shift 2 ;;
    --next) NEXT="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

[ "$(id -u)" -eq 0 ] || { echo "must run as root: sudo $0" >&2; exit 2; }
[ -r "$BLF_BIN" ] || { echo "missing $BLF_BIN" >&2; exit 2; }

# --- usbmon -----------------------------------------------------------------
modprobe usbmon 2>/dev/null || true
if [ ! -d /sys/kernel/debug/usb/usbmon ]; then
  mountpoint -q /sys/kernel/debug || mount -t debugfs debugfs /sys/kernel/debug 2>/dev/null || true
fi

CAPNODE=""
for n in /sys/kernel/debug/usb/usbmon/*u; do
  [ -e "$n" ] && CAPNODE="$n" && break
done
[ -n "$CAPNODE" ] && echo "capture: $CAPNODE" || echo "capture: unavailable (session still runs)"

if [ -n "$CAPNODE" ]; then
  ( cat "$CAPNODE" > "$CAPTURE" 2>/dev/null ) &
  CAP_PID=$!
  trap 'kill $CAP_PID 2>/dev/null' EXIT
fi

# --- the one thing you have to do -----------------------------------------
cat <<EOF

  ============================================================
   >>> POWER THE BOARD NOW  (off, then on -- power cycle)  <<<
  ============================================================
     download mode lasts ~1.5s and this script claims it
     automatically, so just cycle once when you see this.

EOF

run_session() {
  case "$TOOL" in
    host)       python3 "$REPO/tools/wtp-host.py" --next "$NEXT" --wait 90 ;;
    nopreamble) env LC_ALL=C LANG=C "$TOOLDIR/fbfdownloader-nopreamble" -b "$BLF_BIN" ;;
    vendor)     env LC_ALL=C LANG=C "$TOOLDIR/fbfdownloader" -b "$BLF_BIN" ;;
    *)          echo "unknown --tool $TOOL" >&2; return 2 ;;
  esac
}

run_session 2>&1 | tee "$SESSION"
STATUS=${PIPESTATUS[0]}

sleep 1
[ -n "$CAPNODE" ] && kill "$CAP_PID" 2>/dev/null
sleep 0.3

# --- results ----------------------------------------------------------------
echo
echo "==================== SESSION ===================="
cat "$SESSION"

if [ -s "$CAPTURE" ]; then
  echo
  echo "==================== USB WIRE ==================="
  echo "file: $CAPTURE   ($(wc -l < "$CAPTURE") lines)"
  echo "--- last 40 lines ---"
  tail -40 "$CAPTURE"
  echo
  echo "--- the critical moment: last preamble, if present ---"
  grep -E 'C (Bo|Bi):' "$CAPTURE" | tail -8
else
  echo "(no capture written)"
fi

echo
echo "session exit: $STATUS"
[ -n "$CAPNODE" ] && echo "capture: $CAPTURE"
echo "session: $SESSION"