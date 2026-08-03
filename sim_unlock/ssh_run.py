#!/usr/bin/env python3
"""
Generic SSH runner for the Notion R291 router.
Usage: python3 ssh_run.py "command" [--save filename] [--timeout N]
Connects via paramiko with legacy kex, runs the command, prints output,
optionally saves raw output into sim_unlock/.
"""
import os
import sys
import time
import argparse

try:
    import paramiko
except ImportError:
    print("[-] paramiko is required: pip install paramiko")
    sys.exit(1)

ROUTER_IP = "192.168.1.1"
SSH_PORT = 22
SSH_USER = "root"
SSH_PASS = "19222019"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def connect():
    t = paramiko.Transport((ROUTER_IP, SSH_PORT))
    t._preferred_kex = ("diffie-hellman-group1-sha1", "diffie-hellman-group14-sha1")
    t._preferred_keys = ("ssh-rsa",)
    t.connect(username=SSH_USER, password=SSH_PASS)
    return t


def exec_cmd(t, cmd, wait=0.6, timeout=30):
    ch = t.open_session()
    ch.exec_command(cmd)
    time.sleep(wait)
    out = b""
    deadline = time.time() + timeout
    last_data = time.time()
    while time.time() < deadline:
        while ch.recv_ready():
            out += ch.recv(65536)
            last_data = time.time()
        if ch.exit_status_ready():
            # keep draining until 0.8s of silence to avoid truncation
            if time.time() - last_data > 0.8:
                break
        time.sleep(0.15)
    while ch.recv_ready():
        out += ch.recv(65536)
    ch.close()
    return out.decode(errors="replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="+", help="command to run on the router")
    ap.add_argument("--save", default=None, help="save output to this file (in sim_unlock)")
    ap.add_argument("--wait", type=float, default=0.6)
    ap.add_argument("--timeout", type=float, default=20)
    args = ap.parse_args()
    cmd = " ".join(args.cmd)

    t = connect()
    res = exec_cmd(t, cmd, wait=args.wait, timeout=args.timeout)
    t.close()
    sys.stdout.write(res)
    sys.stdout.flush()
    if args.save:
        path = os.path.join(OUT_DIR, args.save)
        with open(path, "w", encoding="utf-8", errors="replace") as f:
            f.write(res)
        print(f"\n[+] saved -> {path}")


if __name__ == "__main__":
    main()
