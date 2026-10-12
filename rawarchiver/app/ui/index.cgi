#!/bin/bash
# RAW 归档 —— fnOS CGI 入口
#
#   /cgi/ThirdParty/rawarchiver/index.cgi/            -> www/index.html
#   /cgi/ThirdParty/rawarchiver/index.cgi/<file>      -> www/<file>（静态资源）
#   /cgi/ThirdParty/rawarchiver/index.cgi/api[...]    -> api/index.cgi（JSON API，调用核心脚本）
#
# 路径一律通过 TRIM_APPDEST 或脚本自身位置推导，不硬编码部署路径。

APP_NAME="rawarchiver"

resolve_target() {
    local self="$0"
    case "$self" in
        /*) ;;
        *) self="$(pwd)/$self" ;;
    esac
    local guess
    guess="$(cd "$(dirname "$self")/.." 2>/dev/null && pwd)"
    if [ -n "$guess" ] && [ -d "$guess/www" ]; then
        printf '%s' "$guess"
        return 0
    fi
    if [ -n "${TRIM_APPDEST:-}" ] && [ -d "${TRIM_APPDEST}" ]; then
        printf '%s' "${TRIM_APPDEST}"
        return 0
    fi
    printf '%s' "/var/apps/${APP_NAME}/target"
}

APP_TARGET="$(resolve_target)"
APP_VAR="${TRIM_PKGVAR:-/var/apps/${APP_NAME}/var}"
WWW="${APP_TARGET}/www"

send_status() {
    echo "Status: $1"
    echo "Content-Type: text/plain; charset=utf-8"
    echo ""
    echo "$2"
    exit 0
}

URI_NO_QUERY="${REQUEST_URI%%\?*}"
REL_PATH="/"
case "$URI_NO_QUERY" in
    *index.cgi*) REL_PATH="${URI_NO_QUERY#*index.cgi}" ;;
esac
[ -z "$REL_PATH" ] && REL_PATH="/"

# ---- API 路由（保持 POST body / CONTENT_* 环境透传给 api/index.cgi）----
case "$REL_PATH" in
    /api|/api/|/api/*|api|api/index.cgi|api/*)
        PY=""
        if [ -f "${APP_VAR}/python_path" ]; then
            PY="$(head -n 1 "${APP_VAR}/python_path" 2>/dev/null | tr -d '[:space:]')"
        fi
        [ -z "$PY" ] && [ -x "${APP_VAR}/venv/bin/python3" ] && PY="${APP_VAR}/venv/bin/python3"
        [ -z "$PY" ] && PY="$(command -v python3 2>/dev/null || command -v python 2>/dev/null)"
        if [ -z "$PY" ]; then
            echo "Content-Type: application/json; charset=utf-8"
            echo ""
            echo '{"ok":false,"error":"运行环境缺少 python3"}'
            exit 0
        fi
        exec "$PY" "${APP_TARGET}/api/index.cgi"
        ;;
esac

# ---- 静态文件 ----
[ "$REL_PATH" = "/" ] && REL_PATH="/index.html"
case "$REL_PATH" in
    /*) ;;
    *) REL_PATH="/${REL_PATH}" ;;
esac

echo "$REL_PATH" | grep -q '\.\.' && send_status "400 Bad Request" "Bad Request"

FILE="${WWW}${REL_PATH}"
[ -f "$FILE" ] || send_status "404 Not Found" "Not Found"

case "$REL_PATH" in
    *.html)       CT="text/html; charset=utf-8" ;;
    *.css)        CT="text/css; charset=utf-8" ;;
    *.js)         CT="application/javascript; charset=utf-8" ;;
    *.json|*.webmanifest) CT="application/json; charset=utf-8" ;;
    *.png)        CT="image/png" ;;
    *.jpg|*.jpeg) CT="image/jpeg" ;;
    *.svg)        CT="image/svg+xml" ;;
    *)            CT="application/octet-stream" ;;
esac
echo "Content-Type: ${CT}"
echo ""
cat "$FILE"
exit 0
