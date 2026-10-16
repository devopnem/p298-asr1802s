#!/bin/bash
# swd-diag-run.sh -- run swdl_linux once and capture EVERYTHING when it stalls.
#
# The stall is deterministic: five prior runs across four tool binaries, two
# payload sizes and two DKBs produced byte-identical 996-byte per-device logs.
# So we can afford a single expensive run that collects everything at the stall
# point, instead of one fact per run.
#
# Captures, at the stall:
#   1. full per-device WTP log + the tool's stdout
#   2. strace -ff of every thread   (which syscall blocks, and on which fd)
#   3. gdb backtrace of every thread + registers  (where in .text it is)
#   4. /proc/PID/{maps,status,cmdline,fds}          (image base for offsets)
#   5. lsusb -v for the board       (is it still sane?)
#
# Usage:  sudo tools/swd-diag-run.sh <path-to.blf> [stall-seconds]
#
# Leave the process running when it reports STALLED. Do not Ctrl-C it: if the
# stall is ever a false negative, the payload may still be flowing.

set -u

ROOT=/home/void/Downloads/Modems/Notion_P298_ASR1802S
BIN=$ROOT/flashing_tools/SWDownloader_5_0_0_2/binlinux
SWDL=$BIN/swdl_linux
OUT=/tmp/swd-diag
STAMP=$(date +%Y%m%d-%H%M%S)
RUN=$OUT/run-$STAMP

[ "$(id -u)" = 0 ] || { echo "must run as root (gdb attach needs it)" >&2; exit 1; }

# Resolve the BLF before touching anything else. A relative path under sudo has
# already cost one run: `[ -f ]` succeeded, `stat` failed a line later, and the
# download started against a path that did not exist. Pin it down hard, and
# make the failure loud instead of continuing.
mkdir -p "$OUT" || exit 1
cd "$ROOT" || { echo "cannot cd to $ROOT" >&2; exit 1; }

if ! BLF=$(readlink -f -- "${1:?usage: swd-diag-run.sh <blf> [stall-secs]}" 2>/dev/null); then
    echo "cannot resolve blf argument" >&2; exit 1
fi
if [ ! -r "$BLF" ]; then
    echo "FATAL: blf not readable: $BLF" >&2
    echo "  cwd was: $PWD" >&2
    echo "  args were: $*" >&2
    exit 1
fi
BLF_SIZE=$(stat -c%s -- "$BLF") || { echo "FATAL: stat failed on $BLF" >&2; exit 1; }
STALL_SECS=${2:-45}

mkdir -p "$RUN" || exit 1
cd "$BIN" || exit 1

echo "=== swd-diag run $STAMP ==="
echo "cwd  : $PWD"
echo "blf  : $BLF  ($BLF_SIZE bytes)"
echo "out  : $RUN"
echo

# --- 1. launch under strace -----------------------------------------------
# -ff  : one file per thread, so we see what each thread is blocked in
# -tt  : absolute timestamps, to correlate with the WTP log
# -T   : duration spent inside each syscall -- this is the money shot; a
#        read() that never returns tells us exactly which fd is dead
env LC_ALL=C LANG=C strace -ff -tt -T -s 256 \
    -o "$RUN/strace" \
    "$SWDL" -D "$BLF" -S -T 1800 -N >"$RUN/stdout.log" 2>"$RUN/stderr.log" &
SPID=$!
echo "strace pid $SPID, swdl_linux under it"

# Sample lsusb throughout. If the board resets or re-enumerates between the
# TIM-header stage and the payload, this is the only record of it -- the stall
# hypothesis says the tool may be waiting for a device event that never comes.
( while true; do
      printf '%s %s\n' "$(date +%H:%M:%S.%N | cut -c1-11)" \
          "$(lsusb | awk '/2ecc:/{printf "%s dev=%s", $6, substr($3,2)}')"
      sleep 2
  done > "$RUN/usb-timeline.txt" 2>&1 ) &
UPID=$!

# give it time to enumerate and hit the first transfer
sleep 20

# --- 2. watch the per-device log for the stall ----------------------------
WTPLOG=$(ls -t "$BIN"/wtp_dev_bus_usb_*.log 2>/dev/null | head -1)
[ -n "$WTPLOG" ] || { echo "FATAL: no per-device log appeared -- tool never opened the board"; exit 1; }
cp "$WTPLOG" "$RUN/wtp.log"
echo "wtp log: $(basename "$WTPLOG") ($(stat -c%s "$WTPLOG") bytes)"
echo "watching for ${STALL_SECS}s of no growth..."

