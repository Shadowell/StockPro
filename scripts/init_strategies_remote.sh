#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${STOCKPRO_SEED_SSH:?请设置环境变量 STOCKPRO_SEED_SSH（如 root@your-server）}"

REMOTE_DB="${STOCKPRO_REMOTE_DB:-/opt/stockpro/data/stockpro.db}"
FORCE_FLAG=""
if [[ "${STOCKPRO_SEED_FORCE:-}" == "1" || "${STOCKPRO_SEED_FORCE:-}" == "yes" ]]; then
  FORCE_FLAG="--force"
fi

echo "[INFO] 远程: $STOCKPRO_SEED_SSH"
echo "[INFO] DB: $REMOTE_DB"

ssh -o BatchMode=yes "$STOCKPRO_SEED_SSH" "mkdir -p /opt/stockpro/{data,strategies,scripts}"

rsync -azP "$ROOT/strategies/" "$STOCKPRO_SEED_SSH:/opt/stockpro/strategies/"
rsync -azP "$ROOT/scripts/init_strategies.py" "$STOCKPRO_SEED_SSH:/opt/stockpro/scripts/init_strategies.py"

ssh -o BatchMode=yes "$STOCKPRO_SEED_SSH" \
  "cd /opt/stockpro && LOCAL_DB_PATH='$REMOTE_DB' /opt/stockpro/backend/venv/bin/python scripts/init_strategies.py $FORCE_FLAG"

echo "[DONE] 策略导入完成"
