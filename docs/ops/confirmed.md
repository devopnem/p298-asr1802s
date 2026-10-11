# Ooredoo P298 (Notion P298) — معلومات مؤكدة

## معلومات الجهاز
| الخاصية | القيمة |
|---------|--------|
| الموديل | Ooredoo P298 (HW: P298_N13) |
| النسخة الحالية | Ooredoo P298 (build 20240411_18_29) |
| الجهاز الشبيه | **Megafon C300-1 / Yota C300-1** — نفس اللوحة تماماً |
| العائلة | ASR1802S — **ARM Cortex-A7** (تصحيح: استنتاج "MT7621 MIPS" المبكر كان خاطئاً — مؤكد من dmesg الجهاز الحي: `CPU: ARMv7 Processor [410fc073]`) |

## المعالج (SoC)
- **ASR Microelectronics ASR1802S** (ARMv7 Cortex-A7، مشتق من تصميم Marvell MMP)
- الوصول: U-Boot 1.1.3 (Marvell `mrvlboot`)، kernel vendor 3.10.33
- الذاكرة: DDR 128MB، NAND SPI-NAND 128MB (24 قسم MTD)
- الرقاقة الفيزيائية تحمل نقش "M221" (تحت المشتت الحراري)
- AP وCP داخل نفس الـ SoC: نواة Cortex-A7 واحدة + مودم LTE (CP) بمعالج مستقل

## الرقاقات
| الرقاقة | الوظيفة |
|---------|---------|
| **ASR Microelectronics ASR1802S** | SoC الرئيسي — ARM Cortex-A7 (مشتق Marvell MMP) |
| **MaxLinear SLIC** | VoIP SLIC (موصل SPI، reset GPIO 23، wakeup GPIO 24) |
| **Marvell 88PM801 / 88PM805** | PMIC / Audio codec (I2C 0x30 / 0x38) |
| **Realtek RTL8812FR** | WiFi 5 GHz (802.11ac) |
| **Realtek RTL8192FR** | WiFi 2.4 GHz (802.11b/g/n) |
| **Motorcomm YT9215RB** | سويتش Ethernet خارجي |
| **F35UQA001G** | SPI-NAND 128MB (24 قسم MTD) |

## 🔴 تنبيه: المعمارية ARM وليست MIPS
- **AP (Application Processor)** = ASR1802S Cortex-A7 → **ARM** ← هذا هو الراوتر
- **CP (Cellular Processor)** = المودم داخل الـ SoC (LTE Cat.6)
- استنتاج "MT7621 MIPS" في المراحل المبكرة كان **خطأً** (الجهاز المقارن Megafon C300-1
  هو نفسه ASR1802S ARM). الأدلة القاطعة: dmesg الحي، /proc/iomem (كتل Marvell MMP)،
  درايفرات kernel 3.10.33 (pxa2xx-uart، marvell 88pm…)، والـ SoC عليه نقش "M221".
- كل firmware المتاحة: **ARM** ✅
- **الخلط يسبب ضياع وقت — الراوتر ARM قطعاً**

## البرنامج والويب
| الخاصية | القيمة |
|---------|--------|
| صلاحية WebUI | `admin` / `Om@0Yt#5` |
| Digest nonce | `1000` (ثابت!) |
| csrftoken | `hfiehifejfklihefiuehflejhfueihfeuihfeui` (ثابت!) |
| SSH (port 22) | **🟢 مفتوح** (بعد eng_mode أو set_dropbear_info) |
| Telnet (port 23) | **🔴 مغلق** |
| كلمة سر root SSH | **غير معروفة** — set_dropbear_info لا يغير password (يغير mode و key_type فقط) |
| dropbear | v2016.74, mode=1, key_type=99 (بعد التعديل) |
| XML API base | `/xml_action.cgi?method=set` (Digest + Cookie + csrftoken) |
| Upload CGI | `/xml_action.cgi?Action=Upload&file=upgrade&command=` |

## واجهات الرفع (Upload) — تم اختبارها بدقة 2026-07-30

| الطريقة | upload_type | الحجم الأقصى | HTTP | error_cause | ملاحظة |
|---------|-------------|-------------|------|-------------|--------|
| multipart | upgrade | ≤ 6144 بايت | 200 | 0-2 | يعمل فقط للملفات الصغيرة |
| multipart | upgrade | ≥ 7168 بايت | **500** | -4 | CGI ينهار (buffer overflow في parser) |
| multipart | cp_upgrade | أي حجم | 200 | -2 | يقبل الملف لكن يرفضه ("error") |
| multipart | ca/cert/key/dh | أي حجم | 200 | -2 | يقبل الملف لكن يرفضه |
| **RAW body ⭐** | **upgrade** | **أي حجم** | **200** | **2** | **يتجاوز multipart crash!** |
| RAW body | cp_upgrade | أي حجم | 200 | -2 | يرفضه كـ "error" |
| HTTPS + multipart | upgrade | ≤ 7168 | 200 | 0-2 | HTTPS يعطي +1KB عن HTTP |

RAW body = Content-Type: application/octet-stream مع البيانات مباشرة (بدون multipart)

## error_cause — رموز الخطأ
| الرمز | المعنى |
|-------|---------|
| 0 | ✅ نجاح (بدأت الترقية) — لم نراه أبداً! |
| 1 | خطأ عام |
| 2 | ❌ فشل التحقق من firmware — كل ملفاتنا تعيد هذا |
| -2 | "error" (قبول الملف لكن رفض المحتوى) |
| -4 | HTTP 500 (CGI crash — multipart فقط) |

