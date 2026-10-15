# Download mode in the ASR1802S OBM — reverse engineering of `mtd0`

Date: 2026-10-15 · Target: `findings/nand-dumps/mtd0.bin` (OBM, 256 KiB) ·
Tool: REA 6.5.0 CLI + Ghidra 12.1.4 headless, analysis snapshot
`obm_snapshot.reasnap`

Every claim below is tagged **[OBS]**, **[INF]** or **[UNK]**. **[OBS]** means
read out of the disassembly or the dump at a stated address; **[INF]** means
consistent with the evidence but not confirmed at the instruction level;
**[UNK]** means open.

---

## 1. Method and why the mapping is trustworthy

`mtd0.bin` is a raw SPI-NAND partition, not an ELF, so it was mapped as a
raw-binary ARM image. The load address was **derived, not guessed**:

| field | value | source |
|---|---|---|
| image flash offset | `0x20000` | TIM image entry in the mtd0 header at `+0x9C` |
| image size | `0x1A9B0` | same entry, `+0xA8`/`+0xAC` |
| RAM load base | `0x3E8000` | same entry, `+0xA4` |

Two independent checks confirm the mapping:

1. **[OBS]** The literal pool at file `0x20060` holds `0x3E8080`, which is
   exactly `0x3E8000 + (0x20080 - 0x20000)`. The pool holds a pointer *into the
   image*, so the base is right.
2. **[OBS]** Ghidra placed `SWDownloader 4.9.0.5 for %s` at `0x3FFD2C` and
   `TIMDownloadMain Init Flash Done` at `0x400094` — both exactly what the
   computed base predicts, and neither was supplied to the tool.

**[OBS]** The bytes after the image are `0xFF` (NAND erase state) from file
`0x3A9B0` to the end. The partition is TIM header + image, nothing else.

**[OBS]** The identity the SWDownloader tool reads over USB —
`Version: 3311`, `Date: 06012014`, `Processor: NZA3` — is present verbatim at
**image offset `+0x24`**, as the dwords `0x33333131`, `0x06012014`, `0x4E5A4133`.
This is the TIM header of the OBM image itself.

---

## 2. The download-mode gate

`FUN_003eeacc` (`0x3EEACC`, 636 bytes) is the boot-mode decision. It returns
`1` = enter download mode, `2` = DKB payload path, `3` = normal boot.

Decompiled, in order:

```c
if (FUN_003f1dcc() == 0xd) {                 /* [OBS] */
    print("User force to download");  return 1;
}
if (rec->DLFG == 0x47464c44 && rec->DLOK != 0x4b4f4c44) {   /* [OBS] */
    print("Wait for download change timeout to true...");  return 1;
}
if ((_DAT_d428287c & 0x8000) == 0) return 3;                /* [OBS] */
```

**[OBS]** The four 4-character tags, decoded from the little-endian
immediates:

| dword | bytes | tag |
|---|---|---|
| `0x444B4249` | `IBKD` | DKB / flasher payload record |
| `0x47464C44` | `DLFG` | download flag |
| `0x4B4F4C44` | `DLOK` | download-ok latch |
| `0x4C444F4E` | `NODL` | "no download" (production skip) |
| `0x4F544149` | `IATO` | the config partition record |

**[OBS]** `FUN_003f97fc(context, 0x444B4249)` is a record-table search: it
walks entries of stride `0x40` (or `0x60` when the header word at offset `0`
exceeds `0x303FF`), comparing the first dword of each entry against the tag.
`FUN_003eeacc` calls it with `IBKD`; **if an `IBKD` record is present it
returns 2 instead of 1**. So `IBKD` presence is what selects the DKB-payload
path — this is the device-side confirmation that the 4-byte tag the host tool
prepends to `Dkb.bin` is the tag the OBM actually looks for.

---

## 3. The latch, and why the board never waits for us

**[OBS]** `rec` comes from `FUN_003f2c18`, which locates the record tagged
`IATO` and reads **0x110 bytes** into a RAM buffer. Field offsets used by the
gate are `+0x8C` (`DLFG`) and `+0x90` (`DLOK`); `+0x30` is `booting_mode`.

**[OBS]** In mtd0's own TIM table, the `IATO` entry carries the dword
`0x05F00000` — which is exactly the flash base of **mtd19**.

**[OBS]** mtd19 offset `0x00` is a 0x110-byte record followed by `0xFF`, with:

```
000080  00 00 00 00 4f 42 4d 44 00 00 00 00 44 4c 46 47  |....OBMD....DLFG|
000090  44 4c 4f 4b 00 ...                              |DLOK............|
0000f8  00 00 00 00 00 00 00 00 00 00 00 00 4e 4f 43 50  |............NOCP|
```

Offsets match the decompiled gate exactly: `OBMD` at `+0x84`, **`DLFG` at
`+0x8C`, `DLOK` at `+0x90`**, `NOCP` at `+0x108`.

