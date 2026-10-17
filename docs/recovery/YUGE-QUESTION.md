# Question for the Yuge / ASR support team

**Board:** Notion P298 router, ASR1802S module (`NEZHA3` platform, processor reports `NZA3`)
**Tool:** SWDownloader **5.0.0.2**, dated 2024-5-24
**Contact:** via Yuge support, the same channel that supplied the toolchain

---

## The short version

Following your own documented Linux procedure
(`asr:cat4:update_l` → `fbfmake` then `fbfdownloader -b BinFile.bin`), the tool
transfers the first image successfully, the board confirms it, and then the tool
hangs forever waiting for a reply that never arrives.

We are almost certainly using the toolchain incorrectly. We have been unable to
find documentation that says how, and we would rather ask than keep guessing.

**One question would answer most of it:**

> **Is the host supposed to send a WTPTP Preamble before every image, or only once
> at the start of a session?**

The tool sends one before the first image and one before the second. The board
answers the first and returns nothing for the second — it accepts the 4 bytes and
then never replies. If no Preamble belongs between images, that is our bug and we
will fix our BLF. If one does belong there, we would like to understand what the
board is waiting for.

Everything we have measured is below, so you do not have to reproduce it from
scratch unless you want to.

---

## Environment

| | |
|---|---|
| Module | ASR1802S, `NEZHA3` platform, processor reports `NZA3` |
| Board | Notion P298 router |
| Flash | 128 MiB SPI-NAND (`Flash Family = SPI-NAND`) |
| USB | `2ecc:3002` — `VID_2ECC&PID_3002`, present in your `dl_WinUSB.inf` |
| Toolchain | SWDownloader 5.0.0.2 (2024-5-24), `binlinux/` |
| Linux | x86-64, glibc, run as root |
| Build | `./fbfmake -r <file>.blf -f <outdir>` then `./fbfdownloader -b BinFile.bin` |

Also reproduced with `swdl_linux -D <blf>` (5.0.0.1 and 5.0.0.2). Identical
result at the identical point.

---

## Reproducing it

```
mkdir -p /tmp/swd-fbf
cd SWDownloader_5_0_0_2/binlinux
LC_ALL=C LANG=C ./fbfmake -r <file>.blf -f /tmp/swd-fbf
LC_ALL=C LANG=C sudo ./fbfdownloader -b /tmp/swd-fbf/BinFile.bin
```

Board powered **off** when the tool starts. Power-cycle the board once
`Please plug your USB device` appears.

Board stays enumerated at the same USB device node throughout. It does not reset.
All WTPTP transfers are issued with `timeout = 0`, i.e. no deadline, so the tool
waits indefinitely and has to be killed; the process then requires the USB cable
to be unplugged to release the device.

Reproducible on **six consecutive runs**, with per-device logs byte-identical
apart from the USB device number.

### Attached: `p298-vendor-handoff.zip` (7.2 MB)

| file | |
|---|---|
| `BinFile.bin` | 8,491,524 B, built by `fbfmake` from the BLF below, accepted by `MakeDownloadPackage` 5.0.0.2 |
| `p298_payload_b3.blf` | run 1 — slot B payload |
| `p298_switch_b.blf` | run 2 — the 272-byte A/B switch, alone |
| `README.txt` | reproduction steps and file contents |

`fbfdownloader -b BinFile.bin` needs nothing else. To rebuild, note that the BLF
references its five input images by bare filename, so `fbfmake` and
`MakeDownloadPackage` will fail unless they are present in the working
directory — they are omitted here only to keep the attachment small, and we will
send them on request.

One caveat on the payload: `ow-kernel.bin` and `ow-rootfs.bin` are from a
work-in-progress OpenWrt port and are almost certainly **not** the problem.
Byte-identical stock images taken from the board's own verified NAND dump fail in
exactly the same way. Please do not spend time on the image content; we would
rather you compare the BLF configuration and the message sequence.

---

## What the board actually says

From the tool's own per-device log:

