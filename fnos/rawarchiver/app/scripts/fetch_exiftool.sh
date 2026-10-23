#!/bin/sh
# RAW 归档 —— ExifTool 获取脚本（打包前跑一次，产物进 vendor/exiftool/）
# 来源按顺序尝试：本机已有 → SourceForge 官方包（版本取 ver.txt 最新）→ 主站直链
# 注意：exiftool.org 主站只保留最新版 tar，写死旧版本号会 404。
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/vendor/exiftool"
LATEST="$(curl -fsSL -m 20 https://exiftool.org/ver.txt 2>/dev/null | tr -d '[:space:]' || true)"
VER="${EXIFTOOL_VER:-${LATEST:-13.59}}"
SF_URL="https://sourceforge.net/projects/exiftool/files/Image-ExifTool-${VER}.tar.gz/download"
ORG_URL="https://exiftool.org/Image-ExifTool-${VER}.tar.gz"
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

# 2) 官方包（SourceForge 优先，主站兜底）
TMP="$(mktemp -d)"
echo "下载 ExifTool $VER ..."
if command -v curl >/dev/null 2>&1; then
  curl -fsSL -m 300 "$SF_URL" -o "$TMP/et.tar.gz" 2>/dev/null \
    || curl -fsSL -m 300 "$ORG_URL" -o "$TMP/et.tar.gz"
elif command -v wget >/dev/null 2>&1; then
  wget -O "$TMP/et.tar.gz" "$SF_URL" || wget -O "$TMP/et.tar.gz" "$ORG_URL"
else echo "无 curl/wget，无法下载"; rm -rf "$TMP"; exit 1; fi

tar -xzf "$TMP/et.tar.gz" -C "$TMP"
DIR="$(find "$TMP" -maxdepth 1 -mindepth 1 -type d | head -1)"
[ -n "$DIR" ] || { echo "解压失败"; rm -rf "$TMP"; exit 1; }
cp -a "$DIR/exiftool" "$DEST/exiftool"
cp -a "$DIR/lib"      "$DEST/lib"
chmod +x "$DEST/exiftool"
rm -rf "$TMP"
perl "$DEST/exiftool" -ver && echo "OK: ExifTool $VER 已就位 -> $DEST"
