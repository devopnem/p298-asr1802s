#!/usr/bin/env python3
"""
فتح SSH وإدارة الوصول إلى راوتر Ooredoo R291 V2 (MT7621 MIPS)
⚠️ الراوتر MIPS (MT7621). المودم ARM (ASR 1826s). لا تخلط.

======================================
 وثيقة SSH
======================================

1. الحالة الحالية (2026-07-30):
   --------------------------
   - SSH (22): 🟢 مفتوح بعد eng_mode
   - Telnet (23): 🔴 مغلق
   - SSH server: dropbear 2016.74
   - كلمة سر root: ❌ غير معروفة (30+ كلمة سر جربت)

2. API methods المتعلقة بـ SSH:
   ---------------------------
   ✅ router/get_dropbear_info   → dropbear_mode=1, key_type=0
   ✅ cm/set_eng_mode mode=2     → يفعّل SSH بعد إعادة التشغيل
   ❌ router/set_dropbear_info   → يعلّق HTTP server (يحتاج صيغة صحيحة)
   ❌ account/set_userpass       → لا تأثير
   ❌ cm/telnet                  → لا تأثير

3. تفعيل SSH:
   ----------
   الخطوات:
   1. سجّل الدخول (api_login.login())
   2. cm/set_eng_mode مع mode=2 (يخزّن في NVRAM)
   3. أعد تشغيل الراوتر (router/router_call_reboot)
   4. بعد الإقلاع: SSH على port 22 مفتوح
   5. كلمة سر root: غير معروفة (جرب passwd القياسية)

4. set_dropbear_info (⚠️ خطر):
   --------------------------
   - يعلّق HTTP server ← watchdog يعيد التشغيل بعد ~5 ثوانٍ
   - قد يكون يحذف root من /etc/shadow (dropbear_key_type=0)
   - يحتاج صيغة XML صحيحة:
     <RGW><param><method>call</method>...
       <obj_path>router</obj_path><obj_method>set_dropbear_info</obj_method>
     </param>
     <dropbear_info>
       <dropbear_mode>1</dropbear_mode>
       <dropbear_user>root</dropbear_user>
       <dropbear_password>كلمة_السر</dropbear_password>
       <dropbear_key_type>99</dropbear_key_type>
     </dropbear_info></RGW>

5. UART:
   ------
   - باود 57600
   - اضغط f خلال 6 ثوانٍ من التشغيل لدخول U-Boot
   - أوامر: mount_root → passwd root -d → reboot

6. كلمات سر SSH التي جربت:
   -----------------------
   admin, root, password, 12345678, Om@0Yt#5, Om@5Wr%8,
   $Passworld143, Passworld143, passworld143, Zte521,
   P@ssw0rd, 7icF3j8W, ooredoo, Ooredoo, MTK7621, mtk7621,
   ZTE, zte, user, guest, (فارغ), admin123,
   IMEI 868139070652232, Serial R291240826015571,
   wifirp90&$MM, notion, root123, toor

======================================
"""

import sys, os, time, socket, hashlib, json, subprocess

ROUTER_IP = "192.168.1.1"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api_login


# ======================== SSH Client ========================

def ssh_connect(password: str, user: str = "root",
                timeout: int = 10) -> dict:
    """محاولة اتصال SSH بكلمة سر محددة"""
    import paramiko
    
    result = {"user": user, "password": password, "success": False}
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(ROUTER_IP, username=user, password=password,
                       timeout=timeout, look_for_keys=False,
                       allow_agent=False)
        result["success"] = True
        result["note"] = "✅ اتصال ناجح!"
        client.close()
    except paramiko.AuthenticationException:
        result["note"] = "كلمة سر خاطئة"
    except socket.timeout:
        result["note"] = "المهلة انتهت"
    except socket.error as e:
        result["note"] = f"خطأ اتصال: {e}"
    except Exception as e:
        result["note"] = f"استثناء: {e}"
    
    return result


def ssh_bruteforce(passwords: list = None, user: str = "root",
                   timeout: int = 5, stop_on_found: bool = True) -> list:
    """محاولة جميع كلمات السر"""
    if not passwords:
        passwords = [
            "", "admin", "root", "password", "12345678",
            "Om@0Yt#5", "Om@5Wr%8",
            "$Passworld143", "Passworld143", "passworld143",
            "P@ssw0rd", "7icF3j8W",
            "ooredoo", "Ooredoo", "Ooredoo1",
            "MTK7621", "mtk7621", "mt7621",
            "Zte521", "ZTE", "zte",
            "user", "guest", "admin123",
            "root123", "toor", "notion",
            "868139070652232",  # IMEI
            "R291240826015571",  # Serial
            "wifirp90&$MM",
            "marvell", "Marvell",
            "PXA1826", "ASR",
            "R291", "r291",
            "Superlightweight123",
            "123456789", "qwerty", "letmein",
            "admin:Om@0Yt#5", "admin:Om@5Wr%8",
        ]
    
    import paramiko
    
    results = []
    for pw in passwords:
        r = ssh_connect(pw, user, timeout)
        status = "✅" if r["success"] else "❌"
        pw_display = f"'{pw}'" if pw else "(فارغ)"
        print(f"  {status} {user}@{ROUTER_IP}:{ROUTER_IP} [{pw_display}]")
        results.append(r)
        
        if r["success"] and stop_on_found:
            break
    
    return results


