# vsyscall=emulate — required by pre-5.3 Linux binaries

**Status:** solved 2026-10-16. Applies to this machine and, by inspection, to
any Void/systemd box where these tools are used.

## Symptom

Every Linux binary in `flashing_tools/SWDownloader_5_0_0_2/binlinux/` dies
immediately, before `main`, with no output:

```
swdl_linux, MakeDownloadPackage, tim_builder, fbfmake,
fbfdownloader, DownloadZipPackage      -> all SIGSEGV, all identical
```

Under gdb:

```
Program received signal SIGSEGV
0xffffffffff600000 in ?? ()
#0  0xffffffffff600000 in ?? ()
#1  0x000000000070d69d in ?? ()
```

## Not libc

Ruled out immediately:

```
$ ldd ./swdl_linux
ldd: ./swdl_linux: Not a valid dynamic program
$ readelf -d ./swdl_linux
There is no dynamic section in this file.
```

The binaries are fully static. No dynamic loader, no libc, no interpreter. So
musl vs glibc, and ia32 multiarch, are both irrelevant — and a container or
distrobox cannot change the outcome, because it shares the host kernel. That
is why the failure reproduces identically inside a lightbox podman distrobox.

## Cause

`0xffffffffff600000` is the **legacy x86-64 vsyscall page**. Offset 0 of that
page is `gettimeofday`.

The call site in `swdl_linux`:

```
70d690  48 83 ec 08                 sub  $0x8,%rsp
70d694  48 c7 c0 00 00 60 ff ff     mov  $0xffffffffff600000,%rax
70d69b  ff d0                       call *%rax
70d69d  3d 01 f0 ff ff              cmp  $0xfffff001,%eax
70d6a2  0f 83 08 d7 fa ff           jae  <error>
```

and its caller:

```
73db75  48 8d bc 24 c0 00 00 00     lea  0xc0(%rsp),%rdi   ; struct timeval *tv
73db7d  31 f6                       xor  %esi,%esi         ; struct timezone *tz = NULL
73db7f  e8 0c fb fc ff              call 0x70d690
```

That is `gettimeofday(tv, NULL)` written as a direct call into the vsyscall
page rather than through the libc symbol, with the standard `-errno` range
check (`>= -4095`) immediately after.

The immediate is `48 c7 c0` + a sign-extended imm32: `0xff600000` sign-extends
to `0xffffffffff600000`, which is why the disassembly looks like a nonsense
absolute address. It is not a bad relocation.

Since Linux 5.3 the default is `vsyscall=none`, which leaves the page
**unmapped**. Anything calling into it faults. Confirm:

```
$ grep vsyscall /proc/self/maps
(no output)
```

## Eight sites

`swdl_linux` has 7 `gettimeofday` and 1 `time` call site, all encoded as
`48 c7 c0 <imm32>`:

```
gettimeofday  0xff600000 -> 0x6536bc 0x65393a 0x6562bc 0x656af8
                             0x656c03 0x656d9a 0x70d694
time          0xff600400 -> 0x70d674
```

## Fix

Use `emulate`. Do **not** use `native` — that maps the page for real execution
and re-opens the Spectre window the default was introduced to close.

```sh
doas sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="loglevel=4 vsyscall=emulate"/' /etc/default/grub
doas grub-mkconfig -o /boot/grub/grub.cfg
# reboot
```

Verify after reboot:

```
$ grep vsyscall /proc/self/maps
ffffffffff600000-ffffffffff601000 r-xp 00000000 00:00 0        [vsyscall]
```

Confirmed working: `SWDL Version: 5.0.0.2 / SWDL Date: 2024-5-24` now starts
and prints its usage.

## Alternative, if rebooting is not acceptable

Patch the 8 sites to real syscalls instead. Each is the same 10-byte shape and
replaces in place with no size change:

```
48 c7 c0 00 00 60 ff ff     mov  $0xffffffffff600000,%rax
ff d0                       call *%rax
```

becomes

```
b8 60 00 00 00              mov  $0x60,%eax    ; __NR_gettimeofday = 96
0f 05                       syscall
90 90 90                    nop; nop; nop
```

and the `time` site at `0x70d674` uses `__NR_time = 201` (`0xc9 00 00 00`).
The `cmp $0xfffff001` that follows works unchanged, since the kernel returns
`-errno` in `rax`. Not implemented — the kernel parameter is one line and fixes
all eight sites at once — but recorded here so the option is not lost.

## Why it was worth chasing

Before this, the only route to 5.0.0.2 was running `SWDownloader.exe` under
Wine, which needs WinUSB to expose `2ecc:3002` to a Wine driver. The native
Linux binary talks to `/dev/bus/usb` directly and has the device in its
whitelist already:

```
2ecc:3001  2ecc:3002  2ecc:3003     all present, bcdDevice = 0xFFFFFFFF
```

plus `ASR1802S` as a native `Processor_Type` and an `ASR1802S platform type`
path, and the identity constants `06012014` / `3311` that 4.8.8.2 needed a
platform-enum patch to reach.