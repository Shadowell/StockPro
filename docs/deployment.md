# StockPro 运行与部署手册

本地开发使用 `restart.sh`。配置好的生产环境由 GitHub Actions 从 `main` 构建和部署；真实交易能力不随 Web 部署启用。

生产 Web 正式入口为 `https://stockpro.notenap.com`，
`www.stockpro.notenap.com` 与 HTTP 请求会永久跳转到该地址。服务器仍保留
`http://47.79.36.92:4444` 作为兼容与故障排查入口，不应作为对外链接。

## 1. 本地服务

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| 前端 | `http://localhost:4444` | React + Vite |
| 后端 | `http://localhost:4445` | FastAPI |
| 健康检查 | `http://localhost:4445/api/health/health` | 后端进程状态 |
| 存储检查 | `http://localhost:4445/api/health/storage` | PostgreSQL 状态 |
| OpenAPI | `http://localhost:4445/docs` | 运行时接口文档 |
| PostgreSQL | `127.0.0.1:55432` | 到服务器 PostgreSQL 的 SSH 隧道端口 |

## 2. 环境准备

- Python 3.11+
- Node.js 18+、npm 9+
- 已配置数据库服务器的 SSH 主机别名
- 可选 `tmux`

## 3. 首次安装

在 StockPro 根目录执行：

```bash
cp backend/.env.example backend/.env
```

编辑 `backend/.env`：

- 修改 `ADMIN_PASSWORD` 和 `ADMIN_TOKEN_SECRET`；
- 将 `DATABASE_URL` 指向本机 SSH 隧道端口，并配置 `DATABASE_SSH_HOST`；
- 按需填写 `TUSHARE_TOKEN` 和 `QWEN_API_KEY`；
- 首次运行建议保持实时同步、策略执行和启动期写操作关闭。

然后初始化：

```bash
python3 -m venv backend/venv
backend/venv/bin/python -m pip install -r backend/requirements.txt

(cd backend && venv/bin/python bootstrap_runtime.py)
npm --prefix frontend install
```

`bootstrap_runtime.py` 显式执行迁移、数据目录安装、数据集注册和预置策略初始化。它会写入配置的服务器 PostgreSQL，但不会自动执行外部市场同步。

## 4. 启动、停止和重启

```bash
./restart.sh
./stop.sh
```

`restart.sh` 会：

1. 停止占用 4444/4445 的旧本地进程；
2. 建立到服务器 PostgreSQL 的 SSH 隧道；
3. 确保 Python/Node 依赖已安装；
4. 启动 FastAPI 和 Vite；
5. 轮询后端健康接口和前端首页。

如果安装了 `tmux`，前后端分别运行在 `stockpro-backend` 和 `stockpro-frontend` 会话中；否则使用后台进程。

它不会：

- 自动运行数据库迁移或 bootstrap；
- 自动同步全市场数据；
- 部署代码、rsync 或 scp 文件到远程服务器；
- 自动部署 GitHub 上的新提交。

## 5. 日志与状态

```bash
tail -f logs/backend.log
tail -f logs/frontend.log

lsof -nP -iTCP:4444 -sTCP:LISTEN
lsof -nP -iTCP:4445 -sTCP:LISTEN

curl -fsS http://127.0.0.1:4445/api/health/health
curl -fsS http://127.0.0.1:4445/api/health/storage
curl -I http://127.0.0.1:4444/
```

如果使用 `tmux`：

```bash
tmux attach -t stockpro-backend
tmux attach -t stockpro-frontend
```

按 `Ctrl+B`、再按 `D` 可离开会话而不停止服务。

## 6. 配置开关

| 变量 | 说明 |
| --- | --- |
| `RUN_MIGRATIONS_ON_STARTUP` | 后端启动时执行迁移；常规本地运行保持 `false` |
| `RUN_BOOTSTRAP_ON_STARTUP` | 启动时写入目录/预置数据；保持 `false`，改用显式命令 |
| `RUN_PAPER_RECOVERY_ON_STARTUP` | 启动时恢复 Paper；保持 `false`，按需显式执行 |
| `ENABLE_SCHEDULER` | 启用 PG 调度计划 |
| `ENABLE_REALTIME_SYNC` | 启用外部实时数据轮询 |
| `ENABLE_STRATEGY_EXECUTION` | 启用策略定时执行 |
| `ENABLE_EXTERNAL_MARKET_FETCH` | 页面读取时允许外部取数；建议关闭 |
| `ENABLE_LOCAL_PG_BACKUP` | 启用本地 PostgreSQL 备份任务 |