def ssh_execute(password: str, command: str, user: str = "root",
                timeout: int = 10) -> dict:
    """تنفيذ أمر عبر SSH"""
    import paramiko
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(ROUTER_IP, username=user, password=password,
                       timeout=timeout, look_for_keys=False,
                       allow_agent=False)
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        result = {
            "success": True,
            "stdout": stdout.read().decode("utf-8", errors="replace"),
            "stderr": stderr.read().decode("utf-8", errors="replace"),
            "exit_code": stdout.channel.recv_exit_status()
        }
        client.close()
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


# ======================== API methods ========================

def check_ssh_port() -> dict:
    """فحص منفذ SSH (22)"""
    try:
        s = socket.socket()
        s.settimeout(3)
        s.connect((ROUTER_IP, 22))
        banner = s.recv(1024).decode("utf-8", errors="replace")
        s.close()
        return {"open": True, "banner": banner.strip()}
    except socket.timeout:
        return {"open": False, "banner": "مهلة"}
    except ConnectionRefusedError:
        return {"open": False, "banner": "مرفوض"}
    except Exception as e:
        return {"open": False, "banner": str(e)}


def check_telnet_port() -> dict:
    """فحص منفذ Telnet (23)"""
    try:
        s = socket.socket()
        s.settimeout(3)
        s.connect((ROUTER_IP, 23))
        banner = s.recv(1024).decode("utf-8", errors="replace")
        s.close()
        return {"open": True, "banner": banner.strip()}
    except:
        return {"open": False, "banner": "مغلق"}


def enable_eng_mode(mode: str = "2") -> dict:
    """تفعيل Engineering Mode (مطلوب لفتح SSH)"""
    xml = ('<?xml version="1.0" encoding="US-ASCII"?>'
           '<RGW><param><method>call</method><session>000</session>'
           '<obj_path>cm</obj_path><obj_method>set_eng_mode</obj_method>'
           '</param><wan><mode>%s</mode></wan></RGW>' % mode)
    resp = api_login.api(xml)
    success = resp and "setting_response" in resp and "OK" in resp
    return {"success": success, "response": resp, "mode": mode}


def get_eng_mode() -> dict:
    """قراءة وضع Engineering الحالي"""
    xml = ('<?xml version="1.0" encoding="US-ASCII"?>'
           '<RGW><param><method>call</method><session>000</session>'
           '<obj_path>router</obj_path><obj_method>get_eng_mode</obj_method>'
           '</param><wan><mode>0</mode></wan></RGW>')
    resp = api_login.api(xml)
    if resp:
        try:
            mode = resp.split("<mode>")[1].split("<")[0]
            return {"success": True, "mode": mode}
        except:
            pass
    return {"success": False, "response": resp}


def get_dropbear_info() -> dict:
    """الحصول على معلومات dropbear (SSH)"""
    xml = ('<?xml version="1.0" encoding="US-ASCII"?>'
           '<RGW><param><method>call</method><session>000</session>'
           '<obj_path>router</obj_path><obj_method>get_dropbear_info</obj_method>'
           '</param><wan><mode>0</mode></wan></RGW>')
    resp = api_login.api(xml)
    info = {}
    if resp:
        for tag in ["dropbear_mode", "dropbear_key_type"]:
            try:
                val = resp.split(f"<{tag}>")[1].split("<")[0]
                info[tag] = val
            except:
                pass
    info["response"] = resp
    return info


