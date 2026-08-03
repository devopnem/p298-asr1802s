# فتح SSH على Ooredoo R291 V2

## الملخص

تم فتح SSH (dropbear 2016.74) على الراوتر عن طريق تفعيل Engineering Mode عبر RGW API، ثم إعادة تشغيل الراوتر.

## الخطوات بالتفصيل

### 1. تسجيل الدخول عبر Digest Auth

```
GET /login.cgi → WWW-Authenticate: Digest realm="Highwmg", nonce="1000", qop="auth"

HA1 = MD5("admin:Highwmg:Om@0Yt#5")
HA2 = MD5("GET:/cgi/xml_action.cgi")
cnonce = MD5(random + timestamp)[:16]
response = MD5(HA1 + ":1000:00000001:" + cnonce + ":auth:" + HA2)

GET /login.cgi?Action=Digest&username=admin&realm=Highwmg&nonce=1000&response=RESPONSE&qop=auth&cnonce=CNONCE&nc=00000001&temp=marvell

← CGISID:<session_cookie>
```

### 2. تفعيل Engineering Mode

إرسال طلب API بتنسيق RGW:

```
POST /xml_action.cgi?method=set
Authorization: Digest ... (نفس الهوية لكن HA2 لـ POST)
csrftoken: hfiehifejfklihefiuehflejhfueihfeuihfeui
Content-Type: application/xml

<?xml version="1.0" encoding="US-ASCII"?>
<RGW>
  <param>
    <method>call</method>
    <session>000</session>
    <obj_path>cm</obj_path>
    <obj_method>set_eng_mode</obj_method>
  </param>
  <wan>
    <mode>2</mode>
  </wan>
</RGW>
```

الاستجابة:
```xml
<?xml version="1.0" encoding="utf-8"?>
<RGW>
  <response>
    <setting_response>OK</setting_response>
  </response>
</RGW>
```

### 3. إعادة تشغيل الراوتر (غير مقصودة)

بعد نجاح `set_eng_mode`، تم إرسال طلب `set_dropbear_info` لتغيير كلمة سر SSH. هذا الطلب تسبب في تعليق خادم HTTP وانقطاع الاتصال بالراوتر. الراوتر أعاد تشغيل نفسه.

### 4. بعد إعادة التشغيل

فحص المنافذ أظهر:
- **SSH (22): مفتوح** ← `SSH-2.0-dropbear_2016.74`
- Telnet (23): لا يزال مقفولاً

API أكد أن eng_mode محفوظ بعد إعادة التشغيل:
```xml
<RGW>
  <connect_switch>...</connect_switch>
  <eng_mode><mode>1</mode></eng_mode>
  ...
</RGW>
```

## التحليل

تفعيل Engineering Mode (`set_eng_mode`) يخزّن القيمة في NVRAM ويستمر عبر إعادة التشغيل. عند الإقلاع مع `eng_mode=1`، يبدأ الراوتر خدمات إضافية غير متاحة في الوضع العادي، ومنها:

- **dropbear** (SSH server) على المنفذ 22
- إمكانية الوصول إلى صفحات ويب مخفية

## كلمة سر SSH

كلمة سر root لـ SSH غير معروفة. المحاولات شملت:
- `$Passworld143` (المذكورة في Pastebin لـ R281)
- `Om@0Yt#5` (كلمة سر WebUI)
- `admin`, `root`, `Zte521`, `ooredoo`
- IMEI (`868139070652232`), serial number (`R2912408260`)
- 15 كلمة سر أخرى شائعة

كلها فشلت. يجب إيجاد طريقة أخرى:

1. فك تشفير config backup للحصول على كلمة السر
2. تغيير كلمة السر عبر API (`set_dropbear_info`)
3. عمل factory reset وإنشاء كلمة سر جديدة
4. فلاش firmware مفتوح (OpenWrt أو Smartbro)

## ملاحظات

- nonce ثابت = `1000` ← Digest auth غير آمن ويمكن إعادة استخدامه
- csrftoken ثابت = `hfiehifejfklihefiuehflejhfueihfeuihfeui`
- إعادة تشغيل الراوتر قد تكون ضرورية لتطبيق eng_mode
- `set_dropbear_info` يسبب تعليق HTTP server (يحتاج صيغة XML مختلفة)
