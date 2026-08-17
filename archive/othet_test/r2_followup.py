#!/usr/bin/env python3
"""Follow-up: check set_eng_mode result and try more API calls"""
import hashlib, requests, time, sys, os, random
import socket
requests.packages.urllib3.disable_warnings()

ROUTER_IP = "192.168.1.1"
ROUTER_URL = f"http://{ROUTER_IP}"
USERNAME = "admin"
PASSWORD = "Om@0Yt#5"

sess = requests.Session()
sess.verify = False
sess.timeout = 15

def do_login():
    url = f"{ROUTER_URL}/login.cgi"
    r = sess.get(url, timeout=10)
    auth_header = r.headers.get("WWW-Authenticate", "")
    params = {}
    for part in auth_header.replace("Digest ", "").split(", "):
        k, v = part.split("=", 1)
        params[k] = v.strip('"')
    realm, nonce, qop = params.get("realm",""), params.get("nonce",""), params.get("qop","")
    ha1 = hashlib.md5(f"{USERNAME}:{realm}:{PASSWORD}".encode()).hexdigest()
    ha2 = hashlib.md5(f"GET:/cgi/xml_action.cgi".encode()).hexdigest()
    salt = str(random.randint(0,100000)) + str(int(time.time()*1000))
    cnonce = hashlib.md5(salt.encode()).hexdigest()[:16]
    nc = "00000001"
    response = hashlib.md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}".encode()).hexdigest()
    login_url = f"{url}?Action=Digest&username={USERNAME}&realm={realm}&nonce={nonce}&response={response}&qop={qop}&cnonce={cnonce}&nc={nc}&temp=marvell"
    r = sess.get(login_url, timeout=10)
    if "CGISID:" in r.text or sess.cookies.get("CGISID"):
        cgisid = sess.cookies.get("CGISID","")
        print(f"[+] Login OK, CGISID: {cgisid}")
        return True
    print(f"[-] Login failed")
    return False

def make_auth(method="POST"):
    make_auth.nc = getattr(make_auth, "nc", 0) + 1
    url = f"{ROUTER_URL}/login.cgi"
    r = sess.get(url, timeout=10)
    auth_header = r.headers.get("WWW-Authenticate", "")
    params = {}
    for part in auth_header.replace("Digest ", "").split(", "):
        k, v = part.split("=", 1)
        params[k] = v.strip('"')
    realm, nonce, qop = params.get("realm",""), params.get("nonce",""), params.get("qop","")
    ha1 = hashlib.md5(f"{USERNAME}:{realm}:{PASSWORD}".encode()).hexdigest()
    ha2 = hashlib.md5(f"{method}:/cgi/xml_action.cgi".encode()).hexdigest()
    salt = str(random.randint(0,100000)) + str(int(time.time()*1000))
    cnonce = hashlib.md5(salt.encode()).hexdigest()[:16]
    nc = f"{make_auth.nc:08d}"
    response = hashlib.md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}".encode()).hexdigest()
    return f'Digest username="{USERNAME}", realm="{realm}", nonce="{nonce}", uri="/cgi/xml_action.cgi", response="{response}", qop={qop}, nc={nc}, cnonce="{cnonce}"'

def call_api(xml):
    url = f"{ROUTER_URL}/xml_action.cgi?method=set"
    headers = {
        "Authorization": make_auth("POST"),
        "csrftoken": "hfiehifejfklihefiuehflejhfueihfeuihfeui",
        "Content-Type": "application/xml",
    }
    try:
        r = sess.post(url, data=xml, headers=headers, timeout=15)
        txt = r.text if r.text else "(empty)"
        print(f"[*] {r.status_code}: {txt[:200]}")
        return r.text
    except Exception as e:
        print(f"[-] Error: {e}")
        return None

def check_port(port, name="port"):
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect((ROUTER_IP, port))
        banner = s.recv(1024)
        print(f"[+] {name}: OPEN! {banner[:80]}")
        s.close()
        return True
    except:
        print(f"[-] {name}: closed")
        return False

print("=" * 60)
print("R291 Follow-up: Check set_eng_mode & more APIs")
print("=" * 60)

do_login()

# Check current ports
check_port(23, "Telnet")
check_port(22, "SSH")

# Try get_wan_configs to see if eng_mode was set
print("\n[*] get_wan_configs:")
call_api('''<?xml version="1.0" encoding="US-ASCII"?>
<RGW><param><method>call</method><session>000</session>
<obj_path>cm</obj_path><obj_method>get_wan_configs</obj_method>
</param></RGW>''')

# Try get_link_context 
print("\n[*] get_link_context:")
call_api('''<?xml version="1.0" encoding="US-ASCII"?>
<RGW><param><method>call</method><session>000</session>
<obj_path>cm</obj_path><obj_method>get_link_context</obj_method>
</param></RGW>''')

# Try get_eng_info
print("\n[*] get_eng_info:")
call_api('''<?xml version="1.0" encoding="US-ASCII"?>
<RGW><param><method>call</method><session>000</session>
<obj_path>cm</obj_path><obj_method>get_eng_info</obj_method>
</param></RGW>''')

# Try version/get_version 
print("\n[*] version get_version:")
call_api('''<?xml version="1.0" encoding="US-ASCII"?>
<RGW><param><method>call</method><session>000</session>
<obj_path>version</obj_path><obj_method>get_version</obj_method>
</param></RGW>''')

# Try router_get_product_info
print("\n[*] router router_get_product_info:")
call_api('''<?xml version="1.0" encoding="US-ASCII"?>
<RGW><param><method>call</method><session>000</session>
<obj_path>router</obj_path><obj_method>router_get_product_info</obj_method>
</param></RGW>''')

# Try account/get_account
print("\n[*] account get_account:")
call_api('''<?xml version="1.0" encoding="US-ASCII"?>
<RGW><param><method>call</method><session>000</session>
<obj_path>account</obj_path><obj_method>get_account</obj_method>
</param></RGW>''')

# Try router_call_reboot (will reboot router if it works!)
# Commented out for safety
# print("\n[*] router_call_reboot:")
# call_api('''<?xml version="1.0" encoding="US-ASCII"?>
# <RGW><param><method>call</method><session>000</session>
# <obj_path>router</obj_path><obj_method>router_call_reboot</obj_method>
# </param></RGW>''')

# Try wifi_ate_enable with different format
print("\n[*] wireless wifi_ate_enable (try 2):")
call_api('''<?xml version="1.0" encoding="US-ASCII"?>
<RGW><param><method>call</method><session>000</session>
<obj_path>wireless</obj_path><obj_method>wifi_ate_enable</obj_method>
</param></RGW>''')

# Try set_eng_mode with mode=1 instead of 2
print("\n[*] set_eng_mode mode=1:")
call_api('''<?xml version="1.0" encoding="US-ASCII"?>
<RGW><param><method>call</method><session>000</session>
<obj_path>cm</obj_path><obj_method>set_eng_mode</obj_method>
</param>
<wan><mode>1</mode></wan></RGW>''')

print("\n[*] Final ports check:")
check_port(23, "Telnet")
check_port(22, "SSH")

print("\n[*] Done")