## لماذا error_cause=2 لكل firmware؟
- **ليس** بسبب معمارية خاطئة (كلها ARM ✅)
- **ليس** بسبب صيغة خاطئة (كلها uImage + SquashFS صحيح ✅)
- **على الأرجح**: أداة الترقية (sysupgrade) **محذوفة** من Ooredoo firmware!
  أو أداة الترقية تتحقق من توقيع رقمي غير موجود في firmware المجتمع
- كل firmware اختُبرت: notionv3r291.bin، OpenWrt initramfs، OpenWrt factory، R281 unlocked، Smartbro OldWebUI

## firmware المتاحة وجميعها ARM ✅
| الملف | الحجم | arch | محتوى |
|-------|-------|------|-------|
| notionv3r291.bin | 10.6MB | ARM | uImage kernel (1.6MB) + SquashFS (9MB) |
| OpenWrt initramfs | 9.6MB | ARM | uImage kernel-only (initramfs) |
| OpenWrt factory | 12.7MB | ARM | uImage (2.5MB) + SquashFS (8.4MB) |
| R281 unlocked | 11.4MB | ARM | uImage (1.6MB LZMA) + SquashFS |
| Smartbro OldWebUI | 10.1MB | ARM | uImage (1.6MB LZMA) + SquashFS |
| uboot.img (TFTP) | 132KB | ARM | U-Boot 1.1.3 مع bootcmd=tftp |

## API methods — SSH/التعديل
| الطريقة | obj_path | obj_method | النتيجة |
|---------|----------|------------|---------|
| ✅ set_eng_mode | cm | set_eng_mode | يفعّل Engineering Mode (mode=2). يخزّن في NVRAM |
| ✅ get_dropbear_info | router | get_dropbear_info | mode=1, key_type=99 (حالياً) |
| ⚠️ set_dropbear_info | router | set_dropbear_info | **يغيّر mode و key_type فقط** — لا يغير password! |
| ❌ set_dropbear_info | router | set_dropbear_info | كان يعلّق HTTP server سابقاً (ربما بسبب صيغة XML) |
| ✅ router_call_reboot | router | router_call_reboot | إعادة تشغيل |
| ✅ ota/query | ota | query | يعيد "failed" (OTA daemon معطل) |
| ❌ upload_fw_ota_init | — | — | دوال داخلية في CGI، ليست ubus methods |

## كلمات سر SSH التي جربت (جميعها فشلت)
admin, root, password, 12345678, Om@0Yt#5, Om@5Wr%8,
$Passworld143, Passworld143, passworld143, P@ssw0rd, 7icF3j8W,
ooredoo, Ooredoo, MTK7621, mtk7621, Zte521, ZTE, zte,
user, guest, (فارغ), admin123, root123, toor, notion,
IMEI 868139070652232, Serial R291240826015571, wifirp90&$MM,
marvell, Marvell, PXA1826, ASR, P298, p298,
Superlightweight123, 123456789, qwerty, letmein

> ✅ **الحل الفعلي**: كلمة المرور موجودة في U-Boot env (`dropbear_password`،
> لهذا الجهاز = `19222019`) — تُقرأ عبر `acs_tr069.py root-shell --discover-pw` ثم `root-check`.

## ماذا يمنعنا؟
1. **error_cause=2**: ترقية firmware عبر API لا تعمل (sysupgrade محذوف؟)
2. **كلمة سر SSH**: SSH مفتوح لكن كلمة سر root مجهولة
3. **set_dropbear_info**: لا يغير كلمة السر الفعلية (يغير mode و key_type فقط)

## الخطوات القادمة الممكنة
4. **بحث عن كلمة سر SSH**: في firmware Ooredoo الأصلي (استخراج shadow)

## SSH command
```
ssh 192.168.1.1 \
  -oKexAlgorithms=+diffie-hellman-group14-sha1 \
  -oHostKeyAlgorithms=+ssh-rsa \
  -oCiphers=+aes128-cbc \
  -oMACs=+hmac-sha1
```

sshpass -p 19222019 ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -o PreferredAuthentications=password \
  -o HostKeyAlgorithms=ssh-rsa \
  -o KexAlgorithms=diffie-hellman-group1-sha1,diffie-hellman-group14-sha1 \
  root@192.168.1.1


# 1) احصل على كلمة المرور الفعلية للجهاز الجديد (بلا تخمين):
python3 acs_tr069.py root-shell --discover-pw
#  ↳ يقرأ env U-Boot dropbear_password ويطبعها، مثلاً: 19222019  أو  أخرى

# 2) إثبات الوصول الجذعري على الجهاز الجديد:
python3 acs_tr069.py root-check
#  ↳ "uid=0(root) ..." → نجحت، أو "فشل" → ننتقل للخطوة 3

# 3) إذا كانت كلمة المرور الافتراضية غير عاملة (dropbear_password فارغة أو مختلطة):
python3 acs_tr069.py arm-root-pw      # (دالة جديدة: تكتب shadow root بكلمة مرور تختارها
                                        #   عبر %EXE fw_setenv + change_ssh_key.sh، ثم reboot)
                                        




# على جهازك (void) الآن — ssh لا يعلق

هذا راوتر notion p298 ip - 192.168.1.1 مجلد النسخة الاحتياطية : ooredoo_backup
هذا الملف: probe فيه بعض البيانات من داخل الراوتر
هذا الملف: archive/openwrt_port/DEVICE_PROFILE.md فيه معلومات الجهاز (قديم — المصدر المحدث:
docs/ + porting/

ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no \
    -o KexAlgorithms=diffie-hellman-group14-sha1 -o HostKeyAlgorithms=+ssh-rsa \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    root@192.168.1.1
    
    pass =    19222019