```
GetTargetMessage after sendpreamble
GetWtpMessage...
 Platform ready status: 0
Getting Version...
GetWtpMessage...
 Platform ready status: 0

Version: 3311
Date: 06012014
Processor: NZA3

Begin DownloadImage...........
download file name is /mp/SWD-4lou11/temp/FBF_Ntimheader.bin
 GetWtpMessage...
WTPTP Notification:  0x0
 Platform ready status: 0
Return flag in Dataheader CMD: 4,FDSwitch is 1,BufferSize is 0xF8
*******NOTE:: Fast Download is NOW activated!
Last Data
Download data finished
 GetWtpMessage...
WTPTP Notification:  0x0
 Platform ready status: 0
Completed DownLoad file: /mp/SWD-4lou11/temp/FBF_Ntimheader.bin
Begin DownloadImage...........            <-- hangs here, nothing further logged
```

**This is the part that confuses us.** The board accepts the 248-byte FBF TIM
header and then reports success — `Platform ready status: 0`, notification
`0x0`. As far as we can tell it has completed the operation successfully. It is
not refusing the first image; it agrees to it and then stops responding to
anything.

---

## The USB transfers, in order

`(endpoint, length)` from `ioctl(USBDEVFS_BULK)`:

```
  #2   OUT 4      <- Preamble (during device open)
  #3   IN  38           OK
  #4   OUT 8             GetWtpMessage
  #5   IN  262           OK
  ...      (version, device type)
  #10  OUT 8             SelectImage
  #11  IN  10            OK
  #12  OUT 9
  #13  IN  6             OK
  #14  OUT 8             file 1 transfer begins
  #15  IN  262
  #16  OUT 12
  #17  IN  10
  #18  OUT 248           <-- the FBF TIM header
  #19  IN  6             OK
  #20  OUT 8
  #21  IN  262
  #22  OUT 8
  #23  IN  6             file 1 completes, board reports ready
      --- tool logs "Begin DownloadImage" for file 2 ---
  #24  OUT 4       <- Preamble AGAIN, identical bytes
  #25  IN  38            <-- blocks forever, no reply
```

The Preamble written at #2 and at #24 is byte-identical:

```
  00 D3 02 2B
```

