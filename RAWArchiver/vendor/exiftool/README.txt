此目录由 sh scripts/fetch_exiftool.sh 填充，打包前必须存在 exiftool：
  Linux/DSM: vendor/exiftool/exiftool (+ lib/)
  Windows:   vendor/exiftool/exiftool.exe (+ exiftool_files/)
缺失时 build_all.sh 会报错退出（可用 ALLOW_NO_EXIFTOOL=1 强行打包，视频日期会退化为文件时间）。
