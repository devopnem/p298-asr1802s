# SWDownloader 5.0.0.2 stalls before the payload — technical abstract

Written 2026-10-17 for outside consultation. Self-contained: nothing here
depends on the surrounding conversation. Every claim is marked **measured** (it
came from a run, a dump, or static analysis of the binary) or **inferred**
(reasoning that has not been confirmed).

---

## 1. The problem in one paragraph

`swdl_linux` from Marvell/ASR SWDownloader 5.0.0.2 opens a Notion P298 router
in USB download mode, negotiates the WTPTP protocol successfully, and transfers
the first image (a 248-byte FBF TIM header) to completion. It then issues a
control command, and **blocks forever waiting for a reply the device never
sends**. No payload has ever been transmitted. No run has ever written to the
board's flash.

## 2. Environment

| | |
|---|---|
| board | Notion P298, ASR1802S (Marvell PXA-class), ARM Cortex-A7 |
| USB IDs | `2ecc:3001`, `2ecc:3002`, `2ecc:3003` (board enumerates as `2ecc:3002`) |
| device string reported by tool | `Version: 3311  Date: 06012014  Processor: NZA3` |
| tool | `SWDownloader_5_0_0_2/binlinux/swdl_linux`, dated 2024-5-24 |
| tool build | statically linked, **stripped**, non-PIE `ET_EXEC`, x86-64 |
| host | Void Linux, kernel 6.18, glibc, `vsyscall=emulate` required |
| transport | `ioctl(fd, USBDEVFS_BULK, &bulk)` on `/dev/bus/usb/001/NNN` |
| protocol | Marvell WTPTP over USB bulk endpoints 0x01 (OUT) / 0x81 (IN) |

## 3. What works — measured

The tool's per-device log always reaches this exact state, byte for byte:

```
openUsbPort  m_fdUsb = /dev/bus/usb/001/020
GetTargetMessage after sendpreamble
GetWtpMessage... / WTPTP Notification: 0x0 / Platform ready status: 0
Version: 3311   Date: 06012014   Processor: NZA3
Begin DownloadImage...........
download file name is /tmp/SWD-XXXXXX/temp/FBF_Ntimheader.bin
Return flag in Dataheader CMD: 4, FDSwitch is 1, BufferSize is 0xF8
*******NOTE:: Fast Download is NOW activated!
Last Data
Download data finished
Completed DownLoad file: /tmp/SWD-XXXXXX/temp/FBF_Ntimheader.bin
Begin DownloadImage...........          <-- STALLS HERE, ALWAYS
```

So: device enumeration, WTPTP preamble, version query, the first image
transfer, Fast Download negotiation (buffer 248 B), and image completion all
succeed. 5.0.0.2 supports this board natively — `2ecc:3001/3002/3003` are
already in its USB whitelist and `ASR1802S` is a recognised platform type.

## 4. The stall — measured, in detail

### 4.1 Kernel-level

At the stall, the download thread is:

```
state = D (uninterruptible sleep)
wchan = usbfs_start_wait_urb
syscall = ioctl(fd=7, request=0xc0185502, arg=&bulk)
```

`0xc0185502` decodes as `_IOWR('U', 2, 24)` = `USBDEVFS_BULK`.

Reading the 24-byte `struct usbdevfs_bulktransfer` out of `/proc/PID/mem`:

| field | value | meaning |
|---|---|---|
| `ep` | `0x81` | **endpoint 1 IN** — the tool is *reading* |
| `len` | `38` | expecting a 38-byte WTPTP reply |
| `timeout` | `0` | **no timeout** — blocks indefinitely, cannot fail and retry |

### 4.2 Syscall sequence

Thread traces (via `strace -ff`), abbreviated, pointer values elided:

