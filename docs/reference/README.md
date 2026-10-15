# Reference material — what it covers and what it does not

## `air720-asr1802-pxa1802-webui-at-commands.txt`

Obtained from `https://www.cnblogs.com/DirWang/p/18928955`.

Translated summary of the ASR1802 / PXA1802 / ASR1803 MiFi **web UI and AT
command** architecture: the `xml_action.cgi?method=get&module=duster&file=lan`
request flow, the `lan.xml` schema, the 27 `webdata/xmldata` modules, and the
identity AT commands (`AT*MRD_IMEI`, `AT+MIFIMAC`, `AT*MRD_SN`,
`AT*MRD_SECOND_SN`, `AT+clck`).

### Relevance to the P298 recovery: NONE

Checked exhaustively rather than skimmed. Zero occurrences of `uboot`, `mtd`,
`SWDownloader`, `WTPTP`, `blf`, `DKB`, `FBF`, `OBM`, `partition`, `jtag`,
`uart`, `erase`, `flash`, `env`, `rsa`. The single `download` hit is in a
Quark-drive advertisement at the end of the file.

It also describes the **wrong chip** in at least one place — the `AT*READVER`
sample output reports `HW: ASR1803_EVB_V1.0`, which is PXA1826, our sibling
part, not the PXA1802.

The file is machine-translated and lightly edited; line 51 contains a scrape
artefact (`module_post_get_get_get_...` repeated several hundred times).

### What it IS good for

Identity data handling, which is relevant to `ops/sim-unlock` rather than to
the recovery work:

```
AT*MRD_IMEI=W,0101,12NOV2010,01234567890123   write IMEI to RD
AT+MIFIMAC=W,1234567890E3                     set MAC
```

There is also a Quark drive link at the end of the file
(`https://pan.quark.cn/s/039d62a27f39`, "ASR1802 data.zip"). Provenance
unknown, requires the Quark app and account. Nothing from it should be flashed
without the usual verification against `mtd0.bin`.

## What we are actually still looking for

None of the above unblocks the recovery. The two items that would:

1. **A genuine vendor `.blf`** — e.g. `Nezha_B0_MiFi2_Nontrusted.blf`, named in
   the PXA1802 burning guide at `https://bbs.16rd.com/thread-606171-1-1.html`.
   Read its `OBMI` entry and compare `2_Image_Path` and `2_Image_Load_Address`
   against ours (`mtd0.bin`, `0x01C00000`).
2. **`IFL SWD UserGuidev1_0.pdf` and `How_to_add_a_file_in_blf.7z`** from the
   ASR document archive at `http://www.nz998.com/other/216477.html` (2 coins).
   These are the SWD protocol guide and the `.blf` authoring guide — the two
   things we reverse-engineered by hand.