#!/bin/sh
# RAW 归档 —— 完成后钩子（自定义下游动作：通知 / 索引 / 同步）
TID="$1"; OUT="$2"
REPORT="$OUT/_report_$TID.json"
[ -f "$REPORT" ] || { echo "report not found: $REPORT"; exit 1; }

# 1) 通知（填了环境变量才发）
if [ -n "${TG_BOT:-}" ] && [ -n "${TG_CHAT:-}" ]; then
  curl -s "https://api.telegram.org/bot${TG_BOT}/sendMessage" \
    -d chat_id="$TG_CHAT" -d text="RAW 归档完成 $TID" >/dev/null 2>&1 || true
fi

# 2) 下游示例：把报告交给索引程序（自行替换）
# /usr/local/bin/my_indexer --report "$REPORT"

# 3) 下游示例：挑片目录软链
# ln -sfn "$OUT" /volume1/homes/you/photos_latest

echo "[post_done] $TID -> $REPORT"
