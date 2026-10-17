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

## 2. Linux — no BLF at all

`fbfdownloader` takes a raw FBF, so the BLF and its image list are removed from
the picture entirely.

`FBF_h.bin` (8,196,100 B, magic `0x46424644` "FBFD") was produced by the 4.8.8.2
`MakeDownloadPackage` from `p298_payload_b.blf`.

```sh
cd /home/void/Downloads/Modems/Notion_P298_ASR1802S/flashing_tools/SWDownloader_5_0_0_2/binlinux
sudo env LC_ALL=C LANG=C ./fbfdownloader \
  -b /home/void/Downloads/Modems/Notion_P298_ASR1802S/flashing_tools/p298-swd/FBF_h.bin
```

Same board, same protocol, different entry point. If this transfers where
`swdl_linux` hangs, the problem is in the BLF-driven image loop rather than in
WTPTP.

---

## 3. Windows — no BLF, no GUI

`FBFDownloader.exe` in `Utilities/FBFMake/` takes the same FBF. It skips the GUI's
device-detection path, which is where `SWDownloader.exe` failed with
`SendPreamble failed in GetDeviceBootType`.

Copy `flashing_tools/win-swd/FBF_h.bin` to the VM, then:

```
Utilities\FBFMake\FBFDownloader.exe -b FBF_h.bin
```

Board power-cycled into download mode when prompted.

Caveat worth stating: the FBF was produced by the **4.8.8.2** packaging tool,
because 5.0.0.2's `MakeDownloadPackage` rejects our BLF with `Tool version is not
matched with blf version`. A 5.0.0.2-built FBF may be required. If it refuses,
say so and we will find another way to produce one.

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