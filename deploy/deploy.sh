#!/bin/bash
set -euo pipefail

APP_DIR="/opt/stockpro"
BACKEND_PORT=4445
PUBLIC_PORT=4444

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
DB_MODE_VALUE=$(python - <<'PY'
from dotenv import dotenv_values
cfg = dotenv_values("/opt/stockpro/backend/.env")
print(cfg.get("DB_MODE", "postgres"))
PY
)

if [ "$DB_MODE_VALUE" != "postgres" ]; then
    echo "❌ 云端 B/S 生产部署已切为 PG-only，请设置 DB_MODE=postgres"
    exit 1
fi

LEGACY_SQLITE_VALUE=$(python - <<'PY'
from dotenv import dotenv_values
cfg = dotenv_values("/opt/stockpro/backend/.env")
print(str(cfg.get("ENABLE_LEGACY_SQLITE_MODULES", "false")).lower())
PY
)

if [ "$LEGACY_SQLITE_VALUE" = "true" ]; then
    echo "❌ 生产环境不允许启用 ENABLE_LEGACY_SQLITE_MODULES=true"
    exit 1
fi

DATABASE_URL_VALUE=$(python - <<'PY'
from dotenv import dotenv_values
cfg = dotenv_values("/opt/stockpro/backend/.env")
print(cfg.get("DATABASE_URL", ""))
PY
)

if [ -z "$DATABASE_URL_VALUE" ]; then
    echo "❌ DB_MODE=postgres 需要配置 DATABASE_URL"
    exit 1
fi

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
    if curl -sf "http://127.0.0.1:${BACKEND_PORT}/api/v1/health/health" > /dev/null 2>&1; then
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

PUBLIC_IP=$(curl -sf --max-time 3 http://ifconfig.me || hostname -I | awk '{print $1}')
echo ""
echo "✅ 部署完成！"
echo "   访问地址: http://${PUBLIC_IP}:${PUBLIC_PORT}"
