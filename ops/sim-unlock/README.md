# Notion R291 (Ooredoo) — SIM Unlock — سجل العمل والنتائج

التاريخ: 2026-08-02
المجلد: ops/sim-unlock/ (كل الأدوات والنتائج هنا)

## 1. الخلاصة الحالية

- ✅ SSH root يعمل: `root@192.168.1.1` بكلمة `19222019` (من U-Boot env `dropbear_password`).
- ✅ كلمة سر MEP المكتشفة = **`80822207`** (آخر سلسلة في `/tmp/mep1` == `strings /dev/mtd1 | tail -1`).
- ✅ الطريقة الرسمية لفتح القفل لهذه العائلة (من `othet_test/open_ssh_telnet_flash_openwrt/unlock.txt`):
  `AT%EXE="serial_atcmd AT+CLCK=PN,0,80822207,16"` عبر API `version/set_atcmd_info`
- ⛔ لم يُنفَّذ الفتح بعد — الراوتر انهار قبل تنفيذه.

## 2. تقدم المرحلة 1 (جرد + نسخ احتياطي) — تم ✅

أدوات: `phase1_inventory.py` (paramiko + kex قديم: diffie-hellman-group1/14-sha1, ssh-rsa)
النتائج في هذا المجلد:
- `uname.txt` → Linux 3.10.33 armv7l (SoC ASR1802S / لوحة KAGU)
- `mtd.txt` → 25 قسم MTD (mtd1=cp_reliabledata، mtd2=ap_reliabledata، mtd3/4 نسخ، mtd5/6 mep-ota)
- `cpuinfo.txt`, `meminfo.txt`, `partitions.txt`, `iomem.txt`, `dev_nodes.txt`
- `usr_bin.txt` → أدوات مهمة: `/bin/atcmdsrv`، `/bin/nvmproxy`، `/bin/rild`، `/rom/bin/serial_atcmd`، `nvmcp`
- `processes.txt` فارغ (ps aux غير مدعوم؛ استخدمنا `ps w`)
- **نسخ احتياطية** (128KB لكل):
  - `mtd1_cp_reliabledata.bin` ← يحتوي NVM/MEP (MEP.bin عند 0x9A58، كلمة السر 80822207 عند 0xA1F0/0xA295)
  - `mtd2_factory.bin`، `mtd3_cp_reliabledata_bak.bin`
  - `mtd5_mep_ota.bin` = 0 بايت (محمي: "err: mep-ota protected, open failed!" في dmesg)
- `mep_analysis_report.txt` ← تحليل MEP.bin في mtd1

## 3. تقدم المرحلة 2 (قراءة القفل) — جزئي ✅

- `phase2_analyze_mep.py` → تحليل mtd1 محلياً: وجد `MEP.bin` + `80822207` (مرتين)
- `mep1.bin` (2053 بايت) = نسخة `/tmp/mep1` من الراوتر → آخر سطرين: `80822207`/`80822207`
- `atcmdrec`/`atresprec` = آخر أمر AT وآخر استجابة (الموديم حي: `*CESQ: 99,99,...`)
- ملاحظة: `python3` غير موجود على الراوتر، و`cat` على `/rom/bin/*` يعلق في D-state

## 4. المشكلة الحرجة: انحشار SPI-NAND (D-state) — قيد التحقيق ⚠️

- بعد إعادة تشغيل الراوتر (API reboot عند 14:12–14:16)، ظهرت عمليات عالقة في **D state**
  (قراءة كتل معطوبة من squashfs: `lighttpd`، `tr069`، `cm`، `login`، `serial_atcmd`، `nvmcp`، `find`).
