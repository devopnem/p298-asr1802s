# gdb -batch -q -x tools/swdl-crash.gdb --args ./swdl_linux_p298_v8 -D <file>.blf -T 180 -N
#
# One run, everything needed to diagnose the stage-handover SIGSEGV.
#
# Why this exists: three crash-patch cycles on swdl_linux_p298_v{6,7,8} all
# produced a bare "Segmentation fault" from the shell, and two of those were
# the wrong address to reason about. Without the PC and the registers there is
# no way to tell a stale pointer from a null one, or a freed object from a
# merely-closed fd. This dumps all of it automatically.
#
# Output order is deliberate: PC and registers first (cheap, decisive), then
# the backtrace, then the object dump.

set pagination off
set confirm off
set print thread-events off
set backtrace past-main on

run

echo \n===== PC: instruction at the fault =====\n
x/4i $pc-8

echo \n===== REGISTERS =====\n
info registers eax ebx ecx edx esi edi ebp esp eip

echo \n===== BACKTRACE =====\n
bt 25

echo \n===== THREADS =====\n
info threads

echo \n===== FRAME 0 =====\n
frame 0
info args
info locals

echo \n===== FRAME 1 =====\n
frame 1
info args

# The faulting object. If the crash is the log FILE* at CWtpComm+0x638, the
# word at +0x638 is the whole story: 0x0 means a null comm pointer, anything
# else means a stale one.
echo \n===== esi: CWtpComm candidate =====\n
x/8xw $esi
echo ----- CWtpComm+0x424 (thread-exit flag) and +0x638 (log FILE*) -----\n
x/1xw $esi+0x424
x/1xw $esi+0x638
x/1xw $esi+0x640

# And the device, which DownloadImage reaches through ebx+0xc18.
echo \n===== ebx: _DEVICE candidate =====\n
x/4xw $ebx
x/1xw $ebx+0xc18