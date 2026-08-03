admin
Om@0Yt#5

رقاقات WiFi	Realtek RTL8812FR + 8192FR (وليس MediaTek كما كان متوقعاً)
السويتش	Motorcomm YT9215RB (خارجي)
معالج رئيسي	تحت المشتت الحراري - عليه "M221"


Backup كامل قبل أي فلاش:
cat /dev/mtd0 > /tmp/uboot.bin
cat /dev/mtd2 > /tmp/factory.bin
cat /dev/mtd4 > /tmp/firmware1.bin
cat /dev/mtd5 > /tmp/firmware2.bin

sudo picocom -b 57600 /dev/ttyUSB0
# أوpicocom
ctr +a
ctrl + x
doas picocom -b 57600 /dev/ttyUSB0
doas picocom -b 115200 /dev/ttyUSB0
   - https://www.mediafire.com/file/ouyw7goa36asjwl/notionv3r291.bin - Notion V3 firmware for R291

bootcmd=tftp
ipaddr=10.10.10.123 الراوتر
serverip=10.10.10.3 الحاسب
bootfile=firmware.bin
bootdelay=1

These are DIFFERENT from the ALL.bin SmartBro U-Boot which had:
ipaddr=10.10.18.128
serverip=10.10.18.100
  
  ------------- محاولات ناجحة
  1-  استطاع واحد تفليشه بسكربت غير مفتوح المصدر، السكربت يكتب هذا:
المستخدم وضع session id من المتصفح وأدخلاه في السكربت ثم الكربت كتب:
flashing
[::ffff:192.168.1.1]:52547: response:200
[::ffff:192.168.1.1]:52548: response:200
بعد دقيقة واحدة كتب: done flashing
ثم صاحب الفيديو قطع معه الاتصال بالموديم وانتظر قليلا فأعاد الموديم الاتصال وظهرت نسخة جديدة بالمتصفح
التطبيق exe حجمه حوالي 8 ميغابات وأكثر بقليل
 r291-tunisia-unlock.exe

 حب ما فهمته: أنه استطاع فلاش النظام عبر api واستعمل cookie
 حاول بنفس الطريقة، نجرب تفليش هذا: notionv3r291.bin
 
   
  2- وجدت فيديو آخر يظهر تطبيقات لفلاش هذا الراوتر مكتوب:
  المستخدم فتح هذا المجلد:
  File List:
  Name Size Type
  7za.exe 938 KBA pplication
  a.bin 10,810 KB BIN File
  all.7z 10,657 KB Compressed...
  busybox.exe 739 KB Application 
  curl.exe 4,551 KB Application 
  curl-ca-bundle.crt 217 KB Security Certificate
  exit.bat 1 KB Windows Batch File
  flash 2 KB File 
  flash.bat 27 KB Windows Batch File
  libcurl.def 3 KB DEF File
  libcurl.dll 4,200 KB Application 
  Extensions 1 KB File
  uboot.bin 312 KB BIN File
    ثم فتح إحدى الملفات:
  
UNLOCKING...
FLASHING BOOTLOADER
Checking hash!
707b4f4c5f2cee77affcbd7d0cc731ec = 707b4f4c5f2cee77affcbd7d...
Enabling TFTP Flashing... Done.
FLASHING NOTION V3 ABS FIRMWARE
CHECKING HASH
caa5c1d2c5287bdfc85d61e9b2753a1d = caa5c1d2c5287bdfc85d61e9b...
SAME!
FLASHING NOTION V3 ABS SUPERLITE FIRMWARE
WAIT FOR THE MODEM TO REBOOT

The hashes:
- notionv3r291.bin hash = caa5c1d2c5287bdfc85d61e9b2753a1d — هذا يطابق الـ

3- وواحد آخر استعمال: temper monkey واستعمل:  lucas-liam-router-unlock-beta.user.js 

إذا هذه 3 محاولات. كيف نستطيع محاكاتها.
كذلك عندي سؤال: أنا جربت دخول tftp بطرق كثيرة مختلفة ولم أستطع. لو كان يعمل مباشرة فلماذ قال flasher enabling tftp? هذا يعني أنه لم يكن مفعلا وأنه يحاتاج مثلا فلاش bootloader ليتم تفعيله؟


https://www.mediafire.com/file/wwq939t1u3d547x/firmware_telnetd.bin/file
https://www.mediafire.com/file/ouyw7goa36asjwl/notionv3r291.bin/file 
https://www.mediafire.com/file/9vnad9s6wkauod5/R281_notion_v3.bin/file

flash unlockscript
USB TO TTL R291
Serial speed COM3: 57600 
tapos after 6secs mag boot Usb  to TTL
Press f and hit enter 

mount_root
passwd root -d
root
reboot

press 3 and hit enter

just press enter and rightclick to paste the command below

root
firstboot -y
jffs2reset -y

wget http://192.168.1.103/firmware_telnetd.bin -O /tmp/firmware.bin

cat /proc/mtd

mtd -r write /tmp/firmware.bin /dev/mtd4

mtd -r write /tmp/firmware.bin /dev/mtd5

telnet after flash to USB-TTL- Stock firmware

firstboot -y
jffs2reset -y

wget http://192.168.1.103/notionv3r291.bin -O /tmp/firmware.bin

wget http://192.168.1.103/R281_notion_v3.bin -O /tmp/firmware.bin

cat /proc/mtd

mtd -r write /tmp/firmware.bin /dev/mtd4

mtd -r write /tmp/firmware.bin /dev/mtd5

Telnet password
@Superlightweight123
#R281 5.4
#R291
#BOOSTEVEN
#SMARTBRO
#OPENLINE

ssh 192.168.1.1 -o HostKeyAlgorithms=ssh-rsa -o KexAlgorithms=diffie-hellman-group14-sha1 -l root
19222019

ssh -i ~/.ssh/id_rsa_modified  -o HostKeyAlgorithms=ssh-rsa -o KexAlgorithms=diffie-hellman-group14-sha1 root@192.168.1.1


python3 api_ssh.py enable

