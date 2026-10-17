#!/bin/bash
# swd-live-gdb.sh -- watch swdl_linux walk into the stall, in real time.
#
# The problem this solves: once the download thread issues a USBDEVFS_BULK read
# that the board never answers, it sits in uninterruptible sleep (D) inside
# usbfs_start_wait_urb. A task in D cannot be ptrace-stopped, so gdb attaching
# at that point hangs forever. Every gdb.txt captured so far ended at
# "[New LWP ...]" for exactly that reason.
#
# The way around it is timing. Before the board is plugged in, swdl_linux has
# printed "Please plug your USB device" and is blocked in recvfrom() on its
# netlink hotplug socket -- all threads interruptible, fully stoppable. So:
#
#   1. launch the tool
#   2. attach gdb NOW, while it is still waiting for a device
#   3. arm hardware breakpoints across the stall window
#   4. hand control back so you can power-cycle the board
#   5. gdb logs every breakpoint hit with a backtrace, live
#
# No strace. gdb and strace contend for the ptrace slot, and here gdb wins by
# default. Syscall detail comes from /proc/PID/task/*/syscall, which needs no
# ptrace at all.
#
# Usage: sudo tools/swd-live-gdb.sh <path-to.blf> [stall-secs]
#
# Ctrl-C stops gdb and the tool. Nothing is written to the board until the
# payload stage is reached, and no run has ever reached it.

set -u

BLF_ARG=${1:?usage: swd-live-gdb.sh <blf> [stall-secs]}
STALL_SECS=${2:-60}

ROOT=/home/void/Downloads/Modems/Notion_P298_ASR1802S
BIN=$ROOT/flashing_tools/SWDownloader_5_0_0_2/binlinux
SWDL=$BIN/swdl_linux
GDB_SCRIPT=$ROOT/tools/swd-stall.gdb
OUT=/tmp/swd-diag
STAMP=$(date +%Y%m%d-%H%M%S)
RUN=$OUT/live-$STAMP

[ "$(id -u)" = 0 ] || { echo "must run as root (gdb attach needs it)" >&2; exit 1; }
[ -f "$GDB_SCRIPT" ] || { echo "missing $GDB_SCRIPT" >&2; exit 1; }

mkdir -p "$OUT" || exit 1
cd "$ROOT" || exit 1

if ! BLF=$(readlink -f -- "$BLF_ARG" 2>/dev/null); then
    echo "cannot resolve: $BLF_ARG" >&2; exit 1
fi
if [ ! -r "$BLF" ]; then
    echo "FATAL: blf not readable: $BLF" >&2
    echo "  cwd was: $PWD" >&2
    exit 1
fi
BLF_SIZE=$(stat -c%s -- "$BLF") || exit 1

mkdir -p "$RUN" || exit 1
cd "$BIN" || exit 1

# Record which per-device logs already exist. Only one created after this
# launch tells us anything; an earlier run's 996-byte leftover must never be
# mistaken for this run stalling.
START_EPOCH=$(date +%s)

echo "=== swd-live-gdb $STAMP ==="
echo "cwd : $PWD"
echo "blf : $BLF  ($BLF_SIZE bytes)"
echo "out : $RUN"
echo

# --- pre-flight: refuse to run beside a stale instance ---------------------
# swdl_linux takes a lock file and refuses to start a second copy, printing
# "there is already an swdl_inux is running, you can't run it again." The
# failure is silent from the harness's point of view -- the tool exits, but
# `pgrep -x swdl_linux` still finds the OLD process, so the harness happily
# attaches gdb to the previous run. That process already has a thread in D, so
# the attach hangs and the whole exercise produces nothing.
#
# Hence: check before launching, and never trust pgrep to identify our process.
STALE=$(pgrep -x swdl_linux || true)
if [ -n "$STALE" ]; then
    echo "FATAL: swdl_linux is already running:" >&2
    ps -o pid,etime,stat,args -p "$(echo "$STALE" | tr '\n' ',' | sed 's/,$//')" >&2
    echo >&2
    echo "  Each stalled run leaves one behind holding the lock. Stop them with:" >&2
    echo "      sudo pkill -x swdl_linux" >&2
    exit 1
fi

# A stale strace still holds a ptrace slot. It does not block this run, but it
# is worth surfacing rather than accumulating unnoticed.
if pgrep -x strace >/dev/null 2>&1; then
    echo "note: stale strace processes are still around (they hold ptrace slots):"
    pgrep -a -x strace | sed 's/^/    /'
