#!/usr/bin/env python3
"""
R291 Ooredoo API Login — الطريقة الصحيحة والمضمونة
الاستعمال: from api_login import login, api
"""
import hashlib, requests, random, time
from typing import Optional

requests.packages.urllib3.disable_warnings()

ROUTER_IP = "192.168.1.1"
ROUTER_URL = f"http://{ROUTER_IP}"
USER = "admin"
PASS = "Lj%5Qp$1"
# Lj%5Qp$1 Om@0Yt#5
sess = requests.Session()
sess.verify = False
sess.timeout = 15

CGISID: Optional[str] = None
_nc_counter = 0

def get_auth_params() -> dict:
    r = sess.get(f"{ROUTER_URL}/login.cgi", timeout=10)
    ah = r.headers.get("WWW-Authenticate", "")
    p = {}
    for part in ah.replace("Digest ", "").split(", "):
        k, v = part.split("=", 1)
        p[k] = v.strip('"')
    return p

def login() -> bool:
    global CGISID, _nc_counter
    _nc_counter = 0
    p = get_auth_params()
    ha1 = hashlib.md5(f"{USER}:{p['realm']}:{PASS}".encode()).hexdigest()
    # مهم: HA2 للدخول هو GET:/cgi/xml_action.cgi وليس /login.cgi
    ha2 = hashlib.md5("GET:/cgi/xml_action.cgi".encode()).hexdigest()
    salt = str(random.randint(0, 100000)) + str(int(time.time() * 1000))
    cn = hashlib.md5(salt.encode()).hexdigest()[:16]
    nc = "00000001"
    resp = hashlib.md5(f"{ha1}:{p['nonce']}:{nc}:{cn}:{p['qop']}:{ha2}".encode()).hexdigest()
    url = (f"{ROUTER_URL}/login.cgi?Action=Digest&username={USER}&realm={p['realm']}"
           f"&nonce={p['nonce']}&response={resp}&qop={p['qop']}&cnonce={cn}&nc={nc}&temp=marvell")
    r = sess.get(url, timeout=10)
    if "CGISID:" in r.text:
        CGISID = r.text.split("CGISID:")[1].strip().split("\r")[0].split("\n")[0]
        return True
    # Try cookie
    c = sess.cookies.get("CGISID")
    if c:
        CGISID = c
        return True
    return False

def make_auth(method="POST", uri="/cgi/xml_action.cgi") -> str:
    global _nc_counter
    _nc_counter += 1
    p = get_auth_params()
    ha1 = hashlib.md5(f"{USER}:{p['realm']}:{PASS}".encode()).hexdigest()
    ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
    salt = str(random.randint(0, 100000)) + str(int(time.time() * 1000))
    cn = hashlib.md5(salt.encode()).hexdigest()[:16]
    nc = f"{_nc_counter:08d}"
    resp = hashlib.md5(f"{ha1}:{p['nonce']}:{nc}:{cn}:{p['qop']}:{ha2}".encode()).hexdigest()
    return (f'Digest username="{USER}", realm="{p["realm"]}", nonce="{p["nonce"]}", '
            f'uri="{uri}", response="{resp}", qop={p["qop"]}, nc={nc}, cnonce="{cn}"')

def api(xml_body: str, obj_path: str = "", obj_method: str = "") -> Optional[str]:
    url = f"{ROUTER_URL}/xml_action.cgi?method=set"
    auth = make_auth("POST")
    headers = {
        "Authorization": auth,
        "csrftoken": "hfiehifejfklihefiuehflejhfueihfeuihfeui",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": ROUTER_URL + "/",
        "Origin": ROUTER_URL
    }
    try:
        r = sess.post(url, data=xml_body, headers=headers, timeout=30)
        return r.text
    except Exception as e:
        return f"ERROR: {e}"

def api_call(obj_path: str, obj_method: str, params: dict = None) -> Optional[str]:
    xml = '<?xml version="1.0" encoding="US-ASCII"?><RGW>'
    xml += '<param><method>call</method><session>000</session>'
    xml += f'<obj_path>{obj_path}</obj_path><obj_method>{obj_method}</obj_method>'
    xml += '</param>'
    if params:
        xml += f'<{obj_path}>'
        for k, v in params.items():
            xml += f'<{k}>{v}</{k}>'
        xml += f'</{obj_path}>'
    xml += '</RGW>'
    return api(xml)

def test():
    if login():
        print(f"[+] CGISID: {CGISID}")
        r = api_call("version", "get_version")
        print(f"[*] version: {r[:200]}")
    else:
        print("[-] Login failed")

if __name__ == "__main__":
    test()
