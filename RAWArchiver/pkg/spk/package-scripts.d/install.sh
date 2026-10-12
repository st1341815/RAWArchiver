#!/bin/bash
# RAW 归档 v1.0.0 —— DSM 套件生命周期脚本（DSM6/7 通用，由 synopkg 调用）
set -u
APP="rawarchiver"
WEBROOT_DEFAULT="/volume1/web/rawarchiver"
LOG() { echo "[rawarchiver] $*"; }

synopkg_pre_inst() {
  command -v perl >/dev/null 2>&1 || LOG "警告：系统未检测到 perl，ExifTool 可能无法运行（脚本会自动降级为 exifread/Pillow）"
  return 0
}

synopkg_post_inst() {
  local DEST="$SYNOPKG_PKGDEST"
  [ -n "$DEST" ] || DEST="$WEBROOT_DEFAULT"

  # 1) 目录与权限：套件目录 root:admin 只读；data/logs 归 http 可写
  mkdir -p "$DEST/data/$APP/tasks" "$DEST/etc" "$DEST/logs"
  chown -R root:admin "$DEST" 2>/dev/null || true
  chmod -R u+rwX,go+rX "$DEST" 2>/dev/null || true
  chmod -R 775 "$DEST/data" "$DEST/logs" 2>/dev/null || true
  chown -R http:users "$DEST/data" "$DEST/logs" 2>/dev/null || true
  chmod +x "$DEST/scripts/"*.sh 2>/dev/null || true
  [ -f "$DEST/vendor/exiftool/exiftool" ] && chmod +x "$DEST/vendor/exiftool/exiftool"

  # 2) 站点内容放到 Web Station 根（URL: /app/rawarchiver/）
  local RT="$DEST"
  if [ -d /volume1/web ]; then
    mkdir -p "$WEBROOT_DEFAULT"
    cp -a "$DEST/app/rawarchiver/." "$WEBROOT_DEFAULT/" 2>/dev/null || true
    cp -a "$DEST/scripts" "$DEST/vendor" "$DEST/agent" "$WEBROOT_DEFAULT/" 2>/dev/null || true
    mkdir -p "$WEBROOT_DEFAULT/data/$APP/tasks"
    chown -R http:users "$WEBROOT_DEFAULT/data" 2>/dev/null || true
    chmod -R 775 "$WEBROOT_DEFAULT/data" 2>/dev/null || true
    [ -f "$WEBROOT_DEFAULT/api/index.cgi" ] && chmod 755 "$WEBROOT_DEFAULT/api/index.cgi"
    RT="$WEBROOT_DEFAULT"
  fi
  echo "$RT" > "$DEST/etc/env"

  # 3) Web Server 映射（DSM7 nginx；无 root 时不阻断安装）
  if [ -d /etc/nginx/sites-enabled ]; then
    cat > "/etc/nginx/sites-enabled/$APP.conf" 2>/dev/null <<EOF || LOG "无法写 nginx 配置：请在 Web Station 手动加 /app/rawarchiver -> $RT"
location /app/rawarchiver/ {
    alias $RT/;
    index index.html;
}
EOF
    nginx -s reload >/dev/null 2>&1 || LOG "nginx reload 需 root：装完后重启 Web Station 生效"
  fi

  # 4) Python 依赖（离线 wheels 优先）
  local PYB="${PYTHON_BIN:-/usr/bin/python3}"
  if [ -x "$PYB" ] && [ -d "$DEST/vendor/wheels" ] && [ -n "$(ls -A "$DEST/vendor/wheels" 2>/dev/null)" ]; then
    "$PYB" -m pip install --no-index --find-links "$DEST/vendor/wheels" exifread Pillow >/dev/null 2>&1 \
      || LOG "依赖离线安装未完成：核心脚本将降级（RAW/JPG 用内置解析，视频日期依赖 ExifTool）"
  fi

  # 5) USB 读权限
  command -v synogroup >/dev/null 2>&1 && synogroup --add disk http >/dev/null 2>&1 || true
  if ! sudo -u http ls /volumeUSB1/usbshare >/dev/null 2>&1; then
    LOG "提示：http 用户可能读不到 /volumeUSB1/usbshare；清卡(move)需 root，请改用 root 执行 scripts/pipeline.sh 或 agent"
  fi
  LOG "安装完成。Web: /app/rawarchiver/  核心: $RT/scripts/raw_archiver.py"
  return 0
}

synopkg_start-stop-status() {
  case "$1" in
    start)  return 0;;
    stop)   pkill -f "raw_archiver.py" >/dev/null 2>&1 || true; return 0;;
    status) return 0;;
  esac
  return 0
}

synopkg_pre_uninstall() { return 0; }

synopkg_post_uninstall() {
  rm -f "/etc/nginx/sites-enabled/$APP.conf" 2>/dev/null || true
  nginx -s reload >/dev/null 2>&1 || true
  rm -rf "$WEBROOT_DEFAULT" 2>/dev/null || true
  LOG "已卸载（用户归档数据与 _report_*.json 一律保留）"
  return 0
}
