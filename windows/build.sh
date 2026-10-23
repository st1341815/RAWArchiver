#!/bin/bash
# RAW 归档 —— Windows 应用构建脚本（在 Windows（git-bash）/CI 的 windows runner 上运行）
#
# 流程：同步核心与前端（fnOS 平台副本）→ 下载 ExifTool.exe → venv + 依赖 →
#       生成 .ico → PyInstaller（onedir + 双 exe）→ CLI 自测 → zip 便携包
#
# 产物：dist/RawArchiver/（RawArchiver.exe + RawArchiver-cli.exe + _internal/）
#      dist/RawArchiver-windows-x64.zip
set -euo pipefail
export PYTHONIOENCODING=utf-8   # Windows 控制台默认 GBK，避免 python print 中文/符号编码崩
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
FOS="$ROOT/fnos/rawarchiver/app"
VER="$(awk -F'"' '/^VERSION = /{print $2}' app/server_win.py)"
[ -n "$VER" ] || { echo "无法从 app/server_win.py 读到 VERSION"; exit 1; }

# Windows git-bash 下 venv 路径是 Scripts/，POSIX 是 bin/
if [ "${OS:-}" = "Windows_NT" ]; then
  PY=".venv/Scripts/python.exe"
else
  PY=".venv/bin/python3"
fi

echo "== [1/6] 同步核心与前端（fnOS 平台副本 → windows/app）=="
mkdir -p app/scripts app/www
cp "$FOS/scripts/raw_archiver.py" app/scripts/raw_archiver.py
cp "$FOS/www/index.html"          app/www/index.html
cp "$FOS/www/auth-callback.html"  app/www/auth-callback.html 2>/dev/null || true
echo "   core: $(wc -c < app/scripts/raw_archiver.py) B；index.html: $(wc -c < app/www/index.html) B"

echo "== [2/6] ExifTool（Windows 独立 exe，随包）=="
ET_LATEST="$(curl -fsSL -m 20 https://exiftool.org/ver.txt 2>/dev/null | tr -d '[:space:]' || true)"
ET_VER="${EXIFTOOL_VER:-${ET_LATEST:-13.59}}"
mkdir -p app/vendor/exiftool
if [ -f app/vendor/exiftool/exiftool.exe ]; then
  echo "   已存在 app/vendor/exiftool/exiftool.exe（跳过）"
else
  # Windows 版只有 SourceForge 一个来源（exiftool.org 直链不含 _64.zip）。
  # 官方 Windows 包 = exiftool(-k).exe 包装器 + exiftool_files/（perl 运行时 + lib），
  # 两者都要随包：包装器改名 exiftool.exe（core 找这个名），运行时目录原样带上。
  echo "   下载 ExifTool $ET_VER (Windows) ..."
  TMP="$(mktemp -d)"
  curl -fsSL -m 300 "https://sourceforge.net/projects/exiftool/files/exiftool-${ET_VER}_64.zip/download" -o "$TMP/et.zip"
  (cd "$TMP" && unzip -o -q et.zip)
  DIR="$(find "$TMP" -maxdepth 1 -mindepth 1 -type d | head -1)"   # exiftool-<ver>_64/
  ETEXE="$(find "$DIR" -maxdepth 1 -iname 'exiftool*.exe' | head -1)"
  [ -n "$ETEXE" ] || { echo "解压失败：未找到 exiftool*.exe"; exit 1; }
  cp -a "$ETEXE" app/vendor/exiftool/exiftool.exe
  if [ -d "$DIR/exiftool_files" ]; then
    cp -a "$DIR/exiftool_files" app/vendor/exiftool/exiftool_files
  fi
  rm -rf "$TMP"
fi
echo "   ExifTool.exe 就位（$(wc -c < app/vendor/exiftool/exiftool.exe) B + exiftool_files/）"

echo "== [3/6] 依赖（.venv）=="
if [ ! -f "$PY" ] || [ "${FORCE_VENV:-0}" = "1" ]; then
  python -m venv .venv
fi
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q pyinstaller pywebview exifread Pillow
echo "   $("$PY" --version) · pyinstaller $("$PY" -m PyInstaller --version)"

echo "== [4/6] 图标（.ico）=="
mkdir -p build
"$PY" make_icon.py "$ROOT/fnos/icon-source.png" build/RawArchiver.ico
echo "   build/RawArchiver.ico 就位"

echo "== [5/6] PyInstaller 打包（onedir + 双 exe）=="
rm -rf build/RawArchiver dist/RawArchiver
"$PY" -m PyInstaller RawArchiver.spec --noconfirm --distpath dist --workpath build
[ -f "dist/RawArchiver/RawArchiver.exe" ] || { echo "打包失败：RawArchiver.exe 不存在"; exit 1; }
[ -f "dist/RawArchiver/RawArchiver-cli.exe" ] || { echo "打包失败：RawArchiver-cli.exe 不存在"; exit 1; }

echo "== [6/6] CLI 自测（验证 frozen + 动态 import core + ExifTool 链路）=="
# 用 Python 脚本做自测：git-bash 的 mktemp 返回 /tmp/...（Windows 原生 Python 不认），
# 所以临时目录、路径、断言全部交给 python（tempfile）。
"$PY" tests/cli_selftest.py

ZIP="dist/RawArchiver-windows-${VER}-x64.zip"
rm -f "$ZIP" dist/RawArchiver-windows-x64.zip
# Git for Windows 不带 zip 命令，用 python zipfile 打包（相对路径 RawArchiver/...）
"$PY" make_zip.py "$ZIP"
echo ""
echo "构建完成："
echo "  · dist/RawArchiver/（RawArchiver.exe + RawArchiver-cli.exe）"
echo "  · $ZIP ($(du -h "$ZIP" | cut -f1))"
echo ""
echo "[发版用] Release 附件名: $(basename "$ZIP")"
