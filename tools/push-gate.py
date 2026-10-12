#!/usr/bin/env python3
"""Pre-push gate for the asr1802s OpenWrt work.

Everything in here exists because the openwrt-ai review bot caught it and we
did not. Each check is named after the mistake it prevents.

Run standalone:
    python3 tools/push-gate.py [--base upstream/master]

Installed as a git pre-push hook on the fork, so a push cannot happen without
it running.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tarfile

FORK = "/home/void/Downloads/openwrt/openwrt-fork"
TARBALL = os.path.join(FORK, "dl/linux-6.18.55.tar.xz")
SERIES = "target/linux/asr1802s/patches-6.18"

failures: list[str] = []
notes: list[str] = []


def fail(check: str, msg: str) -> None:
    failures.append(f"[{check}] {msg}")


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", FORK, *args], text=True).strip()


_TAR_MEMBERS: set[str] | None = None


def tar_has(path: str) -> bool:
    """True if `path` exists anywhere in the pristine kernel tarball.

    The member list is read once and cached: re-scanning the ~1.2 GB archive
    for every #include made the gate unusably slow.
    """
    global _TAR_MEMBERS
    if _TAR_MEMBERS is None:
        with tarfile.open(TARBALL, "r:xz") as tf:
            _TAR_MEMBERS = {m.name for m in tf.getmembers()}
    return f"linux-6.18.55/{path}" in _TAR_MEMBERS


# --------------------------------------------------------------------------
# 1. commit-message form
#    Bot: "missing Signed-off-by", over-long subject, merge commits.
# --------------------------------------------------------------------------
def check_commits(base: str) -> None:
    shas = git("rev-list", "--reverse", f"{base}..HEAD").split()
    seen: dict[str, str] = {}

    for sha in shas:
        subj = git("show", "-s", "--format=%s", sha)
        body = git("show", "-s", "--format=%b", sha)
        ident = subj[:12]

        if not body.strip():
            fail("commit-body", f"{sha[:8]}: empty commit message")
        if "Signed-off-by:" not in body:
            fail("signoff", f"{sha[:8]} {ident}: missing Signed-off-by")
        if len(subj) > 60:
            fail("subject-len",
                 f"{sha[:8]} {ident}: subject is {len(subj)} chars (max 60)")
        for i, line in enumerate(body.splitlines(), 1):
            if len(line) > 100:
                fail("body-len",
                     f"{sha[:8]}: body line {i} is {len(line)} chars (max 100)")
        key = re.sub(r"\W+", "", body.lower())[:120]
        if key in seen:
            fail("dup-body",
                 f"{sha[:8]} {ident}: body duplicates {seen[key][:8]}")
        seen[key] = sha

    if git("log", "--merges", "--oneline", f"{base}..HEAD"):
        fail("merge-commit", "series contains a merge commit")


# --------------------------------------------------------------------------
# 2. file hygiene
#    Bot: "File README.md is missing a trailing newline".
# --------------------------------------------------------------------------
def check_files(base: str) -> None:
    for f in git("diff", "--name-only", f"{base}..HEAD").splitlines():
        p = os.path.join(FORK, f)
        if not os.path.isfile(p):
            continue
        with open(p, "rb") as fh:
            data = fh.read()
        if not data:
            continue

        if not data.endswith(b"\n"):
            fail("eof-newline", f"{f}: missing trailing newline")
        if b"\r\n" in data:
            fail("crlf", f"{f}: contains CRLF line endings")
        if data.endswith(b"\n\n"):
            fail("eof-blank", f"{f}: ends with a blank line")

        # Trailing whitespace only matters outside unified-diff bodies, where
        # a " " or "+ " line is the normal encoding of a blank source line.
        text = data.decode("utf-8", "replace")
        first_hunk = next(
            (i for i, l in enumerate(text.splitlines()) if l.startswith("@@")), None)
        for i, line in enumerate(text.splitlines(), 1):
            if first_hunk is not None and i > first_hunk:
                break
            if line != line.rstrip() and not re.match(r"^[+\-\s]", line):
                fail("trailing-ws", f"{f}:{i}: trailing whitespace")


# --------------------------------------------------------------------------
# 3. the patch series still applies to a pristine kernel
# --------------------------------------------------------------------------
def check_series_applies() -> None:
    if not os.path.exists(TARBALL):
        notes.append("kernel tarball absent; skipped series-apply check")
        return
    r = subprocess.run(["bash", "/tmp/opencode/apply618.sh"],
                       capture_output=True, text=True)
    if "FAIL" in r.stdout or r.returncode != 0:
        bad = [l.strip() for l in r.stdout.splitlines() if "FAIL" in l]
        fail("series-apply", "patch does not apply cleanly: " + "; ".join(bad))


# --------------------------------------------------------------------------
# 4. binding examples only #include headers that exist
#    Bot: "Neither header exists: there is no dt-bindings/.../icu.h anywhere".
# --------------------------------------------------------------------------
def check_binding_includes() -> None:
    headers_created = set()
    for f in os.listdir(os.path.join(FORK, SERIES)):
        p = os.path.join(FORK, SERIES, f)
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = re.match(r"\+\+\+ b/include/(dt-bindings/\S+)", line)
                if m:
                    headers_created.add(m.group(1))

    for f in os.listdir(os.path.join(FORK, SERIES)):
        p = os.path.join(FORK, SERIES, f)
        with open(p, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, 1):
                m = re.match(r"\+\s*#include <(dt-bindings/[^>]+)>", line)
                if not m:
                    continue
                hdr = m.group(1)
                if hdr in headers_created:
                    continue
                if not tar_has("include/" + hdr):
                    fail("dangling-include",
                         f"{f}:{i}: #include <{hdr}> exists nowhere")


# --------------------------------------------------------------------------
# 5. no vendor prefix is registered unless the DTS actually uses it
#    Bot: "The notion prefix is registered, but nothing uses it".
# --------------------------------------------------------------------------
def check_vendor_prefixes() -> None:
    p = os.path.join(FORK, SERIES, "0001-dt-bindings-vendor-prefixes-add-ASR-Microelectronics.patch")
    if not os.path.exists(p):
        return
    added = []
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = re.match(r'\+\s*"\^([a-z0-9-]+),\.\*":', line)
            if m:
                added.append(m.group(1))
    if not added:
        return

    # every compatible / *-gpios phandle-ish reference across the series
    body = ""
    for f in os.listdir(os.path.join(FORK, SERIES)):
        with open(os.path.join(FORK, SERIES, f),
                  encoding="utf-8", errors="replace") as fh:
            body += fh.read()

    for pfx in added:
        if not re.search(r'"%s,' % re.escape(pfx), body):
            fail("unused-prefix",
                 f"vendor prefix '{pfx}' is registered but never used in a compatible")


# --------------------------------------------------------------------------
# 6. identifiers quoted in a commit body must exist in that commit's tree
#    Bot-adjacent, but this is the class that bit us repeatedly:
#    claiming "TX descriptors of 32 bytes" when the driver says 16, claiming a
#    "kmod-asr1802s-qspi" entry that was never added, attributing David Yang's
#    driver to ourselves. These are prose-vs-code contradictions.
# --------------------------------------------------------------------------
def check_commit_claims(base: str) -> None:
    shas = git("rev-list", "--reverse", f"{base}..HEAD").split()
    for sha in shas:
        body = git("show", "-s", "--format=%b", sha)
        files = git("show", "--name-only", "--format=", sha).splitlines()
        tree = ""
        for f in files:
            p = os.path.join(FORK, f)
            if os.path.isfile(p):
                with open(p, encoding="utf-8", errors="replace") as fh:
                    tree += fh.read()
        if not tree:
            continue

        # "adds a `kmod-x` entry" must correspond to a real definition
        for m in re.finditer(r"`(kmod-[a-z0-9-]+)`", body):
            if m.group(1) not in tree:
                fail("false-claim",
                     f"{sha[:8]}: body names {m.group(1)}, which this commit "
                     f"does not add")
        # numeric byte sizes must match a define
        for m in re.finditer(r"`?([A-Z_]+)`?\s+(?:is|are)\s+(\d+)\s+bytes", body):
            name, val = m.group(1), m.group(2)
            d = re.search(r"#define\s+%s\s+(\d+)" % re.escape(name), tree)
            if d and d.group(1) != val:
                fail("false-claim",
                     f"{sha[:8]}: body says {name} is {val} bytes, "
                     f"driver says {d.group(1)}")


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="upstream/master")
    ap.add_argument("--skip-slow", action="store_true",
                    help="skip the series-apply check (slow: re-extracts the kernel)")
    args = ap.parse_args()

    check_commits(args.base)
    check_files(args.base)
    check_binding_includes()
    check_vendor_prefixes()
    check_commit_claims(args.base)
    if not args.skip_slow:
        check_series_applies()

    for n in notes:
        print("note: " + n)

    if failures:
        print(f"\nPUSH GATE FAILED — {len(failures)} problem(s):\n")
        for f in failures:
            print("  " + f)
        return 1

    print("\nPUSH GATE PASSED\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())