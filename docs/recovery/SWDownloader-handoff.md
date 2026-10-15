# Handoff brief — SWDownloader USB window on Notion P298 / ASR1802S

Self-contained. Written to be handed to another engineer or AI agent with no
access to this conversation. Every claim below is either measured or marked
unverified.

---

## 1. The problem, in one paragraph

A Notion P298 router (Marvell PXA1802 / "NEZHA", ASR1802S) will not boot: it
initialises DDR, identifies the NAND, starts U-Boot 2014.01, then goes silent
because mtd0 (the OBM) passes `quiet=1` and `bootcmd=mrvlboot` runs and never
returns. **Nothing is flash-corrupt.** The goal is a U-Boot shell.

The obvious route is Marvell/ASR SWDownloader over USB. That route is now
working **through the full handshake** — device found, opened, preamble
accepted, identity read, first image transferred — and then aborts. This
brief is about that last obstacle.

> **UPDATE 2026-10-14 (third pass)** — **the "1.58 s USB window" does not
> exist.** A live run showed the board appearing and *never disappearing*;
> `lsusb` still listed it 22 minutes later. See **§11h**, which invalidates
> the premise this document was built on and re-traces `remove DevName:` to a
> detect-thread re-check rather than a disconnect. §11's chunk-size work
> stands on its own; the window argument around it does not.

> **UPDATE 2026-10-14 (second pass)** — two facts were found that change the
> shape of the problem, both verified offline against the vendor's own
> `MakeDownloadPackage` oracle plus disassembly of `swdl_linux`.  **§11 has the
> procedure.**  In short: `Dkb.bin` is byte-for-byte the OBMI image file with a
> 4-byte `IBKD` tag, `*_Image_Enable = 0` means "supply this file but do not
> write it to flash", and "Fast Download" is unreachable dead code in 4.8.8.2.
> The remaining lever on the 248-byte channel is the chunk size, which is
> patched by `tools/swdl-chunksize-patch.py`.

## 2. Device facts (measured)

| property | value |
|---|---|
| SoC | ASR1802S, PXA1802, tool reports `NEZHA platform type` |
| OBM strings in `mtd0.bin` | `OBM 4.9.0.0 for %s`, `SWDownloader 4.9.0.5 for %s` |
| OBM build date | `-- Apr 11 2024 - 18:25:10 --` |
| Flash | 128 MiB SPI-NAND, part `F35UQA001G`, mfr `0xCD`, 25 MTD partitions |
| Download-mode USB ID | **`2ecc:3002`**, product `KSTR`, manufacturer `ASR` |
| Enumeration lifetime | **unbounded** — still enumerating 22 min after a run (§11h) |
| Host | Linux x86-64, Void, `swdl_linux` needs root |

`mtd0` also contains `[Non-Prod]Wait for download...`, `[PROD]Don't enum USB
port`, `USB Enum timeout`, `User force to download`, and
`Wait for download change timeout to true...`.

## 3. What works today

Verified working, in order of discovery:

1. **`.blf` format solved.** See `findings/tooling/blf/p298_fixed.blf`. The
   blocker was our own bug: `*_Image_Image_ID` is parsed as an **integer**, so
   `1_Image_Image_ID = OBMI` reads as 0. Must be hex: `0x4F424D49`. Two more:
   `Erase_Size` must be ≥ the image file size, and two enabled images must not
   share a `Flash_Entry_Address`.

2. **VID/PID whitelist patched.** `CBulkDevNonDrv_Linux::ChecHWIds` at
   `0x0813b220` walks a stride-12 `{vid,pid,bcdDevice}` array at va
   `0x083D72E0`, file offset `0x38e2e0`, via the global at `0x08337304`. 30
   entries, all `0x8086` or `0x1286`. `0x2ECC` absent. Patched by replacing the
   last entry: **4 bytes**, data only, `.text` unchanged.

3. **Platform enum forced.** `GetDeviceBootType` rejects the identity with
   `cmp DWORD PTR [esi+0x1c4c],0x12; jbe ok; else "Unknown platform type"`.
   Forced to a valid index `0x12`: **6 bytes** in `.text`,
   `mov eax,[esi+0x1c4c]` → `mov eax,0x12; nop`.

With both patches the log reaches:

```
openUsbPort  m_fdUsb = /dev/bus/usb/001/031....
 GetTargetMessage after sendpreamble
 Platform ready status: 0
Version: 3311
Date: 06012014
Processor: NZA3
Open an BootRom Device
Get type of device successfully
Open device successfully
Enter into WTPTPDownLoad
download file name is .../temp/DKB_ntimheader.bin
Completed DownLoad file: .../temp/DKB_ntimheader.bin
Begin DownloadImage...........
Sending Preamble...
remove DevName:...            <-- device gone
```

The board speaks the protocol correctly. Reproduced consistently.

## 4. The actual obstacle

