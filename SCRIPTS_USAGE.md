# StockPro 脚本使用说明

日常本地开发优先使用以下入口。完整安装与排障见 [本地运行手册](docs/deployment.md)。

## `restart.sh`

清理旧的 StockPro 前后端进程，启动 FastAPI 和 Vite，并验证：

- 前端 `http://localhost:4444`
- 后端 `http://localhost:4445`
- 健康接口 `/api/health`

脚本还会尝试执行 `scripts/database-tunnel.sh start` 建立数据库 SSH 隧道；使用本地隔离库黄金路径时，未配置 `DATABASE_SSH_HOST` 可忽略该步输出。

```bash
./restart.sh
```

脚本会安装缺失依赖，但不会自动运行数据库迁移/bootstrap，不会自动同步全市场数据，也不会部署服务器。

日志：

```bash
tail -f logs/backend.log
tail -f logs/frontend.log
```

## `stop.sh`

停止本地前后端进程或 tmux 会话：

```bash
./stop.sh
```

默认不会删除 PostgreSQL 容器或数据卷。

## `scripts/setup_isolation_db.sh`

一键创建 `./scripts/check.sh` 要求的隔离库 `stockpro_bitpro_rebase_dev`：

```bash
./scripts/setup_isolation_db.sh
export DATABASE_URL="$(./scripts/setup_isolation_db.sh --print-url)"
./scripts/setup_isolation_db.sh --migrate
```

Docker 不可用时对已有 Postgres 使用 `scripts/sql/create_isolation_db.sql` 或
`scripts/provision_isolation_db.py`。说明见 [隔离库](docs/deployment.md#7-隔离库)。

## `scripts/check.sh`

统一验证入口。必须指向隔离库；缺失时脚本会打印 setup 命令：

```bash
export DATABASE_URL="$(./scripts/setup_isolation_db.sh --print-url)"
./scripts/check.sh
```

包含前端类型检查、lint、build、后端测试和 Python 编译。只修改文档时最低要求为：

```bash
git diff --check
```

## `scripts/run_demo.py`

A 股 Paper 演示（CNY 现金账本、T+1、100 股），不再使用加密 SQLite / Kairos / OKX：

```bash
PYTHONPATH=backend python3 scripts/run_demo.py
PYTHONPATH=backend python3 scripts/run_demo.py --list-instances
```

## 数据库 bootstrap

首次安装或新增迁移后显式执行：

```bash
(cd backend && venv/bin/python bootstrap_runtime.py)
```

需要修复中断的 Paper 周期时：

```bash
(cd backend && venv/bin/python bootstrap_runtime.py --recover-paper)
```

两个命令都会写入 `DATABASE_URL` 指向的数据库，执行前必须确认目标。

## 策略初始化

只导入预置策略：

```bash
backend/venv/bin/python scripts/init_strategies.py
backend/venv/bin/python scripts/init_strategies.py --force
```

`--force` 会覆盖同名预置内容。

## 远程边界

不要把 `deploy/` 下的历史脚本作为日常启动入口。当前规则只允许本地启动；SSH、rsync、服务器重启、远程迁移和生产数据变更必须由用户在当前会话中明确授权。
