#!/usr/bin/env bash
# 将种子策略写入「线上」SQLite（在远程主机上执行 seed_strategies.py），默认不写本地库。
#
# 必填：
#   BITPRO_SEED_SSH   例如 root@your-server（勿把真实地址提交进仓库）
#
# 可选：
#   BITPRO_REMOTE_DB        默认 /opt/bitpro/data/crypto_data.db
#   BITPRO_SEED_FORCE       设为 1 时传 --force（覆盖同名种子行 + 更新 db_name_aliases 指向的行）
#   BITPRO_SEED_RESET       设为 1 或 yes 时传 --reset（先清空 strategies 链上表再导入）
#
# 用法：
#   BITPRO_SEED_SSH=root@x.x.x.x ./scripts/seed_strategies_remote.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${BITPRO_SEED_SSH:?请设置环境变量 BITPRO_SEED_SSH（如 root@your-server）}"

REMOTE_DB="${BITPRO_REMOTE_DB:-/opt/bitpro/data/crypto_data.db}"
[[ -z "$REMOTE_DB" ]] && REMOTE_DB="/opt/bitpro/data/crypto_data.db"
FORCE_FLAG=""
if [[ "${BITPRO_SEED_FORCE:-}" == "1" || "${BITPRO_SEED_FORCE:-}" == "yes" ]]; then
  FORCE_FLAG="--force"
fi

RESET_FLAG=""
if [[ "${BITPRO_SEED_RESET:-}" == "1" || "${BITPRO_SEED_RESET:-}" == "yes" ]]; then
  RESET_FLAG="--reset"
fi

REMOTE_TMP=$(ssh -o BatchMode=yes "$BITPRO_SEED_SSH" "mktemp -d")

cleanup() {
  if [[ -n "${REMOTE_TMP:-}" ]]; then
    ssh -o BatchMode=yes "$BITPRO_SEED_SSH" "rm -rf '$REMOTE_TMP'" || true
  fi
}
trap cleanup EXIT

scp -q "$ROOT/data/seed/strategies.json" "$BITPRO_SEED_SSH:$REMOTE_TMP/strategies.json"
scp -q "$ROOT/scripts/seed_strategies.py" "$BITPRO_SEED_SSH:$REMOTE_TMP/seed_strategies.py"

echo "[INFO] 远程: $BITPRO_SEED_SSH"
echo "[INFO] DB_PATH: $REMOTE_DB"
ssh -o BatchMode=yes "$BITPRO_SEED_SSH" \
  "BITPRO_SEED_FILE='$REMOTE_TMP/strategies.json' DB_PATH='$REMOTE_DB' python3 '$REMOTE_TMP/seed_strategies.py' $FORCE_FLAG $RESET_FLAG"

echo "[DONE] 线上种子导入完成（未触碰本机 DB_PATH）"
