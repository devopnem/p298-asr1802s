# WTPTP simulator and client

A stand-in for the P298 / ASR1802S boot ROM, plus a client that runs against
it or against real hardware.

## Why this exists

We do not know why the board stops answering after the DKB lands. Until now
each hypothesis cost a power cycle. This puts the hypotheses in code, as named
behaviour models, and runs the client against all of them.

```sh
python3 tools/wtptp/harness.py      # add -v for the device's own log
```

## Layout

| file | what |
|---|---|
| `protocol.py` | wire format. Every constant tagged VERIFIED or INFERRED. |
| `device.py` | the simulated boot ROM and its behaviour models |
| `client.py` | the state machine; knows nothing about USB |
| `transport.py` | byte channel: `LoopbackTransport` (tests), `UsbfsTransport` (real) |
| `harness.py` | runs every model, reports which ones the client can tell apart |

The split that matters is client vs transport. The same `WtptpClient` runs
against a pipe and against `/dev/bus/usb/...`.

## Confidence

This is the point of the module. Anything not read out of the disassembly is
labelled, so a future session knows what to confirm first on real hardware.

**VERIFIED** — read from `swdl_linux` 4.8.8.2, with the address that proves it:

- `CWtpComm::SendPreamble` (0x0816d820) writes **4 bytes**, `00 D3 02 2B`
  (`WriteUSB(this, 4)` at 0x0816d8c0). `D3 02 2B` is a three-byte magic, not
  four — `buf[0]` is zero from the memset, not an opcode.
- The preamble reply is **0x26 = 38 bytes**, checked as `status[0] == 0`,
  `status[1] == 0xD3`, `status[2] == 0x02` (0x0816d904 onward).
- Every message is **8 header bytes + payload**: `DownloadImage` issues
  `WriteUSB(buf, chunk + 8)`.
- The DataHeader reply advertises `FDSwitch 1`, `BufferSize 0xF8` — from the
  tool's own log line, on every run we have done.
- Identity: `Version 3311`, `Date 06012014`, `Processor NZA3`.
- A DKB is `IBKD` followed by the image verbatim:
  `Dkb.bin[0:4] == b"IBKD"`, `Dkb.bin[4:] == mtd0.bin`.

**INFERRED** — consistent with the logs, not confirmed at the instruction
level. `with_header()` in `protocol.py` is the single place to fix if the
framing is wrong:

- that the command occupies header bytes 0..3 and the payload length 4..7
- the byte offsets of return-flag / FDSwitch / BufferSize in the reply
- the command value used for "get version"

## Behaviour models

| model | device behaviour |
|---|---|
| `stay_awake` | keeps answering for the FBF |
| `mute_after_dkb` | DKB completes, then silence — **what the real board does** |
| `require_valid_dkb` | mutes mid-image-1 if the DKB lacks `IBKD` |
| `require_timhdr` | mutes mid-image-1 if no TIM header follows `IBKD` |
| `reset_usb` | disconnects after the DKB, rather than going quiet |
| `idle_timeout` | mutes after `idle_ms` of silence — models the ~1.6 s window |

`mute_after_dkb` reproduces our real failure exactly: DKB completes, the FBF
gets no reply.

## The current finding

```
  [1] fails at -:  completed
          stay_awake
  [2] fails at DKB: MUTED
          bad magic
          no TIM hdr
  [4] fails at FBF:  MUTED
          mute_after_dkb
          require_valid_dkb
          require_timhdr
          reset_usb
```

**Where the failure lands is the only discriminating signal.** A client can
tell "the DKB was rejected mid-transfer" from "the DKB was accepted and the
device went quiet afterwards", and nothing else.

That gives a concrete experiment for the real board. `swdl_linux` buffers and
cannot answer this — it prints the same EBUSY either way. This client can,
because it knows which chunk stopped getting replies. If the real board fails
during the DKB, the DKB content is the problem. If it fails at the FBF, the
handoff is.

## Next

`UsbfsTransport` is written but untested. It needs the bulk endpoint numbers
from the device descriptor — `bNumEndpoints` was 2, and which is IN and which
is OUT has to be read from `1-1:1.0`'s endpoint directory on a live board.

Then: run the client against the real device with `p298_probe_small.blf`'s
DKB and see which side of the DKB the failure falls on.