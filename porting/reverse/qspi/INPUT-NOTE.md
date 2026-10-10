# QSPI register extraction — input note

`vmlinux.extracted` is **not** a vmlinux. It is a symlink to
`findings/firmware-backup/kernel-a.bin`, i.e. the **raw stock zImage**
(5,242,880 bytes, with the vendor DTB appended at offset `0x2b9ef0`).

The naming was misleading: nothing was "extracted" from it. It is the stock
kernel image verbatim, kept under an old name so existing commands and notes
keep working.

For the actual disassembly artefacts in this directory see:

| file | what it is |
|---|---|
| `Image.from_gzip` | the vendor `Image` after gunzip |
| `Image.disasm` | its disassembly (gitignored, ~47 MB) |
| `disasm.err` | disassembly errors / warnings |
| `extract_qspi.py` | the script that produced the above |

Vendor DT bindings extracted from that image are tracked upstream in
[`clock_re/`](../clock_re/) and the DTS files in this directory.
