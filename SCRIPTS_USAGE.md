# StockPro 脚本使用说明

日常本地开发优先使用以下入口。完整安装与排障见 [本地运行手册](docs/deployment.md)。

## `restart.sh`

清理旧的 StockPro 前后端进程，启动 Docker PostgreSQL、FastAPI 和 Vite，并验证：

- 前端 `http://localhost:4444`
- 后端 `http://localhost:4445`
- 健康接口 `/api/health/health`

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

## `scripts/check.sh`

统一验证入口：

```bash
./scripts/check.sh
```

包含前端类型检查、lint、build、后端测试和 Python 编译。只修改文档时最低要求为：

```bash
git diff --check
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