**[OBS]** On this unit `DLFG == "DLFG"` **and** `DLOK == "DLOK"`, so the
condition `DLFG=="DLFG" && DLOK!="DLOK"` is **false**. The board therefore does
not take the download path at all, and boots straight through to U-Boot.

**[INF]** This is the answer to open question A of
[`SWDownloader-handoff.md`](SWDownloader-handoff.md) §6. The unit is not
racing us on a short window; the download latch has already been **closed**,
and every earlier "the device only appears for 1.58 s" observation was a
*power-on* artefact of a different route (the force-download strap), not a
window we were losing.

**Proposed test.** Clear `DLOK` (write `00000000` to mtd19 offset `0x90`). The
gate is evaluated before the fuse check and before any timeout, so this should
put the board into download mode on **every** boot, with no race against the
tool. `tools/mtd19-force-download.py` prepares this on a copy.

**[INF], and it may defeat itself.** In the download path the OBM itself
stamps the latch:

```c
if (_DAT_004029dc != 0) {          /* "isDownload=" / "bootMode=" */
    rec = FUN_003f2c18(...);
    *(uint32 *)(rec + 0x8c) = 0x47464c44;   /* DLFG */
    *(uint32 *)(rec + 0x90) = 0x4b4f4c44;   /* DLOK */
    if (FUN_003f2dd8(...)) print("OTA_Save_Config error");
}
```

So entering download mode may re-close the latch. **[UNK]** whether this
write persists, and whether the wait is bounded before or after it.

---

## 4. The download wait is a variable, not a constant

**[OBS]** `FUN_003ef72c` is the entry for modes 1 and 2:

```c
uVar1 = FUN_003ef4f4();
if (_DAT_004029dc == 0) {                 /* isDownload == 0 */
    if (DAT_00403be1 == 0) return FUN_003ef3e4(...);   /* no wait -> boot */
    if (DAT_00403be2 != 0) usleep(DAT_00403be2 * 1000000);
    FUN_003f4564();
    FUN_003f2098();                      /* start the download server */
}
```

`DAT_00403be1` is an enable flag and **`DAT_00403be2` is the wait in seconds**.
It is not a ROM constant.

**[OBS]** `FUN_003f5d58` assigns both from a 0x10-byte options block and
labels them `ResetUE` and `ResetDelay`:

```c
FUN_003e8e28(local_30, _DAT_00403bb4 + 8, 0x10);
...
DAT_00403be2 = local_22;   /* offset 13 of the block */
DAT_00403be1 = local_23;   /* offset 12 of the block */
print("ResetUE");   print(DAT_00403be1);
print("ResetDelay"); print(DAT_00403be2);
```

**[INF]** This is the device-side counterpart of the `.blf` keys the spec
already recovered — `ResetUE_AfterUpload` and `Reset_DelayTime` — and of the
`[UE_Options]` section. The same 0x10-byte block therefore carries the
download wait, and raising it is the second lever on the window.

**[UNK]** which flash record `_DAT_00403bb4` is loaded from, and whether the
block is writable. It is not in mtd19's first 0x110 bytes under those names.

---

## 5. State of the checklist

| question | status |
|---|---|
| How is download mode entered? | **answered** — three gates, §2 |
| Why does this unit not wait for a downloader? | **answered** — latch closed, §3 |
| Is the wait a fixed constant? | **no** — it is `ResetDelay` seconds, §4 |
| Why does the device go mute after the DKB lands? | **open** — §6 |
| Where does `_DAT_00403bb4` come from? | **open** |

## 6. Still open: the DKB handoff

**[OBS]** `IBKD` present selects return value 2, which enters the same
`FUN_003ef72c` handler. **[UNK]** what the OBM does with the IBKD record's
payload afterwards, and at what address it jumps.

**[INF], worth checking first.** `Dkb.bin` as the tool builds it is the whole
`mtd0.bin` partition — a TIM header, 0x1E000 bytes of padding, then the image
at `+0x20000`. If the OBM jumps to the start of the received blob it would land
in TIM header data rather than code, and the device would go silent exactly as
observed. The payload may be expected to be a bare RAM flasher image rather
than a TIM-wrapped partition. Not yet confirmed either way.

---

## 7. Reproducing

The Ghidra session needs the load base; a bare `open_binary` on the partition
will mis-map it.

```sh
python3 - <<'EOF'
d=open('mtd0.bin','rb').read()
open('obm_code.bin','wb').write(d[0x20000:0x20000+0x1A9B0])
EOF
npx -y rea-agents@6.5.0 analyze obm_code.bin \
    --target-format raw-binary --architecture arm --entry-point 0x3e8000
```

Working directory for all of the above: `flashing_tools/p298-swd`-style scratch,
**never** `flashing_tools/Marvell_SWDownloader_v4.8.8.2/`, whose `mtd7.bin` is a
symlink into `findings/nand-dumps/`.
