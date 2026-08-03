#!/usr/bin/env python3
"""
رفع الملفات إلى راوتر Ooredoo R291 V2 (MT7621 MIPS)
⚠️ الراوتر = MIPS (MT7621). المودم = ARM (ASR 1826s). لا تخلط.

======================================
 وثيقة شاملة لآلية رفع الملفات
======================================

1. مشكلة Multipart (اكتشاف 2026-07-30)
   ------------------------------------
   - XML Action CGI: /xml_action.cgi?Action=Upload&file=upgrade
   - Content-Type: multipart/form-data → ينهار HTTP 500 للملفات > 6144 بايت
   - السبب: خطأ في parser الـ multipart/form-data في CGI (buffer overflow?)
   - الحل: استخدم Content-Type: application/octet-stream مع RAW body
   - RAW body ينجح لأي حجم (حتى 10.8MB) بدون انهيار!

2. طرق الرفع المدعومة:
   -------------------
   multipart/form-data  |  file=upgrade    |  ≤ 6144 بايت  |  HTTP 200
   multipart/form-data  |  file=upgrade    |  ≥ 7168 بايت  |  HTTP 500 (CGI crash)
   multipart/form-data  |  file=cp_upgrade  |  أي حجم       |  HTTP 200 (يرفض "error")
   multipart/form-data  |  file=ca|cert|key|dh | أي حجم    |  HTTP 200 (يرفض "error")
   RAW body             |  file=upgrade    |  أي حجم       |  HTTP 200 ⭐
   RAW body             |  file=cp_upgrade  |  أي حجم       |  HTTP 200 ("error")
   HTTPS+multipart      |  file=upgrade    |  ≤ 7168       |  HTTP 200 (HTTPS يعطي +1KB)

3. error_cause:
   -----------
   0 = نجاح (بدأت الترقية)
   1 = خطأ عام
   2 = فشل التحقق من صحة firmware (التوقيع/المعمارية) ← الأكثر شيوعاً
   3 = الطريقة غير موجودة
   -1 إلى -5 = أخطاء محلية من السكربت

4. ⚠️ معمارية الراوتر (اقرأ جيداً — لا تخلط!)
   ------------------------------------
   - **AP (الراوتر)**: MediaTek MT7621DAT ← **MIPS** (ثنائي النواة @ 880MHz)
   - **CP (المودم)**: Marvell PXA1826 / ASR 1826s ← **ARM** (لـ LTE فقط)
   - API `system/board` يظهر ARM/ASR 1826s ← هذا **المودم** وليس الراوتر
   - جميع firmware المتاحة: **MIPS** ← متوافقة ✅
   - سبب error_cause=2: **ليس** معمارية — بل فشل التحقق (توقيع/إصدار/board ID)

5. سبب error_cause=2:
   ------------------
   ليس بسبب العمارة (firmware MIPS والروتر MIPS).
   الأسباب المحتملة:
   - firmware غير موقع بتوقيع مطلوب
   - Ooredoo عدّل التحقق من صحة الترقية
   - upgrade script يتحقق من hw_ver/FW version
   - الـ EXE يرفع uboot.bin أولاً (لتعطيل التحقق) ثم firmware
   - الـ uboot.bin المخصص (من الـ EXE) يكتب فوق bootloader بآخر يسمح بـ TFTP

6. مسار الـ EXE لعمل الفتح:
   ------------------------
   1. uboot.bin (312KB, hash 707b4f4c5f2cee77affcbd7d0cc731ec)
      ← يرفع عبر CGI ثم يفلش bootloader
      ← bootloader مخصص يبدأ TFTP بعد إعادة التشغيل
   2. a.bin = notionv3r291.bin (10.8MB)
      ← يرفع عبر TFTP (وليس CGI!) بعد إعادة التشغيل بالـ bootloader الجديد

   الـ uboot.bin المخصص ليس عندنا (ملفنا 132KB فقط، مختلف).
   لكن عندنا U-Boot لـ MT7621: openwrt-ramips-mt7621-sxx-u-boot.img

7. استراتيجيات غير فعالة:
   ----------------------
   - cp_upgrade + upgrade متتالي: upgrade يعيد كتابة /tmp/firmware.bin
   - &command= parameter: لا تأثير له
   - &size= مختلف عن الحجم الحقيقي: لا فائدة
   - TR-069 OTA: غير متوفر في Ooredoo firmware

8. مسارات العمل الممكنة:
   --------------------
   - فتح SSH عبر API (eng_mode + إيجاد كلمة سر root)
   - تجربة `set_dropbear_info` بطريقة صحيحة (صيغة XML مناسبة)
   - فلاش uboot.img الموجود ثم استخدام TFTP لنقل firmware
   - AT commands عبر USB (ttyACM0) لفتح المودم
   - الوصول عبر UART (باود 57600)
   - استخراج firmware من الراوتر نفسه
   - هندسة عكسية للـ CGI لإيجاد RCE

======================================
"""

