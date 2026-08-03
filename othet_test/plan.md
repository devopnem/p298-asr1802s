ر:
📋 خطة العمل والهيكلية البرمجية المعتمدة
/home/void/Downloads/Modems/notion_r291/modular_tests/
├── api_login.py               (الموديول المعتمد لتسجيل الدخول والـ Auth Digest)
├── api_ssh.py                 (الموديول المعتمد لإدارة خادم SSH)
├── api_upload.py              (الموديول المعتمد لرفع الملفات والـ RAW Upload)
│
├── track3_cp_bridge.py        (جديد: المسار 3 - استغلال مودم CP والـ AT Commands)
├── track2_cmd_injection.py    (جديد: المسار 2 - فحص ثغرات حقن الأوامر في Web UI)
└── track1_config_decrypt.py   (جديد: المسار 1 - فك تشفير وفحص ملفات Config Backup)
1️⃣ المسار 3: استغلال المودم الداخلي CP كجسر (track3_cp_bridge.py)
الهدف: استغلال معالج المودم (Marvell PXA1826 / ASR) المربوط داخلياً مع الراوتر عبر واجهة USB/Serial، حيث أن نظام المودم يحمل صلاحية root وكلمة سر معروفة (notion).
خطة العمل البرمجية:
فحص الواجهات المتاحة: الاتصال بجميع منافذ Serial المتوفرة (/dev/ttyACM* و /dev/ttyUSB* و /dev/ttyS*) بسرعة 57600 و 115200 باود.
فحص أوامر AT المتقدمة المكتشفة في cp_rootfs:
AT+CHECKATVALID, AT+aconfig, AT*PROD
AT*MRD_LIST, AT*CPMRD_LIST, AT*MRD_IMEI
AT+CGACT?, AT+CGDCONT?
اختبار حقن الأوامر عبر AT Commands: تجربة إرسال مدخلات تحتوي على فاصلة أوامر مثل ; أو | أو $(...) لمعرفة إذا كانت أداة atcmdsrv في المودم تمرر الأوامر لـ /bin/sh.
إنشاء موديول track3_cp_bridge.py يحتوي على الدوال التالية:
scan_serial_ports(): مسح كاشف للمنافذ.
send_at_cmd(port, cmd): إرسال أوامر AT وقراءة الرد بدقة.
fuzz_at_injection(): تجربة حزم فحص ثغرات الحقن في أوامر AT.
2️⃣ المسار 2: فحص ثغرات حقن الأوامر في Web UI (track2_cmd_injection.py)
الهدف: البحث عن معلمات داخل واجهة الويب (xml_action.cgi) التي قد تمرر المدخلات إلى سكريبتات النظام بدون تنظيف (Unsanitized Shell Inputs).
خطة العمل البرمجية:
تحديد المعلمات الحساسة المستهدفة:
أدوات التشخيص: ping_ip, traceroute_ip, nslookup_host.
إعدادات الشبكة: apn, ssid, hostname, ntp_server, dns1.
معلمات الرفع والـ CGI: filename, command, file.
أنماط الحقن المستعملة (Injection Vectors):
; echo INJECTED > /tmp/test_inject
| echo INJECTED > /tmp/test_inject
$(echo INJECTED > /tmp/test_inject)
 `echo INJECTED > /tmp/test_inject` 
إنشاء موديول track2_cmd_injection.py يحتوي على:
fuzz_diag_tools(): اختبار أدوات التشخيص بالـ XML.
fuzz_network_settings(): اختبار معلمات الـ Network/WAN.
fuzz_upload_parameters(): اختبار معلمات الـ Header واسم الملف في POST requests.
verify_injection(): التحقق من نجاح الحقن.

