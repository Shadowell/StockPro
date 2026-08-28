#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT_DIR/logs"
BACKEND_SESSION="stockpro-backend"
FRONTEND_SESSION="stockpro-frontend"
BACKEND_PORT=4445
FRONTEND_PORT=4444
BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"
FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT}"
MODE="start"

case "${1:-}" in
  "") ;;
  --check) MODE="check" ;;
  -h|--help)
    echo "Usage: ./start.sh [--check]"
    exit 0
    ;;
  *) echo "Unknown argument: $1" >&2; exit 2 ;;
esac

BACKEND_PYTHON="$ROOT_DIR/backend/venv/bin/python"
FRONTEND_VITE="$ROOT_DIR/frontend/node_modules/.bin/vite"

if [ ! -x "$BACKEND_PYTHON" ]; then
  echo "[start] 缺少 backend/venv，请先安装后端依赖。" >&2
  exit 1
fi
if [ ! -x "$FRONTEND_VITE" ]; then
  echo "[start] 缺少 frontend/node_modules，请先运行 npm --prefix frontend install。" >&2
  exit 1
fi

LOCAL_DATABASE_URL="$($ROOT_DIR/scripts/local_database.sh --print-url)"
LOCAL_DATABASE_NAME="$(psql "$LOCAL_DATABASE_URL" -X -Atqc "SELECT current_database()")"

if [ "$MODE" = "check" ]; then
  echo "本地启动检查通过"
  echo "database=$LOCAL_DATABASE_NAME"
  echo "backend_python=$BACKEND_PYTHON"
  echo "frontend_vite=$FRONTEND_VITE"
  exit 0
fi

mkdir -p "$LOG_DIR"

port_listener() {
  lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null | head -n 1 || true
}

for service_port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  listener_pid="$(port_listener "$service_port")"
  if [ -n "$listener_pid" ]; then
    echo "[start] 端口 ${service_port} 已被 PID ${listener_pid} 占用；请先运行 ./stop.sh。" >&2
    exit 1
  fi
done

if command -v tmux >/dev/null 2>&1; then
  for session_name in "$BACKEND_SESSION" "$FRONTEND_SESSION"; do
    if tmux has-session -t "$session_name" >/dev/null 2>&1; then
      echo "[start] tmux 会话 ${session_name} 已存在；请先运行 ./stop.sh。" >&2
      exit 1
    fi
  done
fi

rotate_log() {
  local log_file="$1"
  if [ -s "$log_file" ]; then
    mv "$log_file" "${log_file}.previous"
  fi
  : > "$log_file"
}

rotate_log "$LOG_DIR/backend.log"
rotate_log "$LOG_DIR/frontend.log"

printf -v quoted_database_url '%q' "$LOCAL_DATABASE_URL"
printf -v quoted_root '%q' "$ROOT_DIR"
printf -v quoted_python '%q' "$BACKEND_PYTHON"

cleanup_on_error() {
  exit_code=$?
  if [ "$exit_code" -ne 0 ]; then
    "$ROOT_DIR/stop.sh" >/dev/null 2>&1 || true
  fi
  exit "$exit_code"
}
trap cleanup_on_error EXIT

if command -v tmux >/dev/null 2>&1; then
  tmux new-session -d -s "$BACKEND_SESSION" \
    "cd $quoted_root/backend && exec env DATABASE_URL=$quoted_database_url $quoted_python -m uvicorn app.main:app --host 127.0.0.1 --port $BACKEND_PORT >> $quoted_root/logs/backend.log 2>&1"
  BACKEND_PID="$(tmux display-message -p -t "$BACKEND_SESSION" '#{pane_pid}')"
  echo "$BACKEND_SESSION" > "$LOG_DIR/backend.session"

  tmux new-session -d -s "$FRONTEND_SESSION" \
    "cd $quoted_root/frontend && exec env VITE_DEV_SERVER_PORT=$FRONTEND_PORT VITE_DEV_API_PROXY_TARGET=$BACKEND_URL npm run dev -- --host 127.0.0.1 --port $FRONTEND_PORT >> $quoted_root/logs/frontend.log 2>&1"
  FRONTEND_PID="$(tmux display-message -p -t "$FRONTEND_SESSION" '#{pane_pid}')"
  echo "$FRONTEND_SESSION" > "$LOG_DIR/frontend.session"
else
  (
    cd "$ROOT_DIR/backend"
    nohup env DATABASE_URL="$LOCAL_DATABASE_URL" "$BACKEND_PYTHON" -m uvicorn app.main:app \
      --host 127.0.0.1 --port "$BACKEND_PORT" >> "$LOG_DIR/backend.log" 2>&1 &
    echo $! > "$LOG_DIR/backend.pid"
  )
  BACKEND_PID="$(cat "$LOG_DIR/backend.pid")"
  (
    cd "$ROOT_DIR/frontend"
    nohup env VITE_DEV_SERVER_PORT="$FRONTEND_PORT" VITE_DEV_API_PROXY_TARGET="$BACKEND_URL" \
      npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" >> "$LOG_DIR/frontend.log" 2>&1 &
    echo $! > "$LOG_DIR/frontend.pid"
  )
  FRONTEND_PID="$(cat "$LOG_DIR/frontend.pid")"
fi

echo "$BACKEND_PID" > "$LOG_DIR/backend.pid"
echo "$FRONTEND_PID" > "$LOG_DIR/frontend.pid"

wait_for_url() {
  local label="$1"
  local url="$2"
  local attempts="$3"
  local attempt
  for attempt in $(seq 1 "$attempts"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "[start] ${label} 已就绪: ${url}"
      return 0
    fi
    sleep 1
  done
  echo "[start] ${label} 启动超时，请查看 logs。" >&2
  return 1
}

wait_for_url "后端" "$BACKEND_URL/api/health" 60
wait_for_url "前端" "$FRONTEND_URL/" 30

storage_payload="$(curl -fsS "$BACKEND_URL/api/health/storage")"
STORAGE_PAYLOAD="$storage_payload" EXPECTED_DATABASE="$LOCAL_DATABASE_NAME" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["STORAGE_PAYLOAD"])
database = payload.get("database")
status = payload.get("status")
expected = os.environ["EXPECTED_DATABASE"]
if database != expected or status != "healthy":
    raise SystemExit(f"storage mismatch: status={status!r} database={database!r} expected={expected!r}")
PY

trap - EXIT
echo "[start] 本地服务启动完成"
echo "[start] database=$LOCAL_DATABASE_NAME"
echo "[start] database_url=$("$ROOT_DIR/scripts/local_database.sh" --check | awk -F= '/^url=/{print $2}')"
echo "[start] frontend=$FRONTEND_URL"
echo "[start] backend=$BACKEND_URL"
echo "[start] status=./status.sh"
