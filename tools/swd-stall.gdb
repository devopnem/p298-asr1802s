# swd-stall.gdb -- trace the exact window where swdl_linux stops making progress.
#
# Used by tools/swd-live-gdb.sh, which attaches this to the process BEFORE the
# board is plugged in. That timing is the whole point:
#
#   swdl_linux finishes its setup, prints "Please plug your USB device", and then
#   blocks in recvfrom() on its netlink hotplug socket. All threads are in
#   interruptible sleep, so ptrace can stop them and gdb can attach.
#
# Once the board is plugged in, the download thread issues a USBDEVFS_BULK read
# with timeout = 0. If the board does not answer, that thread sits in
# uninterruptible sleep (D) inside usbfs_start_wait_urb. A task in D cannot be
# ptrace-stopped, so attaching then hangs forever -- which is why every previous
# gdb.txt was four lines ending at "[New LWP ...]".
#
# So we attach early and use hardware breakpoints to walk the code ourselves.
# Addresses come from static analysis of swdl_linux 5.0.0.2; see
# docs/recovery/SWD-v5-status.md. The binary is stripped, so these are raw
# addresses and the landmark table in tools/swd-symbolize.py is what turns the
# resulting frames back into names.
#
# Software breakpoints, not `hbreak`. Hardware breakpoints need four x86 debug
# registers and gdb reports "No hardware breakpoint support in the target" when
# it cannot read them over ptrace -- which is precisely the situation here, since
# attaching is the thing being attempted. Software breakpoints need only
# PTRACE_POKETEXT and are safe on this binary because it is non-PIE with fixed
# load addresses, so the addresses below are stable.
#
# All four sit inside the DownloadImage() stall window (0x5181e0 .. 0x518445).

set pagination off
set confirm off
set print thread-events off
set height 0
set width 0

set $hits = 0

# --- image boundary -------------------------------------------------------
# 0x51825c: the call that writes "Begin DownloadImage.........". It is the last
# log line ever emitted, so hitting it tells us a new image transfer started.
break *0x51825c
commands
  silent
  set $hits = $hits + 1
  printf "\n########## HIT %d: Begin DownloadImage  (0x51825c) ##########\n", $hits
  printf "pc=0x%lx\n", $pc
  bt 8
  x/4i $pc - 16
  printf "\n"
  continue
end

# --- GetVersion -----------------------------------------------------------
# 0x518376: call 0x5ffdb0, the wrapper that sends "GetVersion command......"
# through the shared WTPTP sender at 0x5fe210.
break *0x518376
commands
  silent
  set $hits = $hits + 1
  printf "\n########## HIT %d: GetVersion command  (0x518376) ##########\n", $hits
  bt 8
  x/6i $pc - 8
  printf "\n"
  continue
end

# --- SelectImage ----------------------------------------------------------
# 0x51839e: call 0x5ff970, the wrapper that sends "SelectImage command".
# This is the command the board is believed not to answer. The print that
# should follow it is "download file name is %s" at 0x518445.
break *0x51839e
commands
  silent
  set $hits = $hits + 1
  printf "\n########## HIT %d: SelectImage command  (0x51839e) ##########\n", $hits
  bt 8
  printf "--- return site ---\n"
  x/6i $pc - 8
  printf "\n"
  continue
end

# --- the print that never happens ----------------------------------------
# 0x518445: call 0x6d9a30 with esi = "download file name is %s". If this is
# never hit for image 2, the stall is confirmed to be upstream of it.
break *0x518445
commands
  silent
  set $hits = $hits + 1
  printf "\n########## HIT %d: download-file-name print  (0x518445) ##########\n", $hits
  bt 8
  printf "\n"
  continue
end

printf "=== breakpoints armed ===\n"
info breakpoints
printf "=== now power-cycle the board; gdb will log every hit to gdb-hits.log ===\n"
continue