#!/bin/sh
# RAW 归档 —— ExifTool 获取脚本（打包前跑一次，产物进 vendor/exiftool/）
# 三种来源，按顺序尝试：本机已有 → 官方 tar.bz2 → 直接下 .pl
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/vendor/exiftool"
VER="${EXIFTOOL_VER:-13.00}"
URL="https://exiftool.org/Image-ExifTool-${VER}.tar.bz2"
mkdir -p "$DEST"

if [ -f "$DEST/exiftool" ]; then
  echo "已存在: $DEST/exiftool（跳过）。要覆盖请先删除该文件。"
  exit 0
fi

# 1) 本机已装的 ExifTool：直接复制自包含
if command -v exiftool >/dev/null 2>&1; then
  SRC="$(command -v exiftool)"
  echo "发现本机 ExifTool: $SRC"
  # 若是 perl 脚本，连 exiftool_files/lib 一起带上
  if head -c 40 "$SRC" | grep -qi perl; then
    cp "$SRC" "$DEST/exiftool"
    LIBDIR="$(dirname "$SRC")/../exiftool_files"
    [ -d "$LIBDIR/lib" ] && cp -a "$LIBDIR/lib" "$DEST/lib"
    [ -d "$(dirname $(readlink -f $SRC))/../exiftool_files/lib" ] && cp -a "$(dirname $(readlink -f $SRC))/../exiftool_files/lib" "$DEST/lib" 2>/dev/null || true
  else
    cp -a "$SRC" "$DEST/exiftool"
  fi
  chmod +x "$DEST/exiftool"
  "$DEST/exiftool" -ver 2>/dev/null || perl "$DEST/exiftool" -ver
  echo "OK: 已从本机复制 ExifTool"
  exit 0
fi

# 2) 官方源码包
TMP="$(mktemp -d)"
echo "下载 $URL"
if command -v curl >/dev/null 2>&1; then curl -fL "$URL" -o "$TMP/et.tar.bz2"
elif command -v wget >/dev/null 2>&1; then wget -O "$TMP/et.tar.bz2" "$URL"
else echo "无 curl/wget，无法下载"; rm -rf "$TMP"; exit 1; fi

tar -xjf "$TMP/et.tar.bz2" -C "$TMP"
DIR="$(find "$TMP" -maxdepth 1 -type d -name 'Image-ExifTool-*' | head -1)"
[ -n "$DIR" ] || { echo "解压失败"; rm -rf "$TMP"; exit 1; }
cp -a "$DIR/exiftool" "$DEST/exiftool"
cp -a "$DIR/lib"      "$DEST/lib"
chmod +x "$DEST/exiftool"
rm -rf "$TMP"
perl "$DEST/exiftool" -ver && echo "OK: ExifTool $VER 已就位 -> $DEST"
