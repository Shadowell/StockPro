#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ISOLATION_DB="stockpro_bitpro_rebase_dev"
BACKUP_DIR="${STOCKPRO_LOCAL_BACKUP_DIR:-$ROOT_DIR/data/local-backups}"
BACKUP_TIMESTAMP="${STOCKPRO_BACKUP_TIMESTAMP:-$(date '+%Y%m%d-%H%M%S')}"
DATABASE_URL="$($SCRIPT_DIR/local_database.sh --print-url)"
BACKUP_BASENAME="${ISOLATION_DB}-${BACKUP_TIMESTAMP}"
PARTIAL_DUMP="$BACKUP_DIR/${BACKUP_BASENAME}.dump.partial"
FINAL_DUMP="$BACKUP_DIR/${BACKUP_BASENAME}.dump"
METADATA_FILE="$BACKUP_DIR/${BACKUP_BASENAME}.json"

for required_command in pg_dump pg_restore psql; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    echo "[backup] 缺少命令: $required_command" >&2
    exit 1
  fi
done

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

cleanup_partial() {
  rm -f "$PARTIAL_DUMP"
}
trap cleanup_partial EXIT

pg_dump \
  --format=custom \
  --compress=6 \
  --no-owner \
  --no-privileges \
  --file "$PARTIAL_DUMP" \
  "$DATABASE_URL"

pg_restore --list "$PARTIAL_DUMP" >/dev/null
mv "$PARTIAL_DUMP" "$FINAL_DUMP"

if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$FINAL_DUMP" > "${FINAL_DUMP}.sha256"
else
  sha256sum "$FINAL_DUMP" > "${FINAL_DUMP}.sha256"
fi

facts="$(psql "$DATABASE_URL" -X -Atqc \
  "SELECT COUNT(*),COUNT(DISTINCT symbol),COALESCE(MIN(date)::text,''),COALESCE(MAX(date)::text,'') FROM stock_history")"
IFS='|' read -r history_rows symbols first_trade_date last_trade_date <<< "$facts"

cat > "$METADATA_FILE" <<EOF
{
  "database": "$ISOLATION_DB",
  "dump_file": "$(basename "$FINAL_DUMP")",
  "first_trade_date": "$first_trade_date",
  "last_trade_date": "$last_trade_date",
  "stock_history_rows": $history_rows,
  "symbols": $symbols
}
EOF

ln -sfn "$(basename "$FINAL_DUMP")" "$BACKUP_DIR/latest.dump"
trap - EXIT

echo "[backup] 本地数据备份完成"
echo "[backup] database=$ISOLATION_DB"
echo "[backup] stock_history_rows=$history_rows"
echo "[backup] symbols=$symbols"
echo "[backup] dump=$FINAL_DUMP"
echo "[backup] metadata=$METADATA_FILE"
