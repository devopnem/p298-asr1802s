# Live device-tree validation

Comparing our built DTB against the device tree the stock kernel is actually
running. No flash writes, no UART, no soldering — SSH only.

## How

The board was reachable at 192.168.1.1 and exposes `/proc/device-tree`. That
was pulled over SSH and decompiled with `dtc -I fs`:

    ssh root@192.168.1.1 'tar cf - /proc/device-tree' > live-dt.tar
    dtc -I fs -O dts -o live.dts

It was then compared against our own build output,
`build_dir/.../arch/arm/boot/dts/asr/asr1826s-p298.dtb`, decompiled the same
way. The live tree was also compared against the DTB extracted from the stock
firmware in `findings/`, and the two agree except as noted below.

## Results

### The firmware DTB is not what the kernel uses

The live tree differs from the embedded firmware DTB in exactly two places:

| | firmware DTB | live tree |
|---|---|---|
| `memory@0` reg | `<0x4000000 0x8000000>` | `<0x00 0x8000000>` |
| `chosen/bootargs` | short, `root=/dev/mtdblock5` | full runtime line, `root=/dev/mtdblock16` |

So the embedded DTB claims a 64 MB base and the live one claims base 0.
**Ours uses `<0x0 0x08000000>`, matching the live tree.** Anyone comparing
against the firmware DTB alone would conclude our memory node is wrong.

`/proc/cmdline` confirms `mem=128M@0x0`, and `free` shows ~90 MiB because
`cpmem=32M@0x06000000` is reserved for the Communication Processor. Our board
DTS already reserves that region with `no-map` in `reserved-memory`.

### Every address our drivers bind to exists in the live tree

`qspi`, `pcie`, `clock-controller`, `gpio` register addresses all match.
The only two "addresses" in our DTB absent from the live tree are
`0x2faf080` (which is `spi-max-frequency = 50000000`, a frequency, not an
address) and `0x80b0000` (a PCIe `ranges` window size). Neither is a
discrepancy.

### BUG FOUND AND FIXED: PCIe PERST# polarity inverted

The live tree and the firmware DTB agree:

```
pcie-rst-gpio  = <0x10 0x48 0x00>;
pcie-rst-gpio2 = <0x10 0x50 0x00>;
```

Phandle `0x10` resolves to `gpio@d4019000` / `marvell,mmp-gpio` — the same
controller our DTS uses. Pins 0x48 (72) and 0x50 (80) match our order.
But the third cell is `0x00` = **GPIO_ACTIVE_HIGH**, and all five
reset-gpio properties in the vendor tree use `0x00`.

Our board DTS had:

```
reset-gpios = <&gpio 72 GPIO_ACTIVE_LOW>,
              <&gpio 80 GPIO_ACTIVE_LOW>;
```

Corrected in patches 0003 and 0013 to `GPIO_ACTIVE_HIGH`. Left as-is, the
driver would have driven PERST# asserted when the hardware expects it
deasserted.

Note the vendor tree also carries a second pair, `rst-gpio = <0x10 0x50>` /
`rst-gpio2 = <0x10 0x48>`, in a different node with the **pin order swapped**
relative to `pcie-rst-gpio`. We follow `pcie-rst-gpio`, the more specific
name. The polarity is unambiguous either way.

## What this does and does not prove

It proves our DTS describes the hardware that actually exists: memory base,
the CP carve-out, and every register address match. It does not execute a
line of our kernel.

That still needs `kexec` (the stock 3.10.33 kernel exposes
`/sys/kernel/kexec_loaded`) or a U-Boot `bootz`. `kexec` from user space on
this ARM board is not straightforward: 3.10 predates the kexec payload
interface (Linux 4.5), and user space cannot write to the physical addresses
the kernel hands back on ARM.