> **CORRECTION (2026-10-14).** Earlier versions of this brief blamed a
> "1.58 second USB window" measured by a 50 Hz sysfs poller. **That was a
> measurement artefact and every conclusion drawn from it was wrong.**
> dmesg from a clean run shows no disconnect at all:
>
> ```
> [235613.844441] usb 1-1: USB disconnect, device number 37   <- the PREVIOUS instance
> [235617.260320] usb 1-1: new high-speed USB device number 38 using xhci_hcd
> ```
>
> There is no `USB disconnect, device number 38` anywhere in the log. Device 38
> enumerated once and stayed on the bus for the rest of the run. **There is no
> timing budget.** Nothing about round-trip budgets, fitting a payload into a
> deadline, or shrinking the DKB to make it land in time applies.
>
> A second tool, `tools/swdl-budget.py`, built to measure the window at 200 Hz
> reported `USB window : nan ms (disappear still present)` — it never observed
> a disappearance. That contradicted the poller's 1.58 s figure at the time and
> was the clue that the window did not exist.

The DKB stage is now known to work. With the 4096-byte chunk override
(`tools/swdl-chunksize-patch.py`) the 79,928-byte DKB transferred in its
entirety — the first complete DKB transfer achieved on this board. Every
earlier attempt died inside it.

The live blocker is **one stage later** and is a bug in `swdl_linux`, not a
property of the board. See §4d.

### 4a. What the chunk size actually is (disassembly, verified)

`CWtptpDownLoad::DownloadImage` (`0x08132f90`, 4,197 bytes) runs this loop per
image:

```
0813382a  mov  ecx,[ebp-0x4878]        ; remaining = bytes left in this image
08133830  mov  [ebp-0x4860],esi        ; chunk  = BufferSize, parsed from the reply
0813836  mov  [ebp-0x4868],ecx        ; keep remaining
0813860  cmp  [ebp-0x4860],esi        ; esi = remaining
0813866  jbe  skip
0813868  mov  [ebp-0x4860],esi        ; chunk = min(chunk, remaining)
08138aa  call operator new[]           ; buf = new[chunk]
08138eb  call fread                    ; fread(buf, 1, chunk, f)
...         call CWtpComm::Data(buf, chunk)
```

`BufferSize` is packed little-endian out of the DataHeader reply
(`WTPSTATUS+6` upward, `WTPSTATUS+5` bytes of it).  Our device answers with a
single byte `0xF8`.  **The 248 is the device's advertised buffer, not a tool
limit** — `CWtpComm::Data`'s legacy path memcpy's up to `0x4000` bytes and
issues one `WriteUSB` of `len + 8` bytes per chunk, so the tool can
comfortably send 16 KiB per round trip and simply chooses not to.

### 4b. "Fast Download" is dead code in 4.8.8.2 (verified)

The gate is one instruction:

```
08137c5  test BYTE PTR [ebp-0x481e],0x4     ; [ebp-0x481e] == WTPSTATUS+4
08137cc  je   0813cdf                       ; -> "Fast Download is not activated"
```

`WTPSTATUS+4` is the **top byte of the 4-byte little-endian length field** in
the reply.  Testing bit 2 of it means "is `length & 0x04000000` set", i.e. is
the reply ≥ 64 MiB.  No reply to a DataHeader ever will be.  So the branch is
unreachable and every run prints the same message.

Two further corrections to what was written here before:

* **`FDSwitch is 1` is a hardcoded literal `1` in the binary**, not device
  data.  The `fprintf` at `0x0813379f` loads `mov DWORD PTR [esp+0x10],0x1`
  as the second `%d`.  It carries no information about the board.
* **`CWtpComm::SendPreamble(bool)` ignores its argument entirely.**  It always
  sends the fixed 4-byte `00 D3 02 2B`.  "Original Preamble Mode" vs
  "Customize Preamble Mode" is a log message only in this build, so it is not
  a lever.

### 4c. Tested and rejected

* **Shrinking the DKB on its own.** Substituting the Air720
  `Nezha_loader_...Release.bin` (79,924 B) for our OBM as the `OBMI` image gives
  `Dkb.bin` → 79,928 B. Correct and worth keeping, but on its own it did not fix
  anything — the run still failed later, at the re-open. The combination of the
  small DKB *and* the 4096-byte chunk override is what made the DKB complete.
* **Pursuing the timing question at all.** Premise retracted, see the
  correction at the top of this section.

### 4d. The live blocker: EBUSY on re-open (verified 2026-10-14)

Once the ROM hands control to the uploaded DKB, the tool's hotplug thread
decides the device vanished and re-detects it. It then re-opens the very node
it is still holding:

```
|Completed DownLoad file: .../temp/DKB_ntimheader.bin
|Begin DownloadImage...........        <- image 2 = FBF
remove DevName:/dev/bus/usb/001/038
add DevName:/dev/bus/usb/001/038
ERROR: n = -1, errno = 16 (Device or resource busy)   x ~700
swdl_linux timeout exit
```

