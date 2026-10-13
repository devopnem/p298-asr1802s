# UART bring-up — status and procedure

Hardware: FTDI USB-serial on the P298 UART header, 115200 8N1, no flow control.
GND must be connected; TX/RX crossed; **do not connect VCC**.

Raw captures and their analysis live in the findings repo:
`github.com/devopnem/p298-asr1802s-findings` → `uart/`.

## Where this actually stands

The unit is **not bricked**. DDR initialises, the SPI-NAND is identified as
F35UQA001G, 128 MiB is confirmed, and U-Boot 2014.01 starts. Every capture
stops at exactly the same point:

```
get_quiet_from_obm params->quiet: 1
```

…and then nothing. The board neither reaches a usable prompt nor boots.

> **An earlier version of this document was wrong.** It described tapping a
> key during a `bootdelay=1` countdown to reach `Marvell>>`. That cannot work
> on this unit, and the reason is in the environment rather than the timing.

## The interrupt window is silent, not absent

> **Correction, 2026-10-13.** This section previously said no keypress can
> abort the boot because mtd21 contains `autostart=yes`. **That was wrong.**
> See [`../recovery/mtd21_clip_procedure.md`](../recovery/mtd21_clip_procedure.md).

In U-Boot 2014.01, `autoboot_command()` runs the countdown and the `tstc()`
poll *before* `run_command_list()`. `autostart` is read **only** by
`autoboot_command_autostart()`, which is reached **only when `bootcmd`
contains a `;` run-list separator**. `bootcmd=mrvlboot` has none, so
`autostart` is never consulted.

The window exists. It is `bootdelay=1` — one second — and `quiet=1` from the
OBM means the board emits no sign the countdown is running. `mtd11.bin`
contains both `Hit any key to stop autoboot: %2d` and the `autostart`
variable, so the path is compiled in.

What is still true from the original note:

```c
static int autoboot_command_autostart(const char *s)
{
        if (!autostart)
                autoboot_command(s);
        return 1;
}
```

`bootcmd=mrvlboot` runs immediately under `quiet=1` and does not return — but
only *if no key arrives first*.

```c
static int autoboot_command_autostart(const char *s)
{
        if (!autostart)
                autoboot_command(s);
        return 1;
}
```

```c
static int autoboot_command(const char *s)
{
        if (stored_bootdelay != -1 && s && !abortboot) {
                int i;
                printf("Hit any key to stop autoboot: %2d ", bootdelay);
                bootdelay_start = get_timer(0);
                bootdelay = bootdelay_start % 1000;
                for (i = 0; i < bootdelay; ++i) {
                        if (tstc()) {
                                abort_boot(1);
                                break;
                        }
                        mdelay(10);
                }
                run_command_list(s, s);   /* only reached if no key */
        }
        return 0;
}
```

The key poll runs **before** `run_command_list()`, so pressing anything during
the countdown sets `abort_boot` and skips `mrvlboot` entirely. `CONFIG_SILENT_BOOT`
suppresses the `printf`, which is why nothing appears on the console — the
countdown is still happening.

**Open questions, stated honestly:** the board was observed printing
`get_quiet_from_obm params->quiet: 1` and then nothing, with no `Marvell>>`
across repeated attempts using both `picocom` and `tools/uart-exec.py`. That
is consistent with a silent countdown that was never hit, but also with other
explanations — e.g. the OBM consuming early UART input, or `tstc()` polling a
different console than the one monitored. `bootdelay=1` gives roughly one
second, and there is no on-screen cue for when it starts.

This is why the clip route raises `bootdelay` to 10 rather than relying on
winning a one-second silent race. See
[`../recovery/mtd21_clip_procedure.md`](../recovery/mtd21_clip_procedure.md).

The env is otherwise locked: `fw_setenv` needs a system that boots, which is
what is being recovered.

## Tools

| tool | purpose |
|---|---|
| `tools/uart-exec.py` | send commands to the console and log replies. Repeat with `--seconds/--every` for a cold board. |
| `tools/uart-spam.py` | passive capture with optional key injection. Superseded by `uart-exec.py` for reaching the shell. |

```sh
sudo ./tools/uart-exec.py /dev/ttyUSB0 --seconds 150 --every 10 --log /tmp/p298.log
```

Then power the board on. It re-probes until something answers.

## Read-only rules

Only the serial port is ever written. Do not run `nand erase`, `nand write`,
`erase`, or `saveenv` — and never write **mtd0** (OBM), **mtd7/mtd8**
(DTIM/TIM), or **mtd20** (RSA secure-boot keys). Overwriting the DTIM or OBM
leaves the unit unbootable; the RSA keys are what OBM verifies the DTIM
against.

## Next routes, in order of preference

1. **Check the board is actually dead, not merely silent.** LEDs on is not
   proof. Plug Ethernet in and `ping -c 3 192.168.1.1`; plug in a **data** USB
   cable and watch `lsusb` / `dmesg`. If Linux is running, `ssh
   root@192.168.1.1` plus `fw_setenv autostart 0` resolves everything. This is
   the cheapest test and should always be done first.
2. **Force the OBM into USB download mode.** `mtd0.bin` contains `User force
   to download`, `[Non-Prod]Wait for download...` and `isDownload=`, none of
   which printed in any capture. The vendor DTS has a `RESTORE_Key`
   (`gpios = <0x10 0x31 0x01>`, GPIO 16 pin 49, active low). A trial produced
   no change, but it is **inconclusive**: the port is `dr_mode = "peripheral"`
   and a charge-only cable enumerates nothing, making the attempt look
   identical to doing nothing.
3. **SWDownloader over USB** — blocked. `WTMI`/`TZII` are absent from every
   dump and `mtd0.bin` holds none of the four DKB magic tags. See
   `docs/recovery/swdownloader_blf_findings.md`.
4. **NAND clip / external programmer** — the only remaining write path.
   Destructive, and requires physical access to the SPI-NAND.

## bootargs: do not trust either stored value

Both stock sources point at partitions that cannot be a rootfs:

| source | root= | that partition is |
|---|---|---|
| vendor DTS `chosen` | `/dev/mtdblock5` | mtd5 = `mep-ota`, 128 KiB, empty |
| U-Boot env | `/dev/mtdblock11` | mtd11 = `u-boot-a`, 768 KiB |

`mrvlboot` must construct `root=` dynamically. Anything booting a kernel here
has to supply `root=` itself. Our board DTS deliberately sets only
`bootargs = "console=ttyS0,115200"` and leaves `root=` to the caller.