```
# --- initial handshake, on a different thread ---
USBDEVFS_CLAIMINTERFACE = 0
ioctl BULK = 4 ; 4 ; 8 ; 6            <- preamble / device type
   log: "Getting Version..."
ioctl BULK = 8 ; 6 ; 8 ; 30           <- 30 B = version block

# --- download thread, IMAGE 1 (FBF_Ntimheader.bin) ---
log "Begin DownloadImage..........."
ioctl BULK = 8 ; 10 ; 9 ; 6           <- GetVersion + SelectImage exchange
log "download file name is .../FBF_Ntimheader.bin"
ioctl BULK = 8 ; 6 ; 12 ; 10
log "Return flag in Dataheader CMD: 4,FDSwitch is 1,BufferSize is 0xF8"
log "Fast Download is NOW activated!"
ioctl BULK = 248                      <- the 248-byte TIM header payload
log "Last Data / Download data finished"
ioctl BULK = 8 ; 6 ; 8 ; 6
log "Completed DownLoad file: .../FBF_Ntimheader.bin"

# --- download thread, IMAGE 2 (FBF_h.bin, the real payload) ---
log "Begin DownloadImage..........."
ioctl BULK = 4                         <- device replies 4 B, not 8 B as in image 1
ioctl BULK = ...                       <- HANGS: ep 0x81, len 38, timeout 0
```

The notable asymmetry: **image 1's first reply is 8 bytes; image 2's is 4.**
After the 4-byte reply the tool issues a 38-byte read that never completes.

Also note the log line `download file name is ...` is **never emitted for
image 2**. The tool therefore dies *before it opens the payload file*.

## 5. Static analysis of the stall — measured

The binary hides most of its log strings, assembling them at runtime from
`movabs` immediates (so `strings` proximity analysis is useless — this is why
`Begin DownloadImage...........` cannot be found in the binary at all). Strings
that survive as `.rodata` literals were cross-referenced by scanning `.text` for
their 4-byte little-endian address.

Load base is 0 and `vaddr == file_offset + 0x400000`.

| `.rodata` string | xref in `.text` |
|---|---|
| `Getting Version...` | `0x51834e` |
| `download file name is %s` | `0x51843c` |
| `Download data finished` | `0x518e56` |
| `Completed DownLoad file: %s` | `0x518eaa` |
| `Begin to upload data from 0x%x to 0x%x to file %s` | `0x51bc67` |

`DownloadImage()` begins at `0x5181e0`. Its structure:

```asm
5181ec: mov  eax, [rsi+0xd78]
5181fc: cmp  eax, 1
5181ff: je   0x5185e0            ; alternate path, logs nothing
518205: lea  r12, [rsi+0x800]    ; build "Begin DownloadImage........."
...                             ;   from movabs immediates
51825c: call 0x517ab0            ; log write  <- last line ever emitted
518269: call 0x514200            ; walk image list at [+0x1ca8]
51827a: call 0x6d9870            ; jump-table dispatch
518297: call 0x5fded0            ; trivial setter
5182a8: call 0x400398            ; memset(buf, 0, 0x4006)
...
51834e: log "Getting Version..."
518357: call 0x6db920            ; (the GetVersion log)
518376: call 0x5ffdb0            ; wrapper -> "GetVersion command......"
51838a: call 0x6daef0            ; refcount/mutex, "lock cmpxchg"  <- CAN BLOCK
51839e: call 0x5ff970            ; wrapper -> "SelectImage command"
518416: call 0x6918c0            ; snprintf
518426: call 0x5ff800
51843b: mov  esi, 0x75e81f       ; "download file name is %s"
518445: call 0x6d9a30            ; NEVER REACHED
```

`0x5fe210` is the shared WTPTP command sender. Called by both `0x5ffdb0` and
`0x5ff970`; it formats a debug string such as `GetVersion command......\n` or
`SelectImage command\n`, builds a command header carrying `0x10` and `0x30` at
`[rsp+0x400]`/`[rsp+0x404]`, then waits for the reply.

`0x6daef0` performs `lock cmpxchg` against `(%fs:0x10)->0x8` — a
refcount/mutex that could block independently of the protocol.

**Conclusion (inferred, strongly supported):** the tool hangs while waiting for
the reply to the `GetVersion` or `SelectImage` WTPTP command, in a 238-byte
window between `0x518357` and `0x518445`.

## 6. Hypotheses already tested and eliminated