errno 16 is EBUSY. usbfs permits one open per device per process, so the second
open fails forever while `OpenUsbPort` retries at `usleep(5000)` until the `-T`
timeout expires. **The FBF never leaves the host and nothing is ever written.**

The close logic already exists in the tool and is simply never called on this
path. `CloseDev` has exactly one caller, `CWtpComm::CloseUsbPort`:

```
0816d2f0  CWtpComm::CloseUsbPort()
  8b 50 04                mov edx,[eax+4]        ; this->m_dev
  8b 8a 00 02 00 00       mov ecx,[edx+0x200]    ; handle->fd
  85 c9                   test ecx,ecx
  74 11                   je  +0x11              ; skip if fd == 0
  05 48 06 00 00          add eax,0x648          ; handle = this+0x648
  e8 79 e4 fc ff          call CloseDev          ; 0x0813b790
```

`CBulkDevNonDrv_Linux::OpenDev` (`0x0813b660`) opens at `0x0813b6b3` with no
preceding close:

```
813b6a8  mov DWORD PTR [esp+0x4],2      ; O_WRONLY
813b6b0  mov [esp],ebx                  ; path
813b6b3  call __libc_open64
```

Handle layout, from `OpenDev`'s tail and `CloseDev`'s body:

```
[handle+0x000 .. 0x0ff]  zeroed by CloseDev's `rep stos` (0x40 dwords)
[handle+0x200]  primary fd        <- CloseDev closes this one
[handle+0x204]  bulk pipe
[handle+0x208]  bulk pipe
handle            = CWtpComm+0x648 ; m_dev = CWtpComm+0x4
```

Fixed by `tools/swdl-reopen-patch.py` — two edits, 11 bytes, verified by
objdump on the produced binary. See §11.

## 5. Ruled out

- **Kernel driver claiming the device.** `tools/usb-watch.py` reports
  `usbfs bound` (which is `swdl_linux` itself, not a blocker) and nothing else.
  `cdc_acm`/`usb-storage` are not binding.
- **Missing WTMI/TZII blobs.** These are temp files the tool generates, not
  vendor inputs. `DKB_ntimheader.bin` contains one `IBKD` entry and zero
  `WTMI`/`TZII`. The original blocker was our own `Image_ID` bug.
- **Permission / root / udev.** Root is required and works.
- **PROD flag gating.** The board does enumerate. `[PROD]Don't enum USB port`
  did not apply; behaviour matches `[Non-Prod]Wait for download...`.
- **Timing as a host-side problem.** The tool is already listening before
  power-on; `usb-watch` confirms it opens the device within ~150 ms.

## 6. Specific questions for whoever picks this up

**A. Can the OBM's 1.58 s USB window be extended or held? — ANSWERED 2026-10-15.**

> The premise is wrong, and so is the remedy. The board is not racing us.
> Full analysis in [`DOWNLOAD_MODE_RE.md`](DOWNLOAD_MODE_RE.md).
>
> Download mode is gated in the OBM (`FUN_003eeacc`, `0x3EEACC`) by three
> conditions, in order:
>
> 1. a force-download code read from a register, or
> 2. **a latch in mtd19**: `DLFG == "DLFG" && DLOK != "DLOK"`, or
> 3. the PROD fuse bit `0x8000` at `0xD428287C`.
>
> **This unit fails gate 2 and never reaches download mode at all.** mtd19
> holds `DLFG` at `+0x8C` and `DLOK` at `+0x90`; because `DLOK == "DLOK"` the
> latch is **closed** and the board boots straight through. Every earlier
> "device appears for 1.58 s" observation came from the force-download strap
> (gate 1), not from a window we were losing.
>
> Clearing `DLOK` reopens the gate. It is evaluated *before* the fuse check
> and before any timeout, so it should hold download mode open on every boot.
> `tools/mtd19-force-download.py` prepares it (`--inspect` reads the state).
>
> The wait is also not a constant: `FUN_003ef72c` sleeps
> `ResetDelay * 1000000` us, where `ResetDelay` is a byte read from a 0x10-byte
> options block — the device-side counterpart of the `.blf` `Reset_DelayTime`
> key. Raising it is the second lever.
>
> **Untested on hardware**, and the OBM re-stamps `DLOK` on entering download
> mode, so it may buy one boot per write rather than a permanent change.
>
> `RESTORE_Key` / GPIO 16 is therefore no longer the cheapest experiment — it
> is gate 1 of three, and not the gate that is closed.

<details><summary>Original open question (superseded)</summary>

Strings in `mtd0.bin` suggest it is adjustable:
`Wait for download change timeout to true...`, `USB Enum timeout`,
`User force to download`.

