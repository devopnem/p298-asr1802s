# دليل عملي — TFTP و Failsafe على Ooredoo R291 (بدون UART)

> كل الأوامر تُنفَّذ من جهازك Linux عبر SSH على `root@192.168.1.1`
> كلمة المرور: `85719364` (أو ما يعيده `dropbear_password` من بيئة U-Boot)

```
SSHOPT="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
 -o PreferredAuthentications=password -o PubkeyAuthentication=no \
 -o HostKeyAlgorithms=+ssh-rsa -o KexAlgorithms=diffie-hellman-group1-sha1,diffie-hellman-group14-sha1 \
 -o Ciphers=+aes128-cbc -o MACs=+hmac-sha1"
```

---

## أولاً: TFTP — ⚠️ غير ممكن على البوتلودر الحالي

### لماذا؟
فحصنا ثنائي U-Boot (mtd11) بالكامل: **لا يوجد فيه أي كود شبكة إطلاقاً**
(لا tftpboot، لا إيثرنت، لا PHY، لا DHCP). مستحيل جعله يعمل TFTP بالإعدادات.

### ماذا فعلت أداة المجتمع إذن؟
الفيديو المعروف (flash.bat) كان يعمل هكذا بالترتيب:
1. `FLASHING BOOTLOADER` — **استبدال U-Boot أولاً** بملف `uboot.bin`
   (312KB، md5 `707b4f4c5f2cee77affcbd7d0cc731ec`) — نسخة بديلة تحوي TFTP
2. `Enabling TFTP Flashing... Done` — ثم ضبط `bootcmd=tftp` و`serverip` و`ipaddr`
3. التفليش عبر TFTP ثم إعادة التركيب

أي أن "فتح TFTP" عندهم = تركيب بوتلودر آخر. **لا نفعل ذلك إلا كحل أخير** —
لأن bootloader المخصص قد لا يحترم منطق DTIM/A-B ويُفقدك مزايا المصنع.

### البدائل العملية للتفليش بدون UART (مرتبة بالأولوية)

| المسار | الأداة | متى تستخدمه |
|--------|--------|-------------|
| 1. كتابة مباشرة عبر SSH | `mtderase` على mtd13/mtd15 + إعادة بناء DTIM بالهاشات | الحالة الطبيعية (النظام حي) |
| 2. Failsafe (أدناه) | env + telnet | النظام يقلع لكن SSH/الصورة مكسورة |
| 3. قشرة UART (اختياري) | bootdelay أطول + أوامر spi_flash | عند توفر محول TTL |
| 4. USB download (OBM) | أداة Marvell SWDownloader + كابل USB | تعطّل كلا الـ slot |
| 5. NAND clip | برمجة خارجية | الكارثة المطلقة |

### إن أردت استخدام UART (مكمل فقط)
```bash
# وسّع نافذة المقاطعة من ثانية إلى 10 ثوانٍ (تُطبق بعد إعادة الإقلاع):
sshpass -p 85719364 ssh $SSHOPT root@192.168.1.1 'fw_setenv bootdelay 10'
# ثم من الكونسول 115200: أرسل أي مفتاح خلال 10 ثوانٍ → سترى "Marvell>> "
# أوامر مفيدة هناك:
#   printenv            # عرض البيئة
#   setenv bootcmd run   # استعادة
#   spi_flash read/write # قراءة وكتابة NAND يدوياً
```

---

## ثانياً: Failsafe — ✅ تعمل بالكامل بدون UART

### الفكرة
النظام المصنعي هو OpenWrt (Barrier Breaker 14.07). الـ failsafe يُفعَّل من
`preinit` إذا وجد في سطر إقلاع النواة (`/proc/cmdline`):
- `failsafe_wait=N` (N>0) — يفتح النافذة (بدونها يكون معطلاً افتراضياً!)
- `failsafe=1` — دخول فوري دون أي ضغطة مفتاح

وسطر الإقلاع يأتي من بيئة U-Boot (mtd21) — ونحن نملك `fw_setenv` على الجهاز.

### الخطوة 0 — نسخة احتياطية من البيئة (إلزامي أول مرة)
```bash
sshpass -p 85719364 ssh $SSHOPT root@192.168.1.1 \
  'fw_printenv > /tmp/env_backup.txt; cat /tmp/env_backup.txt'
# احفظ المخرجات عندك — تُستخدم لاحقاً للتراجع
```

