#!/bin/sh
{
echo "===== 宿主机根目录 /hostfs ====="
ls -la /hostfs/ 2>&1 | head -60
echo "===== /hostfs/vol* 和 usb/media/mnt 顶层 ====="
ls /hostfs/vol1/ 2>&1 | head -30
echo "---vol2---"
ls /hostfs/vol2/ 2>&1 | head -30
echo "---找 volumeUSB / usbshare---"
find /hostfs -maxdepth 3 \( -name "volumeUSB*" -o -name "usbshare*" -o -name "*usb*" \) 2>/dev/null | head -30
echo "===== 宿主机 /proc/mounts 里 usb/sd/exfat/vfat/ntfs ====="
grep -iE "usb|sd[b-z][0-9]|mmcblk|exfat|vfat|ntfs|/volumeUSB|usbshare" /hostfs/proc/mounts 2>/dev/null | head -30
echo "===== 宿主机 lsblk（含可移动）====="
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT,LABEL,RO,RM 2>/dev/null | head -40
} > /work/1000/hostdiag.txt 2>&1