- Is the timeout a fixed ROM constant, or is it read from a TIM record, a
  GPIO strap, or the `PROD` flag?
- `User force to download` — what hardware signal sets it? The vendor DTS has
  `RESTORE_Key` on GPIO 16, pin 49, active low. One earlier trial was
  inconclusive because we could not observe the result; `usb-watch.py` now can.
  **If holding that pin keeps the OBM in forced download mode, the window may
  not expire and the whole route reopens.** This is the cheapest untested
  experiment.

</details>

**B. Can Fast Download be enabled? — ANSWERED: not in this binary.**

See §4b. The gate tests bit 2 of the *length field's* top byte, so it is
structurally unreachable, and the "FDSwitch is 1" in the log is a literal.
`CWtpComm::isFastDownload(bool,bool)` at `0x0816d060` is a plain
getter/setter on the byte at `this+0x63c`:

```asm
cmp BYTE PTR [ebp+0xc],0x0       ; arg1 = "set?"
jne setter
  movzx eax,BYTE PTR [eax+0x63c]     ; getter
  ret
setter:
  mov BYTE PTR [eax+0x63c],dl        ; this->fastDownload = arg2
```

`tools/swdl-chunksize-patch.py --force-fast-download` can force the setter to
run, which switches `CWtpComm::Data` onto `WriteUSBWithNoRsp` (no per-chunk
ACK). Worth a try only *after* the chunk-size override, and only because a
failed attempt writes nothing to flash — the DKB stage precedes every flash
write.

**C. Is there a smaller boot-ROM flasher for PXA1802/NZA3? — no longer the
binding question.** See §11: because the OBMI entry can be marked
`Enable = 0`, its only remaining job is to be the DKB. It does not have to be
a flashable OBM at all, so the 79,924-byte Air720 loader beats our
262,144-byte OBM.

**D. Does SWDownloader 4.9.x behave differently?**

Requested from Yuge (`support@yuge-info.com`) on 2026-10-14. They document
`SWDownloader_4_9_1_1`; our OBM advertises `4.9.0.5`. Their answer decides
whether this route is worth continuing at all.

**E. "Get type of device failed" after a clean handshake — ANSWERED 2026-10-15.**

> The failure is in our `.blf`, not in the tool and not on the board. Full
> analysis in
> [`findings/tooling/blf/swdl-platform-enum.md`](../../findings/tooling/blf/swdl-platform-enum.md).
>
> `GetDeviceBootType` does not *determine* the platform, it dispatches on one
> the BLF already chose:
>
> ```
> [TIM_Configuration] Processor_Type
>   -> CBlfParser::GetPlatFormType   -> ePlatForm
>   -> CIFL_SWD::Initilizeparameter   -> _InstanceParams+0x24
>   -> CWtptpDownLoad::InitializeBL  -> this+0x1C4C
>   -> GetDeviceBootType jump table at 0x083371DC (19 entries)
> ```
>
> `PXA1802` maps to ePlatForm **6**, and slot 6 is one of the three (0, 6, 12)
> whose handler is the `"Unknown platform type"` stub. `PXA1826` maps to
> ePlatForm **15**, whose handler tests exactly the identity this board reports:
> date `06012014`, processor `NZA3`, version `3311`.
>
> **One-token fix, no binary patch:**
>
> ```diff
> -Processor_Type = PXA1802
> +Processor_Type = PXA1826
> ```
>
> Confirmed offline with the vendor's own oracle: `MakeDownloadPackage`
> printed `NEZHA platform type` for the old BLF and `NEZHA3 platform type` for
> the corrected one. Note `PXA1802` is plain *Nezha* and `PXA1826` is *Nezha 3*;
> the board's own processor string is `NZA3`, so the BLF was mis-declaring the
> SoC family.
>
> If you prefer the patch route, `tools/swdl-platform-patch.py --enum 0x0F` is
> correct; the previous default `0x12` selects the HLN4 / `3313` branch.

## 7. Recovered protocol constants

`swdl_linux` is **unstripped and carries DWARF**. `readelf -sW swdl_linux |
c++filt` gives every method of `CWtpComm` and `CWtptpDownLoad` with address
and size.

**Corrected 2026-10-15.** These were the little-endian encodings of the
compiler's *dword stores*, read backwards. The WTP opcode is at **offset 0**.

