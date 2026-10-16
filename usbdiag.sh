#!/bin/sh
{
echo "===== /volume* ====="
ls -la /volumeUSB* 2>&1
echo "===== /vol1 /vol2 顶层 ====="
ls /vol1/ /vol2/ 2>&1
echo "===== find volumeUSB ====="
find /vol1 /vol2 / -maxdepth 2 -name "volumeUSB*" -o -maxdepth 2 -name "*usb*" 2>/dev/null | head -20
echo "===== mount | grep -i usb ====="
mount 2>/dev/null | grep -i "usb\|sd[b-z]" | head -20
echo "===== /proc/mounts usb/sd ====="
grep -iE "usb|sd[b-z]|exfat|vfat|ntfs" /proc/mounts 2>/dev/null | head -20
echo "===== lsblk ====="
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT,LABEL 2>/dev/null | head -30
echo "===== blkid ====="
blkid 2>/dev/null | head -20
echo "===== /media /mnt ====="
ls -la /media/ /mnt/ /run/media/ 2>&1 | head -30
echo "===== df ====="
df -h 2>/dev/null | head -20
echo "===== id ====="
id
echo "===== test readdir / ====="
python3 -c "import os; print(sorted([d for d in os.listdir('/') if 'vol' in d.lower() or 'usb' in d.lower() or 'media' in d.lower() or 'mnt' in d.lower()]))"
} > /work/1000/usbdiag.txt 2>&1
