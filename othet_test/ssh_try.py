#!/usr/bin/env python3
"""SSH to R291 with password using pty"""
import os, pty, select, sys, time

def ssh_with_password(host, user, password, cmd="id; uname -a; cat /proc/version"):
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("ssh", ["ssh",
                          "-o", "StrictHostKeyChecking=no",
                          "-o", "UserKnownHostsFile=/dev/null",
                          "-o", "ConnectTimeout=10",
                          "-o", "ServerAliveInterval=5",
                          "-o", "KexAlgorithms=+diffie-hellman-group14-sha1",
                          "-o", "HostKeyAlgorithms=+ssh-rsa",
                          f"{user}@{host}", cmd])
        sys.exit(1)
    
    output = b""
    password_sent = False
    while True:
        r, _, _ = select.select([fd], [], [], 1.0)
        if r:
            try:
                data = os.read(fd, 4096)
            except OSError:
                break
            if not data:
                break
            output += data
            sys.stdout.write(data.decode(errors='replace'))
            sys.stdout.flush()
            if b"password:" in data.lower() and not password_sent:
                os.write(fd, (password + "\r").encode())
                password_sent = True
        else:
            # Check if process is still alive
            wpid, status = os.waitpid(pid, os.WNOHANG)
            if wpid != 0:
                break
    
    # Wait for remaining output
    try:
        while True:
            r, _, _ = select.select([fd], [], [], 0.5)
            if not r:
                break
            data = os.read(fd, 4096)
            if not data:
                break
            output += data
            print(data.decode(errors='replace'), end='')
    except:
        pass
    
    os.close(fd)
    return output.decode(errors='replace')

print("=" * 60)
print("SSH to R291 Router")
print("=" * 60)

# Try root with $Passworld143
print('\n[*] Trying root / $Passworld143...')
output = ssh_with_password("192.168.1.1", "root", "$Passworld143", 
    "id; uname -a; cat /proc/version; ls /; which telnetd; ps | grep dropbear")
print(f"\n[*] Output length: {len(output)}")

# Also try admin password
if "Permission denied" in output or "Authentication failed" in output or "password:" in output:
    print("\n[*] Trying admin / Om@0Yt#5...")
    output = ssh_with_password("192.168.1.1", "admin", "Om@0Yt#5",
        "id; uname -a")
    print(f"\n[*] Output length: {len(output)}")
    if "Permission denied" in output or "Authentication failed" in output:
        print("\n[-] SSH credentials unknown, trying more passwords...")
