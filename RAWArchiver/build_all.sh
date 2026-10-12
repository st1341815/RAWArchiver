#!/bin/sh
# RAW 归档 v1.0.0 —— 统一打包（SPK for DSM / FPK for fnOS / 源码包）
set -eu
VER=1.0.0; NAME=RAWArchiver
cd "$(dirname "$0")"
ROOT="$(pwd)"
DIST="$ROOT/dist"; STAGE="$ROOT/.stage"
rm -rf "$DIST" "$STAGE"; mkdir -p "$DIST" "$STAGE/spk" "$STAGE/fpk"

say(){ printf '==> %s\n' "$*"; }
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }

say "校验必需文件"
for f in scripts/raw_archiver.py app/rawarchiver/www/index.html app/rawarchiver/api/index.cgi \
         agent/agent.py pkg/spk/INFO pkg/fpk/package.conf; do
  [ -f "$f" ] || die "缺少 $f"
done
chmod +x scripts/raw_archiver.py app/rawarchiver/api/index.cgi agent/agent.py scripts/*.sh 2>/dev/null || true
python3 -c "import ast;ast.parse(open('scripts/raw_archiver.py',encoding='utf-8').read())" || die "raw_archiver.py 语法错误"
perl -c app/rawarchiver/api/index.cgi >/dev/null 2>&1 || say "提示：本机无 perl，跳过 CGI 语法检查"

if [ ! -f vendor/exiftool/exiftool ]; then
  if [ "${ALLOW_NO_EXIFTOOL:-0}" = "1" ]; then
    say "警告：无 ExifTool（ALLOW_NO_EXIFTOOL=1），视频日期会退化为文件时间"
  else
    die "缺 vendor/exiftool/exiftool，先执行: sh scripts/fetch_exiftool.sh （或 ALLOW_NO_EXIFTOOL=1 强行打包）"
  fi
fi

fill(){
  OUT="$1"
  mkdir -p "$OUT/app"
  cp -a app/rawarchiver "$OUT/app/rawarchiver"
  cp -a scripts         "$OUT/scripts"
  cp -a agent           "$OUT/agent"
  if [ -d vendor/exiftool ]; then mkdir -p "$OUT/vendor"; cp -a vendor/exiftool "$OUT/vendor/exiftool"; fi
  if [ -d vendor/wheels  ]; then mkdir -p "$OUT/vendor"; cp -a vendor/wheels  "$OUT/vendor/wheels"; fi
  cp -f requirements.txt "$OUT/" 2>/dev/null || true
  find "$OUT" -name '.DS_Store' -delete 2>/dev/null || true
  find "$OUT" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
}
say "组装 SPK 载荷"; fill "$STAGE/spk"
say "组装 FPK 载荷"; fill "$STAGE/fpk"

cp -a pkg/spk/INFO "$STAGE/spk/INFO"
cp -a pkg/spk/conf "$STAGE/spk/conf"
mkdir -p "$STAGE/spk/package-scripts.d" "$STAGE/spk/etc" "$STAGE/spk/var"
cp -a pkg/spk/package-scripts.d/install.sh "$STAGE/spk/package-scripts.d/install.sh"
chmod 755 "$STAGE/spk/package-scripts.d/install.sh" "$STAGE/spk/app/rawarchiver/api/index.cgi"

cp -a pkg/fpk/package.conf "$STAGE/fpk/package.conf"
cp -a pkg/fpk/cmd_script   "$STAGE/fpk/cmd_script"
chmod -R 755 "$STAGE/fpk/cmd_script"

SPK_ITEMS=$(cd "$STAGE/spk" && ls -A | tr '\n' ' ')
FPK_ITEMS=$(cd "$STAGE/fpk" && ls -A | tr '\n' ' ')
say "打 SPK: $SPK_ITEMS"; ( cd "$STAGE/spk" && tar -czf "$DIST/${NAME}-${VER}.spk" $SPK_ITEMS )
say "打 FPK: $FPK_ITEMS"; ( cd "$STAGE/fpk" && tar -czf "$DIST/${NAME}-${VER}.fpk" $FPK_ITEMS )
say "打源码包"; ( cd "$ROOT" && tar -czf "$DIST/${NAME}-${VER}-src.tar.gz" \
    --exclude='./dist' --exclude='./.stage' --exclude='./agent/venv' --exclude='*/__pycache__' . )

say "产物（sha256 前 16 位）"
( cd "$DIST" && for f in *; do printf '%s  %s\n' "$(sha256sum "$f" | cut -c1-16)" "$f"; done )
( cd "$DIST" && sha256sum * | grep -v SHA256SUMS > SHA256SUMS.txt )
say "完成：$DIST"
