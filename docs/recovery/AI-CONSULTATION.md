# Consulting prompt for Grok / Gemini

Self-contained — paste everything below the rule into either model. Written to be
answerable by a model with web access but no knowledge of this project.

Two rules are deliberate:

* **Citations are mandatory and checkable.** These models will produce confident,
  plausible, wrong protocol details. A wrong `BufferSize` field offset would cost
  us more days than no answer at all.
* **"I don't know" is an acceptable answer, and is preferred over a guess.**

---

I am trying to flash a custom OpenWrt firmware onto a WiFi router built on an
ASR1802S / Marvell PXA1826 SoC (the platform reports itself as `NEZHA3`, and the
stored TIM says `NZA3`), with a 128 MiB SPI-NAND. The board's flash is only
writable through the vendor's USB "download mode", using Marvell's SWDownloader
toolchain, version 5.0.0.2. The documented Linux flow is:

    fbfmake -r <file>.blf -f <outdir>      # builds BinFile.bin
    fbfdownloader -b BinFile.bin           # performs the download

`fbfdownloader` accepts only `-b` and `-p`. It is a stripped, statically linked,
non-PIE x86-64 ELF.

**I am stuck, and everything I can control has been ruled out. I am asking
because the protocol is not publicly documented and I would rather be told "I
don't know" than receive a plausible invention.**

---

## What happens, measured

The board enumerates as USB `2ecc:3002`. The WTPTP session proceeds like this,
quoted directly from the vendor tool's own device log:

    GetTargetMessage after sendpreamble
    GetWtpMessage... Platform ready status: 0
    Getting Version...
    Version: 3311
    Date: 06012014
    Processor: NZA3

So the Preamble exchange and the version query both succeed. Version string is
`3311`, date `06012014`, processor `NZA3`.

Then, for image 1 — a 248-byte FBF TIM header:

    download file name is /mp/SWD-4lou11/temp/FBF_Ntimheader.bin
    Return flag in Dataheader CMD: 4,FDSwitch is 1,BufferSize is 0xF8
    *******NOTE:: Fast Download is NOW activated!
    Last Data
    Download data finished
    GetWtpMessage...
    WTPTP Notification:  0x0
    Platform ready status: 0
    Completed DownLoad file: .../FBF_Ntimheader.bin

Image 1 completes cleanly. The board reports `Platform ready status: 0` and
notification `0x0` — as far as I can tell, a success. `BufferSize is 0xF8` is
248, exactly the image size, so the whole image went in one chunk.

Then the host begins image 2 (the 8 MB payload) and hangs forever. Every WTPTP
transfer is issued with `timeout = 0`, meaning wait-forever in usbfs, so there
is no host-side timeout.

## The measurement I care most about

I read the blocked syscall out of the hung process:

    tid 9321  D  ioctl -> USBDEVFS_BULK ep=0x81 (IN, board must reply)
                     len=38, timeout INFINITE

`ep=0x81` is an IN endpoint and `len=38` (0x26) is exactly the size the tool
reads for a Preamble reply. So:

* the board **accepted** the 4-byte Preamble on the OUT endpoint — it is ACKing;
* the board then **returned nothing at all** on the IN endpoint.

The board stays enumerated for the whole time. It does not reset — the USB
device node number is unchanged across the hang. The host thread is in `D`
state, so it cannot even be killed; the board has to be unplugged.

Reproducible byte-for-byte across six runs, on two different toolchains.

## What I have already ruled out

Please do not re-propose any of these; each was eliminated by measurement, not
by argument:

* payload content — byte-identical stock images taken from a verified NAND dump
  fail identically
* payload size — 36 KB and 8 MB fail identically
* DKB identity — the board's own `mtd0.bin` OBM and a completely unrelated
  loader both fail identically
* number of images in the BLF (3, 4 and 5 all fail identically)
* the BLF version field
* the TIM identity fields (issue date, OEM unique ID, boot flash signature) —
  these were genuinely wrong at first; I found them by diffing my generated
  TIM against the board's own stored TIM in `mtd8`, and corrected them. Still
  fails.