fi

# The tool's lock is a pid file in its own directory. If a previous run was
# killed rather than exited, the file outlives the process and the next launch
# reports "lock is acquired by pid NNNNN" for a pid that no longer exists.
LOCK=$BIN/swdlinux.pid
if [ -f "$LOCK" ]; then
    LOCKPID=$(tr -dc '0-9' < "$LOCK" 2>/dev/null)
    if [ -n "$LOCKPID" ] && ! kill -0 "$LOCKPID" 2>/dev/null; then
        echo "removing stale lock file $LOCK (pid $LOCKPID is gone)"
        rm -f "$LOCK"
    fi
fi

# --- launch ---------------------------------------------------------------
# Process substitution rather than a pipe to tee: with `cmd | tee`, $! is tee's
# pid, not swdl_linux's, and the only way to identify the process is pgrep --
# which cannot tell ours from a stale one.
env LC_ALL=C LANG=C \
    "$SWDL" -D "$BLF" -S -T 1800 -N \
    > >(tee -a "$RUN/stdout.log") \
    2> >(tee -a "$RUN/stderr.log" >&2) &
SWPID=$!
sleep 2

# Identify the process by the pid we launched, and confirm it is alive and is
# actually swdl_linux rather than a shell that has already exited.
CPID=$SWPID
if ! kill -0 "$CPID" 2>/dev/null; then
    echo "FATAL: swdl_linux (pid $CPID) exited immediately. stdout:"
    tail -20 "$RUN/stdout.log"
    echo
    if grep -q "already an swdl_inux is running" "$RUN/stdout.log"; then
        echo "It refused to start: another copy holds the lock."
        echo "Stale instances:"; pgrep -a -x swdl_linux
    fi
    exit 1
fi
echo "swdl_linux pid $CPID (launched by us)"
ps -o pid,etime,stat,args -p "$CPID" | tail -1

# Wait for the tool to reach its "waiting for a device" state. Until it has
# opened the board, every thread is in interruptible sleep and therefore
# stoppable. Attaching now is the only window where gdb will work at all.
echo "waiting for the tool to arm its device wait..."
READY=0
for _ in $(seq 1 30); do
    if grep -q "Please plug your USB device" "$RUN/stdout.log" 2>/dev/null; then
        READY=1
        break
    fi
    sleep 1
done
if [ "$READY" != 1 ]; then
    echo "warning: never saw the device prompt; attaching anyway"
else
    echo "tool is waiting for a device -- good, that is the window we need"
fi

# --- attach, armed, while the board is still absent ------------------------
gdb -q -batch -p "$CPID" -x "$GDB_SCRIPT" > "$RUN/gdb-hits.log" 2>&1 &
GPID=$!
sleep 5

# Judge success by whether the breakpoints were armed, not by whether gdb is
# still alive. If the board is already in download mode the device is detected
# immediately, a breakpoint fires within these five seconds, and any error in
# the hit handler takes gdb down. Calling that "exited immediately" hid the fact
# that a hit had already been recorded and was worth reading.
if grep -q "breakpoints armed" "$RUN/gdb-hits.log"; then
    HITS=$(grep -c "^########## HIT" "$RUN/gdb-hits.log" || true)
    if kill -0 $GPID 2>/dev/null; then
        echo "gdb attached and armed (4 breakpoints)"
    else
        echo "gdb armed the breakpoints but has since exited; $HITS hit(s) recorded."
        echo "Those hits are still valid -- read gdb-hits.log."
    fi
else
    echo "FATAL: gdb never armed the breakpoints. gdb-hits.log:"
    cat "$RUN/gdb-hits.log"
    echo
    echo "If it says 'already traced', another debugger is attached."
    exit 1
fi

echo
echo "############################################################"
echo "#  gdb is attached and armed."
echo "#"
echo "#  Have the board POWERED OFF or UNPLUGGED until now."
echo "#  >>> POWER-CYCLE IT NOW <<<"
echo "#"
echo "#  If it was already in download mode when this started, the"
echo "#  early breakpoints may have been missed. Unplug it and"
echo "#  re-run if the hit list looks incomplete."
echo "#"
echo "#  Watch:  sudo tail -f $RUN/gdb-hits.log"
echo "############################################################"
echo

