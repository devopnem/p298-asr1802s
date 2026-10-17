# Next experiments, in priority order

Three tracks. The first is the one that has never been run and is the only
one that answers the open question.

---

## 1. Linux — does the board still answer after file 1?

The stall is a `USBDEVFS_BULK` read with `timeout = 0`, so `swdl_linux` cannot
fail, cannot retry, and never releases the device. Every run so far has ended in
`SIGKILL` and an unplug.

`--usb-timeout=2000` rewrites that timeout on every IN read, so the read returns
`ETIMEDOUT`, the tool takes its own error path, and exits. That frees the device
for `wtp-probe.py`, which speaks the same protocol with no tool in the loop.

```sh
sudo kill -9 $(pgrep -n gdb)
                                    # unplug the board, then:
sudo pkill -9 -x swdl_linux
cd /home/void/Downloads/Modems/Notion_P298_ASR1802S
sudo tools/swd-live-gdb.sh flashing_tools/p298-swd/p298_payload_b.blf 60 \
 --force-no-preamble --usb-timeout=2000
```

Board off until the banner. When it ends, with the board still powered and still
enumerated:

```sh
sudo tools/wtp-probe.py
```

| probe | meaning |
|---|---|
| replies, ~38 bytes | board is alive; `swdl_linux` desyncs. Host-side bug. |
| silent | the target stops servicing WTPTP. No host-side fix exists. |

Also note in the run log what the tool prints once the read times out — it may
name the failing command, which would beat anything we have inferred.

---

## 2. Linux — the vendor's own flow, no BLF at run time

This is the procedure the vendor documents for Linux, and it is a different
route through the same protocol. Two steps.

Build the upgrade file with `fbfmake`, which is in `binlinux` and is the
5.0.0.2 tool -- so it accepts our BLF where `MakeDownloadPackage` did not:

```sh
mkdir -p /tmp/swd-fbf
cd /home/void/Downloads/Modems/Notion_P298_ASR1802S/flashing_tools/SWDownloader_5_0_0_2/binlinux
env LC_ALL=C LANG=C ./fbfmake \
  -r /home/void/Downloads/Modems/Notion_P298_ASR1802S/flashing_tools/p298-swd/p298_payload_b.blf \
  -f /tmp/swd-fbf
```

It produces `BinFile.bin` and `FBF_Ntimheader.bin`. Confirmed working:
`DoFBFMake successfully`, and `BinFile.bin` starts `00 04 03 00 48 4d 49 54` --
`dwTimId` 0x00030400 and the TIMH magic 0x54494d48 that the tool prints as
`TIMH=0x54494d48`.

Then download it, per the vendor's instructions:

```sh
sudo env LC_ALL=C LANG=C \
  /home/void/Downloads/Modems/Notion_P298_ASR1802S/flashing_tools/SWDownloader_5_0_0_2/binlinux/fbfdownloader \
  -b /home/void/Downloads/Modems/Notion_P298_ASR1802S/flashing_tools/p298-swd/BinFile.bin
```

**The order matters.** `fbfdownloader` runs until it is ready, then *waits for
the module to enter download mode*. Power-cycle the board at that point. The
vendor's words: run the command, wait for it to reach that state, then reboot
the module. When the upgrade finishes the program exits on its own and the
module reboots itself.

This bypasses `swdl_linux` entirely -- no BLF parsing, no image list, no
per-image loop, and therefore none of the `SendPreamble` / `SelectImage`
machinery that stalls.

### What went wrong before we found this

`fbfdownloader` was previously run against `FBF_h.bin`, which is the wrong file.
`FBF_h.bin` is what `MakeDownloadPackage` emits and it begins `DFBF`; the vendor
flow wants `BinFile.bin` from `FBFMake`, which begins with the TIM header. Given
the wrong file, `fbfdownloader` read `ffffffff` for the map offset and size and
segfaulted. That was a format mismatch, never a board fault.

## 3. Windows — no BLF, no GUI

`FBFDownloader.exe` in `Utilities/FBFMake/` takes the same FBF. It skips the GUI's
device-detection path, which is where `SWDownloader.exe` failed with
`SendPreamble failed in GetDeviceBootType`.

Copy `flashing_tools/win-swd/FBF_h.bin` to the VM, then:

```
Utilities\FBFMake\FBFDownloader.exe -b FBF_h.bin
```

Board power-cycled into download mode when prompted.

Use `BinFile.bin`, not `FBF_h.bin`. Built with the 5.0.0.2 `fbfmake` on Linux,
the same way the vendor documents. The 4.8.8.2-era `FBF_h.bin` starts `DFBF`
and is the wrong format for this tool.

---

## What has already been eliminated

Do not spend effort re-testing these:

