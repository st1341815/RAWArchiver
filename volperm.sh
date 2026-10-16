#!/bin/sh
{
echo "===== /v00 (挂载的 /vol00) 权限 ====="
ls -la /v00/ 2>&1 | head -20
echo "===== /v00/MassStorageClass 权限 ====="
ls -la /v00/MassStorageClass/ 2>&1 | head -20
echo "===== stat ====="
stat -c '%A %U %G %n' /v00 /v00/MassStorageClass 2>&1
echo "===== 模拟 978 读（setpriv）====="
setpriv --reuid=978 --regid=978 --clear-groups ls /v00/ 2>&1 | head -10
setpriv --reuid=978 --regid=978 --clear-groups ls /v00/MassStorageClass/ 2>&1 | head -10
} > /work/1000/vol00perm.txt 2>&1
