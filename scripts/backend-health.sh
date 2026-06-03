#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
PYTHON_BIN="${PYTHON_BIN:-python3}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:4445/api/v1/health/health}"
DO_PING="${1:-}"

if [ ! -d "$BACKEND_DIR" ]; then
  echo "[backend-health] backend directory not found: $BACKEND_DIR"
  exit 1
fi

echo "[backend-health] root: $ROOT_DIR"
echo "[backend-health] backend: $BACKEND_DIR"
echo "[backend-health] python: $PYTHON_BIN"

echo "[backend-health] checking python dependencies..."
"$PYTHON_BIN" - <<'PY'
import importlib
import sys

required = [
    "fastapi",
    "uvicorn",
    "apscheduler",
    "akshare",
    "pandas",
]

missing = []
for name in required:
    try:
        importlib.import_module(name)
    except Exception:
        missing.append(name)

if missing:
    print("[backend-health] missing python packages:", ", ".join(missing))
    sys.exit(1)

print("[backend-health] dependencies OK")
PY

echo "[backend-health] compiling critical backend files..."
(
  cd "$BACKEND_DIR"
  "$PYTHON_BIN" -m py_compile \
    app/main.py \
    app/db/local_db.py \
    app/services/scheduler_service.py \
    app/services/batch_import_service.py \
    app/api/endpoints/data_dev.py \
    app/api/endpoints/batch_import.py \
    app/api/endpoints/stocks.py
)
echo "[backend-health] py_compile OK"

if [ "$DO_PING" = "--ping" ]; then
  echo "[backend-health] pinging health endpoint: $HEALTH_URL"
  if command -v curl >/dev/null 2>&1; then
    curl --silent --show-error --fail "$HEALTH_URL" >/dev/null
    echo "[backend-health] health endpoint OK"
  else
    echo "[backend-health] curl not found, skip ping"
  fi
fi

echo "[backend-health] done"