def set_dropbear_info(user: str = "root", password: str = "root",
                      mode: str = "1", key_type: str = "99") -> dict:
    """
    🔴 **خطر!** هذه الدالة تعلّق HTTP server!
    
    الضبط: watchdog يعيد تشغيل الراوتر بعد ~5 ثوانٍ.
    لكن القيم قد تُحفظ في NVRAM قبل التعليق.
    
    الصيغة المستعملة:
    <RGW><param><method>call</method><session>000</session>
      <obj_path>router</obj_path><obj_method>set_dropbear_info</obj_method>
    </param>
    <dropbear_info>
      <dropbear_mode>{mode}</dropbear_mode>
      <dropbear_user>{user}</dropbear_user>
      <dropbear_password>{password}</dropbear_password>
      <dropbear_key_type>{key_type}</dropbear_key_type>
    </dropbear_info></RGW>
    """
    xml = ('<?xml version="1.0" encoding="US-ASCII"?>'
           '<RGW><param><method>call</method><session>000</session>'
           '<obj_path>router</obj_path><obj_method>set_dropbear_info</obj_method>'
           '</param>'
           '<dropbear_info>'
           '<dropbear_mode>%s</dropbear_mode>'
           '<dropbear_user>%s</dropbear_user>'
           '<dropbear_password>%s</dropbear_password>'
           '<dropbear_key_type>%s</dropbear_key_type>'
           '</dropbear_info></RGW>' % (mode, user, password, key_type))
    
    print("⚠️ إرسال set_dropbear_info... قد يعلّق HTTP server!")
    resp = api_login.api(xml)
    return {"response": resp, "note": "الخادم قد يعلق بعد هذا"}


def reboot() -> dict:
    """إعادة تشغيل الراوتر"""
    resp = api_login.api_call("router", "router_call_reboot")
    return {"response": resp}


def wait_for_reboot(timeout: int = 180) -> dict:
    """انتظار عودة الراوتر بعد إعادة التشغيل"""
    print(f"⏳ انتظار إعادة التشغيل (مهلة {timeout} ثانية)...")
    start = time.time()
    for i in range(timeout):
        try:
            s = socket.socket()
            s.settimeout(2)
            s.connect((ROUTER_IP, 80))
            s.close()
            elapsed = time.time() - start
            print(f"✅ عاد بعد {elapsed:.0f} ثانية")
            return {"success": True, "elapsed": elapsed}
        except:
            if i == 0:
                print("   الراوتر بدأ إعادة التشغيل...")
            time.sleep(1)
    print("❌ لم يعد بعد المهلة")
    return {"success": False, "elapsed": timeout}


def full_enable_ssh(password: str = None) -> dict:
    """
    تفعيل SSH كاملاً:
    1. تفعيل eng_mode (mode=2)
    2. إعادة تشغيل
    3. فتح SSH
    4. تغيير كلمة سر root (اختياري)
    5. إعادة تشغيل مرة أخرى
    """
    print("=" * 60)
    print("تفعيل SSH الكامل")
    print("=" * 60)
    
    # 1. eng_mode
    print("\n[1] تفعيل Engineering Mode...")
    r1 = enable_eng_mode("2")
    print(f"   {'✅' if r1['success'] else '❌'} {r1['response'][:100]}")
    
    if not r1["success"]:
        return {"success": False, "stage": "eng_mode", "response": r1}
    
    # 2. إعادة تشغيل
    print("\n[2] إعادة تشغيل الراوتر...")
    reboot()
    time.sleep(2)
    wr = wait_for_reboot(180)
    
    if not wr["success"]:
        return {"success": False, "stage": "reboot", "response": wr}
    
    # 3. إعادة تسجيل الدخول
    print("\n[3] إعادة تسجيل الدخول...")
    time.sleep(2)
    api_login.login()
    
    # 4. فحص SSH
    print("\n[4] فحص منفذ SSH...")
    ssh_status = check_ssh_port()
    print(f"   {'✅' if ssh_status['open'] else '❌'} {ssh_status['banner']}")
    
    # 5. إذا طلب تغيير كلمة السر
    if password:
        print(f"\n[5] تغيير كلمة سر root إلى '{password}'...")
        print("   ⚠️ هذا قد يعلّق الخادم!")
        r5 = set_dropbear_info(password=password)
        print(f"   الرد: {r5['response'][:100] if r5['response'] else 'لارد'}")
        print("   ⏳ انتظار إعادة التشغيل (watchdog)...")
        time.sleep(10)
        wr2 = wait_for_reboot(180)
        
        if wr2["success"]:
            print("\n✅ تم إعادة التشغيل. جرب SSH الآن:")
            print(f"   ssh root@{ROUTER_IP}")
    
    return {
        "success": ssh_status["open"],
        "ssh_port": ssh_status,
        "eng_mode": r1
    }


# ======================== فحص النظام بعد SSH ========================

