#!/bin/bash
set -euo pipefail

APP_DIR="/opt/stockpro"
BACKEND_PORT=4445
PUBLIC_PORT=4444
PUBLIC_DOMAIN="stockpro.notenap.com"

echo "🚀 开始部署 StockPro..."

cd "$APP_DIR"

mkdir -p "$APP_DIR/logs"

if [ ! -f "$APP_DIR/backend/.env" ]; then
    echo "❌ 缺少 $APP_DIR/backend/.env"
    echo "   请先复制 backend/.env.example 并配置 DATABASE_URL、QWEN_API_KEY 等生产变量。"
    exit 1
fi

echo ">>> 停止后端服务..."
systemctl stop stockpro-backend || true
pkill -f "uvicorn app.main:app.*4445" || true

echo ">>> 安装后端依赖..."
cd "$APP_DIR/backend"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate
export PIP_DEFAULT_TIMEOUT="${PIP_DEFAULT_TIMEOUT:-120}"
export PIP_RETRIES="${PIP_RETRIES:-10}"
python -m pip install --upgrade pip setuptools wheel --quiet
python -m pip install -r requirements.txt --quiet

echo ">>> 编译后端源码..."
python -m compileall app >/dev/null

echo ">>> 检查数据库配置并运行迁移..."
DATABASE_URL_VALUE=$(python - <<'PY'
from dotenv import dotenv_values
cfg = dotenv_values("/opt/stockpro/backend/.env")
print(cfg.get("DATABASE_URL", ""))
PY
)

if [ -z "$DATABASE_URL_VALUE" ]; then
    echo "❌ PG-only 部署需要配置 DATABASE_URL"
    exit 1
fi

DATABASE_HOST=$(DATABASE_URL="$DATABASE_URL_VALUE" python - <<'PY'
import os
from urllib.parse import urlparse

print(urlparse(os.environ["DATABASE_URL"]).hostname or "")
PY
)

if [ "$DATABASE_HOST" = "127.0.0.1" ] || [ "$DATABASE_HOST" = "localhost" ] || [ "$DATABASE_HOST" = "::1" ]; then
    echo ">>> 启动本机 PostgreSQL..."
    systemctl enable postgresql >/dev/null 2>&1 || true
    systemctl start postgresql
fi

echo -n ">>> 等待 PostgreSQL 就绪"
for i in $(seq 1 30); do
    if DATABASE_URL="$DATABASE_URL_VALUE" python - <<'PY' >/dev/null 2>&1
import os
import psycopg

with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=2) as connection:
    connection.execute("SELECT 1")
PY
    then
        echo ""
        echo "✅ PostgreSQL 就绪"
        break
    fi

    sleep 1
    echo -n "."
    if [ "$i" -eq 30 ]; then
        echo ""
        echo "❌ PostgreSQL 连接超时"
        if [ "$DATABASE_HOST" = "127.0.0.1" ] || [ "$DATABASE_HOST" = "localhost" ] || [ "$DATABASE_HOST" = "::1" ]; then
            journalctl -u postgresql --no-pager -n 40 || true
        fi
        exit 1
    fi
done

DATABASE_URL="$DATABASE_URL_VALUE" python -m app.db.postgres_migrations

echo ">>> 安装 systemd 服务..."
cp "$APP_DIR/deploy/stockpro-backend.service" /etc/systemd/system/stockpro-backend.service
systemctl daemon-reload
systemctl enable stockpro-backend

echo ">>> 启动后端..."
systemctl start stockpro-backend

echo ">>> 同步 Nginx 配置..."
cp "$APP_DIR/deploy/stockpro.nginx" /etc/nginx/sites-available/stockpro
ln -sf /etc/nginx/sites-available/stockpro /etc/nginx/sites-enabled/stockpro

echo ">>> 重载 Nginx..."
nginx -t
if systemctl is-active --quiet nginx; then
    systemctl reload nginx
else
    systemctl start nginx
fi

echo -n ">>> 等待后端就绪"
for i in $(seq 1 30); do
    sleep 1
    echo -n "."
    if curl -sf "http://127.0.0.1:${BACKEND_PORT}/api/health" > /dev/null 2>&1; then
        echo ""
        echo "✅ 后端就绪"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo ""
        echo "❌ 后端启动超时"
        journalctl -u stockpro-backend --no-pager -n 40
        exit 1
    fi
done

echo -n ">>> 等待前端入口"
for i in $(seq 1 10); do
    sleep 1
    echo -n "."
    if curl -sf "http://127.0.0.1:${PUBLIC_PORT}/" > /dev/null 2>&1; then
        echo ""
        echo "✅ 前端入口就绪"
        break
    fi
    if [ "$i" -eq 10 ]; then
        echo ""
        echo "❌ 前端入口不可达"
        journalctl -u nginx --no-pager -n 20 || true
        exit 1
    fi
done

echo -n ">>> 验证 HTTPS 域名"
for i in $(seq 1 10); do
    sleep 1
    echo -n "."
    if curl -sf --resolve "${PUBLIC_DOMAIN}:443:127.0.0.1" \
        "https://${PUBLIC_DOMAIN}/api/health" > /dev/null 2>&1; then
        echo ""
        echo "✅ HTTPS 域名就绪"
        break
    fi
    if [ "$i" -eq 10 ]; then
        echo ""
        echo "❌ HTTPS 域名不可达"
        journalctl -u nginx --no-pager -n 20 || true
        exit 1
    fi
done

PUBLIC_IP=$(curl -sf --max-time 3 http://ifconfig.me || hostname -I | awk '{print $1}')
echo ""
echo "✅ 部署完成！"
echo "   正式地址: https://${PUBLIC_DOMAIN}"
echo "   兼容地址: http://${PUBLIC_IP}:${PUBLIC_PORT}"
