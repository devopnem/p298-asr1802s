# Question for the Yuge / ASR support team

Written 2026-10-17. Self-contained; please send the whole thing.

---

## Short version

The download tool transfers the first file successfully, then stops responding
to the board for the second file. Comparing the two, the only difference is that
the tool sends a **WTPTP Preamble** before the second file and the board never
replies to it. The same Preamble, at session start, works fine.

We believe this is a host/tool behaviour question rather than a configuration
problem, so we are asking rather than guessing.

---

## Environment

| | |
|---|---|
| Module | ASR1802S / `NEZHA3` platform, processor reports `NZA3` |
| Board | Notion P298 router |
| USB | `2ecc:3002` (`VID_2ECC&PID_3002`, present in your `dl_WinUSB.inf`) |
| Tool | `swdl_linux`, **SWDownloader 5.0.0.2**, dated 2024-5-24 |
| Build | statically linked, GCC 4.4.7 (Red Hat 4.4.7-23), glibc |
| Package | built by your `MakeDownloadPackage` from a `.blf` |

## Observed behaviour

Device enumeration, WTPTP preamble, version query and the **first** transfer all
succeed. The tool then logs `Begin DownloadImage` for the second file and hangs
there forever, with zero CPU. The per-device log is byte-identical across every
run.

The second file is never opened by the tool, so it is not a data or size
problem. It hangs on a **control command**.

### The USB traffic, in order

`(ep, len)` from `ioctl(USBDEVFS_BULK)`:

```
  #2   OUT 4      <- Preamble          (during device open)
  #3   IN  38     <- reply             OK
  #4   OUT 8                              GetWtpMessage
  #5   IN  262                            OK
 ...      (version, device type)
  #10  OUT 8                              SelectImage
  #11  IN  10                             OK
  #12  OUT 9
  #13  IN  6                              OK
  #14  OUT 8      (file 1 transfer begins)
  #15  IN  262
  #16  OUT 12
  #17  IN  10
  #18  OUT 248                           <-- the 248-byte FBF TIM header
  #19  IN  6                              OK
  #20  OUT 8
  #21  IN  262
  #22  OUT 8
  #23  IN  6                              file 1 completes OK
      --- tool logs "Begin DownloadImage" for file 2 ---
  #24  OUT 4      <- Preamble AGAIN     <-- no reply, ever
  #25  IN  38                           <-- blocks forever
```

### The bytes

The 4-byte Preamble the tool writes is:

```
  00 D3 02 2B
```

(both occurrences, at session start and before file 2, are identical)

### Why it never returns

The `usbdevfs_bulktransfer` for the stalled transfer is:

| field | value |
|---|---|
| `ep` | `0x81` (endpoint 1 IN) |
| `len` | `38` |
| `timeout` | `0` |

`timeout = 0` means the transfer has no deadline, so the tool cannot time out,
report an error and retry. It simply waits. This is why the process has to be
killed with `SIGKILL` and why cleanup requires unplugging the USB cable.

---

## What we would like to ask

1. **Is a second WTPTP Preamble legal within one session?** The tool sends one
   before every file after the first, and the board answers the first one but not
   the second. Should the host re-send a Preamble between files at all?

2. **Is the module expected to reset / re-enumerate between files?** The tool
   keeps a `NETLINK_KOBJECT_UEVENT` socket open watching for hotplug events, and
   the binary contains `TerminateBL.....`, `please wait .....` and
   `Begin OpenUsbPort`. Our module stays enumerated the whole time, so if a reset
   is expected, we may need to trigger it.

3. **What is the correct host sequence between two files in one run?** The
   command set we can see used is: Preamble, GetVersion, SelectImage, GetWtpMessage,
   and a "Data header" step. Is there a `TerminateBL` or `VerifyImage` step we
   are missing, and should it be issued before the next file begins?

4. **What is `0xD3`?** It appears in the 4-byte Preamble. We would like to know
   the command IDs so we can log them properly.

5. **`GetWtpMessage` after the first file returns a 262-byte read.** Is a
   notification expected there, and could a module that answers with a shorter
   message leave the host waiting?

6. **Is there a reference `.blf` for the `NEZHA3` platform we should be using as
   a baseline?** Ours is built with your `MakeDownloadPackage` from a hand-written
   `.blf`, so we would like to diff against a vendor file.

---

## Reproducing

Any `.blf` for this platform reproduces it — we have confirmed that a package
containing **byte-identical stock firmware images** taken from a verified NAND
dump stalls at exactly the same point, so it is not caused by our image content.

