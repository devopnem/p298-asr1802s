#!/usr/bin/env python3
"""
Run Phase 1: Enable SSH via API (eng_mode + reboot), then run inventory & MTD backup.
"""

import sys
import os
import time

# Add modular_tests to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../modular_tests")))

import api_login
import api_ssh
import phase1_inventory

def main():
    print("[*] Step 1: Logging in to router API ...")
    if not api_login.login():
        print("[-] API login failed!")
        sys.exit(1)
    print("[+] API login successful.")

    print("[*] Step 2: Enabling SSH via api_ssh.full_enable_ssh() ...")
    res = api_ssh.full_enable_ssh()
    print(f"[*] full_enable_ssh result: {res}")

    if not res.get("success"):
        print("[-] Failed to open SSH port. Trying to check SSH port directly...")
        status = api_ssh.check_ssh_port()
        print(f"    SSH status: {status}")
        if not status["open"]:
            print("[-] SSH port is still closed. Exiting.")
            sys.exit(1)

    print("[*] Step 3: Running inventory and MTD partition dumps ...")
    phase1_inventory.main()
    print("[+] Phase 1 completed successfully!")

if __name__ == "__main__":
    main()