import sys, os, time, hashlib, http.client, socket, json, struct
from datetime import datetime

# ======================== الإعدادات ========================
ROUTER_IP = "192.168.1.1"
ROUTER_URL = f"http://{ROUTER_IP}"
ROUTER_HTTPS = f"https://{ROUTER_IP}"

# مسارات الفيرموير المحلية (كلها MIPS! ليست لـ ARM)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLASHING_DIR = os.path.join(REPO_ROOT, "flashing_files")
FW_DIR = os.path.join(FLASHING_DIR, "r291-main")
FW_PATH = os.path.join(FW_DIR, "notionv3r291.bin")  # 10.6MB MIPS uImage
OPENWRT_DIR = os.path.join(REPO_ROOT, "openwrt")
OPENWRT_INITRAMFS = os.path.join(OPENWRT_DIR, "notion_r291-initramfs-kernel.bin")  # MIPS
OPENWRT_FACTORY = os.path.join(OPENWRT_DIR, "notion_r291-squashfs-factory.bin")  # MIPS

# ------------------------ الاستيراد ------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api_login

# ======================== أدوات فحص الـ firmware ========================

ARCH_NAMES = {0: "Invalid", 1: "Alpha", 2: "ARM", 3: "x86", 4: "IA64",
              5: "MIPS", 6: "MIPS64", 7: "PPC", 8: "SPARC", 9: "SuperH"}

COMP_NAMES = {0: "none", 1: "gzip", 2: "bzip2", 3: "lzma", 4: "lzo", 5: "lz4",
              6: "zstd"}

def inspect_firmware(path: str) -> dict:
    """تحليل ترويسة firmware وعرض معلومات المعمارية"""
    info = {"path": path, "exists": os.path.exists(path)}
    if not info["exists"]:
        return info
    
    with open(path, "rb") as f:
        data = f.read()
    
    info["size"] = len(data)
    info["size_kb"] = f"{len(data)/1024:.1f}"
    
    if len(data) < 64:
        info["error"] = "صغير جداً"
        return info
    
    magic = struct.unpack('>I', data[0:4])[0]
    info["magic"] = f"0x{magic:08X}"
    
    if magic == 0x27051956:
        info["type"] = "uImage"
        info["timestamp"] = datetime.fromtimestamp(struct.unpack('>I', data[8:12])[0]).isoformat()
        info["image_size"] = struct.unpack('>I', data[12:16])[0]
        info["load_addr"] = f"0x{struct.unpack('>I', data[16:20])[0]:08X}"
        info["entry"] = f"0x{struct.unpack('>I', data[20:24])[0]:08X}"
        info["arch"] = data[29]
        info["arch_name"] = ARCH_NAMES.get(data[29], "?")
        info["compression"] = COMP_NAMES.get(data[31], "?")
        info["name"] = data[32:64].split(b'\x00')[0].decode('ascii', errors='replace')
        
        # بيان الملف المضغوط
        img_data = data[64:]
        if img_data[:2] == b'\x1f\x8b':
            info["compressed"] = "gzip"
        elif img_data[:4] == b'\x89PNG':
            info["compressed"] = "PNG (خطأ)"
        else:
            info["compressed"] = f"غير مضغوط (أول 4: {img_data[:4].hex()})"
    elif data[:2] == b'\x1f\x8b':
        info["type"] = "gzip"
    elif data[:7] == b'\x7fELF':
        e_class = {1: 32, 2: 64}.get(data[4], "?")
        e_machine = {40: "ARM", 3: "x86", 8: "MIPS"}.get(struct.unpack('<H', data[18:20])[0], "?")
        info["type"] = f"ELF {e_class}-بت {e_machine}"
    elif data[:4] in (b'UBI#', b'UBI!'):
        info["type"] = "UBI"
    elif data[:4] == b'hsqs':
        info["type"] = "SquashFS"
    else:
        info["type"] = "غير معروف"
    
    return info