```
swdl_linux -D <package>.blf -S -T 1800 -N
```

Power-cycle the module into download mode when prompted. The stall is
deterministic and always at the same point.

---

## 中文提问

**问题概述**

下载工具可以正常完成第一个文件的传输，但在开始传输第二个文件时卡死。逐条
对比 USB 流量后，唯一区别是：工具在第二个文件前会再发一次 WTPTP Preamble，
而模块不回复。同样的 Preamble 在打开设备时发送一次则完全正常。

我们认为这属于主机端/工具行为的问题，所以来请教，而不是自行猜测。

**环境**

- 模块：ASR1802S，`NEZHA3` 平台，芯片自报 `NZA3`
- 板子：Notion P298 路由器
- USB：`2ecc:3002`（在贵司 `dl_WinUSB.inf` 中已列出）
- 工具：`swdl_linux`，SWDownloader 5.0.0.2，2024-5-24
- 静态链接，GCC 4.4.7 (Red Hat 4.4.7-23)，glibc

**现象**

设备枚举、WTPTP 前导、版本查询、第一个文件传输全部成功。之后工具打印第二个
文件的 `Begin DownloadImage` 就永久卡住，CPU 占用为 0，且每个设备的日志文件
完全一致。第二个文件的 payload 从未被打开，因此不是数据或长度的问题，卡住
的是一个**控制命令**。

USB 流量（`ioctl(USBDEVFS_BULK)` 的 `ep, len`）：

```
  #2   OUT 4      <- Preamble（打开设备时）
  #3   IN  38     <- 应答，正常
  ...   （版本、设备类型、SelectImage 均正常）
  #18  OUT 248    <- 248 字节的 FBF TIM 头
  #19  IN  6      正常
  ...   第一个文件传输完成，正常
      --- 工具打印第二个文件的 Begin DownloadImage ---
  #24  OUT 4      <- 再次发送 Preamble   <- 没有任何回复
  #25  IN  38     <- 永久阻塞
```

Preamble 的 4 字节内容（两处完全相同）：

```
  00 D3 02 2B
```

卡住的那次传输，其 `usbdevfs_bulktransfer` 为：

| 字段 | 值 |
|---|---|
| `ep` | `0x81`（端点 1 IN） |
| `len` | `38` |
| `timeout` | `0` |

`timeout = 0` 意味着这个传输没有超时，所以工具无法超时退出、报错重试，只会一直
等待。这也是为什么最后只能用 `SIGKILL` 结束进程、并且必须拔掉 USB 线才能清理。

**想请教的问题**

1. **同一个会话内，第二次发送 WTPTP Preamble 是否合法？** 工具会在第一个之后的
   每个文件前都发一次 Preamble；模块对第一次有回复，对第二次完全没有回复。主机
   端在文件之间是否应该重新发送 Preamble？

2. **模块在两个文件之间是否应该复位 / 重新枚举？** 工具一直持有
   `NETLINK_KOBJECT_UEVENT` 套接字监听热插拔事件，二进制里也能看到
   `TerminateBL.....`、`please wait .....`、`Begin OpenUsbPort` 等字符串。我们的
   模块在整个过程中始终保持枚举状态。如果确实需要复位，可能需要我们主动触发。

3. **一次运行中传输两个文件，主机端的正确顺序是什么？** 我们能看到的命令集合是：
   Preamble、GetVersion、SelectImage、GetWtpMessage，以及一个 "Data header" 步骤。
   是否缺少 `TerminateBL` 或 `VerifyImage` 之类的步骤？是否应该在下一个文件开始前
   发送？

4. **`0xD3` 是什么？** 它出现在 4 字节 Preamble 中。我们想知道各个命令 ID，以便
   做正确的日志。

5. **第一个文件之后的 `GetWtpMessage` 会产生一次 262 字节的读操作。** 那里是否应
   该有通知消息？如果模块返回了更短的消息，主机是否会一直等待？

6. **有没有 `NEZHA3` 平台的参考 `.blf` 可以作为基准？** 我们的包是用贵司
   `MakeDownloadPackage` 从手工编写的 `.blf` 生成的，希望能和原厂文件做对比。

**复现方式**

该平台上任意 `.blf` 均可复现。我们已经确认：即使使用**从已校验 NAND 备份中取出的、
与板上内容逐字节相同的固件镜像**，卡住的位置也完全相同，因此与我们的镜像内容无关。