| command | transmitted bytes | function |
|---|---|---|
| Preamble | `00 D3 02 2B` (4 B) | `CWtpComm::SendPreamble` `0x0816d820` |
| GetVersion | `20 00 …` (8 B) | `CWtpComm::GetVersion` `0x0816f0c0` |
| Data | `22 <seq> …` (8 + N B) | `CWtpComm::Data` `0x0816e7d0` |
| SelectImage | `26 …` (8 B) | `CWtpComm::SelectImage` `0x0816ee70` |
| VerifyImage | `27 00 … 01000000 <mode>` (9 B) | `CWtpComm::VerifyImage` `0x0816eca0` |
| DataHeader | `2A <seq> 00 <04 if fast> 04000000 <size BE32>` (12 B) | `CWtpComm::DataHeader` `0x0816ea00` |
| GetWtpMessage | `2B …` (8 B) | `CWtpComm::GetWtpMessage` `0x0816dbb0` |
| Done | `30 …` (8 B) | `CWtpComm::Done` `0x0816e600` |
| Disconnect | `31 …` (8 B) | `CWtpComm::Disconnect` `0x0816e480` |
| UploadDataHeader | `32 … 10000000 <4×u32>` (24 B) | `CWtpComm::UploadDataHeader` `0x0816f530` |
| UploadData | `33 …` (8 + N B) | `CWtpComm::UploadData` `0x0816dfd0` |
| GetProtocolVersion | `34 …` (8 B) | `CWtpComm::GetProtocolVersion` `0x0816f260` |
| GetParameters | `35 …` (8 B) | `CWtpComm::GetParameters` `0x0816e0f0` |

NACK is `resp[3] == 1`. Full engine writeup in
[`findings/tooling/blf/swdl_linux-internals.md`](../../findings/tooling/blf/swdl_linux-internals.md).

Key functions:

```
CWtpComm::OpenUsbPort                     0x0816d320    180
CWtpComm::SendPreamble                   0x0816d820    395
CWtpComm::GetWtpMessage                  0x0816dbb0    613
CWtpComm::GetVersion                     0x0816f0c0    406
CWtpComm::GetProtocolVersion             0x0816f260    716
CWtpComm::GetParameters                  0x0816e0f0    901
CWtpComm::Data / VerifyImage / SelectImage / Done / Disconnect
CWtptpDownLoad::WtptpDeviceDetectThread   0x08137460   2718
CWtptpDownLoad::GetDeviceBootType         0x081361f0   3912
CBulkDevNonDrv_Linux::ChecHWIds          0x0813b220     87
CBulkDevNonDrv_Linux::FindAllSupportedDevices 0x0813b9a0 1666
```

`GetDeviceBootType` parses the device identity with `Version: %c%c%c%c`,
`Date: %08X`, `Processor: %c%c%c%c`. Our board returns `3311` / `06012014` /
`NZA3`. The tool's table pairs `3311`+`06012014` with `HLN2`, which is why the
lookup originally failed.

## 8. The alternative, for context

If the USB window proves insurmountable, the fix does not need SWDownloader at
all. `mtd21` (named `bootargs`) is the U-Boot environment at flash offset
`0x06000000`, 256 KiB.

Env format, reverse-engineered and verified:

```
0x0000  4 bytes   CRC32, little-endian
0x0004  N         NUL-separated "name=value", double-NUL terminated
0x8000            end of a 32 KiB env block
```

**No flags byte** — offset 4 is already the first character of the first
entry. Confirmed: `zlib.crc32(d[4:0x8000]) == stored CRC`.

The environment holds `autostart=yes` and `bootdelay=1`. Setting
`autostart=no` and `bootdelay=10` gives a usable autoboot window.
`tools/mtd21-unlock.py` does this and self-verifies.

**Correction worth carrying forward:** the claim that `autostart=yes` makes
the interrupt impossible is **wrong**. In U-Boot 2014.01 `autoboot_command()`
polls `tstc()` *before* `run_command_list()`; `autostart` is read only by
`autoboot_command_autostart()`, reached only when `bootcmd` contains `;`.
`bootcmd=mrvlboot` has none. The window exists — it is one second and silent.

So: write `mtd21` (over USB via `.blf`, or a NAND clip), spam keys, get
`Marvell>>`. Verified safe: the DTIM hashes only `mtd13`/`mtd14` (kernel) and
`mtd15`/`mtd16` (rootfs), never `mtd21`.

## 9. Repository map

| path | what |
|---|---|
| `findings/tooling/blf/p298_fixed.blf` | validated `.blf`, header explains all three bugs |
| `findings/tooling/blf/swdownloader-blf-spec.md` | full `.blf` + USB spec, sections 8f–8j are the RE |
| `findings/tooling/blf/flash-map.md` | annotated 128 MiB partition map |
| `findings/nand-dumps/` | all 25 partition dumps + `MANIFEST.sha256` |
| `tools/swdl-whitelist-patch.py` | VID/PID patch |
| `tools/swdl-platform-patch.py` | platform enum patch |
| **`tools/swdl-chunksize-patch.py`** | **override the 248-byte chunk; `--force-fast-download`** |
| **`tools/mk-mtd21-blf.py`** | **generate the mtd21-only `.blf`; `--validate` runs the oracle** |
| **`tools/swdl-budget.py`** | **measure the real USB window and transfer budget** |
| `tools/mtd21-unlock.py` | U-Boot env patcher |
| `tools/usb-watch.py` | 50 Hz USB enumeration capture (superseded by `swdl-budget.py`) |
| `flashing_tools/p298-swd/` | run directory: patched binaries + configs |
| **`flashing_tools/p298-swd/p298_mtd21_only.blf`** | **the mtd21-only config — see §11** |
| **`flashing_tools/p298-swd/swdl_linux_p298_v3`** | **v2 + 4096-byte chunk override** |
| **`flashing_tools/p298-swd/mtd21.env32k.bin`** | **32 KiB env image (the rest of the partition is 0xFF)** |
| `docs/recovery/swdownloader_blf_findings.md` | narrative findings |

