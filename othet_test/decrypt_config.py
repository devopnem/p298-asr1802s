#!/usr/bin/env python3
"""Try to decrypt OpenSSL-encrypted config backups"""
import subprocess
import os
import tempfile

FILES = [
    "/home/void/Downloads/Modems/notion_r291/backup_config/pxa1826_cfg.tar.gz",
    "/home/void/Downloads/Modems/notion_r291/backup_config/pxa1826_cfg_0.tar.gz",
    "/home/void/Downloads/Modems/notion_r291/config_backup.bin",
]

# The -md is required for older OpenSSL encrypted files
# Try both md5 (legacy default) and sha256 (newer default)
PASSWORDS = [
    "", "admin", "Om@0Yt#5",
    "hfiehifejfklihefiuehflejhfueihfeuihfeui",
    "JRNXpgF5Fp6rHDIVbtrfuZFQYWaVNAnpQbI7qwEF8cBATQShjM6COMzZhGRSYJRGTShihby1F",
    "password", "12345678", "admin123",
    "root", "toor", "user", "guest", "1234", "0000",
    "notion", "r291", "r281", "smartbro", "pldt", "ooredoo",
    "marvell", "pxa1826",
    "CGISID", "debug", "factory", "factorymode",
    "nE%jA@5b", "aDm8H%MdA", "nE7jA%5m",
    "telecomadmin", "admintelecom", "CUAdmin",
    "Salted__", "openssl",
    "123", "12345", "1234567890",
    "changme", "default", "letmein",
    "notion123", "r291admin", "smart",
    "PASSWORD", "Admin", "Notion@123",
    # IMEI/SN related - common passwords
    "012345678901234", "123456789012345",
    "000000000000000",
    # Common Arabic operator codes
    "Ooredoo", "ooredoo!@#", "Ooredoo123",
    "OOREDOO", "Oored00",
]

ALGO = "-aes-256-cbc"

def try_decrypt(filepath, password, md):
    outfile = tempfile.mktemp()
    try:
        r = subprocess.run(
            ["openssl", "enc", "-d", ALGO, "-md", md, "-salt", "-pass", f"pass:{password}", "-in", filepath, "-out", outfile],
            capture_output=True, timeout=10
        )
        if r.returncode == 0 and os.path.getsize(outfile) > 0:
            with open(outfile, "rb") as f:
                magic = f.read(4)
            if magic[:2] == b"\x1f\x8b" or magic[:3] == b"\x1f\x8b\x08":
                size = os.path.getsize(outfile)
                print(f"[SUCCESS] md={md} pass='{password}' -> {outfile} ({size} bytes)")
                final = filepath + ".decrypted"
                os.rename(outfile, final)
                print(f"  Saved to: {final}")
                return True
            else:
                size = os.path.getsize(outfile)
                print(f"[GOT_DATA] md={md} pass='{password}' -> {size} bytes, magic=0x{magic.hex()} (not gzip)")
    except subprocess.TimeoutExpired:
        pass
    except Exception as e:
        print(f"  Error: {e}")
    finally:
        if os.path.exists(outfile):
            os.unlink(outfile)
    return False

for f in FILES:
    print(f"\n=== {os.path.basename(f)} ({os.path.getsize(f)} bytes) ===")
    for p in PASSWORDS:
        if try_decrypt(f, p, "md5"):
            break
        if try_decrypt(f, p, "sha256"):
            break

print("\nDone!")
