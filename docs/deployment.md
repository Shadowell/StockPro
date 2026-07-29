# StockPro 本地运行手册

> 当前授权只允许本地运行。本文不提供远程服务器部署步骤；GitHub commit/push 只是源码交付，不会自动部署。

## 1. 本地服务

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| 前端 | `http://localhost:4444` | React + Vite |
| 后端 | `http://localhost:4445` | FastAPI |
| 健康检查 | `http://localhost:4445/api/health/health` | 后端进程状态 |
| 存储检查 | `http://localhost:4445/api/health/storage` | PostgreSQL 状态 |
| OpenAPI | `http://localhost:4445/docs` | 运行时接口文档 |
| PostgreSQL | `127.0.0.1:55432` | Docker 映射端口 |

## 2. 环境准备

- Python 3.11+
- Node.js 18+、npm 9+
- Docker Desktop / Docker Compose
- 可选 `tmux`

## 3. 首次安装

在 StockPro 根目录执行：

```bash
cp backend/.env.example backend/.env
```

编辑 `backend/.env`：

- 修改 `ADMIN_PASSWORD` 和 `ADMIN_TOKEN_SECRET`；
- 保持 `DATABASE_URL` 指向本地 PG；
- 按需填写 `TUSHARE_TOKEN` 和 `QWEN_API_KEY`；
- 首次运行建议保持实时同步、策略执行和启动期写操作关闭。

然后初始化：

```bash
docker compose up -d postgres

python3 -m venv backend/venv
backend/venv/bin/python -m pip install -r backend/requirements.txt

(cd backend && venv/bin/python bootstrap_runtime.py)
npm --prefix frontend install
```

`bootstrap_runtime.py` 显式执行迁移、数据目录安装、数据集注册和预置策略初始化。它会写入本地 PostgreSQL，但不会自动执行外部市场同步。

## 4. 启动、停止和重启

```bash
./restart.sh
./stop.sh
```

`restart.sh` 会：

1. 停止占用 4444/4445 的旧本地进程；
2. 启动 Docker PostgreSQL；
3. 确保 Python/Node 依赖已安装；
4. 启动 FastAPI 和 Vite；
5. 轮询后端健康接口和前端首页。

如果安装了 `tmux`，前后端分别运行在 `stockpro-backend` 和 `stockpro-frontend` 会话中；否则使用后台进程。

它不会：

- 自动运行数据库迁移或 bootstrap；
- 自动同步全市场数据；
- SSH、rsync、scp 或连接远程服务器；
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

此命令会改变本地数据库状态，执行前先确认目标数据库连接。

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
docker compose ps
docker compose logs postgres
curl -fsS http://127.0.0.1:4445/api/health/storage
```

确认 `backend/.env` 的 `DATABASE_URL` 与 `docker-compose.yml` 一致。

### 登录失败

检查 `backend/.env` 的管理员账号、密码和 Token 密钥，重启后端。不要在文档、日志或 Git 中公开真实密码。

### 页面空白或 API 401

查看浏览器控制台和后端日志，确认登录 Token 未过期、Vite 代理目标为 `http://127.0.0.1:4445`。

## 10. 远程部署边界

仓库可能保留历史部署脚本或工作流作为未来基础，但当前项目规则禁止自动部署、远程重启和服务器数据变更。需要部署时，用户必须在当前会话中明确指定目标、范围和验证要求，并单独审查密钥、数据库迁移、回滚和真实交易隔离。
