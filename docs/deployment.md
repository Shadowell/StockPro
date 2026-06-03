# StockPro 云端 B/S 生产部署

StockPro 采用参考 BitPro 的单机生产模式：GitHub Actions 构建 React 前端，rsync 到生产服务器，远端 `deploy.sh` 安装依赖、运行 Postgres migrations、重启 FastAPI systemd 服务，并由 Nginx 对外提供静态前端和 `/api` 反代。

## 生产目标

| 项目 | 值 |
|---|---|
| 服务器 | `root@47.79.36.92` |
| 应用目录 | `/opt/stockpro` |
| 公网入口 | `http://47.79.36.92:4444` |
| 后端监听 | `127.0.0.1:4445` |
| Nginx | `:4444` 静态前端 + `/api/` 反代 |
| 数据库 | PostgreSQL 服务端，新建 `stockpro_prod` |
| systemd | `stockpro-backend` |

## 目录结构

```text
/opt/stockpro/
├── backend/          # FastAPI 源码 + venv
├── frontend/dist/    # Vite 构建产物
├── deploy/           # deploy.sh、setup、nginx、systemd
├── logs/             # 运行日志
├── strategies/       # 预置策略脚本（后续迁移到 PG strategy_versions）
└── scripts/          # 运维脚本
```

## 首次服务器初始化

在服务器上执行：

```bash
ssh root@47.79.36.92
bash /opt/stockpro/deploy/setup-server.sh
```

如果 `/opt/stockpro/deploy` 还没有同步，先从本地同步部署目录：

```bash
rsync -azP deploy/ root@47.79.36.92:/opt/stockpro/deploy/
ssh root@47.79.36.92 "bash /opt/stockpro/deploy/setup-server.sh"
```

## 创建 Postgres 数据库

`setup-server.sh` 会安装 PostgreSQL 服务端和客户端；随后使用脚本创建独立数据库和最小权限用户。密码只通过环境变量传入，不写入仓库：

```bash
ssh root@47.79.36.92
STOCKPRO_DB_PASSWORD='replace-with-strong-password' \
  bash /opt/stockpro/deploy/setup-postgres.sh
```

脚本默认创建：

- 数据库：`stockpro_prod`
- 用户：`stockpro_app`

## 生产环境变量

复制示例文件并填写真实值：

```bash
cp /opt/stockpro/backend/.env.example /opt/stockpro/backend/.env
vim /opt/stockpro/backend/.env
```

关键项：

```bash
DB_MODE=postgres
DATABASE_URL=postgresql://stockpro_app:<password>@127.0.0.1:5432/stockpro_prod
ENABLE_SCHEDULER=false
ENABLE_REALTIME_SYNC=false
ENABLE_STRATEGY_EXECUTION=false
ENABLE_LEGACY_SQLITE_MODULES=false
BACKEND_CORS_ORIGINS=["http://47.79.36.92:4444"]
QWEN_API_KEY=<your-qwen-api-key>
```

不要提交 `.env`、数据库密码、API key 或券商凭证。

## 手动部署

```bash
# 构建前端
cd frontend
VITE_API_URL=/api/v1 npm run build
cd ..

# 同步到服务器
rsync -azP --delete --exclude='venv/' --exclude='.env' --exclude='*.db' --exclude='*.sqlite' \
  backend/ root@47.79.36.92:/opt/stockpro/backend/
rsync -azP --delete frontend/dist/ root@47.79.36.92:/opt/stockpro/frontend/dist/
rsync -azP deploy/ root@47.79.36.92:/opt/stockpro/deploy/
rsync -azP --delete strategies/ root@47.79.36.92:/opt/stockpro/strategies/
rsync -azP --delete scripts/ root@47.79.36.92:/opt/stockpro/scripts/

# 远端部署
ssh root@47.79.36.92 "chmod +x /opt/stockpro/deploy/deploy.sh && bash /opt/stockpro/deploy/deploy.sh"
```

`deploy.sh` 会：

1. 校验 `/opt/stockpro/backend/.env` 存在。
2. 校验 `DB_MODE=postgres` 且 `ENABLE_LEGACY_SQLITE_MODULES=false`。
3. 安装 Python 依赖。
4. 编译后端源码。
5. 运行 `python -m app.db.postgres_migrations`。
6. 安装/启动 `stockpro-backend` systemd 服务。
7. 安装/重载 Nginx 配置。
8. 轮询后端和前端健康检查。

## GitHub Actions 自动部署

工作流：`.github/workflows/deploy.yml`

触发方式：

- push 到 `main`
- 每 5 分钟 schedule 兜底
- `workflow_dispatch`，支持 `force_deploy`

生产 runner：

- self-hosted runner label：`stockpro-production`

GitHub Secrets：

- `SERVER_HOST=47.79.36.92`
- `SERVER_USER=root`
- `SSH_PRIVATE_KEY`

部署成功并通过健康检查后，工作流写入：

```text
/opt/stockpro/deploy/last_deployed_sha
```

同一个 main SHA 已部署时，后续 schedule 会跳过，除非手动 `force_deploy=true`。

## 验证

服务器本机：

```bash
curl http://127.0.0.1:4445/api/v1/health/health
curl http://127.0.0.1:4445/api/v1/health/storage
curl -I http://127.0.0.1:4444/
```

外网：

```bash
curl http://47.79.36.92:4444/api/v1/health/health
curl http://47.79.36.92:4444/api/v1/health/storage
curl -I http://47.79.36.92:4444/
```

运维：

```bash
systemctl status stockpro-backend
journalctl -u stockpro-backend -f
nginx -t && systemctl reload nginx
```

## 当前限制

- 生产入口暂时是 IP + 端口，未启用 HTTPS；接入真实交易前应迁移到域名 + TLS。
- 仓库仍包含 legacy SQLite 服务代码，但 PG-only 生产默认不挂载旧 SQLite API，也不启动旧后台任务；旧模块需要按 sprint 逐步迁移到 PG repositories。
- 实盘交易默认不启用；broker adapter 和 live order submission 必须单独开 contract。
