#!/usr/bin/env python3
"""
Phase 2: MEP / SIM-lock unlock tool for Notion R291 (Ooredoo) — ASR1802S CP.

Method (official for this device family, from unlock.txt):
    AT%EXE="serial_atcmd AT+CLCK=PN,0,<MEP-password>,16"
sent via the RGW API `version/set_atcmd_info`.

Password source: last printable string of /tmp/mep1 (== strings /dev/mtd1 | tail -1).

Usage:
    python3 phase2_unlock.py --query      # read-only: query lock state (AT+CLCK=PN,2)
    python3 phase2_unlock.py --status     # read-only: sim/get_sim_status + /tmp/mep1 info
    python3 phase2_unlock.py --unlock     # perform the permanent unlock
    python3 phase2_unlock.py --verify     # re-check lock state after unlock
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../ops/api")))

import api_login

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(OUT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

ROUTER_IP = "192.168.1.1"
SSH_USER = "root"
SSH_PASS = "19222019"

MEP_PASSWORD = "80822207"  # from /tmp/mep1 last string; will be re-verified at runtime


def log(msg):
    print(msg, flush=True)
    with open(os.path.join(LOG_DIR, "phase2_unlock.log"), "a") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def ssh_run(cmd, wait=1.0, timeout=25):
    """Run a command on the router over SSH (legacy kex)."""
    import paramiko
    t = paramiko.Transport((ROUTER_IP, 22))
    t._preferred_kex = ("diffie-hellman-group1-sha1", "diffie-hellman-group14-sha1")
    t._preferred_keys = ("ssh-rsa",)
    t.connect(username=SSH_USER, password=SSH_PASS)
    ch = t.open_session()
    ch.exec_command(cmd)
    time.sleep(wait)
    out = b""
    deadline = time.time() + timeout
    last = time.time()
    while time.time() < deadline:
        while ch.recv_ready():
            out += ch.recv(65536)
            last = time.time()
        if ch.exit_status_ready() and time.time() - last > 0.6:
            break
        time.sleep(0.15)
    while ch.recv_ready():
        out += ch.recv(65536)
    ch.close()
    t.close()
    return out.decode(errors="replace")


def send_atcmd(atcmd):
    """Send an AT command via version/set_atcmd_info (AT%EXE wrapper). Returns API response."""
    cmd = f'AT%EXE="serial_atcmd {atcmd}"'
    log(f"[API] set_atcmd_info -> {cmd}")
    resp = api_login.api_call("version", "set_atcmd_info", {"atcmd": cmd})
    log(f"[API] response: {resp}")
    time.sleep(2.5)
    atcmdrec = ssh_run("cat /tmp/atcmdrec 2>/dev/null; echo; echo ---; cat /tmp/atresprec 2>/dev/null")
    log(f"[MODEM] atcmdrec : {atcmdrec}")
    return resp, atcmdrec


def get_mep_password():
    """Re-read the MEP password from the live router (strings /tmp/mep1 | tail -1)."""
    raw = ssh_run("strings /tmp/mep1 2>/dev/null | tail -1")
    pw = raw.strip()
    log(f"[MEP] live password from /tmp/mep1: '{pw}'")
    if pw:
        return pw
    return MEP_PASSWORD


def cmd_status():
    resp = api_login.api_call("sim", "get_sim_status")
    log(f"[API] sim/get_sim_status -> {resp}")
    raw = ssh_run("ls -la /tmp/mep1 /tmp/atcmdrec /tmp/atresprec 2>&1; echo; strings /tmp/mep1 2>/dev/null | tail -3")
    log(f"[ROUTER] mep1/at files:\n{raw}")


def cmd_query():
    log("=== QUERY lock state (read-only) ===")
    resp, rec = send_atcmd("AT+CLCK=PN,2")
    log(f"[RESULT] query done; check logs for AT+CLCK=PN,2 response")


def cmd_unlock():
    log("=== UNLOCK: AT+CLCK=PN,0,<pw>,16 ===")
    pw = get_mep_password()
    atcmd = f"AT+CLCK=PN,0,{pw},16"
    log(f"[UNLOCK] sending: {atcmd}")
    resp, rec = send_atcmd(atcmd)
    log("[UNLOCK] done. Next: insert a non-Ooredoo SIM and run --verify")


def cmd_verify():
    log("=== VERIFY ===")
    resp, rec = send_atcmd("AT+CLCK=PN,2")
    st = api_login.api_call("sim", "get_sim_status")
    log(f"[API] sim/get_sim_status -> {st}")
    log("[VERIFY] check atresprec above: expect '+CLCK: 0' (unlocked) or 'ERROR'")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", action="store_true", help="query lock state (read-only)")
    ap.add_argument("--status", action="store_true", help="device/SIM status (read-only)")
    ap.add_argument("--unlock", action="store_true", help="perform permanent MEP unlock")
    ap.add_argument("--verify", action="store_true", help="verify lock state after unlock")
    args = ap.parse_args()

    log("=" * 60)
    log("Phase 2 — MEP/SIM unlock — Notion R291 Ooredoo")
    log("=" * 60)

    if not api_login.login():
        log("[-] API login FAILED")
        sys.exit(1)
    log("[+] API login OK")

    if args.status:
        cmd_status()
    if args.query:
        cmd_query()
    if args.unlock:
        cmd_unlock()
    if args.verify:
        cmd_verify()
    if not (args.status or args.query or args.unlock or args.verify):
        ap.print_help()


if __name__ == "__main__":
    main()
