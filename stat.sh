#!/bin/sh
stat -c '%a %U %G %n' /work/@appcenter/file.dedupe/file-dedupe.sock > /work/1000/sockstat.txt 2>&1
stat -c '%a %U %G %n' /work/@appcenter/rawarchiver >> /work/1000/sockstat.txt 2>&1
ls -la /work/@appcenter/rawarchiver/ > /work/1000/sockstat.txt2 2>&1
