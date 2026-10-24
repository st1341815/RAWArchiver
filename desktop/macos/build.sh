#!/bin/bash
# RAW 归档 macOS 原生版（SwiftUI）构建：swift build + 内嵌 Python CLI + 组装 .app + dmg
# 在 macOS（Apple Silicon）或 CI 的 macos runner 上运行。
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd ../.. && pwd)"
FOS="$ROOT/fnos/rawarchiver/app"
VER="1.1.0"

echo "== [1/6] 同步核心 + ExifTool =="
mkdir -p cli-src/scripts cli-src/vendor/exiftool
cp "$FOS/scripts/raw_archiver.py" cli-src/scripts/raw_archiver.py
ET_LATEST="$(curl -fsSL -m 20 https://exiftool.org/ver.txt 2>/dev/null | tr -d '[:space:]' || true)"
ET_VER="${EXIFTOOL_VER:-${ET_LATEST:-13.59}}"
if [ ! -f cli-src/vendor/exiftool/exiftool ]; then
  TMP="$(mktemp -d)"
  curl -fsSL -m 300 "https://sourceforge.net/projects/exiftool/files/Image-ExifTool-${ET_VER}.tar.gz/download" -o "$TMP/et.tar.gz"
  tar -xzf "$TMP/et.tar.gz" -C "$TMP"
  DIR="$(find "$TMP" -maxdepth 1 -mindepth 1 -type d | head -1)"
  cp -a "$DIR/exiftool" cli-src/vendor/exiftool/exiftool
  cp -a "$DIR/lib" cli-src/vendor/exiftool/lib
  chmod +x cli-src/vendor/exiftool/exiftool
  rm -rf "$TMP"
fi
echo "   core $(wc -c < cli-src/scripts/raw_archiver.py) B · ExifTool $(perl cli-src/vendor/exiftool/exiftool -ver)"

echo "== [2/6] 依赖 + PyInstaller 打包 CLI（onedir，console）=="
if [ ! -x .venv/bin/python3 ]; then python3 -m venv .venv; fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q pyinstaller exifread Pillow
rm -rf dist/RawArchiver-cli build/cli
.venv/bin/pyinstaller --onedir --console --name RawArchiver-cli \
  --distpath dist --workpath build/cli \
  --add-data "cli-src/scripts/raw_archiver.py:scripts" \
  --add-data "cli-src/vendor/exiftool:vendor/exiftool" \
  --hidden-import exifread --hidden-import PIL.Image \
  ../core-ipc/ipc_main.py --noconfirm
CLI="dist/RawArchiver-cli/RawArchiver-cli"
[ -x "$CLI" ] || { echo "CLI 打包失败"; exit 1; }
echo "   CLI 就位: $CLI"

echo "== [3/6] swift build（SwiftUI）=="
swift build -c release --arch arm64 2>&1 | tail -3
SWBIN=".build/release/RawArchiver"
[ -x "$SWBIN" ] || SWBIN=".build/arm64-apple-macosx/release/RawArchiver"
[ -x "$SWBIN" ] || { echo "swift build 失败，未找到 $SWBIN"; exit 1; }

echo "== [4/6] 组装 .app =="
rm -rf "dist/RawArchiver.app"
APP="dist/RawArchiver.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$SWBIN" "$APP/Contents/MacOS/RawArchiver"
cp -R "dist/RawArchiver-cli" "$APP/Contents/Resources/RawArchiver-cli"
cp Resources/Info.plist "$APP/Contents/Info.plist"
# 图标（复用 fnos 源图）
mkdir -p build
.venv/bin/python3 - "$ROOT/fnos/icon-source.png" build/RawArchiver.iconset <<'PY'
import sys
from PIL import Image
im = Image.open(sys.argv[1]).convert("RGBA")
w, h = im.size; side = min(w, h)
im = im.crop(((w-side)//2, (h-side)//2, (w+side)//2, (h+side)//2))
sizes = {"icon_16x16.png":16,"icon_16x16@2x.png":32,"icon_32x32.png":32,"icon_32x32@2x.png":64,
         "icon_128x128.png":128,"icon_128x128@2x.png":256,"icon_256x256.png":256,"icon_256x256@2x.png":512,
         "icon_512x512.png":512,"icon_512x512@2x.png":1024}
import os
os.makedirs(sys.argv[2], exist_ok=True)
for name, px in sizes.items():
    im.resize((px, px), Image.LANCZOS).save(os.path.join(sys.argv[2], name))
PY
iconutil -c icns build/RawArchiver.iconset -o "$APP/Contents/Resources/icon.icns"

echo "== [5/6] 签名 + 冒烟 =="
codesign --force --sign - --deep "$APP" >/dev/null 2>&1 || echo "   codesign 跳过"
# 冒烟：内嵌 CLI doctor + preview
INNER="$APP/Contents/Resources/RawArchiver-cli/RawArchiver-cli"
"$INNER" --doctor | .venv/bin/python3 -c '
import json,sys
d=json.load(sys.stdin); assert d["exifread"] and d["pillow"], d
assert d["exiftool"], d
print("   doctor OK: exiftool=%s" % d["exiftool"])
'
T="$(mktemp -d)"
.venv/bin/python3 -c "from PIL import Image; Image.new('RGB',(8,6)).save('$T/a.jpg', quality=85)"
"$INNER" "$T" --output "$T/out" --preview | .venv/bin/python3 -c '
import json,sys
d=json.load(sys.stdin); assert d["total"]==1, d
print("   preview OK")
'
rm -rf "$T"

echo "== [6/6] dmg =="
rm -f "dist/RawArchiver-macOS-${VER}-arm64.dmg"
# 清理可能的残留挂载（CI 偶发 Resource busy）
hdiutil detach "/Volumes/RAW 归档" >/dev/null 2>&1 || true
DMG_STAGE="$(mktemp -d)"
cp -R "$APP" "$DMG_STAGE/"
ln -s /Applications "$DMG_STAGE/Applications"
TMPDMG="dist/.tmp-$$.dmg"
rm -f "$TMPDMG"
hdiutil create -volname "RAW 归档" -srcfolder "$DMG_STAGE" -ov -format UDZO "$TMPDMG" >/dev/null \
  || { sleep 2; hdiutil detach "/Volumes/RAW 归档" >/dev/null 2>&1 || true; hdiutil create -volname "RAW 归档" -srcfolder "$DMG_STAGE" -ov -format UDZO "$TMPDMG" >/dev/null; }
mv "$TMPDMG" "dist/RawArchiver-macOS-${VER}-arm64.dmg"
rm -rf "$DMG_STAGE"
echo ""
echo "构建完成："
echo "  · $APP"
echo "  · dist/RawArchiver-macOS-${VER}-arm64.dmg"
echo ""
echo "[发版用] Release 附件名: RawArchiver-macOS-${VER}-arm64.dmg"
