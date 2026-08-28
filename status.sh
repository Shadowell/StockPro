#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_MODE="text"
case "${1:-}" in
  "") ;;
  --json) OUTPUT_MODE="json" ;;
  -h|--help) echo "Usage: ./status.sh [--json]"; exit 0 ;;
  *) echo "Unknown argument: $1" >&2; exit 2 ;;
esac

listener_pid() {
  lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null | head -n 1 || true
}

backend_pid="$(listener_pid 4445)"
frontend_pid="$(listener_pid 4444)"
database_url=""
database_status="unreachable"
database_name="stockpro_bitpro_rebase_dev"
history_rows=0
symbols=0
first_trade_date=""
last_trade_date=""

if database_url="$($ROOT_DIR/scripts/local_database.sh --print-url 2>/dev/null)"; then
  database_status="reachable"
  facts="$(psql "$database_url" -X -Atqc \
    "SELECT COUNT(*),COUNT(DISTINCT symbol),COALESCE(MIN(date)::text,''),COALESCE(MAX(date)::text,'') FROM stock_history" 2>/dev/null || true)"
  if [ -n "$facts" ]; then
    IFS='|' read -r history_rows symbols first_trade_date last_trade_date <<< "$facts"
  fi
fi

backend_health="down"
storage_health="down"
if [ -n "$backend_pid" ]; then
  if curl -fsS --max-time 5 http://127.0.0.1:4445/api/health >/dev/null 2>&1; then
    backend_health="healthy"
  fi
  if curl -fsS --max-time 5 http://127.0.0.1:4445/api/health/storage >/dev/null 2>&1; then
    storage_health="healthy"
  fi
fi

latest_backup=""
if [ -L "$ROOT_DIR/data/local-backups/latest.dump" ]; then
  latest_backup="$(cd "$ROOT_DIR/data/local-backups" && pwd)/$(readlink "$ROOT_DIR/data/local-backups/latest.dump")"
fi

if [ "$OUTPUT_MODE" = "json" ]; then
  BACKEND_PID_VALUE="$backend_pid" FRONTEND_PID_VALUE="$frontend_pid" \
  BACKEND_HEALTH_VALUE="$backend_health" STORAGE_HEALTH_VALUE="$storage_health" \
  DATABASE_STATUS_VALUE="$database_status" DATABASE_NAME_VALUE="$database_name" \
  HISTORY_ROWS_VALUE="$history_rows" SYMBOLS_VALUE="$symbols" \
  FIRST_DATE_VALUE="$first_trade_date" LAST_DATE_VALUE="$last_trade_date" \
  LATEST_BACKUP_VALUE="$latest_backup" python3 - <<'PY'
import json
import os

print(json.dumps({
    "frontend": {"running": bool(os.environ["FRONTEND_PID_VALUE"]), "pid": int(os.environ["FRONTEND_PID_VALUE"] or 0)},
    "backend": {"running": bool(os.environ["BACKEND_PID_VALUE"]), "pid": int(os.environ["BACKEND_PID_VALUE"] or 0), "health": os.environ["BACKEND_HEALTH_VALUE"]},
    "storage_health": os.environ["STORAGE_HEALTH_VALUE"],
    "database": {"name": os.environ["DATABASE_NAME_VALUE"], "status": os.environ["DATABASE_STATUS_VALUE"]},
    "data": {
        "stock_history_rows": int(os.environ["HISTORY_ROWS_VALUE"] or 0),
        "symbols": int(os.environ["SYMBOLS_VALUE"] or 0),
        "first_trade_date": os.environ["FIRST_DATE_VALUE"] or None,
        "last_trade_date": os.environ["LAST_DATE_VALUE"] or None,
    },
    "latest_backup": os.environ["LATEST_BACKUP_VALUE"] or None,
}, ensure_ascii=False))
PY
  exit 0
fi

echo "StockPro 本地状态"
if [ -n "$frontend_pid" ]; then
  echo "  前端: running PID $frontend_pid  http://localhost:4444"
else
  echo "  前端: stopped  http://localhost:4444"
fi
if [ -n "$backend_pid" ]; then
  echo "  后端: $backend_health PID $backend_pid  http://localhost:4445"
else
  echo "  后端: stopped  http://localhost:4445"
fi
echo "  存储接口: $storage_health"
echo "  数据库: $database_name ($database_status)"
echo "  日线: $history_rows 条 / $symbols 个标的 / ${first_trade_date:--} ~ ${last_trade_date:--}"
echo "  最新备份: ${latest_backup:--}"