# --- watch ----------------------------------------------------------------
WTPLOG=""
STABLE=0
LAST=0
DEADLINE=$((SECONDS + 900))

while [ $SECONDS -lt $DEADLINE ]; do
    sleep 5

    if [ -z "$WTPLOG" ]; then
        for f in "$BIN"/wtp_dev_bus_usb_*.log; do
            [ -e "$f" ] || continue
            [ "$(stat -c%Y "$f")" -ge "$START_EPOCH" ] || continue
            WTPLOG=$f
            break
        done
        [ -n "$WTPLOG" ] && echo "device opened: $(basename "$WTPLOG")"
        continue
    fi

    NOW=$(stat -c%s "$WTPLOG" 2>/dev/null || echo "$LAST")
    if [ "$NOW" != "$LAST" ]; then
        echo "  $(basename "$WTPLOG") $LAST -> $NOW"
        LAST=$NOW
        STABLE=0
    else
        STABLE=$((STABLE + 5))
        [ $((STABLE % 30)) -eq 0 ] && echo "  quiet ${STABLE}s at $NOW bytes"
        if [ "$STABLE" -ge "$STALL_SECS" ]; then
            break
        fi
    fi

    kill -0 $CPID 2>/dev/null || { echo "tool exited"; break; }
    kill -0 $GPID 2>/dev/null || { echo "gdb exited"; break; }
done

echo
cp "$WTPLOG" "$RUN/wtp.log" 2>/dev/null
cp "/proc/$CPID/maps" "$RUN/maps.txt" 2>/dev/null
ps -o pid,tid,stat,time,wchan:22,comm -T -p "$CPID" > "$RUN/threads.txt" 2>&1
ls -l "/proc/$CPID/fd" > "$RUN/fds.txt" 2>&1

{
    echo "=== thread states ==="
    cat "$RUN/threads.txt"
} > "$RUN/summary.txt" 2>&1

# Decode the outstanding bulk transfer. Needs no ptrace.
python3 - "$CPID" > "$RUN/bulktransfer.txt" 2>&1 <<'PY'
import glob, os, struct, sys
pid = sys.argv[1]
mem = None
for t in sorted(glob.glob(f"/proc/{pid}/task/*")):
    tid = os.path.basename(t)
    try:
        sc = open(f"{t}/syscall").read().split()
        wch = open(f"{t}/wchan").read().strip()
    except OSError:
        continue
    if not sc or sc[0] in ("running", "-1"):
        print(f"tid {tid}: wchan={wch} (not in a syscall)")
        continue
    num = int(sc[0])
    print(f"tid {tid}: syscall {num}  wchan={wch}")
    if num == 16 and len(sc) >= 3:
        code = int(sc[2], 16) if len(sc) > 2 else 0
        if (code >> 8) & 0xFF == 0x55 and code & 0xFF == 2 and len(sc) > 3:
            a = int(sc[3], 16)
            if mem is None:
                try:
                    mem = open(f"/proc/{pid}/mem", "rb", buffering=0)
                except OSError as e:
                    print(f"    cannot open /proc/{pid}/mem: {e}")
                    break
            try:
                mem.seek(a); b = mem.read(24)
                ep, ln, to = struct.unpack("<III", b[:12])
                d = "IN (tool reading)" if ep & 0x80 else "OUT (tool writing)"
                print(f"    USBDEVFS_BULK @0x{a:x}: ep=0x{ep:x} endpoint {ep & 0x7f} {d}")
                print(f"      len={ln}  timeout={to} ms" +
                      ("   <-- NO TIMEOUT" if to == 0 else f"  ({to/1000:.1f}s)"))
            except Exception as e:                            # noqa: BLE001
                print(f"    read failed: {e}")
PY

echo "=== bulk transfer ==="
cat "$RUN/bulktransfer.txt" 2>/dev/null
echo
echo "=== gdb breakpoint hits ==="
cat "$RUN/gdb-hits.log" 2>/dev/null
echo
echo "=== files in $RUN ==="
ls -la "$RUN"
echo
echo "gdb is still attached (pid $GPID) and the tool is still running (pid $CPID)."
echo "Read the trace with:  tools/swd-symbolize.py $RUN/gdb-hits.log $RUN/maps.txt"
echo "Stop both with:       sudo pkill -f swd-live-gdb; sudo pkill -x swdl_linux"