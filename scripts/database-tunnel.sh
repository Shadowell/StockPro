#!/usr/bin/env bash

set -euo pipefail

cd "$(dirname "$0")/.."

ACTION="${1:-start}"
ENV_FILE="backend/.env"
SOCKET_FILE="logs/database-tunnel.sock"

read_env_value() {
    local key="$1"
    awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE"
}

if [ ! -f "$ENV_FILE" ]; then
    echo "数据库配置不存在: $ENV_FILE" >&2
    exit 1
fi

DATABASE_URL_VALUE="$(read_env_value DATABASE_URL)"
DATABASE_SSH_HOST="$(read_env_value DATABASE_SSH_HOST)"
DATABASE_SSH_REMOTE_HOST="$(read_env_value DATABASE_SSH_REMOTE_HOST)"
DATABASE_SSH_REMOTE_PORT="$(read_env_value DATABASE_SSH_REMOTE_PORT)"

if [ -z "$DATABASE_URL_VALUE" ]; then
    echo "DATABASE_URL 未配置" >&2
    exit 1
fi

if [ -z "$DATABASE_SSH_HOST" ]; then
    if [ "$ACTION" = "start" ] || [ "$ACTION" = "status" ]; then
        echo "未配置 DATABASE_SSH_HOST，按 DATABASE_URL 直接连接远端 PostgreSQL。"
    fi
    exit 0
fi

DATABASE_SSH_REMOTE_HOST="${DATABASE_SSH_REMOTE_HOST:-127.0.0.1}"
DATABASE_SSH_REMOTE_PORT="${DATABASE_SSH_REMOTE_PORT:-5432}"

read -r DATABASE_LOCAL_HOST DATABASE_LOCAL_PORT <<EOF
$(DATABASE_URL="$DATABASE_URL_VALUE" python3 - <<'PY'
import os
from urllib.parse import urlparse

url = urlparse(os.environ["DATABASE_URL"])
print(url.hostname or "", url.port or 5432)
PY
)
EOF

if [ "$DATABASE_LOCAL_HOST" != "127.0.0.1" ] && [ "$DATABASE_LOCAL_HOST" != "localhost" ]; then
    echo "启用 SSH 隧道时，DATABASE_URL 必须连接 127.0.0.1 或 localhost" >&2
    exit 1
fi

mkdir -p logs

tunnel_is_running() {
    [ -S "$SOCKET_FILE" ] && ssh -S "$SOCKET_FILE" -O check "$DATABASE_SSH_HOST" >/dev/null 2>&1
}

case "$ACTION" in
    start)
        if tunnel_is_running; then
            echo "PostgreSQL SSH 隧道已运行 (127.0.0.1:${DATABASE_LOCAL_PORT})"
            exit 0
        fi

        rm -f "$SOCKET_FILE"
        if lsof -nP -iTCP:"$DATABASE_LOCAL_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
            echo "本地端口 ${DATABASE_LOCAL_PORT} 已被占用；请先停止本地 PostgreSQL 或其他监听进程。" >&2
            lsof -nP -iTCP:"$DATABASE_LOCAL_PORT" -sTCP:LISTEN >&2 || true
            exit 1
        fi

        ssh \
            -M -S "$SOCKET_FILE" -fNT \
            -o ExitOnForwardFailure=yes \
            -o ServerAliveInterval=30 \
            -o ServerAliveCountMax=3 \
            -L "127.0.0.1:${DATABASE_LOCAL_PORT}:${DATABASE_SSH_REMOTE_HOST}:${DATABASE_SSH_REMOTE_PORT}" \
            "$DATABASE_SSH_HOST"

        for _ in $(seq 1 20); do
            if lsof -nP -iTCP:"$DATABASE_LOCAL_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
                echo "PostgreSQL SSH 隧道已建立 (127.0.0.1:${DATABASE_LOCAL_PORT} -> ${DATABASE_SSH_HOST}:${DATABASE_SSH_REMOTE_HOST}:${DATABASE_SSH_REMOTE_PORT})"
                exit 0
            fi
            sleep 0.25
        done

        echo "PostgreSQL SSH 隧道未能监听本地端口 ${DATABASE_LOCAL_PORT}" >&2
        exit 1
        ;;
    stop)
        if tunnel_is_running; then
            ssh -S "$SOCKET_FILE" -O exit "$DATABASE_SSH_HOST" >/dev/null
            echo "PostgreSQL SSH 隧道已停止"
        fi
        rm -f "$SOCKET_FILE"
        ;;
    status)
        if tunnel_is_running; then
            echo "PostgreSQL SSH 隧道运行中"
            exit 0
        fi
        echo "PostgreSQL SSH 隧道未运行" >&2
        exit 1
        ;;
    *)
        echo "用法: $0 {start|stop|status}" >&2
        exit 2
        ;;
esac
