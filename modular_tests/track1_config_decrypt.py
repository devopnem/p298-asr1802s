#!/usr/bin/env python3
"""
Path 1: فك تشفير وفحص ملفات Config Backup (track1_config_decrypt.py)
الهدف: تحليل وفك تشفير ملفات config_backup.bin و pxa1826_cfg.tar.gz المنسوخة من الجهاز والمشفرة بـ OpenSSL (Salted__).

تحديثات حديثة بناءً على التحليل:
- تم استخراج كلمة السر والخوارزمية الصحيحة من ثنائي xml_action.cgi.
- الخوارزمية: aes-128-cbc، KDF: التراثي md5.
- كلمة السر الصحيحة تختلف حسب الجهاز (Om@5Wr%8 أو Om@0Yt#5 أو GYtAlIZh).
"""

import os
import subprocess
import tempfile
import hashlib
import gzip
import tarfile
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Target Files ---
FILES = [
    "/home/void/Downloads/Modems/notion_r291/backup_config/pxa1826_cfg.tar.gz",
    "/home/void/Downloads/Modems/notion_r291/backup_config/pxa1826_cfg_0.tar.gz",
    "/home/void/Downloads/Modems/notion_r291/config_backup.bin",
]

# --- Cryptographic Parameters ---
# Based on the xml_action.cgi binary analysis, the router uses AES-128-CBC with legacy MD5 KDF.
ALGOS = ["-aes-128-cbc", "-aes-256-cbc", "-aes-128-cfb", "-des-ede3-cbc"]
DIGESTS = ["md5", "sha256", "sha1"]
KDFS = ["legacy", "pbkdf2"]

# --- Prioritized Password Candidates ---
HARDCODED_PASSWORDS = [
    # --- Verified Passwords from xml_action.cgi and User Input ---
    "GYtAlIZh", # Extracted from xml_action.cgi (for original device)
    "Om@5Wr%8", # WebUI Password for Router 1 (from user, high priority)
    "Om@0Yt#5", # WebUI Password for Router 2 (from user, high priority)
    "admin",    # Default admin password
    "notion",   # Modem root password
    "r291",     # Model number
    "ooredoo",  # Carrier name

    # --- High-priority derived candidates ---
    "R291240826015571", # Serial Number from real_info.md
    "7C992E4F19AA",     # MAC address from real_info.md (uppercase, no colons)

    # --- Rest of the standard candidate list ---
    "password", "12345678", "admin123",
    "root", "toor", "user", "guest", "1234", "0000",
    "r281", "smartbro", "pldt",
    "marvell", "pxa1826",
    "CGISID", "debug", "factory", "factorymode",
    "nE%jA@5b", "aDm8H%MdA", "nE7jA%5m",
    "telecomadmin", "admintelecom", "CUAdmin",
    "Salted__", "openssl",
    "123", "12345", "1234567890",
    "changeme", "default", "letmein",
    "notion123", "r291admin", "smart",
    "PASSWORD", "Admin", "Notion@123",
    "ooredoo!@#", "Ooredoo123",
    "Ooredoo", "OOREDOO", "Oored00",
]

def generate_password_candidates():
    """توليد قائمة المفاتيح الذكية بناءة على الثوابت والهاشات المستخرجة من النظام."""
    candidates = list(HARDCODED_PASSWORDS)
    base_names = ["r291", "pxa1826", "marvell", "notion", "admin", "smartbro", "ooredoo"]
    
    # Derive passwords from common suffixes and patterns
    for base in base_names:
        candidates.extend([
            base.lower(),
            base.upper(),
            base + "123",
            base.capitalize(),
            base + "@123",
            base + "!",
            f"{base}2023",
            f"{base}2024",
        ])
        
        # Use partial hashes of the base name to create unique candidates
        for hash_func in [hashlib.md5, hashlib.sha1, hashlib.sha256]:
            hashed = hash_func(base.encode()).hexdigest()
            candidates.append(hashed[:8]) # First 8 chars of the hash
            candidates.append(hashed[:16]) # First 16 chars of the hash

    # Deduplicate and return the list
    return list(set(candidates))