**Hazard:** the tool overwrites the `TIMH` image in place, offline, with a
248-byte generated TIM header. `flashing_tools/Marvell_SWDownloader_v4.8.8.2/`
holds `mtd7.bin` as a symlink into `findings/nand-dumps/`. **Never run anything
from that directory** — use `flashing_tools/p298-swd/`.

> **Confirmed the hard way on 2026-10-14.** Running `MakeDownloadPackage -r
> p298_mtd21.blf` *inside* `flashing_tools/p298-swd` rewrote its `mtd7.bin`
> from 262,144 B to 248 B, exactly as warned. The mistake was treating
> "offline validation" as read-only — it is not. Restored from
> `findings/nand-dumps/mtd7.bin`, sha256 re-verified as
> `7de63ddc29453b0a49e0d8531eeef886ec64d4821a2be27c5a89baed299b7e9e`.
> **`tools/mk-mtd21-blf.py --validate` now copies every referenced file into a
> scratch directory before invoking the oracle**, so the hazard cannot recur
> through that path.

## 10. Reproducing a run

```sh
cd flashing_tools/p298-swd
cp ../../findings/nand-dumps/mtd7.bin ../../findings/nand-dumps/mtd0.bin .
sudo env LC_ALL=C LANG=C ./swdl_linux_p298_v2 -D p298_probe.blf -T 300 -N
# then power-cycle the board
```

`p298_probe.blf` has both images `Enable = 0` and carries no payloads, so a
successful run writes nothing. Read `wtp_*.log` afterwards; that per-device log
is the real diagnostic.

---

# 11. UPDATE 2026-10-14 — the two levers, and the procedure

Everything below was verified offline (no hardware): byte-level comparison of
the tool's own generated output, and disassembly of `swdl_linux`.

## 11a. `Dkb.bin` is the OBMI image verbatim, plus 4 bytes

Verified byte-for-byte against every config built:

```
Dkb.bin[0:4] == b"IBKD"
Dkb.bin[4:]  == <the OBMI image file, unchanged>
```

So `Dkb.bin` = 262,148 B is just `mtd0.bin` + a tag, and `DKB_ntimheader.bin`
(248 B) is the DKB's own generated TIM header. **The size of the DKB is the
size of whatever file you point `2_Image_Path` at.** That is the single number
that decides whether the 1.58 s window is enough.

## 11b. `*_Image_Enable = 0` means "supply this file, do not write it to flash"

This is the finding that makes the rest cheap. With TIMH and OBMI disabled and
only ENV0 enabled, the tool's flash payload container shrinks accordingly:

| config | written images | `FBF_h.bin` |
|---|---|---|
| all three enabled | mtd7 + mtd0 + mtd21 | 532,484 B |
| TIMH + OBMI `Enable = 0` | **mtd21 only** | **266,244 B** |

`FBF_h.bin` then contains exactly one image — mtd21 — and nothing else is
written. Removing the OBMI entry entirely aborts with
`OBMImage is NULL in prepareDKB list`, so the OBMI is required *as the DKB
source* but not as a flash target.

## 11c. The DKB is uploaded regardless of `Enable`

`p298_probe.blf` has both images disabled yet still produced a full
`Dkb.bin` upload attempt. The DKB stage is unavoidable; only its size is under
our control.

## 11d. The chunk size is the remaining lever

The device says 248; the tool obeys. `CWtpComm::Data` supports up to `0x4000`.
`tools/swdl-chunksize-patch.py` replaces the `chunk = BufferSize` store at
`0x08133830` with a fixed immediate, keeping the `min(chunk, remaining)`
tail-handling intact:

```
08133830  mov  DWORD PTR [ebp-0x4860],0x1000   ; was: mov [ebp-0x4860],esi
081383a  mov  BYTE  PTR [esp+0x4],0x0
081383f  mov  BYTE  PTR [esp+0x8],0x1
0813844  mov  eax,[ebx+0xc18]
081384a  mov  [esp],eax
081384d  call 816d060 <isFastDownload>
0813852  mov  [ebp-0x4868],ecx
0813858  nop
0813859  nop
```

