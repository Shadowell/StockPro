#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT_DIR/logs"
BACKEND_SESSION="stockpro-backend"
FRONTEND_SESSION="stockpro-frontend"

mkdir -p "$LOG_DIR"

stop_tmux_session() {
  local session_name="$1"
  if command -v tmux >/dev/null 2>&1 && tmux has-session -t "$session_name" >/dev/null 2>&1; then
    tmux kill-session -t "$session_name"
    echo "[stop] tmux 会话已停止: $session_name"
  fi
}

stop_pid_file() {
  local pid_file="$1"
  local label="$2"
  if [ ! -f "$pid_file" ]; then
    return 0
  fi
  local process_id
  process_id="$(tr -cd '0-9' < "$pid_file")"
  if [ -n "$process_id" ] && kill -0 "$process_id" 2>/dev/null; then
    kill "$process_id" 2>/dev/null || true
    echo "[stop] ${label} 已停止: PID ${process_id}"
  fi
  rm -f "$pid_file"
}

stop_matching_listener() {
  local service_port="$1"
  local expected_pattern="$2"
  local listener_pid
  listener_pid="$(lsof -tiTCP:"$service_port" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
  if [ -z "$listener_pid" ]; then
    return 0
  fi
  local command_line
  command_line="$(ps -p "$listener_pid" -o command= 2>/dev/null || true)"
  if [[ "$command_line" != *"$expected_pattern"* ]]; then
    echo "[stop] 端口 ${service_port} 被非 StockPro 进程占用，未结束 PID ${listener_pid}: ${command_line}" >&2
    return 1
  fi
  kill "$listener_pid" 2>/dev/null || true
  echo "[stop] 端口 ${service_port} 的 StockPro 进程已停止: PID ${listener_pid}"
}

stop_tmux_session "$BACKEND_SESSION"
stop_tmux_session "$FRONTEND_SESSION"
rm -f "$LOG_DIR/backend.session" "$LOG_DIR/frontend.session"

stop_pid_file "$LOG_DIR/backend.pid" "后端"
stop_pid_file "$LOG_DIR/frontend.pid" "前端"

stop_matching_listener 4445 "uvicorn app.main:app"
stop_matching_listener 4444 "vite"

for wait_attempt in $(seq 1 20); do
  if ! lsof -tiTCP:4444 -sTCP:LISTEN >/dev/null 2>&1 && ! lsof -tiTCP:4445 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "[stop] 本地服务已停止；数据库与备份未改动。"
    exit 0
  fi
  sleep 0.25
done

echo "[stop] 服务未在超时内退出，请检查端口占用。" >&2
exit 1
