#!/usr/bin/env python3
"""
track1_modify_config.py
Purpose: Modify the decrypted config to enable passwordless SSH via key auth,
         and re-encrypt it for upload to the router.
"""

import os
import tarfile
import gzip
import subprocess
import tempfile
import shutil
import sys
import json

# --- Paths ---
# Note: We use the '_0' variant as it matches the router currently at 192.168.1.1.
DECRYPTED_CONFIG = "/home/void/Downloads/Modems/notion_r291/backup_config/pxa1826_cfg_0.tar.gz.decrypted.tar.gz"
ENCRYPTED_OUTPUT = "/home/void/Downloads/Modems/notion_r291/backup_config/pxa1826_cfg_0_modified.tar.gz"
ENCRYPTION_PASSWORD = "GYtAlIZh"

# Path to the raw encrypted file and its decrypted equivalent
SOURCE_TAR_GZ = "/home/void/Downloads/Modems/notion_r291/backup_config/pxa1826_cfg_0.tar.gz"
DECRYPTED_SOURCE = "/tmp/pxa1826_cfg_0_decrypted.tar.gz"

# --- Router Settings ---
ROUTER_IP = "192.168.1.1"
ROUTER_URL = f"http://{ROUTER_IP}"

# Import authentication module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api_login

def get_ssh_public_key():
    """Retrieve an SSH public key, generating a new one if necessary."""
    key_path = os.path.expanduser("~/.ssh/id_rsa.pub")
    if os.path.exists(key_path):
        with open(key_path, "r") as f:
            return f.read().strip()
    
    # Use the dedicated key for this project
    mod_key_path = os.path.expanduser("~/.ssh/id_rsa_modified")
    mod_key_pub = os.path.expanduser("~/.ssh/id_rsa_modified.pub")
    if os.path.exists(mod_key_pub):
        with open(mod_key_pub, "r") as f:
            return f.read().strip()
        
    # Generate a new key pair if one doesn't exist
    print("[*] No SSH key found. Generating a new one...")
    subprocess.run(["ssh-keygen", "-t", "rsa", "-b", "2048", "-f", mod_key_path, "-N", "", "-q"], check=True)
    with open(mod_key_pub, "r") as f:
        return f.read().strip()

def modify_config_tar(decrypted_tar_path, output_dir):
    """Extract, modify, and repack the config tar.gz."""
    with tarfile.open(decrypted_tar_path, "r:gz") as tar:
        tar.extractall(path=output_dir)
    
    # 1. Enable RootPasswordAuth and PublicKeyAuth in dropbear config
    dropbear_path = os.path.join(output_dir, "etc/config/dropbear")
    if os.path.exists(dropbear_path):
        with open(dropbear_path, "w") as f:
            f.write("config dropbear\n")
            f.write("\toption PasswordAuth 'on'\n")
            f.write("\toption RootPasswordAuth 'on'\n")
            f.write("\toption PubkeyAuth 'on'\n")
            f.write("\toption AuthorizedKeysFile '/etc/dropbear/authorized_keys'\n")
            f.write("\toption Port '22'\n")
        print(f"  [+] Modified {dropbear_path}")
    
    # 2. Add authorized_keys file
    ssh_pub_key = get_ssh_public_key()
    auth_keys_path = os.path.join(output_dir, "etc/dropbear/authorized_keys")
    os.makedirs(os.path.dirname(auth_keys_path), exist_ok=True)
    with open(auth_keys_path, "w") as f:
        f.write(ssh_pub_key + "\n")
    os.chmod(auth_keys_path, 0o600)
    print(f"  [+] Created {auth_keys_path} with public key")

    # 3. Add shadow file setting root password to 'root'
    shadow_path = os.path.join(output_dir, "etc/shadow")
    with open(shadow_path, "w") as f:
        f.write("root:$1$sg1UrDYk$YFnjPoUnUe1ghk8bdZqCW/:19000:0:99999:7:::\n")
        f.write("daemon:*:0:0:99999:7:::\n")
        f.write("ftp:*:0:0:99999:7:::\n")
        f.write("network:*:0:0:99999:7:::\n")
        f.write("nobody:*:0:0:99999:7:::\n")
    os.chmod(shadow_path, 0o600)
    print(f"  [+] Created {shadow_path}")

    # 4. Re-pack into a new tar.gz
    modified_tar_path = os.path.join(output_dir, "modified_config.tar.gz")
    with tarfile.open(modified_tar_path, "w:gz") as tar:
        tar.add(os.path.join(output_dir, "etc"), arcname="etc")
    print(f"  [+] Re-packed config into {modified_tar_path}")
    
    return modified_tar_path

