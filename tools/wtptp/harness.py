"""Run the client against every behaviour model and report what happens.

This is the deliverable that makes the simulator worth having: a table of
which device behaviours the client survives, and -- just as useful -- which
ones it cannot tell apart. Anything it cannot distinguish is a place where we
would be guessing on real hardware.
"""

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from wtptp import device as D
    from wtptp import protocol as P
    from wtptp.client import DeviceMuted, WtptpClient, WtptpError
    from wtptp.transport import LoopbackTransport
else:
    from . import device as D
    from . import protocol as P
    from .client import DeviceMuted, WtptpClient, WtptpError
    from .transport import LoopbackTransport


def build_dkb(payload: bytes, *, magic=b"IBKD", timhdr=True) -> bytes:
    """Build a DKB the way swdl_linux does: a 4-byte magic then the payload.

    VERIFIED: Dkb.bin[0:4] == b"IBKD" and Dkb.bin[4:] == the OBMI image.
    """
    body = payload
    if timhdr:
        body = P.TIM_VERSION.to_bytes(4, "little") + P.TIM_MAGIC + payload
    return magic + body


def run_model(name, params, dkb, fbf, verbose=False):
    dev = D.SimDevice(verbose=verbose, **params)
    cli = WtptpClient(LoopbackTransport(dev), log=lambda m: None)
    outcome = "completed"
    failed_at = None
    try:
        cli.run(dkb, fbf)
    except DeviceMuted as e:
        outcome = f"MUTED: {e}"
        failed_at = dev.images_seen + 1
    except WtptpError as e:
        outcome = f"ERROR: {e}"
        failed_at = dev.images_seen + 1
    except Exception as e:                       # noqa: BLE001
        outcome = f"CRASH: {type(e).__name__}: {e}"
        failed_at = dev.images_seen + 1
    return outcome, dev.stage.value, dev, failed_at


NAMES = {1: "DKB", 2: "FBF"}


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    verbose = "-v" in argv

    # Stand-in payloads. The real ones come out of temp/ after a
    # MakeDownloadPackage run; only the sizes matter here.
    dkb_ok = build_dkb(b"\x00" * 4096)
    dkb_bad_magic = build_dkb(b"\x00" * 4096, magic=b"XXXX")
    dkb_no_tim = build_dkb(b"\x00" * 4096, timhdr=False)
    fbf = b"\x00" * 256

    cases = [
        ("mute_after_dkb",        "mute_after_dkb",    dkb_ok),
        ("stay_awake",            "stay_awake",        dkb_ok),
        ("require_valid_dkb",     "require_valid_dkb", dkb_ok),
        ("  ^ same, bad magic",   "require_valid_dkb", dkb_bad_magic),
        ("require_timhdr",        "require_timhdr",    dkb_ok),
        ("  ^ same, no TIM hdr",  "require_timhdr",    dkb_no_tim),
        ("reset_usb",             "reset_usb",         dkb_ok),
    ]

    print(f"{'model':<24} {'failed at':<10} {'device stage':<14} result")
    print("-" * 84)
    rows = []
    for label, model, dkb in cases:
        outcome, stage, dev, failed_at = run_model(
            model, D.MODELS[model], dkb, fbf, verbose)
        rows.append((label, stage, outcome, dev, failed_at))
        where = NAMES.get(failed_at, "-") if failed_at else "-"
        print(f"{label:<24} {where:<10} {stage:<14} {outcome.split(':')[0]}")
        if verbose:
            for line in dev.log:
                print(f"      {line}")

    # The thing worth reading: which device behaviours can the client actually
    # tell apart? Two models that fail at the same point, with the same
    # message, are indistinguishable on real hardware -- and that is exactly
    # where we would be guessing.
    print()
    groups = {}
    for label, stage, outcome, _dev, failed_at in rows:
        key = (failed_at or 0, outcome)
        groups.setdefault(key, []).append(label)
    print("client-visible outcomes (grouped by WHERE it failed):")
    for (failed_at, outcome), labels in sorted(groups.items()):
        where = NAMES.get(failed_at, "-") if failed_at else "-"
        print(f"  [{len(labels)}] fails at {where}: {outcome.split(':')[0]}")
        for l in labels:
            print(f"        {l}")
    return 0


if __name__ == "__main__":
    sys.exit(main())