def bruteforce_openssl_decryption(filepath, max_workers=4):
    """
    التفكيك البرمجي المتوازي.
    يجرّب جميع مزيجات كلمات المرور، والخوارزميات، ودوال التجزئة، وطرق مشتقة المفتاح بشكل متزامن.
    يتوقف عند العثور على أول ملف صالح يبدأ بسحب gzip (magic bytes 0x1f 0x8b).
    """
    passwords = generate_password_candidates()
    print(f"[*] Starting bruteforce for {os.path.basename(filepath)} with {len(passwords)} candidates...")
    
    task_args = []
    for algo in ALGOS:
        for md in DIGESTS:
            for kdf in KDFS:
                cmd_prefix = ["openssl", "enc", "-d", algo, "-md", md]
                if kdf == "pbkdf2":
                    cmd_prefix.append("-pbkdf2")
                cmd_prefix.append("-salt")
                for password in passwords:
                    task_args.append((filepath, password, algo, md, kdf, cmd_prefix))
    
    # Use ThreadPoolExecutor for parallelization
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(try_decrypt, filepath, password, algo, md, kdf, cmd_prefix): (password, algo, md, kdf)
            for (filepath, password, algo, md, kdf, cmd_prefix) in task_args
        }
        
        for future in as_completed(futures):
            password, algo, md, kdf = futures[future]
            result = future.result()
            if result:
                output_path = result
                print(f"\n[SUCCESS] Password '{password}', Algorithm '{algo}', Digest '{md}', KDF '{kdf}'")
                print(f"  Decrypted file saved to: {output_path}")
                inspect_decrypted_config(output_path)
                return True

    print(f"[-] Bruteforce failed for {os.path.basename(filepath)}.")
    return False

def try_decrypt(filepath, password, algo, md, kdf, cmd_prefix):
    """Helper function to attempt a single decryption. Returns the output path on verified success."""
    outfile = tempfile.mktemp()
    try:
        cmd = cmd_prefix + ["-pass", f"pass:{password}", "-in", filepath, "-out", outfile]
        r = subprocess.run(cmd, capture_output=True, timeout=15)
        if r.returncode == 0:
            if os.path.exists(outfile) and os.path.getsize(outfile) > 0:
                with open(outfile, "rb") as f:
                    magic = f.read(4)
                # A successful OpenSSL decryption of a tar.gz config will yield gzip data.
                if magic[:2] == b"\x1f\x8b" or magic[:3] == b"\x1f\x8b\x08":
                    final = filepath + ".decrypted.tar.gz"
                    shutil.move(outfile, final)
                    return final
    except subprocess.TimeoutExpired:
        pass
    except Exception as e:
        pass # Silently ignore errors during brute-force attempts
    finally:
        if os.path.exists(outfile):
            os.unlink(outfile)
    return None

def inspect_decrypted_config(filepath):
    """
    قراءة واستخراج البيانات الحساسة بعد التفكيك.
    """
    print(f"\n[*] Inspecting decrypted config: {filepath}")
    sensitive_patterns = [b"root:", b"/bin/sh", b"/etc/shadow", b"ssh-rsa", b"PasswordAuth", b"RootPasswordAuth"]

    try:
        if tarfile.is_tarfile(filepath):
            with tarfile.open(filepath, "r:gz") as tar:
                for member in tar.getmembers():
                    f = tar.extractfile(member)
                    if f:
                        content = f.read()
                        if any(p in content for p in sensitive_patterns):
                            print(f"  [+] Sensitive data found in: {member.name}")
                            
        elif filepath.endswith(".tar.gz"):
            with gzip.open(filepath, 'rb') as f:
                content = f.read()
                if any(p in content for p in sensitive_patterns):
                    print(f"  [+] Sensitive data found in decompressed stream")
        else:
            with open(filepath, 'rb') as f:
                content = f.read()
                if any(p in content for p in sensitive_patterns):
                     print(f"  [+] Sensitive data found in raw file")
    except Exception as e:
        print(f"  An error occurred during inspection: {e}")

if __name__ == "__main__":
    print("Starting Path 1: Config Backup Decryption")
    for f in FILES:
        if os.path.exists(f):
            print(f"\n=== Processing File: {os.path.basename(f)} ({os.path.getsize(f)} bytes) ===")
            bruteforce_openssl_decryption(f)
        else:
            print(f"  File not found: {f}")
    print("\nDone!")