def encrypt_config(input_tar_path, output_enc_path, password):
    """Re-encrypt the modified config using OpenSSL."""
    cmd = ["openssl", "enc", "-aes-128-cbc", "-md", "sha256", "-salt",
           "-pass", f"pass:{password}", "-in", input_tar_path, "-out", output_enc_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        print(f"[SUCCESS] Encrypted modified config saved to: {output_enc_path}")
        return True
    else:
        print(f"[-] Encryption failed: {r.stderr}")
        return False

def upload_modified_config(encrypted_config_path: str) -> dict:
    """
    رفع ملف الإعدادات المعدّل إلى الراوتر عبر API.
    
    بناءً على تحليل ملف HAR:
    - URL: /xml_action.cgi?Action=Upload&file=restore_config&command=
    - Content-Type: multipart/form-data
    - اسم حقل النموذج: "config_backup.bin"
    """
    if not api_login.CGISID:
        if not api_login.login():
            return {"success": False, "error": "Failed to authenticate with the router"}
    
    if not os.path.exists(encrypted_config_path):
        return {"success": False, "error": f"File not found: {encrypted_config_path}"}
    
    with open(encrypted_config_path, "rb") as f:
        file_data = f.read()
    
    # Construct the multipart form-data payload matching the browser's behavior
    url = f"{ROUTER_URL}/xml_action.cgi?Action=Upload&file=restore_config&command="
    
    files = {
        "config_backup.bin": ("config_backup.bin.decrypted.tar.gz", file_data, "application/gzip")
    }
    
    headers = {
        "Cookie": f"CGISID={api_login.CGISID}",
        "Referer": f"{ROUTER_URL}/",
        "Origin": ROUTER_URL,
    }
    
    try:
        print(f"[*] Uploading modified config to {url}...")
        r = api_login.sess.post(url, files=files, headers=headers, timeout=60)
        
        result = {
            "status": r.status_code,
            "body": r.text[:500],
        }
        
        if r.status_code == 200:
            print(f"  [SUCCESS] Upload complete. Server response: {r.text[:200]}")
            result["success"] = True
        else:
            print(f"  [-] Upload failed with HTTP {r.status_code}: {r.text[:200]}")
            result["success"] = False
        
        return result
    except Exception as e:
        print(f"  [-] Exception during upload: {e}")
        return {"success": False, "error": str(e)}


def reboot_router() -> dict:
    """
    إرسال أمر إعادة تشغيل إلى الراوتر عبر API.
    يلزم هذا لتطبيق إعدادات dropbear الجديدة.
    """
    if not api_login.CGISID:
        if not api_login.login():
            return {"success": False, "error": "Failed to authenticate with the router"}
    
    try:
        print("[*] Sending reboot command to the router...")
        result = api_login.api_call("router", "router_call_reboot")
        
        # استخدام wait_for_reboot من api_upload.py لمراقبة انتهاب التشغيل
        from api_upload import wait_for_reboot
        reboot_status = wait_for_reboot(timeout=180)
        
        return {
            "success": True,
            "api_response": result,
            "reboot_status": reboot_status
        }
    except Exception as e:
        print(f"  [-] Exception during reboot: {e}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    print("Path 1 Continued: Config Modification & Upload")
    tmpdir = tempfile.mkdtemp()
    
    try:
        if not os.path.exists(DECRYPTED_CONFIG):
            print(f"[-] Decrypted config not found: {DECRYPTED_CONFIG}")
        else:
            modified_tar = modify_config_tar(DECRYPTED_CONFIG, tmpdir)
            encrypt_config(modified_tar, ENCRYPTED_OUTPUT, ENCRYPTION_PASSWORD)
            
            args = sys.argv[1:]
            if "--upload" in args:
                print("\n[*] Attempting to upload the modified config to the router...")
                result = upload_modified_config(ENCRYPTED_OUTPUT)
                print(json.dumps(result, indent=2, ensure_ascii=False))
                
                if result.get("success") and "--reboot" in args:
                    print("\n[*] Initiating router reboot to apply new SSH settings...")
                    reboot_result = reboot_router()
                    print(json.dumps(reboot_result, indent=2, ensure_ascii=False))
                elif result.get("success"):
                    print(f"\n[*] Config uploaded successfully. The router needs a reboot for SSH changes to take effect.")
                    choice = input("Would you like to reboot the router now? (y/n): ").strip().lower()
                    if choice == "y":
                        reboot_result = reboot_router()
                        print(json.dumps(reboot_result, indent=2, ensure_ascii=False))
                    else:
                        print("[*] Skipping reboot. SSH changes will be applied on next manual reboot.")
            else:
                print(f"\nDone! Modified config saved to: {ENCRYPTED_OUTPUT}")
                print(f"To upload it, run: python3 track1_modify_config.py --upload")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
