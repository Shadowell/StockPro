#!/bin/bash
set -euo pipefail

echo "🔧 StockPro 服务器环境初始化..."

APP_DIR="/opt/stockpro"

echo ">>> 安装系统依赖..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-pip python3-venv nginx git curl rsync build-essential postgresql postgresql-client

NODE_VER=$(node --version 2>/dev/null | sed 's/v//' | cut -d. -f1 || echo 0)
if ! command -v node >/dev/null 2>&1 || [ "$NODE_VER" -lt 18 ]; then
    echo ">>> 升级 Node.js..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
fi

echo ">>> 创建应用目录..."
mkdir -p "$APP_DIR"/{backend,frontend/dist,deploy,logs,strategies,scripts}

echo ">>> 安装 systemd 服务..."
cp "$APP_DIR/deploy/stockpro-backend.service" /etc/systemd/system/stockpro-backend.service
systemctl daemon-reload
systemctl enable stockpro-backend

echo ">>> 安装 Nginx 站点..."
cp "$APP_DIR/deploy/stockpro.nginx" /etc/nginx/sites-available/stockpro
ln -sf /etc/nginx/sites-available/stockpro /etc/nginx/sites-enabled/stockpro

echo ">>> 启用 Nginx..."
nginx -t
systemctl enable nginx
systemctl restart nginx

echo ""
echo "✅ 服务器初始化完成！"
echo ""
echo "后续步骤："
echo "  1. 创建 $APP_DIR/backend/.env（参考 backend/.env.example）"
echo "  2. 运行 STOCKPRO_DB_PASSWORD='<strong-password>' bash $APP_DIR/deploy/setup-postgres.sh"
echo "  3. 设置 DB_MODE=postgres 和 DATABASE_URL"
echo "  4. 运行 bash $APP_DIR/deploy/deploy.sh 或推送 main 触发 GitHub Actions"
