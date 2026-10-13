# mtd21 clip procedure — open an autoboot interrupt window

Gets the board back to a `Marvell>>` prompt without rewriting the OBM, the
DTIM or anything RSA-signed.

## What is actually wrong

The board is **not flash-dead**. It initialises DDR, identifies the SPI-NAND as
`F35UQA001G`, and starts U-Boot 2014.01. Then:

* mtd0 (OBM) passes `quiet = 1`, so U-Boot prints nothing.
* `bootcmd=mrvlboot` runs, prints nothing, and never returns.

Everything up to and including U-Boot works. Nothing needs re-flashing.

### Correction: there IS an interrupt window

`docs/uart/README.md` says no keypress can abort the boot because mtd21 has
`autostart=yes`. **That is wrong.**

In U-Boot 2014.01, `autoboot_command()` runs the countdown and the `tstc()`
poll **before** `run_command_list()`:

```c
printf("Hit any key to stop autoboot: %2d ", bootdelay);
for (i = 0; i < bootdelay; ++i) {
        if (tstc()) { abort_boot(1); break; }
        mdelay(10);
}
run_command_list(s, s);      /* only reached if no key */
```

`autostart` is read **only** by `autoboot_command_autostart()`, which is
reached **only when `bootcmd` contains a `;` run-list separator**.
`bootcmd=mrvlboot` has none, so `autostart` is never consulted.

The window exists. It is `bootdelay=1` — one second — and `quiet=1` means the
board emits no indication the countdown is running. That is why it reads as
"no window". `mtd11.bin` contains both `Hit any key to stop autoboot: %2d`
and the `autostart` variable, so the path is compiled in.

Raising `bootdelay` makes it usable.

## Why mtd21 is safe to write

* It is the U-Boot environment, 256 KiB at flash offset `0x06000000`.
* mtd0's RSA signature covers the **DTIM**, not this partition
  (`docs/bootloader/bootloader_analyse.md` §4). Editing it does not touch the
  trust chain.
* `bootcmd`, `bootfile`, `dropbear_password` and every other variable are left
  byte-identical. Only `autostart` and `bootdelay` change.
* Fully reversible — keep `mtd21.bin`.

## Env format (reverse-engineered, verified)

```
0x0000  4 bytes   CRC32, little-endian
0x0004  N         NUL-separated "name=value", double-NUL terminated
0x8000            end of the 32 KiB env block
```

**No flags byte** — offset 4 is already `apn_update=0`'s first character.
Confirmed: `zlib.crc32(d[4:0x8000]) == stored LE CRC`. The partition is
256 KiB but only the first 32 KiB is environment.

## Step 1 — build the patched image

```sh
cd ~/Downloads/Modems/Notion_P298_ASR1802S
python3 tools/mtd21-unlock.py findings/nand-dumps/mtd21.bin \
        -o /tmp/mtd21.unlocked.bin
```

It refuses to run if the input CRC does not verify, re-reads its own output
and re-checks the CRC, and prints exactly which values changed. Expected:

```
input CRC stored=0x2d29430e computed=0x2d29430e OK
parsed 20 env entries
output CRC stored=0x337625b5 computed=0x337625b5 OK
re-parsed 20 entries from the written file
changes:
  autostart: 'yes' -> 'no'
  bootdelay: '1' -> '10'
```

Verified independently: 212 bytes differ, all inside `0x0000-0x00fff`;
20 entries before and after; 18 values identical; `bootcmd` still `mrvlboot`;
`bootfile` still `zImage`; everything past `0x8000` untouched.

## Step 2 — write it

Standard SPI-NAND clip, SOIC-8, on the back of the board. **Full chip, not
user area only.** Write offset `0x06000000`, length `0x40000`.

⚠️ Before the first write on an unknown clip setup: read offset `0x06000000`
and compare against `findings/nand-dumps/mtd21.bin`. If your chip's dump
matches ours, the geometry and address base are confirmed and you can write
with confidence. If it does not match, stop and re-check the clip — do not
blind-write at `0x06000000`.

After writing, power off before removing the clip.

## Step 3 — power on and press a key

Attach UART first (see `docs/recovery/flashing_and_failsafe_guide.md` §11a —
measure TX idle, it is likely **1.8 V**, and do not drive 3.3 V into the pin).

Then **spam keys continuously across the whole boot**, starting before power-on:

```sh
sudo tools/uart-exec.py /dev/ttyUSB0 --seconds 120 --every 5 --log /tmp/p298-unlock.log
```

Power the board. Within ~10 s you should get:

```
Hit any key to stop autoboot: 10
Marvell>>
```

You now have a full U-Boot shell. Do not type `saveenv` — there is no need to
persist anything, and it writes back to the partition you just clipped.

## Step 4 — from the prompt

```text
printenv                      # confirm autostart / bootdelay took effect
fastboot                      # USB gadget fastboot (mtd11 has fastboot)
```

U-Boot has **no `nand write` command** — verified, 0 occurrences in
`mtd11.bin`. It has `erase`, `mtdparts`, `fastboot`, `bootz`. Flash through
`fastboot`, not `nand write`. (`archive/.../PROCEDURE_recover_R291.txt` step
1(A) is wrong on this point.)

To RAM-boot the current OpenWrt image with nothing written:

```text
fastboot
# host side:
tools/ramboot.sh
```

## Step 5 — revert

Clip again and restore `mtd21.bin`, or from the prompt just leave
`bootdelay` alone. Reverting matters only if you later want the original
1-second silent behaviour, which nobody does.
