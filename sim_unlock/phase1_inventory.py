#!/usr/bin/env python3
"""
Phase 1: Inventory & Backup script for Notion R291 (Ooredoo)
Executes system reconnaissance via SSH root shell and dumps critical partitions (mtd1, mtd2, mtd3, mtd5)
to the sim_unlock/ directory for offline analysis.
"""

import os
import sys
import time

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

def get_transport():
    t = paramiko.Transport((ROUTER_IP, SSH_PORT))
    t._preferred_kex = ("diffie-hellman-group1-sha1", "diffie-hellman-group14-sha1")
    t._preferred_keys = ("ssh-rsa",)
    t.connect(username=SSH_USER, password=SSH_PASS)
    return t

def exec_cmd(t, cmd):
    ch = t.open_session()
    ch.exec_command(cmd)
    time.sleep(0.5)
    out = b""
    while ch.recv_ready():
        out += ch.recv(8192)
    ch.close()
    return out.decode(errors="replace")

def download_file(t, remote_path, local_path):
    print(f"[*] Downloading {remote_path} -> {local_path} ...")
    ch = t.open_session()
    ch.exec_command(f"cat {remote_path}")
    time.sleep(1)
    with open(local_path, "wb") as f:
        while ch.recv_ready():
            f.write(ch.recv(65536))
    ch.close()
    print(f"[+] Saved {local_path} ({os.path.getsize(local_path)} bytes)")

def main():
    print(f"[*] Connecting to {ROUTER_IP}:{SSH_PORT} as {SSH_USER} ...")
    try:
        t = get_transport()
    except Exception as e:
        print(f"[-] Connection failed: {e}")
        sys.exit(1)
    print("[+] Connected successfully!")

    # 1. Gather reconnaissance commands
    commands = {
        "uname.txt": "uname -a",
        "cpuinfo.txt": "cat /proc/cpuinfo",
        "meminfo.txt": "cat /proc/meminfo",
        "mtd.txt": "cat /proc/mtd",
        "partitions.txt": "cat /proc/partitions",
        "iomem.txt": "cat /proc/iomem",
        "dev_nodes.txt": "ls -la /dev/ci* /dev/tty* /dev/mmc* /dev/usb* 2>/dev/null",
        "processes.txt": "ps aux",
        "usr_bin.txt": "ls -la /usr/bin /usr/sbin /rom/bin /rom/usr/bin 2>/dev/null",
        "nvm_files.txt": "find /overlay/root/NVM -ls 2>/dev/null",
        "slic_config.txt": "cat /etc/config/slic 2>/dev/null",
        "properties_config.txt": "cat /etc/config/properties 2>/dev/null",
    }

    for filename, cmd in commands.items():
        filepath = os.path.join(OUT_DIR, filename)
        print(f"[*] Running: {cmd} -> {filename}")
        res = exec_cmd(t, cmd)
        with open(filepath, "w", encoding="utf-8") as f:
        	f.write(res)

    # 2. Dump critical MTD partitions
    # mtd1 = cp_reliabledata (NVM/MEP)
    # mtd2 = factory (calibration)
    # mtd3 = cp_reliabledata_backup
    # mtd5 = mep-ota
    partitions_to_dump = {
        "mtd1_cp_reliabledata.bin": "/dev/mtd1",
        "mtd2_factory.bin": "/dev/mtd2",
        "mtd3_cp_reliabledata_bak.bin": "/dev/mtd3",
        "mtd5_mep_ota.bin": "/dev/mtd5",
    }

    for local_name, remote_dev in partitions_to_dump.items():
        local_path = os.path.join(OUT_DIR, local_name)
        try:
            download_file(t, remote_dev, local_path)
        except Exception as e:
            print(f"[-] Failed to dump {remote_dev}: {e}")

    t.close()
    print("[+] Phase 1 inventory & backup completed successfully!")

if __name__ == "__main__":
    main()
