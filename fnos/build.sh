#!/bin/bash
# 一键构建 RAW 归档 的 .fpk
# 用法：bash build.sh [fnpack路径]   （默认用系统 /usr/local/bin/fnpack）
set -e
cd "$(dirname "$0")"

# 清空可能被注入的 PYTHONPATH，避免误用宿主环境
export PYTHONPATH=

PKG=rawarchiver
FN="${1:-/usr/local/bin/fnpack}"
[ -x "$FN" ] || { echo "找不到 fnpack：$FN" >&2; exit 1; }

echo "[1/3] 可执行权限"
chmod +x "$PKG/cmd/"* \
         "$PKG/app/ui/index.cgi" "$PKG/app/api/index.cgi" \
         "$PKG/app/server.py" \
         "$PKG/app/scripts/raw_archiver.py" "$PKG/app/scripts/setup.py" \
         "$PKG/app/scripts/fetch_exiftool.sh" "$PKG/app/scripts/hooks/post_done.sh" \
         "$PKG/app/vendor/exiftool/exiftool" 2>/dev/null || true

echo "[2/3] 打包"
mkdir -p dist
rm -f "$PKG.fpk"
"$FN" build -d "$PKG"
mv -f "$PKG.fpk" dist/

echo "[3/3] 完成"
ls -la "dist/$PKG.fpk"
sha256sum "dist/$PKG.fpk"
