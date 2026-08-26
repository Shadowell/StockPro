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
# seed_strategies.py 用 parents[1]/strategies 解析 script_file；放到 scripts/ 子目录，
# 使远端 PROJECT_ROOT=$REMOTE_TMP、SCRIPTS_DIR=$REMOTE_TMP/strategies 与上传布局一致。
ssh -o BatchMode=yes "$BITPRO_SEED_SSH" "mkdir -p '$REMOTE_TMP/scripts'"
scp -q "$ROOT/scripts/seed_strategies.py" "$BITPRO_SEED_SSH:$REMOTE_TMP/scripts/seed_strategies.py"

# seed 条目里的 script_file 相对仓库 strategies/ 目录解析；引用了源码文件的条目
# 必须把对应文件一并上传，否则远端 load_script_content 会回退到占位脚本。
SCRIPTS_DIR="$ROOT/strategies"
if [[ -d "$SCRIPTS_DIR" ]]; then
  referenced=$(python3 - "$ROOT/data/seed/strategies.json" <<'PY'
import json, sys
entries = json.load(open(sys.argv[1]))
for entry in entries:
    script_file = entry.get("script_file")
    if isinstance(script_file, str) and script_file.strip():
        print(script_file.strip())
PY
)
  if [[ -n "${referenced//\n/}" ]]; then
    ssh -o BatchMode=yes "$BITPRO_SEED_SSH" "mkdir -p '$REMOTE_TMP/strategies'"
    while IFS= read -r rel; do
      [[ -z "$rel" ]] && continue
      src_path="$SCRIPTS_DIR/$rel"
      if [[ -f "$src_path" ]]; then
        scp -q "$src_path" "$BITPRO_SEED_SSH:$REMOTE_TMP/strategies/$(basename "$rel")"
        echo "[INFO] 已上传策略源码: $rel"
      else
        echo "[WARN] 缺少策略源码文件: $src_path（该条目将回退占位脚本）" >&2
      fi
    done <<< "$referenced"
  fi
fi

echo "[INFO] 远程: $BITPRO_SEED_SSH"
echo "[INFO] DB_PATH: $REMOTE_DB"
ssh -o BatchMode=yes "$BITPRO_SEED_SSH" \
  "BITPRO_SEED_FILE='$REMOTE_TMP/strategies.json' DB_PATH='$REMOTE_DB' python3 '$REMOTE_TMP/scripts/seed_strategies.py' $FORCE_FLAG $RESET_FLAG"

echo "[DONE] 线上种子导入完成（未触碰本机 DB_PATH）"