### الخطوة 1 — حقن متغيرات failsafe في bootargs
```bash
sshpass -p 85719364 ssh $SSHOPT root@192.168.1.1 \
  'fw_setenv bootargs "root=/dev/mtdblock11 rootfstype=squashfs init=/etc/preinit noinitrd console=ttyS0,115200 panic_debug crashkernel=4k@0x00A00000 RDCA=0x00A00400 rootsize=0xF00000 force_pm80x_fg failsafe_wait=10 failsafe=1"'
# تحقق:
sshpass -p 85719364 ssh $SSHOPT root@192.168.1.1 'fw_printenv bootargs'
```
> القيمة المبدئية يجب أن تطابق ما كنت ستحصل عليه من الخطوة 0 — فقط أضف
> `failsafe_wait=10 failsafe=1` في النهاية. (القيمة هنا من نسختنا الحالية.)

### الخطوة 2 — إعادة الإقلاع إلى failsafe
```bash
sshpass -p 85719364 ssh $SSHOPT root@192.168.1.1 'reboot'
# انتظر 2-3 دقائق (failsafe ينتظر النافذة ثم يقف على القشرة)
```

### الخطوة 3 — الدخول
> ⚠️ **ملاحظة مصححة بشأن الإيثرنت:** بفحص `etc/preinit` على هذا الإصدار وجدنا
> `pi_ifname=` و`fs_failsafe_ifname=` **فارغين** → لا تُهيّأ أي واجهة إيثرنت
> بعنوان 192.168.1.1 أثناء preinit، فمكالمة `telnet 192.168.1.1` **غير قابلة للوصول**
> من LAN في وضع failsafe الافتراضي. القشرة النشطة في failsafe تظهر على **الكونسول UART** فقط:
> - عبر UART (115200): سترى "Please press button now to enter failsafe" ثم بعد الدخول
>   قشرة `ash` root مباشرة على المنفذ.
> - عبر الشبكة: لا تعمل افتراضياً (يلزم تغيير `/etc/preinit` على squashfs للقراءة — غير ممكن).
>
> الطريق العملي للدخول بدون UART هو **نظام الحي نفسه** (الخطوة 0/1 بالأسفل) أو
> "طوق نجاة" مُجهّز مسبقاً كسكربت في `/overlay/etc/init.d/` يستمع على LAN عند وجود
> إشارة مفتاح (أو متغير بيئة) — وهذا يتطلب نظاماً حياً (SSH).

### الخطوة 4 — العودة للحالة الطبيعية (مهم!)
بعد الانتهاء، ارجع bootargs للأصل (بدون متغيرات failsafe):
```bash
sshpass -p 85719364 ssh $SSHOPT root@192.168.1.1 \
  'fw_setenv bootargs "root=/dev/mtdblock11 rootfstype=squashfs init=/etc/preinit noinitrd console=ttyS0,115200 panic_debug crashkernel=4k@0x00A00000 RDCA=0x00A00400 rootsize=0xF00000 force_pm80x_fg"'
# أو من داخل القشرة: نفس الأمر مباشرة
```

### الموقف العملي (مهم)
- **failsafe الحقيقي على هذا الجهاز = قشرة UART** (والنص `99_10_failsafe_login` يشغّل telnetd لكن لا يوصل IP).
- **بديل بدون UART في حاله تعطّل SSH/النظام**: شبكة "طوق نجاة" مثبتة في `/overlay/etc/init.d/`
  تشغّل `telnetd`/`dropbear` على eth عند وصول متغير بيئة U-Boot مثل `dropbear_rescue=1` —
  نظهر هذا لاحقاً عند الحاجة (فيه كتابة مسبقة داخل النظام الحي).

---

## ملاحظات أمان عامة

1. **قبل أي تعديل بيئة**: `fw_printenv` كامل + نسخة mtd21 الخام (لدينا)
2. **قبل أي تفليش**: مزامنة مع ملف DTIM (انظر REPORT.md البند 2) —
   كتابة صورة دون تحديث الهاشات ستُرفض ويقلع الجهاز من الـ slot الآخر
3. U-Boot يتحقق من CRC للبيئة: أي قيمة تالفة → بيئة المصنع الافتراضية
   (آمنة من ناحية عدم التعليق، لكنها تفقد كلمة dropbear_password)
4. لا تلمس mtd0 (OBM) ولا mtd20 (rsa) إلا للضرورة القصوى