The rewritten region is 42 contiguous bytes at `0x08133830`, file offset
`0xeb830`..`0xeb859`; 34 bytes within it actually change value. Everything
outside that window is byte-identical, so the whitelist and platform patches
are untouched. The tool self-checks by disassembling its own output and
refusing to report success if the decode is not exactly
`mov DWORD PTR [ebp-0x4860],0x1000` — a byte diff alone would not have caught
the disp8 mistake below.

**Risk is bounded and one-directional.** The chunk override applies to the DKB
upload *and* the later flash writes because they share the code path. The DKB
upload precedes every flash write, so raising the chunk can at worst make the
boot ROM reject the transfer and re-enumerate. It cannot corrupt flash. If the
DKB stage succeeds and the flash stage then fails, re-run with
`--chunk 0` to restore stock behaviour for the flash writes.

> **Encoding trap worth recording.** The first version of this patch used
> `C7 45 A0 imm32` — 7 bytes — which objdump decoded as
> `mov DWORD PTR [ebp-0x60],0x1000`. The disp8 form sign-extends `0xA0` to
> `-0x60`, not `-0x4860`. It needed the disp32 form `C7 85 A0 B7 FF FF imm32`
> (10 bytes). Disassembling the patched binary is what caught it; reading the
> bytes by eye would not have.

## 11e. The config: `p298_mtd21_only.blf`

Generated by `tools/mk-mtd21-blf.py`:

| | |
|---|---|
| TIMH (mtd7) | `Enable = 0` — not written |
| OBMI | `Enable = 0`, path = Air720 loader (79,924 B) — DKB only |
| ENV0 (mtd21) | `Enable = 1`, `mtd21.env32k.bin` at `0x06000000` |
| **DKB to upload** | 79,928 B = 322 round trips at 248 B |
| **flash payload** | 36,868 B, after the DKB is running |

`mtd21.env32k.bin` is the first `0x8000` of `mtd21.unlocked.bin`; everything
past that in the partition is `0xFF`, and an env block is 32 KiB
(`CRC32 @0x0000`, entries from `0x0004`, double-NUL terminated). Shipping 8×
less env costs nothing.

`--dkb p298` rebuilds the same config with our own OBM as the DKB source
(262,148 B, 1,057 round trips) if the Air720 loader turns out not to be
accepted.

## 11f. Procedure — measure first, then flash

**Step 1 — measure the real budget.** The only measured data points so far are
"248 B works" and "79,928 B does not". Nothing in between, so nobody knows the
budget:

```sh
sudo tools/swdl-budget.py -D flashing_tools/p298-swd/p298_probe_small.blf \
     -b flashing_tools/p298-swd/swdl_linux_p298_v2
# power-cycle when prompted
```

It watches sysfs at 200 Hz, runs the tool, then reports the window, the round
trips that actually happened, and the implied byte budget.

**Step 2 — raise the chunk and re-measure** with the same probe:

```sh
sudo tools/swdl-budget.py -D flashing_tools/p298-swd/p298_probe_small.blf \
     -b flashing_tools/p298-swd/swdl_linux_p298_v2 --chunk 4096
```

A ready-made `swdl_linux_p298_v3` (chunk 4096) is already in
`flashing_tools/p298-swd/`.

**Step 3 — only once step 2 reports the DKB completing: the real run.**

```sh
cd flashing_tools/p298-swd
sudo env LC_ALL=C LANG=C ./swdl_linux_p298_v3 -D p298_mtd21_only.blf -T 300 -N
# then power-cycle the board
```

Expect, in order: `Completed DownLoad file: DKB_ntimheader.bin`, then
`Completed DownLoad file: Dkb.bin`, then a device re-enumeration as the
BootLoader device, then the mtd21 write. Then power-cycle and you should get a
10-second `Marvell>>` autoboot window.

## 11g. Still unverified — say so, do not paper over it

* The actual byte budget of the 1.58 s window. **Unmeasured.**
* Whether the boot ROM tolerates chunks larger than its advertised 248.
  **Untested.** The tool supports it; the device may not.
* Whether the Air720 4.7.2.14 loader is accepted as a DKB by a 4.9.0.5-era
  boot ROM. **Untested end to end** — the earlier attempt died in the DKB
  stage for a reason that is now attributed to the window, not to
  incompatibility, but that attribution is inference, not measurement.
* Whether the post-DKB phase has its own timeout. **Unmeasured.**
* Whether the `1.58 s` figure itself is accurate. It was measured with a 50 Hz
  poller; `swdl-budget.py` polls at 200 Hz and supersedes it.

---

## 11h. UPDATE 2026-10-14 (third pass) — "the device vanishes" is WRONG

The first live run through `tools/swdl-budget.py` produced a result that
invalidates the premise this document has been built on.

### What was observed

```
USB window : nan ms  (appear t+42.137 s, disappear still present)
```

The board appeared at t+42 s and **never disappeared**. Confirmed afterwards:

