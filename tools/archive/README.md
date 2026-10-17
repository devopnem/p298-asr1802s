# `tools/archive/` — superseded, kept for provenance only

**Do not use anything in here.** These target binaries and packaging paths we
no longer run. They are kept only so that claims made in the recovery docs stay
auditable.

Moved 2026-10-17.

## Why they were retired

The campaign now runs the vendor's documented Linux flow from **SWDownloader
5.0.0.2**:

```
fbfmake -r <blf> -f <outdir>       # build
fbfdownloader -b BinFile.bin        # flash
```

`fbfdownloader` reproduces the stall on a code path with no BLF parsing, no
image list and no per-image loop, which is what cleared the BLF as a cause.
The older entry point and its patch family no longer contribute evidence.

## What each one was

### Binary patches against `swdl_linux` (5.0.0.1 / 5.0.0.2)

All seven rewrite a fixed instruction sequence inside the stripped, non-PIE
`swdl_linux` image. They are byte-offset dependent: a different build
invalidates every one of them.

| file | what it patched |
|---|---|
| `swdl-budget.py` | capped the download byte budget |
| `swdl-chunksize-patch.py` | forced the USB chunk size at `0x08133830` |
| `swdl-platform-patch.py` | rewrote the platform/type decision |
| `swdl-reopen-patch.py` | forced a device re-open (the old `EBUSY` blocker) |
| `swdl-teardown-patch.py` | changed teardown ordering |
| `swdl-timeout-patch.py` | forced a non-zero WTPTP timeout |
| `swdl-whitelist-patch.py` | four-byte whitelist edit, the least invasive |
| `swdl-crash.gdb` | GDB script for the old parser segfault |

### Superseded BLF generators

| file | replaced by |
|---|---|
| `mk-single-image-blf.py` | `tools/mk-openwrt-blf.py` |
| `mk-mtd21-blf.py` | `tools/mk-openwrt-blf.py` |
| `mtd19-force-download.py` | `mk-openwrt-blf.py --slot-flag` |

`mk-openwrt-blf.py` gained two-run support, so the separate slot-switch package
is no longer needed. That is why the A/B switch is now written as its own run
rather than carried in a combined package — the downloader orders FBF images by
partition number **descending**, so `mtd19` would be written first regardless of
where it appears in the chain.

## One thing here is still worth reading

`swdl-chunksize-patch.py` documents the observation that the **device** dictates
the chunk size (`BufferSize is 0xF8` = 248), and that `CWtpComm::Data` would
accept up to `0x4000`. That is a property of the board, not of these scripts, and
it is recorded in `docs/recovery/SWDownloader-handoff.md` §11d.