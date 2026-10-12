# UART bring-up — procedure

Hardware: USB-serial adapter on the P298 UART header, 115200 8N1, no flow
control. **GND must be connected.** TX/RX crossed. Do not connect VCC — the
adapter is 5 V and the board's UART is 3.3 V / 1.8 V tolerant only on TX-RX.

## Read-only first

Everything below only reads. Do **not** run `nand erase`, `nand write`,
`erase`, `saveenv`, or `protect`. `saveenv` writes the environment (mtd21) and
`nand erase`/`write` can destroy the bootloader chain.

Never write to **mtd0** (OBM), **mtd7/mtd8** (DTIM/TIM), or **mtd20** (RSA
secure-boot keys). Overwriting the DTIM or OBM leaves the unit unbootable, and
the RSA keys are what OBM checks the DTIM against
(`Trusted OBM without ProductBuild`, `Verify Image: PASS`).

## 1. Get the U-Boot prompt

OBM hands over to U-Boot 2014.01 and autoboot counts down from `bootdelay=1`.
Tap a key repeatedly during power-up — from the moment the adapter attaches.

You want:

```
U-Boot 2014.01-g301f02458 (May 26 2026 - 17:50:03)
ASR KAGU EVB P298
...
Hit any key to stop autoboot: 1
=>
```

Note that OBM sets `quiet=1` (`get_quiet_from_obm params->quiet: 1`), so
output after the banner is suppressed. Clear it first:

```
=> setenv quiet 0
```

## 2. Read the environment

```
=> printenv
```

That is the single most useful command. Save the whole output — `bootcmd`,
`bootargs`, `loadaddr`, `bootdelay`, `ethaddr`, `bootpart`, `active_slot` /
`asr_flag` related vars.

Then specifically:

```
=> printenv bootcmd
=> printenv bootargs
=> printenv loadaddr
```

## 3. Confirm the layout

```
=> mtdparts
=> nand list
```

Expect the table in `docs/bootloader/fw_env_full.txt`: mtd13/mtd14 kernel A/B
at 5 MiB each, mtd15/mtd16 rootfs A/B at 20 MiB each, mtd7/mtd8 DTIM at
256 KiB.

## 4. Read the kernel slot (read-only)

```
=> nand read 0x40800000 0x2100000 0x500000
```

`0x2100000` is mtd13's absolute offset per the dump-derived map. Use a scratch
address in DRAM well clear of U-Boot's own region (U-Boot reports
`Start=00308000`, relocation offset `0x010f1000`, 128 MiB total). If the read
starts failing with ECC errors, move the destination.

Do the same for mtd14 at `0x2600000`.

If the slot starts with `0x27051956` (`uImage`) or the zImage magic
`0x016f2818`, an image is present. If it reads as 0xff or 0x00, the slot is
erased or corrupt.

## 5. Find out what actually terminated

`Terminating...` with no further output is what we need to explain. Candidates:

- `bootcmd` ran and failed silently because `quiet=1`
- the active A/B slot (per mtd19 `asr_flag`) has no bootable image
- `bootargs` references a rootfs that will not mount, so the kernel panics and
  reboots

`run bootcmd` manually will show the error now that `quiet=0`:

```
=> run bootcmd
```

## 6. Boot our mainline kernel manually

Once the slot contents are known, try booting the image built from this tree
without writing anything to flash. Load it over the UART or by TFTP, then:

```
=> bootz <addr> <size>
```

`bootz` is correct here: the image is a raw zImage with the DTB appended
(`KERNEL := kernel-bin | append-dtb` in `image/Makefile`), which U-Boot's
`bootz` handles. Do not use `bootm` — that expects a uImage or FIT, and this
vendor bootloader has no FIT support.

Note that `image/Makefile` sets `KERNEL_LOADADDR := 0x00008000`, which does not
match the `0x00308000` seen in the boot log. Confirm against `printenv loadaddr`
before choosing an address.

Use the kernel `bootargs` from the vendor env, substituting our rootfs. Our
image expects the squashfs on the active rootfs slot.

## What to send back

The output of `printenv`, `mtdparts`, and the two `nand read` results. That is
enough to determine whether the unit can boot our kernel directly, without a
flash write.