def firmware_compatible(path: str) -> bool:
    """هل الـ firmware لـ MIPS (MT7621)؟"""
    info = inspect_firmware(path)
    return info.get("arch_name") in ("MIPS",)

# ======================== الدوال الأساسية للرفع ========================

def upload_raw(data: bytes, upload_type: str = "upgrade",
               use_https: bool = False, timeout: int = 60) -> dict:
    """
    رفع بيانات خام (RAW body) مع Content-Type: application/octet-stream
    
    هذا يتجاوز مشكلة HTTP 500 من multipart/form-data parser.
    ينجح لأي حجم حتى 10.8MB.
    """
    if not api_login.CGISID:
        return {"status": 0, "body": "", "error_cause": -1,
                "note": "CGISID فارغ، سجّل الدخول أولاً"}
    
    result = {"file_size": len(data), "upload_type": upload_type}
    
    suffix = f"/xml_action.cgi?Action=Upload&file={upload_type}&command="
    auth_uri = "/cgi/xml_action.cgi"
    headers = {
        "Cookie": f"CGISID={api_login.CGISID}",
        "Authorization": api_login.make_auth("POST"),
        "csrftoken": "hfiehifejfklihefiuehflejhfueihfeuihfeui",
        "Referer": f"{'https' if use_https else 'http'}://{ROUTER_IP}/",
        "Origin": f"{'https' if use_https else 'http'}://{ROUTER_IP}",
        "Content-Type": "application/octet-stream",
    }
    
    if use_https:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection(ROUTER_IP, timeout=timeout, context=ctx)
    else:
        conn = http.client.HTTPConnection(ROUTER_IP, timeout=timeout)
    
    try:
        conn.request("POST", suffix, body=data, headers=headers)
        r = conn.getresponse()
        result["status"] = r.status
        result["body"] = r.read().decode("latin-1")
        result["reason"] = r.reason
        r.close()
    except Exception as e:
        result["status"] = 0
        result["body"] = str(e)
        result["error_cause"] = -6
        result["note"] = f"استثناء اتصال: {e}"
        conn.close()
        return result
    conn.close()
    
    return _parse_response(result)