| variable | values tried | effect on the stall |
|---|---|---|
| tool version | 4.8.8.2, 5.0.0.2 | same location (crash vs deadlock) |
| payload size | 36 KB, 7.4 MB | none |
| DKB / OBM supplied | board's own `mtd0.bin` (262 KB), foreign Air720 Nezha loader (79 KB) | none |
| BLF content | mtd21-only, OpenWrt slot B, stock-content "null flash" | none |
| BLF image count | 3, 4, 5 enabled images | none |
| board reset | does the board re-enumerate? | **no — device stays enumerated throughout** |
| BootROM vs OBM session | — | tool reports `Open an BootLoader Device` |

The "null flash" case is worth calling out: a BLF whose payload is
**byte-identical stock data from a verified NAND dump**, structurally identical
to the real one, stalls at exactly the same place. Whatever the fault is, it is
not caused by the image content.

Wine + `SWDownloader.exe` does not expose `2ecc:3002` via WinUSB, so the Windows
GUI path is closed on this host.

## 7. Things known about the tool that may matter

- The downloader **constructs the FBF image list sorted by partition number
  DESCENDING**, not in BLF chain order. For a chain of
  `mtd12 → mtd14 → mtd16 → mtd19` it emits `mtd19, mtd16, mtd14, mtd12`. The A/B
  slot switch is therefore written **first**, so the switch must be flashed in a
  separate run to stay safe.
- `MakeDownloadPackage` regenerates the DTIM as **152 bytes containing no image
  digests** (`Trusted = 0`), while the stock DTIM partition holds 2,516 bytes of
  populated DDR and pin-mux settings. Writing the regenerated DTIM would destroy
  boot configuration.
- The tool opens a **netlink `NETLINK_KOBJECT_UEVENT` socket**
  (`bind(6, {AF_NETLINK, nl_groups=0x000001}, 12)`, `SO_RCVBUF` 262144) and
  blocks in `recvfrom()` on it for the whole session, watching for USB
  hotplug events. Strings `TerminateBL.....`, `please wait .....`,
  `Begin OpenUsbPort`, `init_hotplug_sock` exist (stack-built, no xrefs).
- USB transfer timeout is `0` — i.e. unbounded — on at least the control-command
  read path.
- Fast Download ("FDSwitch is 1") is negotiated when the tool's reply-length
  test passes, giving a 248-byte (`0xF8`) buffer size.

## 8. What we would like help with

1. **WTPTP `SelectImage` / `GetVersion` semantics.** What are the actual opcode
   bytes, the expected reply framing, and the correct host-side sequence *between*
   two image transfers in one session? Specifically: is a device reset or
   `TerminateBL` expected after an image completes?
2. **The 8-byte vs 4-byte reply asymmetry.** For image 1 the device's first
   reply is 8 bytes; for image 2 it is 4. What is a 4-byte WTPTP message —
   notification, NAK, or a short header? What should the host do with it?
3. **Fast Download carry-over.** Fast Download is enabled during image 1. Does
   the protocol require it to be disabled or renegotiated before the next
   image? Could a stale fast-download state explain the device going silent?
4. **`timeout = 0` on control reads.** Is that a tool bug, a deliberate
   "wait forever for the bootloader" choice, or configuration-driven? Any known
   field in the BLF that would make this bounded?
5. **BootROM vs OBM session lifetime.** The tool reports `Open an BootLoader
   Device` (not BootRom). Does a WTP session with the OBM survive the transfer
   of an FBF TIM header, or is the device expected to reset into a fresh session
   that the host must detect via hotplug?
6. **Is there a working reference BLF** for an ASR1802S/NZA3 (`NEZHA3` platform)
   device that we could diff against ours? Ours contains `TIMH` and `OBMI` both
   with `Enable = 0` (supplied, not written) plus 3 enabled `RAW` partitions.

## 9. Reproduction

Package: any BLF whose `Enable = 1` images total a few MB. The stock-content
null-flash variant reproduces identically.

```sh
sudo env LC_ALL=C LANG=C swdl_linux -D package.blf -S -T 1800 -N
```

Then power-cycle the board into download mode when prompted. The stall is
deterministic: byte-identical 996-byte per-device logs across every run.