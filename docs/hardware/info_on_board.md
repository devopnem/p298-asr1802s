
# in physical board:

MOTORCOMM
YT9215RB
23021M641
6411311A
8AB452JM0

= Ethernet switch


model M221
2024082106
S/N M22IN3124082415806
الشركة المصنعة: شركة Shanghai Nuoxing Information Technology Co., Ltd. (بالصينية: 上海诺行信息技术有限公司 - وتعرف أيضاً بالعلامة Nuoxing أو Notion)[1][3].

RTL8812FR
01EX3P1 G006

= WIFI 5ghz

realtek 8192FR
M11SQH2 GH10

= Wifi 2.4 ghz

hardware version
P298_N13

MxL
SLLU3
RPN42.08
2321 4 

= telephony

RB47
P61089B
    شريحة P61089B هي شريحة حماية كهربائية تسمى:     Dual Line Programmable Transient Voltage Suppressor (Thyristor)[1].
    
when plug usb:
idVendor=2ecc, idProduct=3002, Product: KSTR, Manufacturer: ASR

= Boot Loader File (.blf)

ملف **نصّي** بصيغة INI-like: أقسام `[Name]` وأسطر `Key = Value`، وليس XML.
الصيغة الكاملة موثّقة في
[findings/tooling/blf/swdownloader-blf-spec.md](../../findings/tooling/blf/swdownloader-blf-spec.md).

ملاحظتان مهمّتان:

* `[TIM_Configuration] Processor_Type` يجب أن يكون **اسم الشريحة** مثل
  `PXA1802` وليس اسم المنصة. الأداة تقارنه بجدول أسماء الشرائح وتعيد اسم
  المنصة (`NEZHA`) كنتيجة، فالكتابة `NEZHA` أو `Falcon` تفشل.
* مفتاح نوع الفلاشة اسمه `Flash_Family` وليس `FlashType`، في قسم
  `[Flash_Properties]`. القيم المقبولة: `NAND`, `eMMC`, `SPI-NOR`, `SPI-NAND`.


