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

echo "[1/5] 清理 __pycache__ / *.pyc"
# 打完包才发现：跑过 py_compile / pytest 后在 app/ 里留下 __pycache__，
# fnpack 会把它一起打进 app.tgz（实测多出 ~140KB）。打包前必须清掉。
find "$PKG" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$PKG" -name '*.pyc' -delete 2>/dev/null || true

echo "[2/5] 可执行权限"
chmod +x "$PKG/cmd/"* \
         "$PKG/app/ui/index.cgi" "$PKG/app/api/index.cgi" \
         "$PKG/app/server.py" \
         "$PKG/app/scripts/raw_archiver.py" "$PKG/app/scripts/setup.py" \
         "$PKG/app/scripts/fetch_exiftool.sh" "$PKG/app/scripts/hooks/post_done.sh" \
         "$PKG/app/vendor/exiftool/exiftool" 2>/dev/null || true

echo "[3/5] 打包"
mkdir -p dist
rm -f "$PKG.fpk"
"$FN" build -d "$PKG"
mv -f "$PKG.fpk" dist/

echo "[4/5] 完成"
ls -la "dist/$PKG.fpk"
sha256sum "dist/$PKG.fpk"

# 发版规范：GitHub Release 附件必须带版本号（见 ../README.md「发版规范」）
VER="$(awk '/^version[ \t]*=/{print $3; exit}' "$PKG/manifest")"
echo "[5/5] Release 附件名（发版时用这个）: rawarchiver-${VER}.fpk"
echo "      仓库内构建产物路径保持不变  : dist/$PKG.fpk（build.sh / app install-fpk 依赖）"