The blocked transfer (#25) has these fields:

| field | value |
|---|---|
| `ep` | `0x81` — endpoint 1, **IN** |
| `len` | `38` |
| `timeout` | `0` (infinite) |

So the board **accepts** the 4-byte Preamble on the OUT endpoint — it is ACKing —
and then produces nothing on the IN endpoint. We are waiting for 38 bytes that
never arrive. We have never seen a Preamble reply beyond the first one.

We read this out of the hung process rather than inferring it:

```
tid 9321  D  ioctl -> USBDEVFS_BULK ep=0x81 (IN, board must reply)
                     len=38, timeout INFINITE
```

---

## What we have ruled out

So that nobody repeats work we have already done. Each item was eliminated by
measurement, not by argument.

| | result |
|---|---|
| payload content | byte-identical stock images from a verified NAND dump fail identically |
| payload size | 36 KB and 8 MB fail identically |
| DKB identity | the board's own `mtd0.bin` OBM and an unrelated loader fail identically |
| image count in the BLF | 3, 4 and 5 enabled images fail identically |
| BLF version field | now `V3.0.0`, as your 5.0.0.2 packager requires |
| TIM identity fields | corrected — see below |
| partition geometry | every flash offset and erase size confirmed against the real NAND partition sizes |
| tool version | 4.8.8.2, 5.0.0.1 and 5.0.0.2 all stop at the same point |
| entry point | `swdl_linux -D` and `fbfmake`+`fbfdownloader` stop at the same point |
| board reset | device node number is unchanged throughout; the board does not reset |
| Windows GUI | fails **earlier**, on the first Preamble during device detection |

### On the TIM identity fields

Our first BLF had TIM header values that had been guessed rather than read from
the board. Diffing our generated header against the board's own stored TIM
(`mtd8` partition) showed:

| offset | stock (`mtd8`) | we had been sending |
|---|---|---|
| `0x0c` | `0x20140601` | `0x20141006` |
| `0x10` | `0x4E5A4133` = `NZA3` | `0x21796B53` = `Sky!` |
| `0x28` | `0x5350491C` | `0x5350490A` |

`Sky!` is a generic Marvell SKU placeholder. We had been telling the board it was
a different product in the one header it reads before deciding whether to talk to
us. Both are now corrected, and our generated FBF TIM header is now
**byte-identical to the board's own stored TIM over the first 56 bytes**, except
the image count.

We are telling you this because it was a real error on our side, and in case
others have hit it. It did not change the outcome.

---

## Our questions

**1. Is a Preamble expected before every image, or only at session start?**
This is the crux, as described at the top.

**2. What is the layout of the 38-byte Preamble reply?** We have only ever
observed one, so we have no reference to compare against. From the tool's own
validation we can see that `buf[0]==0`, `buf[1]==0xD3`, `buf[2]==0x02`, and
`buf[3]==1` means NACK. What occupies bytes 4–37?

**3. What does `Platform ready status` mean, and what do the non-zero values
indicate?** We only ever see `0`. We have also seen `WTPTP Notification: 0x0`.

**4. Is the DKB expected to be uploaded, even when the board's resident OBM
already matches?** The package we build contains four files —
`DKB_ntimheader.bin`, `Dkb.bin`, `FBF_Ntimheader.bin`, `FBF_h.bin` — but the
board never asks us for the DKB. It goes straight to the FBF TIM header. Is that
correct for a board entering download mode with its own OBM already resident, or
are we missing a step?

**5. Does the host sequence need a step between two images that we are not
issuing?** The commands we can see in the binary are Preamble, GetVersion,
SelectImage, VerifyImage, DataHeader and Data. Is there a Terminate or Verify
step that belongs after an image completes and before the next begins?

**6. `Erase All Flash`.** Your published PXA1802 burning guide instructs selecting
**Erase All Flash** in the Options menu before burning. Our BLF has
`Erase_All_Flash = 0`. Does that change the message sequence between the TIM
header and the payload? We have not tried enabling it, because on a single
unrecoverable board it would erase the OBM and we would have no working way back.

**7. Is there a known-good vendor `.blf` for this platform** — anything of the
`Nezha_B0_MiFi2_Nontrusted.blf` family, for NEZHA3 / PXA1826 / SPI-NAND? We have
reverse-engineered the format by hand and would much rather compare against a
real one.

**8. Do you have `IFL SWD UserGuidev1_0.pdf` or `How_to_add_a_file_in_blf.7z`?**
We have not been able to obtain either. Even a table of contents, or the WTPTP
message sequence table from the IFL guide, would help more than anything else.

---

## What we can offer

* **The board itself.** We can make hardware available for bench testing if that
  is the fastest route to an answer.
* **Complete packet captures**, if they help — the full USB transfer trace with
  payload bytes, not just the endpoints and lengths.
* **Our BLF and its oracle-validated `BinFile.bin`**, so you can confirm whether
  it differs from a package you consider correct.
* **An NDA**, if any of the above is sensitive.

We are not asking you to believe our diagnosis. The disassembly of
`fbfdownloader` is in our hands and we can show our working for anything we
claim.

---

## 中文提问

**设备：** Notion P298 路由器，ASR1802S 模块（平台 `NEZHA3`，处理器自报 `NZA3`）
**工具：** SWDownloader **5.0.0.2**（2024-5-24）

### 简要说明

按照贵司文档 `asr:cat4:update_l` 的 Linux 流程（`fbfmake` 生成后运行
`fbfdownloader -b BinFile.bin`），工具成功发送第一个文件，芯片也确认成功，
随后工具永久等待一个永远不会到来的应答。

我们几乎可以确定是**我们使用方式有误**，只是找不到相关说明，因此来请教，
不想继续猜测。

**如果能回答一个问题，基本就能解决：**

> **主机是否应该在每个镜像之前都发送一次 WTPTP Preamble，还是只在会话开始时发送一次？**

工具在第一个镜像前发送一次、第二个镜像前又发送一次。芯片应答了第一次，
第二次则接受了 4 个字节却不再回复。如果镜像之间本就不该发送 Preamble，
那是我们的 BLF 配置问题；如果应该发送，我们希望知道芯片在等待什么。

### 芯片的实际回应（工具自身日志）

```
Version: 3311
Date: 06012014
Processor: NZA3

Return flag in Dataheader CMD: 4,FDSwitch is 1,BufferSize is 0xF8
*******NOTE:: Fast Download is NOW activated!
Last Data
Download data finished
WTPTP Notification:  0x0
 Platform ready status: 0
Completed DownLoad file: .../FBF_Ntimheader.bin
Begin DownloadImage...........          <-- 卡在这里，之后再无任何日志
```

**令人困惑之处在于：芯片接收了 248 字节的 FBF TIM 头之后明确报告成功**
（`Platform ready status: 0`）。它不是拒绝了第一个镜像，而是同意之后
就不再响应任何命令。

### USB 传输顺序

卡住的那次传输参数为：`ep=0x81`（IN 端点）、`len=38`、`timeout=0`（无限等待）。

也就是说，芯片**已经 ACK 了 OUT 方向的 4 字节 Preamble**，但 IN 方向不再返回
任何数据。我们在等待 38 字节，而它们永远不会到达。除第一次之外，
我们从未见过 Preamble 的应答内容。

### 已排除的项目（均为实测，非推测）

负载内容（使用校验过的 NAND 原始镜像同样失败）、负载大小（36 KB 与 8 MB
同样失败）、DKB 身份、BLF 中的镜像数量、BLF 版本号、TIM 头部字段、
分区地址与擦除大小（已与真实 NAND 分区尺寸逐一核对）、工具版本
（4.8.8.2 / 5.0.0.1 / 5.0.0.2 均在同一点停止）、入口程序、
芯片是否复位（全程 USB 设备号未变，芯片没有复位）。

### 我们的 TIM 字段错误（主动说明）

我们最初的 BLF 中，部分 TIM 头部字段是猜测的，并非从芯片读取。与芯片自身
存储的 TIM（`mtd8` 分区）逐字节比对后发现：

| 偏移 | 芯片原值 | 我们原先发送 |
|---|---|---|
| `0x10` | `0x4E5A4133` = `NZA3` | `0x21796B53` = `Sky!` |

`Sky!` 是 Marvell 的通用占位符。此项已更正，现已与芯片自身 TIM 的前
56 字节完全一致（仅镜像数量不同）。但结果没有改变。特此说明，
以防其他人遇到同样问题。

### 具体问题

1. 每个镜像之前是否都应发送 Preamble，还是仅会话开始时发送一次？
2. 38 字节 Preamble 应答的结构是什么？第 4–37 字节的内容是什么？
3. `Platform ready status` 的含义是什么？非零值各代表什么？
4. **即使芯片自身 OBM 已经驻留，DKB 是否仍然应当上传？** 我们生成的包中包含
   `DKB_ntimheader.bin` 与 `Dkb.bin`，但芯片从未索取 DKB，而是直接要求
   FBF TIM 头。这样是否正确？
5. 两个镜像之间是否缺少某个必须执行的步骤？
6. **贵司 PXA1802 烧写指南要求勾选 `Erase All Flash`**，而我们的 BLF 中
   该项为 `0`。这是否会改变 TIM 头与负载之间的消息顺序？我们暂未尝试开启，
   因为只有一台无法恢复的设备，开启会擦除 OBM。
7. 是否有该平台可用的原厂 `.blf`（如 `Nezha_B0_MiFi2_Nontrusted.blf` 系列）？
8. 是否可以提供 `IFL SWD UserGuidev1_0.pdf` 或 `How_to_add_a_file_in_blf.7z`？
   哪怕只有目录，也会非常有帮助。

### 我们可以提供

设备本体（可用于实验室测试）、完整的 USB 抓包（含数据内容）、我们的 BLF
与 `BinFile.bin`，以及保密协议（NDA）。

我们并非要求贵司认可我们的判断——`fbfdownloader` 的反汇编在我们手中，
任何结论都可以展示依据。

---