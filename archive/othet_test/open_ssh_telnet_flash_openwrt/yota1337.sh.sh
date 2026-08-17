#!/bin/sh

echo "UNLOCKING"

ubus call version set_atcmd_info '{"atcmd":"AT*PROD=2"}' > /dev/null
ubus call version set_atcmd_info '{"atcmd":"AT*MRD_MEP=D"}' > /dev/null
ubus call version set_atcmd_info '{"atcmd":"AT*PROD=0"}' > /dev/null
sleep 3

echo "DOWNLOADING FIRMWARE"
wget http://archive.org/download/firmware1337/firmware1337.bin -O /tmp/a.bin
firmware2=$(cat /proc/mtd | grep firmware2 | awk '{print $1}')

echo "CHECKING HASH"
hash=$(md5sum /tmp/a.bin | awk '{print $1}')
echo "$hash = be2651b1afbb0372d8b054f5b28be910" 
if [ $hash == 'be2651b1afbb0372d8b054f5b28be910' ]
then
echo "SAME!"
jffs2reset -y 2> /dev/null && firstboot -y 2> /dev/null
mtd erase rootfs_data 2> /dev/null
if [ $firmware2 == 'mtd7:' ];
then
echo "FLASHING..."
mtd -r write /tmp/a.bin /dev/mtd4
exit
fi
echo "FLASHING..."
mtd -r write /tmp/a.bin /dev/mtd5
exit
else
echo "NOT SAME!"
fi
	