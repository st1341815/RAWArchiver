#!/bin/bash
# RAW 归档 —— macOS 应用构建脚本（在 macOS（Apple Silicon）上运行；CI 也调用本脚本）
#
# 流程：同步核心与前端（来自 fnos 平台副本，保证零漂移）→ 下载 ExifTool →
#       venv + 依赖 → 生成 icns → PyInstaller 打包 → CLI 自测 → ad-hoc 签名 → zip
#
# 产物：dist/RawArchiver.app + dist/RawArchiver-macOS-<版本>-arm64.zip
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
FOS="$ROOT/fnos/rawarchiver/app"
VER="$(awk -F'"' '/^VERSION = /{print $2}' app/server_mac.py)"
[ -n "$VER" ] || { echo "无法从 app/server_mac.py 读到 VERSION"; exit 1; }

echo "== [1/6] 同步核心与前端（fnOS 平台副本 → macos/app）=="
mkdir -p app/scripts app/www
cp "$FOS/scripts/raw_archiver.py" app/scripts/raw_archiver.py
cp "$FOS/www/index.html"          app/www/index.html
cp "$FOS/www/auth-callback.html"  app/www/auth-callback.html 2>/dev/null || true
# fnnas.js 有意不拷贝：macOS 前端用动态 import，404 被 catch，不影响功能
echo "   core: $(wc -c < app/scripts/raw_archiver.py) B；index.html: $(wc -c < app/www/index.html) B"

echo "== [2/6] ExifTool（随包，走系统 perl）=="
mkdir -p app/vendor/exiftool
if [ -f app/vendor/exiftool/exiftool ] && [ -d app/vendor/exiftool/lib ]; then
  echo "   已存在 app/vendor/exiftool（跳过）"
else
  # exiftool.org 主站只保留最新版 tar（旧版本的 Image-ExifTool-<v>.tar.* 会 404），
  # 版本号从 ver.txt 动态取；下载三级兜底：SourceForge → 主站 → GitHub api tarball。
  ET_LATEST="$(curl -fsSL -m 20 https://exiftool.org/ver.txt 2>/dev/null | tr -d '[:space:]' || true)"
  ET_VER="${EXIFTOOL_VER:-${ET_LATEST:-13.59}}"
  echo "   下载 ExifTool $ET_VER ..."
  TMP="$(mktemp -d)"
  curl -fsSL -m 300 "https://sourceforge.net/projects/exiftool/files/Image-ExifTool-${ET_VER}.tar.gz/download" -o "$TMP/et.tar.gz" 2>/dev/null \
    || curl -fsSL -m 300 "https://exiftool.org/Image-ExifTool-${ET_VER}.tar.gz" -o "$TMP/et.tar.gz" 2>/dev/null \
    || curl -fsSL -m 300 "https://api.github.com/repos/exiftool/exiftool/tarball/${ET_VER}" -o "$TMP/et.tar.gz"
  tar -xzf "$TMP/et.tar.gz" -C "$TMP"
  DIR="$(find "$TMP" -maxdepth 1 -mindepth 1 -type d | head -1)"
  [ -n "$DIR" ] && [ -f "$DIR/exiftool" ] || { echo "解压失败：$DIR 下没有 exiftool"; exit 1; }
  cp -a "$DIR/exiftool" app/vendor/exiftool/exiftool
  cp -a "$DIR/lib"      app/vendor/exiftool/lib
  chmod +x app/vendor/exiftool/exiftool
  rm -rf "$TMP"
fi
perl app/vendor/exiftool/exiftool -ver || { echo "ExifTool 无法运行（缺 perl？）"; exit 1; }
echo "   ExifTool $(perl app/vendor/exiftool/exiftool -ver) 就位"

echo "== [3/6] 依赖（.venv）=="
if [ ! -x .venv/bin/python3 ] || [ "${FORCE_VENV:-0}" = "1" ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q pyinstaller pywebview exifread Pillow
echo "   $(.venv/bin/python3 --version) · pyinstaller $(.venv/bin/pyinstaller --version)"

echo "== [4/6] 图标（icns）=="
mkdir -p build
.venv/bin/python3 make_icns.py "$ROOT/fnos/icon-source.png" build/RawArchiver.iconset
iconutil -c icns build/RawArchiver.iconset -o build/RawArchiver.icns
echo "   build/RawArchiver.icns 就位"

echo "== [5/6] PyInstaller 打包（arm64 onedir + .app）=="
rm -rf build/RawArchiver dist/RawArchiver dist/RawArchiver.app
.venv/bin/pyinstaller RawArchiver.spec --noconfirm --distpath dist --workpath build
APP="dist/RawArchiver.app"
[ -d "$APP" ] || { echo "打包失败：$APP 不存在"; exit 1; }
codesign --force --sign - --deep "$APP" >/dev/null 2>&1 || echo "   codesign 跳过（不影响使用，首次打开需右键→打开）"

echo "== [6/6] CLI 自测（验证 frozen 环境 + 动态 import core + ExifTool 链路）=="
CLI="$APP/Contents/MacOS/RawArchiver"
DOC="$("$CLI" --doctor)"
echo "   doctor: $DOC"
echo "$DOC" | .venv/bin/python3 -c '
import json, sys
d = json.load(sys.stdin)
assert d["exifread"], "exifread 未打进包"
assert d["pillow"], "Pillow 未打进包"
assert d["exiftool"] and "vendor/exiftool" in d["exiftool"], "ExifTool 未随包: %s" % d["exiftool"]
print("    OK: exifread / Pillow / ExifTool 全部可用")
'
T="$(mktemp -d)"
.venv/bin/python3 -c "from PIL import Image; Image.new('RGB', (8, 6), (200, 120, 40)).save('$T/a.jpg', quality=85)"
"$CLI" "$T" --output "$T/out" --preview | .venv/bin/python3 -c '
import json, sys
d = json.load(sys.stdin)
assert d["total"] == 1, "preview 应扫到 1 个文件，实际 %s" % d["total"]
print("    OK: CLI 转发 + 预览链路正常（1 个文件）")
'
rm -rf "$T"

ZIP="dist/RawArchiver-macOS-${VER}-arm64.zip"
rm -f "$ZIP"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
echo ""
echo "构建完成："
echo "  · $APP"
echo "  · $ZIP ($(du -h "$ZIP" | cut -f1))"
echo ""
echo "[发版用] Release 附件名: $(basename "$ZIP")"