LAST=$(stat -c%s "$WTPLOG")
STABLE=0
STALLED=0
while [ $STABLE -lt "$STALL_SECS" ]; do
    sleep 5
    NOW=$(stat -c%s "$WTPLOG" 2>/dev/null || echo "$LAST")
    if [ "$NOW" != "$LAST" ]; then
        echo "  log grew $LAST -> $NOW"
        LAST=$NOW; STABLE=0; STALLED=0
    else
        STABLE=$((STABLE + 5))
        [ $((STABLE % 15)) -eq 0 ] && echo "  quiet ${STABLE}s (size $NOW)"
        [ "$STABLE" -ge "$STALL_SECS" ] && STALLED=1
    fi
    kill -0 $SPID 2>/dev/null || { echo "tool exited on its own -- not a stall"; break; }
done

echo
if [ "$STALLED" = 1 ]; then
    echo "STALLED: log frozen at $LAST bytes for ${STALL_SECS}s. Capturing."
else
    echo "NOT confirmed stalled (or tool exited). Capturing anyway."
fi
cp "$WTPLOG" "$RUN/wtp.log"

# --- 3. the actual capture -------------------------------------------------
CPID=$(pgrep -x swdl_linux | head -1)
echo "swdl_linux pid: ${CPID:-none}"
[ -n "$CPID" ] || { echo "no live process to inspect"; exit 0; }

# per-thread CPU time -- zero across the board means blocked, not spinning
ps -o pid,tid,stat,time,wchan:20,comm -T -p "$CPID" > "$RUN/threads.txt" 2>&1
{ echo; echo "=== thread states (00:00:00 cpu everywhere == blocked) ==="
  cat "$RUN/threads.txt"; } | tee -a "$RUN/summary.txt"

gdb -q -batch -p "$CPID" \
    -ex "set pagination off" \
    -ex "set confirm off" \
    -ex "info threads" \
    -ex "thread apply all bt 30" \
    -ex "thread apply all info registers" \
    -ex "info sharedlibrary" \
    > "$RUN/gdb.txt" 2>&1
echo "gdb backtrace -> $RUN/gdb.txt ($(wc -l < "$RUN/gdb.txt") lines)"

# /proc: maps gives us the image base so .text addresses become file offsets
cp /proc/$CPID/maps "$RUN/maps.txt" 2>/dev/null
cp /proc/$CPID/status "$RUN/status.txt" 2>/dev/null
cp /proc/$CPID/cmdline "$RUN/cmdline.txt" 2>/dev/null
ls -l /proc/$CPID/fd > "$RUN/fds.txt" 2>&1
for t in /proc/$CPID/task/*; do
    tid=$(basename "$t")
    { echo "--- tid $tid ---"
      cat "$t/stat" 2>/dev/null | awk '{print "  state="$3}'
      cat "$t/syscall" 2>/dev/null | sed 's/^/  syscall: /'
      cat "$t/wchan" 2>/dev/null | sed 's/^/  wchan: /'
    } >> "$RUN/syscalls.txt" 2>&1
done
echo "proc snapshot -> maps/fds/syscall/threads"

# board state -- is it still enumerated and sane?
lsusb > "$RUN/lsusb.txt" 2>&1
BUSNUM=$(grep -o 'Bus [0-9]*' "$RUN/lsusb.txt" | head -1 | awk '{print $2}')
DEVNUM=$(lsusb | awk '/2ecc:/{print substr($3,2)}' | head -1)
if [ -n "$DEVNUM" ]; then
    lsusb -v -d 2ecc: > "$RUN/lsusb-verbose.txt" 2>&1
    echo "board still enumerated (dev $DEVNUM) -> lsusb-verbose.txt"
else
    echo "BOARD GONE from lsusb"
fi

echo
echo "=== files in $RUN ==="
ls -la "$RUN"
echo
echo "=== USB timeline (did the board reset / re-enumerate?) ==="
awk '{print} $2=="" {print "        (no board)"}' "$RUN/usb-timeline.txt"
kill $UPID 2>/dev/null
echo
echo "The tool is STILL RUNNING (pid $CPID). Do not kill it yet."
echo "Next: tools/swd-symbolize.py $RUN/gdb.txt $RUN/maps.txt"