* partition geometry — every flash offset and erase size is confirmed correct
  against the real NAND partition sizes
* tool version (4.8.8.2 and 5.0.0.2 behave the same)
* the Windows GUI (`SWDownloader.exe`) fails *earlier*, on the very first
  Preamble during device detection

## What I have established about the protocol, by disassembly

From the tool itself:

* Preamble is 4 bytes, `00 D3 02 2B`, sent unconditionally before each image
* the reply is 38 bytes (0x26) and is validated as
  `buf[0]==0 && buf[1]==0xD3 && buf[2]==0x02`; `buf[3]==1` means NACK
* `Fast Download` is enabled when bit 2 of the DataHeader return flag is set;
  here it is set, and the tool logs "Fast Download is NOW activated!"
* in fast-download mode the data write uses a no-response write, dropping the
  per-chunk acknowledgement
* the host calls a `SelectImage`-like operation whose return value is the ID of
  the next image the **board** wants — the board drives the image order
* image IDs the binary tests for: `DFBF` (0x46424644), `TIMH` (0x54494d48),
  `TRAP` (0x50415254)

## My specific questions

1. **Is the host expected to send a Preamble before every image, or only once at
   session start?** This is the crux. The board answers the first Preamble and
   then ignores the second. If no Preamble is expected between images, the host
   should proceed straight to asking for the next image.

2. **What is the structure of the 38-byte Preamble reply?** I have never seen
   one — the board sends nothing on the second attempt. If you know the layout,
   that alone may tell us what we are waiting for.

3. **What does "Platform ready status" mean, and what value indicates the board
   is ready for the next image?** We only ever see `0`.

4. **Is there a known condition where the BootROM or DKB answers exactly one
   Preamble and then stops?** In particular: the download package contains a DKB
   (a 256 KB download kernel, derived from the board's own `mtd0.bin`), but the
   board never asks us to send it — it goes straight to the FBF TIM header. Is
   the DKB expected to be uploaded even when the board's resident OBM appears to
   match? Could the board be waiting for DKB code it was never given?

5. **Does anyone have a working vendor `.blf` for NEZHA3 / PXA1826 / ASR1802S?**
   I have reverse-engineered the format by hand and would much rather compare
   against a real one. A file named something like `Nezha_B0_MiFi_Nontrusted.blf`
   is referenced in a PXA1802 flashing guide I cannot access.

6. **Two documents are said to exist and I have never seen either:**
   `IFL SWD UserGuidev1_0.pdf` (the SWD/WTPTP protocol guide) and
   `How_to_add_a_file_in_blf.7z` (the BLF authoring guide). Do you know their
   content, a mirror, or a summary of the WTPTP message sequence in the IFL guide?
   Even the table of contents would help.

7. Is the SPI-NAND / `Flash Family = SPI-NAND` configuration in a BLF known to
   require anything unusual for this platform?

## How I would like this answered

* **Cite a source for every protocol claim** — a document name and section, a
  manual page, a mailing list post, a forum thread with a URL. If you are citing
  something you cannot name, say so explicitly.
* **If you do not know, say "I don't know."** That is genuinely more useful to
  me than a plausible guess, and I will act on it accordingly.
* **Label anything inferential as inference**, separately from sourced fact.
* Please do not reason from the general shape of USB or from similar protocols.
  This one is Marvell/ASR specific and the details are not transferable.
* If you recognise the symptom from an existing report — a forum thread, a
  mailing list answer, a bug tracker — that is the single most useful thing you
  could give me. A link beats an explanation.

## Context, in case it helps you judge relevance

The vendor's own FBF TIM header for this board (read out of the stock `mtd8`
partition) begins:

    00030400 54494d48 00000001 20140601 4e5a4133 4d4d4308
    ...                    ^issue    ^"NZA3"  ^"MMC"

where the dwords are little-endian, so `4e5a4133` is the ASCII string `NZA3`
read as a big-endian value, and `0x54494d48` is the magic `TIMH`. My generated
header now matches the stock one byte-for-byte over the first 56 bytes, and it
still fails.