# RGW Web API (xml_action.cgi) — Ooredoo P298

> المصدر الأصلي: `othet_test/ooreoo_r291.md` (مؤرشَف في `archive/`) — نُقل هنا بعد تصحيح
> الأخطاء: المعالج هو **ARM Cortex-A7 (ASR1802S)** وليس MIPS؛ منفذ UART الفعلي موثّق أدناه.

## الجهاز
- **موديل**: Ooredoo P298، hw_ver `P298_N13`
- **باب**: `20240411_18_29`, Ooredoo P298
- **ذاكرة**: DDR 128MB, FLASH 128MB (NAND)
- **MAC**: `7C:99:2E:4F:35:12`
- **IP**: `192.168.1.1`
- **SoC**: ASR Microelectronics **ASR1802S** — **ARM Cortex-A7** (وليس MIPS)
  (kernel vendor: 3.10.33، U-Boot 1.1.3 May 11 2018)
- **U-Boot**: 1.1.3 (May 11 2018) موجود في ALL.bin عند offset 0x0، عنده TFTP
  (`tftpboot`, `serverip`, `ipaddr`, `bootcmd`) — bootcmd=mrvlboot
- **UART**: pxa2xx-uart @ `d4017000` (115200n8 — بحسب PORTING_STEPS). ملاحظة قديمة من
  تحليل binary strings ذكرت 57600 على ttyS1 — لم تُستعمل بعد على الهاردوير الفعلي.
  (فشل ربط UART حتى الآن — لا يوجد وصول UART حاليًا)

## Authentication
- **باسورد admin الأصلي**: `Om@0Yt#5` ✅ — HA1 `5f29134628ccd9399f87c070d6ee741f` =
  `md5("admin:Highwmg:Om@0Yt#5")` مطابق لـ `/www/data/pswd.htdigest`
- **Digest**: realm=`"Highwmg"`, nonce دائماً `"1000"`, qop=`"auth"`
- **csrftoken**: `hfiehifejfklihefiuehflejhfueihfeuihfeui`
- **Login**: GET `/login.cgi?Action=Digest&username=admin&realm=Highwmg&nonce=1000&response=<md5>&qop=auth&cnonce=<cnonce>&nc=00000001&temp=marvell` + Authorization header Digest
- **CGISID**: يحصل عليه من Set-Cookie بعد login

## API — 3 Headers مطلوبة
1. `Cookie: CGISID=<session>`
2. `Authorization: Digest ...` (uri="/cgi/xml_action.cgi")
3. `csrftoken: hfiehifejfklihefiuehflejhfueihfeuihfeui`

**XML format**: لازم يبدأ بـ `<?xml version="1.0" encoding="utf-8"?>` ثم
`<RGW><param><method>call</method><session>000</session><obj_path>...</obj_path><obj_method>...</obj_method></param>...</RGW>`

## ما ينجح (API)

| Method | النتيجة |
|--------|---------|
| `version/get_version` | Full info + `setting_response: OK` |
| `system/info` | kernel 3.10.33, hostname cpe.baseline.com |
| `system/board` | معلومات البورد |
| `cm/set_eng_mode mode=2` | OK → engineering mode |
| `router/get_product_info` | DDR=128, FLASH=128 |
| `router/get_dropbear_info` | dropbear_mode=1, key_type=0 |
| `sim/get_sim_status` | sim_status=0, mep_attempts=10 |
| `ota/query` | `"not start"` أو `"failed"` |
| `ota/download` | `"download ready"` (يقبل URL لكن ما في OTA daemon يعالجه) |
| `tr069/tr069_set_info` | OK (يغيّر ACS URL) |
| `account/get_account` | فارغ |
| `router/get_eng_mode` | mode=2 |

## Config Restore — يعمل كاملاً
- **تحميل النسخة المشفرة**: POST `xml_action.cgi?Action=Download&file=backup_config` → 10080
  بايت ملف OpenSSL-encrypted (`Salted__`)
- **رفع واستعادة**: POST `xml_action.cgi?Action=Upload&file=restore_config` multipart مع
  `CGISID` فقط (بدون Digest/csrftoken) → router يdecrypt ويعرض محتويات tar.gz ←
  `restore_status=0` ← reboot بعد ~45 ثانية
- **باسورد التشفير**: مجهول! `notion` من NotionV3 ما يشتغل. جُرّبت 68+ كلمة سر (كلها فشلت).
  ممكن يكون مختلف لكل جهاز (مثل serial number أو MAC). — لاحقًا نجح فك تشفير config عبر
  `othet_test/decrypt_config.py` (راجع `archive/othet_test/decrypted_config/`)
- **Plain tar.gz**: مرفوض (HTTP 500) — لازم OpenSSL-encrypted

## Firmware Upload — الرفع ينجح، التفعيل يفشل
- **رفع**: POST `xml_action.cgi?Action=Upload&file=upgrade` multipart مع `CGISID` cookie +
  `csrftoken` كـ form field → `error_cause=0` (الملف مقبول)
- **التحقق**: `ota/query` → `"failed"` فوراً
- **السبب**: OTA daemon **موقوف**! السطر `# start_instance 0 "ota"` معلّق في
  `/etc/init.d/services.init` (السطر 69). CGI يحفظ الملف في `/tmp/firmware.bin` لكن ما في
  daemon يعالجه.