| variable | result |
|---|---|
| payload content | stock bytes from the verified dump stall identically |
| payload size | 36 KB and 7.4 MB stall identically |
| DKB identity | the board's own `mtd0.bin` and a foreign loader stall identically |
| tool version | 4.8.8.2 and 5.0.0.2 stall at the same point |
| BLF image count | 3, 4 and 5 enabled images stall identically |
| which command | the stall moved from `SendPreamble` (38 B) to `SelectImage` (10 B) |
| board reset | device stays enumerated throughout |

## The finding that reframes everything

`ebp` is the image index at the call site:

```asm
xor  %ebp,%ebp        ; image 1 -> ebp = 0 -> skip Preamble
add  $0x1,%ebp        ; image 2 -> ebp = 1 -> send Preamble
```

and `DownloadImage` branches on it. The tool hard-codes *"send a Preamble for
every file after the first"*. Forcing `ebp = 0` for image 2 skipped the Preamble
and moved the stall to `SelectImage` — whose `OUT 8 / IN 10` exchange is
byte-identical to the one that **succeeded** for image 1.

**The board is not refusing any particular command. It stops answering WTPTP
after the first file completes.**
---

## 0. The one diagnostic never run: `-p <logfile>`  (2026-10-17)

**Do this before anything else below.** It costs one board power-cycle and needs
no code change.

Many messages in `fbfdownloader` go **only** to the log file, never to stdout.
We have never passed `-p`, so we have never seen any of them — including the
board's answer to the one question that matters.

```sh
sudo env LC_ALL=C LANG=C \
  flashing_tools/SWDownloader_5_0_0_2/binlinux/fbfdownloader \
  -b /tmp/swd-fbf/BinFile_tim3.bin -p /tmp/wtp.log
cat /tmp/wtp.log
```

Board off until `Please plug your USB device`. What to look for:

| log line | why it matters |
|---|---|
| `Return flag in Dataheader CMD: %d,FDSwitch is %d,BufferSize is 0x%X` | the **board's** reply. Confirms whether the DataHeader was ACKed at all. |
| `*******NOTE:: Fast Download is NOW activated!` | already seen as active in `SWDownloader-handoff.md` §4b, five runs |
| `TotalBadBlocks: %d, Total Blocks: %d` | only for DFBF images |
| `Getting Version...` / anything after it | how far past the first file it got |

The last FBF-ntimheader run completed at `Completed DownLoad file`, so the log
should end there. **If the log shows a `Return flag` line, the board answered and
the stall is later than we think.**

## WTPTP protocol, recovered from `fbfdownloader` 5.0.0.2 disassembly

Static RE, Ghidra 12.1.4. Addresses are image-base `0x400000`.

`SendPreamble` — `FUN_00403810` at `0x403810`:

```
write 4 bytes:  00 D3 02 2B
read 38 bytes (0x26)                         <- blocking
  reject if buf[0]!=0 || buf[1]!=0xD3 || buf[2]!=0x02   "SendPreamble returned a wrong status"
  reject if buf[3]==0x01                                 "SendPreamble returned a NACK!"
```

**The board's 38-byte reply has never been observed.** That is the exact thing it
owes us and the single most useful datum for the vendor letter.

`DownloadImage` — `FUN_00409c10` at `0x409c10`, 3893 bytes:

```
FUN_00401410(dev,3)
  -> SendPreamble -> GetVersion -> SelectImage -> VerifyImage
  [strip the 4-byte DFBF magic unless the ID is TIMH 0x54494d48 or TRAP 0x50415254]
  -> DataHeader: the board returns BufferSize and return flags
  -> loop: read chunk -> send -> poll -> ack
```

Image-ID constants the binary actually tests: `0x46424644` DFBF, `0x54494d48`
TIMH, `0x50415254` TRAP.

Fast Download is negotiated on the board's own reply:
`if ((local_4854 & 4) == 0) "not activated" else "NOW activated"`.

### The board drives the image order

`SelectImage` returns **the ID of the next image the board wants**. The host is
not pushing a fixed list — it is answering requests. So our stall is not "the
host got stuck mid-transfer": the board fails to answer the *next* preamble,
which means it has already hung inside FBF TIM header processing.

This supersedes the `ebp`/image-index explanation at the end of this file. The
`ebp` finding was real about `swdl_linux`, but the mechanism is the board
selecting the next image and then dying, not the host skipping a preamble.

### Invented image IDs: eliminated, not guessed

`FUN_00407e10` (0x407e10) is a 63-byte linked-list lookup of the board's returned
ID against the map the tool built from the BLF. There is no validation against a
hardcoded set. Our invented `0x52444348` ("RDCH") and `0x4F424D49` ("OBMI") are
therefore self-consistent and **harmless**. Do not spend time on them.
