#!/bin/bash
# RAW 归档 Windows 原生版（WPF）构建：dotnet publish + 内嵌 Python CLI + zip
# 在 Windows（git-bash）或 CI 的 windows runner 上运行。
set -euo pipefail
export PYTHONIOENCODING=utf-8
cd "$(dirname "$0")"
ROOT="$(cd ../.. && pwd)"
FOS="$ROOT/fnos/rawarchiver/app"
VER="1.1.0"

if [ "${OS:-}" = "Windows_NT" ]; then PY=".venv/Scripts/python.exe"; else PY=".venv/bin/python3"; fi

echo "== [1/6] 同步核心 + ExifTool =="
mkdir -p cli-src/scripts cli-src/vendor/exiftool
cp "$FOS/scripts/raw_archiver.py" cli-src/scripts/raw_archiver.py
ET_LATEST="$(curl -fsSL -m 20 https://exiftool.org/ver.txt 2>/dev/null | tr -d '[:space:]' || true)"
ET_VER="${EXIFTOOL_VER:-${ET_LATEST:-13.59}}"
if [ ! -f cli-src/vendor/exiftool/exiftool.exe ]; then
  TMP="$(mktemp -d)"
  curl -fsSL -m 300 "https://sourceforge.net/projects/exiftool/files/exiftool-${ET_VER}_64.zip/download" -o "$TMP/et.zip"
  (cd "$TMP" && unzip -o -q et.zip)
  DIR="$(find "$TMP" -maxdepth 1 -mindepth 1 -type d | head -1)"
  ETEXE="$(find "$DIR" -maxdepth 1 -iname 'exiftool*.exe' | head -1)"
  [ -n "$ETEXE" ] || { echo "解压失败：未找到 exiftool*.exe"; exit 1; }
  cp -a "$ETEXE" cli-src/vendor/exiftool/exiftool.exe
  [ -d "$DIR/exiftool_files" ] && cp -a "$DIR/exiftool_files" cli-src/vendor/exiftool/exiftool_files
  rm -rf "$TMP"
fi
echo "   core $(wc -c < cli-src/scripts/raw_archiver.py) B · ExifTool.exe $(wc -c < cli-src/vendor/exiftool/exiftool.exe) B"

echo "== [2/6] PyInstaller 打包 CLI（onedir，console）=="
if [ ! -f "$PY" ]; then python -m venv .venv; fi
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q pyinstaller exifread Pillow
rm -rf dist/RawArchiver-cli build/cli
"$PY" -m PyInstaller --onedir --console --name RawArchiver-cli \
  --distpath dist --workpath build/cli \
  --add-data "cli-src/scripts/raw_archiver.py;scripts" \
  --add-data "cli-src/vendor/exiftool;vendor/exiftool" \
  --hidden-import exifread --hidden-import PIL.Image \
  ../core-ipc/ipc_main.py --noconfirm
[ -f "dist/RawArchiver-cli/RawArchiver-cli.exe" ] || { echo "CLI 打包失败"; exit 1; }

echo "== [3/6] 图标（.ico）=="
"$PY" - "$ROOT/fnos/icon-source.png" RawArchiver/icon.ico <<'PY'
import sys
from PIL import Image
im = Image.open(sys.argv[1]).convert("RGBA")
w, h = im.size; side = min(w, h)
im = im.crop(((w-side)//2, (h-side)//2, (w+side)//2, (h+side)//2))
sizes = [(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]
im.save(sys.argv[2], format="ICO", sizes=sizes)
PY

echo "== [4/6] dotnet publish（WPF，win-x64）=="
rm -rf dist/publish
dotnet publish RawArchiver/RawArchiver.csproj -c Release -r win-x64 --self-contained true -o dist/publish
[ -f "dist/publish/RawArchiver.exe" ] || { echo "dotnet publish 失败"; exit 1; }

echo "== [5/6] 组合（CLI 内嵌进 publish 目录）=="
rm -rf dist/publish/RawArchiver-cli
cp -R dist/RawArchiver-cli dist/publish/RawArchiver-cli

echo "== [6/6] 冒烟 + zip =="
INNER="dist/publish/RawArchiver-cli/RawArchiver-cli.exe"
"$INNER" --doctor | "$PY" -c '
import json,sys
d=json.load(sys.stdin); assert d["exifread"] and d["pillow"] and d["exiftool"], d
print("   doctor OK: exiftool=%s" % d["exiftool"])
'
ZIP="dist/RawArchiver-windows-${VER}-x64.zip"
rm -f "$ZIP"
"$PY" - "$ZIP" <<'PY'
import os, sys, zipfile
out = sys.argv[1]
src = os.path.join("dist", "publish")
n = 0
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            p = os.path.join(root, f)
            z.write(p, os.path.relpath(p, "dist"))
            n += 1
print("   zip ok: %s (%d files, %d bytes)" % (out, n, os.path.getsize(out)))
PY
echo ""
echo "构建完成："
echo "  · dist/publish/RawArchiver.exe"
echo "  · $ZIP"
echo ""
echo "[发版用] Release 附件名: RawArchiver-windows-${VER}-x64.zip"