- **ما في API** يشغّل الـ OTA daemon أو يستدعي `sysupgrade` مباشرة
- **كل API calls للـ upgrade**: `system/upgrade`, `router/upgrade`,
  `system/flash_firmware`, `router/do_upgrade` — كلها ترجع فارغ (لا تأثير)

## Firmware Format
- `platform.sh` يقبل magic: `27051956` (uImage) أو `4e474953` (NGIS)
- إذا `/etc/public` != `"unspport"` → يقبل NGIS فقط
- Ooredoo live: `/etc/public` **مقروء** (ما في API لقراءة الملفات)
- NotionV3: `"unspport"` → يقبل الاثنين
- OTA يفشل بسبب الـ daemon موقوف، مش بالضرورة بسبب التنسيق

## Firmware Files — Hashes مؤكدة
| ملف | Hash MD5 | حجم | وصف |
|-----|----------|------|------|
| `notionv3r291.bin` (نسخة Downloads) | `caa5c1d2c5287bdfc85d61e9b2753a1d` | 10.4MB | uImage, يطابق video hash |
| `firmware.bin` (jhowel22) | `de4cc508d9ad81df08ac00e2d62a53a7` | 9.8MB | uImage |
| `Smartbro-R291-OldWebui.bin` | `d93c4084d0f15750f5691278247919de` | 8.1MB | uImage |
| `ALL` (NAND dump كامل) | — | 16MB | U-Boot 1.1.3 في offset 0 + uImage في 0x50000 |
| `firmware_telnetd.bin` | — | 1.5MB | **مبتور!** header يقول 1.7MB البيانات، موجود فقط 1.5MB |
| `/tmp/notionv3r291.bin` | `5d44c4d16b13d47e08f7e84ba5f5358d` | 6.5MB | مختلف عن نسخة Downloads (أصغر) |
| `R281-R291_Unlocked_free_firmware.bin` | — | 11.7MB | Unlocked firmware (من jhowel22 repo) |
| `uboot.bin` (من video) | `707b4f4c5f2cee77affcbd7d0cc731ec` | 312KB | Bootloader، يطابق part في ALL.bin |

## تحليل فيديو flash.bat — التسلسل الدقيق
1. `7za.exe x all.7z` — فك ضغط
2. **UNLOCKING** — curl call لفتح القفل
3. **FLASHING BOOTLOADER** — رفع `uboot.bin` (312KB, hash `707b4f4c...`)
4. **Checking hash!** — التحقق من `707b4f4c5f2cee77affcbd7d0cc731ec`
5. **Enabling TFTP Flashing... Done.** — تفعيل الـ TFTP في U-Boot
6. **FLASHING NOTION V3 ABS FIRMWARE** — `a.bin` (10.8MB = notionv3r291.bin, hash `caa5c1d2...`)
7. **CHECKING HASH** — `caa5c1d2c5287bdfc85d61e9b2753a1d`
8. **SAME!** — تأكيد التطابق
9. **FLASHING NOTION V3 ABS SUPERLITE FIRMWARE** — فلاش إضافي
10. **WAIT FOR THE MODEM TO REBOOT**

الأدوات المستخدمة: `busybox.exe` (TFTP server داخلي)، `curl.exe` (HTTP API)، `7za.exe` (فك ضغط 7z)

### ما نعرفه من السكربت
الـ `curl` يستخدم Session ID (وليس باسورد) للتواصل مع الراوتر على port 80. يستخدم
`busybox tftpd` كـ TFTP server على port 69.

## ما لا ينجح

### APIs يكرش الراوتر (يرجع بعد ~5s عبر watchdog)
- `version/set_atcmd_info` — AT commands
- `router/set_atcmd_info` — AT commands
- `sim/set_atcmd_info` — AT commands
- `set_dropbear_info` — تغيير SSH settings
- `account/set_account`, `router/set_hostname` مع metacharacters — buffer overflow محتمل

### APIs يرجع فارغ (لا تأثير)
- `system/exec` — command execution
- `router/reboot`, `router/call_reboot`, `router/poweroff` — إعادة تشغيل
- `uboot/getenv`, `router/get_env` — U-Boot env
- `router/grenerate_key` — مكتوب غلط (generate مش grenerate)

### APIs يرجع ERROR
- `account/set_account` — تغيير الباسورد
- `sim/set_sim_mep` — SIM unlock (يوصل للـ RIL لكن يرجع ERROR لعدم وجود SIM)

### ممنوعات
- **SSH root impossible**: `dropbear_key_type=0` → يحذف root من `/etc/shadow` تماماً
- **ما في perl, php, python** على الجهاز
- **lua** موجود لكن مش في cgi.assign
- **WebDAV**: الملفات دائماً 0644 (لا +x)، PROPPATCH = 501
- **Config encryption password** مجهول (انظر أعلاه)
- **OTA daemon** و **TR-069 daemon** موقوفين في services.init

> ملاحظة تحديث: فتح SSH root أصبح ممكناً لاحقاً عبر
> `ops/api/` (`acs_tr069.py`) + تثبيت dropbear password من U-Boot env —
> راجع `docs/ops/ssh_open.md` و`docs/recovery/solution.md`.