- النتيجة: lighttpd (WebUI) لا يقلع، port 80 ميت، الحمل 8+.
- إعادة التشغيل البرمجية مستحيلة: busybox `reboot` يعلق في `sync()`، لا `/proc/sysrq-trigger`، لا `/dev/watchdog`.
- إعادة التشغيل الفيزيائية أعدت الجهاز مؤقتاً (SSH+80 اشتغلا) ثم انهار مجدداً بعد دقائق، وأصبح غير مستجيب تماماً.
- ملاحظة: `mep-ota protected` تظهر في كل إقلاع — CP يحاول الوصول إلى NAND وقد يتعارض مع قراءات AP.

## 5. الخطوات القادمة (حين يعود الراوتر)

1. فحص: `uptime`، `ps w | grep -E 'D '`، `pidof lighttpd`.
2. إذا WebUI حي:
   `python3 phase2_unlock.py --query` (قراءة AT+CLCK=PN,2)
   ثم `python3 phase2_unlock.py --unlock` (AT+CLCK=PN,0,80822207,16)
   ثم `--verify`
3. إذا WebUI ميت لكن SSH حي:
   - `AT+CLCK=PN,2` ثم الفتح عبر إرسال AT مباشرة على `/dev/cidatatty0` (stty + printf)،
   - أو تنفيذ `serial_atcmd` مباشرة إن كان قابلاً للقراءة بعد إقلاع نظيف.
4. التحقق: شريحة غير Ooredoo + `sim/get_sim_status` + `AT+CREG?`/`AT+CSQ`.

## 6. استرجاع (Backup/Rollback)

- mtd1/mtd2/mtd3 محفوظة محلياً (فوق). استرجاع mtd1 = كتابة النسخة الأصلية.
- `ooredoo_backup/` في المجلد الأب: overlay، etc_config، kernel-a، rootfs-a، oem_data.

## 7. فتح القفل عبر USB CDC-ACM (USB↔PC) — الطريقة الموثوقة

سبب أخذتها: خلية atcmdsrv على الـ Web API تتجاوز `AT*PROD` وأوامر الحماية
(ليست مُرسّاة) وفقّات `set_atcmd_info`، و`serial_atcmd` مُقفّل ببوابة `checkAtCmdValid`
(check `/tmp/flag_usb`). العمود الفقري المثبت في `at_over_usb.txt` على ماودم USB
CDC-ACM يلتف بـ `picocom` — فنافذة نظيفة من غير شبكة.

```
# على الـ PC (بعد توصيل USB والحصول على /dev/ttyACM0):
ls -la /dev/ttyACM0            # أو /dev/ttyUSB0
picocom -b 115200 /dev/ttyACM0   # sudo/doas إذا لزم الخط

# داخل picocom (أرسل كل سطر ثم Enter):
ATE1
AT+CFUN=1            # استعادة إشعال المودم
AT*PROD=2           # فتح بوابة Production Mode (≈ unlock ATCMD gate)
AT*MRD_MEP=D        # تمهيد الوصول لملف MEP (اختياري)
AT+CLCK=PN,0,80822207,16        # ← فتح القفل: كلمة السر 80822207، الصناف 16 (الكل)
AT*PROD=0           # عودة للوضع العادي
AT+CFUN=1
```

تحقق:
```
AT+CLCK=PN,2         # للاستعلام؛ الأمانة هي 0 → غير مقفلة
AT+CPIN?             # READY (لا PH-NET PIN)
AT+CREG?             # +CREG: 0,1 (مسجّل على شبكة غير Ooredoo) مع شريحة غير Ooredoo
```

ملاحظة روتينية: إذا لم يظهر `/dev/ttyACM0` فـ `lsusb` يرى الجهاز (2ecc:3012)
لكن Linux لم يربطه بسبب `usbserial` — شغّله:
```
modprobe usbserial vendor=0x2ecc product=0x3012
# ثم bind الواجهة 2/4 (CDC-ACM) إلى ttyUSB إذا لزم:
echo 1-1:1.4 > /sys/bus/usb/drivers/usbserial/bind   # العنوان قد تختلف
```
كلمة المرور: `19222019` (SSH dropbear) و `Om@0Yt#5` (WebUI). كلمة سر MEP = `80822207`.
