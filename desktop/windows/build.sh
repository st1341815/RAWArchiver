#!/bin/bash
# RAW 归档 Windows 原生版（WPF）构建 —— 单文件免安装 exe
#
# 产物：dist/publish/RawArchiver.exe（一个文件，双击即用）
#   内部包含：.NET 8 自包含运行时（压缩）+ WPF 界面 + 内嵌的 Python 核心 CLI（单文件）
#
# 依赖构建：PyInstaller --onefile 出 CLI → 作为 EmbeddedResource 打进 WPF → dotnet publish 单文件
set -euo pipefail
export PYTHONIOENCODING=utf-8
cd "$(dirname "$0")"
ROOT="$(cd ../.. && pwd)"
FOS="$ROOT/fnos/rawarchiver/app"
VER="1.1.1"

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

echo "== [2/6] PyInstaller --onefile 打包 CLI（单文件）=="
if [ ! -f "$PY" ]; then python -m venv .venv; fi
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q pyinstaller exifread Pillow
rm -rf dist/onefile build/cli
"$PY" -m PyInstaller --onefile --console --name RawArchiver-cli \
  --distpath dist/onefile --workpath build/cli \
  --add-data "cli-src/scripts/raw_archiver.py;scripts" \
  --add-data "cli-src/vendor/exiftool;vendor/exiftool" \
  --hidden-import exifread --hidden-import PIL.Image \
  ../core-ipc/ipc_main.py --noconfirm
CLI="dist/onefile/RawArchiver-cli.exe"
[ -f "$CLI" ] || { echo "CLI 打包失败"; exit 1; }
echo "   CLI 单文件: $CLI ($(du -h "$CLI" | cut -f1))"

echo "== [3/6] 图标 + 内嵌 CLI =="
"$PY" - "$ROOT/fnos/icon-source.png" RawArchiver/icon.ico <<'PY'
import sys
from PIL import Image
im = Image.open(sys.argv[1]).convert("RGBA")
w, h = im.size; side = min(w, h)
im = im.crop(((w-side)//2, (h-side)//2, (w+side)//2, (h+side)//2))
sizes = [(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]
im.save(sys.argv[2], format="ICO", sizes=sizes)
PY
mkdir -p RawArchiver/Assets
rm -f RawArchiver/Assets/RawArchiver-cli.exe
cp "$CLI" RawArchiver/Assets/RawArchiver-cli.exe
echo "   已内嵌 CLI → RawArchiver/Assets/RawArchiver-cli.exe"

echo "== [4/6] dotnet publish（单文件 + 自包含 + 压缩）=="
rm -rf dist/publish
dotnet publish RawArchiver/RawArchiver.csproj -c Release -r win-x64 --self-contained true \
  -p:PublishSingleFile=true -p:EnableCompressionInSingleFile=true \
  -p:IncludeNativeLibrariesForSelfExtract=true -p:DebugType=none \
  -o dist/publish
[ -f "dist/publish/RawArchiver.exe" ] || { echo "dotnet publish 失败"; exit 1; }

echo "== [5/6] 校验单文件 =="
COUNT=$(ls -1 dist/publish | wc -l)
echo "   publish 目录文件数: $COUNT"
ls -la dist/publish
[ "$COUNT" -eq 1 ] || { echo "失败：publish 目录不是单文件"; exit 1; }
SIZE=$(du -h dist/publish/RawArchiver.exe | cut -f1)
echo "   单文件 exe: dist/publish/RawArchiver.exe ($SIZE)"

echo "== [6/6] 冒烟（内嵌 CLI 的 doctor + IPC preview）=="
"$CLI" --doctor | "$PY" -c '
import json,sys
d=json.load(sys.stdin); assert d["exifread"] and d["pillow"] and d["exiftool"], d
print("   doctor OK: exiftool=%s" % d["exiftool"])
'
"$PY" - "$CLI" <<'PY'
import json, os, subprocess, sys, tempfile
cli = sys.argv[1]
from PIL import Image
t = tempfile.mkdtemp(prefix="rawcli-")
Image.new("RGB", (8, 6), (200, 120, 40)).save(os.path.join(t, "a.jpg"), quality=85)
p = subprocess.Popen([cli, "--ipc"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.DEVNULL, encoding="utf-8")
p.stdin.write(json.dumps({"id": 1, "cmd": "preview", "source": t,
                          "output": os.path.join(t, "out"), "opts": {}}) + "\n")
p.stdin.flush()
r = json.loads(p.stdout.readline())
assert r.get("id") == 1 and r["result"]["total"] == 1, r
print("   IPC preview OK")
p.terminate()
PY
echo ""
# 发版用：带版本号的单文件 exe
cp dist/publish/RawArchiver.exe "dist/RawArchiver-windows-${VER}-x64.exe"
echo "构建完成："
echo "  · dist/publish/RawArchiver.exe（单文件免安装，$(du -h dist/publish/RawArchiver.exe | cut -f1)）"
echo "  · dist/RawArchiver-windows-${VER}-x64.exe"
echo ""
echo "[发版用] Release 附件名: RawArchiver-windows-${VER}-x64.exe"
