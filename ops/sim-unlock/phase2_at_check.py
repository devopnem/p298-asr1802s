#!/usr/bin/env python3
"""
Phase 2: AT communication script via SSH on Notion R291.
Sends AT commands to the CP modem interface (/dev/cidatatty0 or /dev/ttymodem0)
and tests production mode / MEP read commands.
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

def main():
    print("[*] Connecting to router via SSH for Phase 2 AT checks ...")
    try:
        t = get_transport()
    except Exception as e:
        print(f"[-] Connection failed: {e}")
        sys.exit(1)

    # Test sending AT commands using python on the router or via echo to tty
    # We will write a small python helper on the router or execute python -c via SSH
    at_script = """
import serial
import time

ports = ['/dev/cidatatty0', '/dev/ttymodem0', '/dev/citty0']
for p in ports:
    print(f"=== Testing port: {p} ===")
    try:
        ser = serial.Serial(p, 115200, timeout=2)
        ser.write(b'AT\\r\\n')
        time.sleep(0.5)
        res = ser.read_all()
        print(f"AT response: {res}")
        
        # Try production mode & MEP read
        commands = [b'AT+CFUN?\\r\\n', b'AT*PROD=2\\r\\n', b'AT*MRD_MEP=D\\r\\n', b'AT*PROD=0\\r\\n']
        for cmd in commands:
            ser.write(cmd)
            time.sleep(0.5)
            r = ser.read_all()
            print(f"Cmd {cmd.strip()} -> {r}")
        ser.close()
    except Exception as e:
        print(f"Port {p} error: {e}")
"""

    # Check if python3-serial is installed on router, or use python base with os/open
    # Alternatively, use python file io on serial device:
    at_script_native = """
import time

ports = ['/dev/cidatatty0', '/dev/ttymodem0', '/dev/citty0']
for p in ports:
    print(f"=== Testing port via file I/O: {p} ===")
    try:
        with open(p, 'rb+', buffering=0) as f:
            f.write(b'AT\\r\\n')
            time.sleep(0.5)
            res = f.read()
            print(f"AT response: {res}")
            
            # Try production mode & MEP read
            for cmd in [b'AT+CFUN?\\r\\n', b'AT*PROD=2\\r\\n', b'AT*MRD_MEP=D\\r\\n', b'AT*PROD=0\\r\\n']:
                f.write(cmd)
                time.sleep(0.5)
                r = f.read()
                print(f"Cmd {cmd} -> {r}")
    except Exception as e:
        print(f"Port {p} error: {e}")
"""

    remote_script_path = "/tmp/test_at.py"
    
    # Upload and run python script on router
    ch = t.open_session()
    ch.exec_command(f"cat << 'EOF' > {remote_script_path}\n{at_script_native}\nEOF")
    time.sleep(1)
    ch.close()

    print("[*] Running AT communication test on router ...")
    at_output = exec_cmd(t, f"python3 {remote_script_path}")
    print(at_output)

    # Save output to sim_unlock/at_test_results.txt
    res_path = os.path.join(OUT_DIR, "at_test_results.txt")
    with open(res_path, "w", encoding="utf-8") as f:
        f.write(at_output)
    print(f"[+] Saved AT test results to {res_path}")

    t.close()

if __name__ == "__main__":
    main()