def get_system_info_ssh(password: str, user: str = "root") -> dict:
    """جمع معلومات النظام عبر SSH بعد الدخول"""
    info = {}
    commands = [
        ("uname", "uname -a"),
        ("uptime", "cat /proc/uptime"),
        ("memory", "cat /proc/meminfo"),
        ("cpu", "cat /proc/cpuinfo"),
        ("mtd", "cat /proc/mtd"),
        ("partitions", "cat /proc/partitions"),
        ("shadow_root", "grep root /etc/shadow 2>/dev/null || echo 'لا يوجد'"),
        ("passwd_root", "grep root /etc/passwd 2>/dev/null || echo 'لا يوجد'"),
        ("dropbear_config", "ls -la /etc/dropbear/ 2>/dev/null"),
        ("dropbear_process", "ps | grep dropbear 2>/dev/null || echo 'لا'"),
        ("services", "ls /etc/init.d/ 2>/dev/null | head -30"),
        ("webui_users", "grep -r 'admin' /etc/ 2>/dev/null | grep -i password | head -10"),
        ("firmware_version", "cat /etc/version 2>/dev/null || cat /proc/version 2>/dev/null"),
    ]
    
    for name, cmd in commands:
        r = ssh_execute(password, cmd, user)
        if r["success"]:
            info[name] = r["stdout"].strip()[:200]
        else:
            info[name] = f"خطأ: {r.get('error', '?')}"
    
    return info


# ======================== سطر الأوامر ========================

def main():
    if not api_login.login():
        print("❌ فشل تسجيل الدخول")
        sys.exit(1)
    
    args = sys.argv[1:]
    
    if not args:
        print("حالة SSH:")
        print(f"  منفذ 22: {check_ssh_port()}")
        print(f"  منفذ 23: {check_telnet_port()}")
        
        print("\nمعلومات SSH (API):")
        dbi = get_dropbear_info()
        for k, v in dbi.items():
            print(f"  {k}: {v}")
        
        print("\nEngineering Mode:")
        eng = get_eng_mode()
        print(f"  {'✅' if eng.get('success') else '❌'} mode={eng.get('mode', '?')}")
        
    elif args[0] == "enable":
        password = args[1] if len(args) > 1 else None
        r = full_enable_ssh(password)
        print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
        
    elif args[0] == "eng_mode":
        mode = args[1] if len(args) > 1 else "2"
        r = enable_eng_mode(mode)
        print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
        
    elif args[0] == "brute":
        r = ssh_bruteforce()
        found = [x for x in r if x.get("success")]
        if found:
            print(f"\n✅ وجدنا كلمة السر: {found[0]['password']}")
        else:
            print("\n❌ لم نجد كلمة السر")
        
    elif args[0] == "try":
        pwd = args[1] if len(args) > 1 else "root"
        r = ssh_connect(pwd)
        print(json.dumps(r, indent=2, ensure_ascii=False))
        
    elif args[0] == "set_dropbear":
        pwd = args[1] if len(args) > 1 else "root"
        r = set_dropbear_info(password=pwd)
        print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
        
    elif args[0] == "info":
        print("حالة المنافذ:")
        print(f"  SSH(22): {check_ssh_port().get('banner')}")
        print(f"  Telnet(23): {check_telnet_port().get('banner')}")
        print(f"\ndropbear info: {get_dropbear_info()}")
        print(f"\neng_mode: {get_eng_mode()}")
        
    elif args[0] == "exec":
        cmd = " ".join(args[1:]) if len(args) > 1 else "id"
        pwd = os.environ.get("SSH_PASS", "root")
        r = ssh_execute(pwd, cmd)
        if r["success"]:
            print(r["stdout"])
            if r["stderr"]:
                print(f"STDERR: {r['stderr']}")
        else:
            print(f"❌ {r.get('error', '?')}")
        
    elif args[0] == "reboot":
        reboot()
        wait_for_reboot()
        
    elif args[0] == "help":
        print("""
الاستعمال:
  python3 api_ssh.py                        # عرض حالة SSH
  python3 api_ssh.py enable                 # تفعيل SSH (eng_mode + reboot)
  python3 api_ssh.py enable <password>      # تفعيل SSH وتغيير كلمة السر
  python3 api_ssh.py eng_mode [1|2]         # تفعيل Engineering Mode فقط
  python3 api_ssh.py brute                  # تجربة جميع كلمات السر
  python3 api_ssh.py try <password>         # تجربة كلمة سر محددة
  python3 api_ssh.py set_dropbear <pass>    # تغيير كلمة سر SSH ⚠️ خطر
  python3 api_ssh.py info                   # معلومات SSH المفصلة
  python3 api_ssh.py exec <command>         # تنفيذ أمر عبر SSH (يتطلب SSH_PASS)
  python3 api_ssh.py reboot                 # إعادة تشغيل الراوتر
""".strip())
        
    else:
        print(f"أمر غير معروف: {args[0]}. استعمل: python3 api_ssh.py help")


if __name__ == "__main__":
    main()