```
$ lsusb | grep 2ecc
Bus 001 Device 037: ID 2ecc:3002 ASR KSTR     # 22 minutes after the run
```

`/sys/bus/usb/devices/1-1` reports `speed=480` — **high-speed USB, 480 Mbps.**

Two consequences, both important:

1. **There is no 1.58 s window.** `usb-watch.py`'s 50 Hz measurement and every
   "device vanishes ~1.58 s after enumerating" statement downstream of it are
   wrong. The board stays in download mode indefinitely.
2. **The channel is not bandwidth-limited.** 480 Mbps means a 248-byte bulk
   transfer costs microseconds. Whatever the budget is, it is set by *round-trip
   count*, not by bytes — which makes the chunk-size patch far more promising
   than it would be on a 12 Mbps link.

### Where "the device vanished" came from

`remove DevName:` in the tool's stdout is **not a USB disconnect**. Traced to
`CWtptpDownLoad::WtptpDeviceDetectThread` (`0x08137460`):

```
813762d  call CheckDevForNetLink(handle, name, 0x20c, &out)
8137632  test eax,eax
8137639  je   81377d0                 ; device still on the bus
813763f  mov  eax,[out]
8137645  test eax,eax
8137647  je   8137ac0                 ; out == 0 -> print "remove DevName:%s"
8137ac0  ... printf("remove DevName:%s")
8137bb8  call SetAndWaitForThreadExit
```

`CheckDevForNetLink` → `CBulkDevNonDrv_Linux::IsSupported` (`0x0813c030`),
which re-parses the `/dev/bus/usb/BBB/DDD` path into bus/dev numbers, re-opens
the device and re-runs the VID/PID check. **`remove DevName` therefore means
"the detect thread's periodic `IsSupported()` re-check said no", not "the
device is gone".**

`SetAndWaitForThreadExit` (`0x0812f950`) is what actually kills the download:

```asm
mov  [ebx+0xc1c],0x1
mov  [[ebx+0xc18]+0x424],0x1     ; the CWtpComm "thread exit" flag
mov  [esp],0x1e8480
call usleep                       ; 2,000,000 us  <-- TWO SECONDS
```

and `CWtpComm::ReadUSB`/`WriteUSB` both start with
`cmp DWORD PTR [this+0x424],0x1; je ...` and fail immediately once it is set.
That is the real abort path — the per-device log ends with
`Thread is to be exit` / `Abnormal Termination in BootRom`.

### What actually failed in that run

The run aborted **during image 1**, after the 248-byte `DKB_ntimheader.bin` was
sent and ACKed — it never reached `Dkb.bin` at all:

```
Begin DownloadImage...........
download file name is .../temp/DKB_ntimheader.bin
Return flag in Dataheader CMD: 0,FDSwitch is 1,BufferSize is 0xF8
Fast Download is not activated
Download data finished
 GetWtpMessage...  Platform ready status: 0
Thread is to be exitCompleted DownLoad file: .../DKB_ntimheader.bin
Abnormal Termination in BootRom
```

Older logs (028/029/031) got one step further — they reached
`Begin DownloadImage` for image 2 and then `Sending Preamble...` before the
same abort. So the failure point moves: it is **not** a fixed wall at 248
bytes, and it is **not** a timeout.

### Honest state of the diagnosis

*Known:* `remove DevName` → `IsSupported()` returning false in the detect
thread's poll loop → `SetAndWaitForThreadExit` → `[CWtpComm+0x424] = 1` → the
BootRom I/O thread aborts with "Abnormal Termination in BootRom".

*Not known:* **why `IsSupported()` returns false.** It re-parses the device
path and re-opens the device; the two candidates are (a) the device
re-enumerates to a new address after the DKB TIM header, so the old
`/dev/bus/usb/001/037` path no longer resolves to a supported device, or (b)
the reopened descriptor no longer passes `ChecHWIds`. `lsusb` still shows
`037` present, which favours neither conclusively. This is the open question.

### What to do next (in order)

1. **Re-run against the warm, still-present device — no power-cycle.** If the
   tool can re-open it, the whole "must be racing the window" problem
   disappears from the procedure:

   ```sh
   cd flashing_tools/p298-swd
   sudo env LC_ALL=C LANG=C ./swdl_linux_p298_v3 -D p298_probe_small.blf -T 60 -N
   ```

   `swdl_linux_p298_v3` is the 4096-byte-chunk build. If it gets past
   `Dkb.bin`, the chunk override is confirmed as the fix and the 1.58 s
   window was never the obstacle.

2. If the warm re-run cannot even open the device, the tool's hotplug socket
   needs a fresh enumeration event; then power-cycle and use the same command.

3. Read `wtp_dev_*.log` **and** the `*_failed_wtp.log` the tool writes on
   abort — the latter is the one that contains the real tail
   (`Abnormal Termination in BootRom`).