def upload_multipart(data: bytes, upload_type: str = "upgrade",
                     use_https: bool = False, use_size_param: bool = False,
                     field_name: str = "fupgrade.bin",
                     filename: str = "firmware.bin",
                     timeout: int = 30) -> dict:
    """
    رفع ملف عبر multipart/form-data
    
    ملاحظة: هذا يعاني من HTTP 500 للملفات > 6144 بايت (عبر HTTP)
    أو > 7168 (عبر HTTPS). يُفضّل استخدام upload_raw().
    """
    if not api_login.CGISID:
        return {"status": 0, "error_cause": -1, "note": "CGISID فارغ"}
    
    result = {"file_size": len(data), "upload_type": upload_type}
    
    suffix = f"/xml_action.cgi?Action=Upload&file={upload_type}&command="
    if use_size_param:
        suffix += f"&size={len(data)}"
    
    boundary = f"----FormBoundary{hashlib.md5(str(time.time()).encode()).hexdigest()[:16]}"
    body = (f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"{field_name}\"; "
            f"filename=\"{filename}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode()
    body += data
    body += f"\r\n--{boundary}--\r\n".encode()
    
    headers = {
        "Cookie": f"CGISID={api_login.CGISID}",
        "Authorization": api_login.make_auth("POST"),
        "csrftoken": "hfiehifejfklihefiuehflejhfueihfeuihfeui",
        "Referer": f"{'https' if use_https else 'http'}://{ROUTER_IP}/",
        "Origin": f"{'https' if use_https else 'http'}://{ROUTER_IP}",
        "Content-Type": f"multipart/form-data; boundary={boundary}"
    }
    
    if use_https:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection(ROUTER_IP, timeout=timeout, context=ctx)
    else:
        conn = http.client.HTTPConnection(ROUTER_IP, timeout=timeout)
    
    try:
        conn.request("POST", suffix, body=body, headers=headers)
        r = conn.getresponse()
        result["status"] = r.status
        result["body"] = r.read().decode("latin-1")
        r.close()
    except Exception as e:
        result["status"] = 0
        result["body"] = str(e)
        result["error_cause"] = -6
        result["note"] = f"استثناء: {e}"
        conn.close()
        return result
    conn.close()
    
    return _parse_response(result)


def _parse_response(result: dict) -> dict:
    """تحليل رد XML من CGI واستخراج error_cause"""
    body = result.get("body", "")
    status = result.get("status", 0)
    
    if status == 0:
        result["success"] = False
        return result
    
    if status == 500:
        result["error_cause"] = -4
        result["note"] = "HTTP 500 — CGI انهار (multipart/form-data فقط)"
        result["success"] = False
        return result
    
    if "<error_cause>" in body:
        try:
            cause = body.split("<error_cause>")[1].split("<")[0]
            result["error_cause"] = int(cause) if cause.isdigit() else cause
            result["success"] = (cause == "0")
            codes = {"0": "نجاح — بدأت الترقية",
                     "1": "خطأ عام",
                     "2": "فشل التحقق من firmware (معمارية/توقيع خاطئ)",
                     "3": "طريقة غير موجودة"}
            result["note"] = codes.get(cause, f"رمز غير معروف: {cause}")
        except Exception as e:
            result["error_cause"] = -1
            result["note"] = f"فشل تحليل XML: {e}"
            result["success"] = False
    elif body.strip() == "error":
        result["error_cause"] = -2
        result["note"] = "الخادم قبل الملف لكن رفضه (cp_upgrade: ليس firmware مودم)"
        result["success"] = False
    else:
        result["error_cause"] = -3
        result["note"] = f"رد غير متوقع: {body[:60]}"
        result["success"] = False
    
    return result


# ======================== واجهات رفع عالية المستوى ========================

def upgrade_firmware(data: bytes, use_raw: bool = True) -> dict:
    """رفع firmware الراوتر (file=upgrade)"""
    if use_raw:
        return upload_raw(data, "upgrade")
    return upload_multipart(data, "upgrade")


def upgrade_cp(data: bytes, use_raw: bool = True) -> dict:
    """رفع firmware المودم (file=cp_upgrade) — يقبل أي حجم"""
    if use_raw:
        return upload_raw(data, "cp_upgrade")
    return upload_multipart(data, "cp_upgrade")


def upgrade_from_file(file_path: str, use_raw: bool = True,
                      upload_type: str = "upgrade") -> dict:
    """رفع ملف firmware من المسار المحلي"""
    if not os.path.exists(file_path):
        return {"status": 0, "error_cause": -7, "note": f"الملف غير موجود: {file_path}"}
    
    with open(file_path, "rb") as f:
        data = f.read()
    
    r = upgrade_firmware(data, use_raw) if upload_type == "upgrade" else upgrade_cp(data, use_raw)
    r["file_path"] = file_path
    return r


# ======================== وظائف مساعدة ========================

def check_ota_status() -> dict:
    """الاستعلام عن حالة OTA (دائماً يعيد failed لأن OTA معطل)"""
    if not api_login.CGISID:
        api_login.login()
    xml = ('<?xml version="1.0" encoding="US-ASCII"?>'
           '<RGW><param><method>call</method><session>000</session>'
           '<obj_path>ota</obj_path><obj_method>query</obj_method></param>'
           '<ota><type>1</type></ota></RGW>')
    r = api_login.api(xml)
    return {"response": r or "لا رد"}


def wait_for_reboot(timeout: int = 180) -> dict:
    """انتظار إعادة تشغيل الراوتر بعد رفع firmware ناجح"""
    print(f"انتظار إعادة التشغيل (مهلة {timeout} ثانية)...")
    start = time.time()
    for i in range(timeout):
        try:
            s = socket.socket()
            s.settimeout(2)
            s.connect((ROUTER_IP, 80))
            s.close()
            elapsed = time.time() - start
            if elapsed > 10:
                print(f"  ✅ الراوتر عاد بعد {elapsed:.0f} ثانية")
            else:
                print(f"  الراوتر لم يغب (لم يُعد التشغيل)")
            return {"rebooted": elapsed > 3, "elapsed": elapsed}
        except:
            time.sleep(1)
    print("  ❌ الراوتر لم يعد!")
    return {"rebooted": False, "elapsed": time.time() - start}


# ======================== اختبارات ========================

def test_comprehensive():
    """اختبار شامل لجميع طرق الرفع وكل الأحجام"""
    print("=" * 80)
    print("اختبار شامل لرفع الملفات")
    print("=" * 80)
    
    # أحجام الاختبار
    sizes = [100, 1024, 5120, 6144, 7168, 8192, 10240, 16384,
             65536, 262144, 1048576, 5242880, 10864265]
    
    results = []
    
    for method, use_https in [("RAW HTTP", False), ("RAW HTTPS", True),
                               ("MULTI HTTP", False), ("MULTI HTTPS", True)]:
        is_raw = "RAW" in method
        is_https = use_https
        
        for size in sizes:
            data = b'\x00' * min(size, 10864265)
            
            if is_raw:
                r = upload_raw(data, "upgrade", use_https=is_https)
            else:
                r = upload_multipart(data, "upgrade", use_https=is_https,
                                    use_size_param=False)
            
            icon = "✅" if r.get("success") else ("⚠️" if r["status"] == 200 else "❌")
            cause = r.get("error_cause", "?")
            note = r.get("note", "")[:30]
            print(f"  {icon} {method:15s} size={size:>8d}: HTTP {r['status']:3d} cause={cause} {note}")
            
            results.append((method, size, r["status"], r.get("success"), r.get("error_cause")))
    
    print("\n=== خلاصة ===")
    for method in ["RAW HTTP", "RAW HTTPS", "MULTI HTTP", "MULTI HTTPS"]:
        meth_results = [r for r in results if r[0] == method]
        successes = sum(1 for r in meth_results if r[3])
        http_200 = sum(1 for r in meth_results if r[2] == 200)
        http_500 = sum(1 for r in meth_results if r[2] == 500)
        print(f"\n{method}:")
        print(f"  نجاح: {successes}/{len(meth_results)}")
        print(f"  HTTP 200: {http_200}, HTTP 500: {http_500}")
        if http_500:
            first_500 = next((r[1] for r in meth_results if r[2] == 500), 0)
            print(f"  أول HTTP 500 عند: {first_500:,} بايت")


def test_firmware_compatibility():
    """فحص معمارية جميع firmware المتاحة"""
    print("=" * 80)
    print("فحص معمارية firmware المتاحة")
    print("=" * 80)
    print(f"روتـرنا: MT7621 MIPS (مودم Marvell PXA1826 ARM)\n")
    
    fws = [
        ("notionv3r291.bin", FW_PATH),
        ("initramfs-kernel", OPENWRT_INITRAMFS),
        ("squashfs-factory", OPENWRT_FACTORY),
        ("R281-R291 Unlocked", os.path.join(
            FLASHING_DIR,
            "R291-main-2", "R281-R291_Unlocked_free_firmware.bin")),
        ("firmware.bin", os.path.join(
            FLASHING_DIR,
            "R291-main-2", "firmware.bin")),
        ("Smartbro-OldWebui", os.path.join(
            FLASHING_DIR,
            "R291-main", "Smartbro-R291-OldWebui.bin")),
    ]
    
    for name, path in fws:
        info = inspect_firmware(path)
        if not info["exists"]:
            print(f"  - {name}: غير موجود")
            continue
        arch = info.get("arch_name", "?")
        fw_type = info.get("type", "?")
        fw_name = info.get("name", "?")
        compatible = firmware_compatible(path)
        compat_str = "✅ متوافق" if compatible else "❌ غير متوافق"
        print(f"  {compat_str:15s} | {name:25s} | {arch:6s} | {fw_type:8s} | {fw_name[:30]}")


# ======================== سطر الأوامر ========================

def main():
    if not api_login.login():
        print("فشل تسجيل الدخول")
        sys.exit(1)
    
    args = sys.argv[1:]
    
    if not args:
        test_firmware_compatibility()
        print("\n")
        test_comprehensive()
        
    elif args[0] == "upgrade":
        file_path = args[1] if len(args) > 1 else FW_PATH
        use_raw = "--multi" not in args
        r = upgrade_from_file(file_path, use_raw=use_raw, upload_type="upgrade")
        print(json.dumps(r, indent=2, ensure_ascii=False))
        if r.get("success"):
            print("\n⏳ انتظار إعادة التشغيل...")
            print(wait_for_reboot())
        
    elif args[0] == "cp_upgrade" or args[0] == "cp":
        file_path = args[1] if len(args) > 1 else FW_PATH
        use_raw = "--multi" not in args
        r = upgrade_from_file(file_path, use_raw=use_raw, upload_type="cp_upgrade")
        print(json.dumps(r, indent=2, ensure_ascii=False))
        
    elif args[0] == "raw":
        file_path = args[1] if len(args) > 1 else FW_PATH
        with open(file_path, "rb") as f:
            data = f.read()
        r = upload_raw(data, "upgrade")
        print(json.dumps(r, indent=2, ensure_ascii=False))
        
    elif args[0] == "test":
        use_raw = "--raw" in args or "-r" in args
        upload_fn = upload_raw if use_raw else upload_multipart
        print(f"اختبار {'RAW' if use_raw else 'MULTIPART'}...")
        for size in [100, 512, 1024, 2048, 4096, 5120, 6144, 7168,
                     8192, 10240, 16384, 65536, 262144]:
            data = b'\x00' * size
            r = upload_fn(data, "upgrade")
            icon = "✅" if r.get("success") else ("⚠️" if r["status"] == 200 else "❌")
            print(f"  {icon} size={size:>8d}: HTTP {r['status']:3d} cause={r.get('error_cause','?'):2} {r.get('note','')[:40]}")
    
    elif args[0] == "check":
        test_firmware_compatibility()
        
    elif args[0] == "ota":
        print(json.dumps(check_ota_status(), indent=2, ensure_ascii=False))
        
    elif args[0] == "reboot":
        r = api_login.api_call("router", "router_call_reboot")
        print(r)
        print(wait_for_reboot())
        
    elif args[0] == "inspect":
        path = args[1] if len(args) > 1 else FW_PATH
        info = inspect_firmware(path)
        print(json.dumps(info, indent=2, ensure_ascii=False, default=str))
        
    elif args[0] == "help" or args[0] == "--help":
        print("""
الاستعمال:
  python3 api_upload.py                        # اختبار شامل
  python3 api_upload.py upgrade <ملف>          # رفع firmware (RAW body)
  python3 api_upload.py upgrade <ملف> --multi  # رفع عبر multipart (محدود)
  python3 api_upload.py cp_upgrade <ملف>       # رفع firmware مودم
  python3 api_upload.py raw <ملف>              # رفع RAW body مباشر
  python3 api_upload.py test                   # اختبار الأحجام
  python3 api_upload.py test --multi           # اختبار multipart
  python3 api_upload.py check                  # فحص معمارية firmware
  python3 api_upload.py inspect <ملف>          # تحليل ترويسة firmware
  python3 api_upload.py ota                    # استعلام OTA
  python3 api_upload.py reboot                 # إعادة تشغيل
    """.strip())
        
    else:
        print("استعمل: python3 api_upload.py help")


if __name__ == "__main__":
    main()