启动后无写入并不意味着所有模块可用。数据同步、因子计算、回测和 Paper 均需要对应数据与任务状态。

## 7. 数据库变更

代码包含新迁移或首次拉取项目时，显式运行：

```bash
(cd backend && venv/bin/python bootstrap_runtime.py)
```

需要恢复中断的 Paper 运行证据时：

```bash
(cd backend && venv/bin/python bootstrap_runtime.py --recover-paper)
```

此命令会改变服务器开发数据库状态，执行前先确认目标数据库连接。

## 8. 验证

```bash
./scripts/check.sh
```

该入口负责前端类型检查、lint、build、后端测试和 Python 编译。真实后端 E2E 需要服务与 PostgreSQL 正常运行：

```bash
npm --prefix frontend run test:e2e:real
```

## 9. 常见排障

### 4444 或 4445 被占用

优先运行 `./restart.sh`。仍失败时用 `lsof` 确认占用者，不要结束与 StockPro 无关的进程。

### PostgreSQL 无法连接

```bash
./scripts/database-tunnel.sh status
ssh your-db-ssh-host true
curl -fsS http://127.0.0.1:4445/api/health/storage
```

确认 `backend/.env` 的 `DATABASE_URL`、`DATABASE_SSH_HOST` 和远端端口一致。本机端口被旧 PostgreSQL 容器占用时，应先停止该容器，再重建隧道。

### 登录失败

检查 `backend/.env` 的管理员账号、密码和 Token 密钥，重启后端。不要在文档、日志或 Git 中公开真实密码。

### 页面空白或 API 401

查看浏览器控制台和后端日志，确认登录 Token 未过期、Vite 代理目标为 `http://127.0.0.1:4445`。

## 10. GitHub Actions 生产部署

`.github/workflows/deploy.yml` 是生产部署入口：

- 只允许 `main`；`push` 立即触发，定时任务负责补偿 runner 暂时离线或事件遗漏；
- 使用提交 SHA 与服务器 `last_deployed_sha` 比较，同一版本直接跳过；
- 前端通过干净的 `npm ci` 构建，所有本地 npm 包必须包含在 StockPro 仓库内；
- 后端、前端产物、部署脚本、策略和运维脚本按白名单同步，保留 `.env`、venv、日志和数据库文件；
- 服务器依次安装后端依赖；当 `DATABASE_URL` 指向本机时，显式启动并等待 PostgreSQL 可连接；随后执行迁移、重启 FastAPI、重载 Nginx 并检查前后端健康；
- 只有全部步骤成功后才写入部署 SHA，失败不会把半完成版本标成已部署。

生产密钥只存放在 GitHub Secrets 或服务器环境文件中。不要在文档、workflow 日志或仓库中写入主机凭据、SSH 私钥、数据库密码或 Provider Token。

### 手动重跑

优先在 GitHub Actions 中使用 `workflow_dispatch`。只有需要重新部署同一个 SHA 时才启用 `force_deploy`；普通失败应先修复根因，不要用重复运行掩盖错误。

### 生产验证

部署完成至少确认：

1. Actions run 结论为成功；
2. `Record deployed SHA` 已执行；
3. 后端健康与存储检查通过；
4. `https://stockpro.notenap.com/` 返回 200；
5. `https://www.stockpro.notenap.com/` 永久跳转到主域名；
6. HTTPS 证书覆盖主域名与 `www`，且 Certbot timer 正常；
7. 服务日志没有启动循环、迁移失败或持续 5xx。

生产 443 端口由服务器级 Nginx SNI 分流器共享。StockPro 的两个主机名必须
指向 `127.0.0.1:8451`，站点配置再从该端口终止 TLS。证书使用 Certbot webroot
方式签发，挑战目录为 `/var/www/letsencrypt`。修改共享 SNI 表前必须备份并运行
`nginx -t`，不能覆盖其他产品已有的域名映射。

真实券商、资金、订单和临时生产数据修改仍需要独立授权和安全审查。
