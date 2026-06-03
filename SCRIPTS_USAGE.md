# 服务管理脚本使用说明

本项目提供了三个便捷的Shell脚本来管理前后端服务。

## 📜 可用脚本

### 1. restart.sh - 一键重启服务 🔄

**功能**: 优雅地停止当前运行的前后端服务，并重新启动它们。

**使用方法**:
```bash
./restart.sh
```

**执行流程**:
1. 停止后端服务 (端口 4445)
2. 停止前端服务 (端口 4444)
3. 清理僵尸进程
4. 准备日志目录
5. 启动后端服务 (FastAPI + uvicorn)
6. 启动前端服务 (Vite)
7. 检查服务状态
8. 保存进程ID到文件

**输出信息**:
- ✅ 服务状态检查结果
- 📝 服务访问地址
- 📋 日志文件位置
- 🛑 停止服务命令
- 🔄 重启服务命令

---

### 2. stop.sh - 停止所有服务 🛑

**功能**: 优雅地停止所有运行中的前后端服务。

**使用方法**:
```bash
./stop.sh
```

**执行流程**:
1. 从PID文件停止服务
2. 按端口检查并停止服务
3. 清理相关进程
4. 最终状态检查

---

### 3. start_app.sh - 启动服务（旧版）

**功能**: 启动前后端服务并保持前台运行。

**使用方法**:
```bash
./start_app.sh
```

**特点**:
- 前台运行，按 CTRL+C 停止
- 自动打开浏览器
- 适合开发调试

---

## 🚀 快速开始

### 首次启动
```bash
# 赋予执行权限（只需执行一次）
chmod +x restart.sh stop.sh start_app.sh

# 启动服务
./restart.sh
```

### 日常使用
```bash
# 重启服务（推荐）
./restart.sh

# 停止服务
./stop.sh

# 查看日志
tail -f logs/backend.log   # 后端日志
tail -f logs/frontend.log  # 前端日志
```

---

## 📁 文件结构

```
stock_app/
├── restart.sh          # 重启脚本
├── stop.sh            # 停止脚本
├── start_app.sh       # 启动脚本（旧版）
├── logs/              # 日志目录
│   ├── backend.log    # 后端日志
│   ├── frontend.log   # 前端日志
│   ├── backend.pid    # 后端进程ID
│   └── frontend.pid   # 前端进程ID
├── backend/           # 后端代码
└── frontend/          # 前端代码
```

---

## 🌐 服务地址

启动成功后，可以访问以下地址：

- **前端应用**: http://localhost:4444
- **后端API**: http://localhost:4445
- **API文档**: http://localhost:4445/docs
- **ReDoc文档**: http://localhost:4445/redoc

---

## 🐛 常见问题

### 1. 端口被占用

如果遇到端口占用问题，使用 `restart.sh` 会自动清理：

```bash
./restart.sh
```

或手动清理：

```bash
# 查看端口占用
lsof -i :4445
lsof -i :4444

# 手动杀死进程
kill -9 $(lsof -t -i :4445)
kill -9 $(lsof -t -i :4444)
```

### 2. 服务启动失败

查看日志文件：

```bash
# 后端日志
tail -f logs/backend.log

# 前端日志
tail -f logs/frontend.log
```

### 3. 虚拟环境问题

如果后端启动失败，可能需要重新创建虚拟环境：

```bash
cd backend
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..
./restart.sh
```

### 4. 权限问题

如果脚本无法执行：

```bash
chmod +x restart.sh stop.sh start_app.sh
```

---

## 💡 高级用法

### 后台运行服务

脚本已经使用 `nohup` 在后台运行服务，即使关闭终端窗口服务也会继续运行。

### 查看进程状态

```bash
# 查看后端进程
ps -p $(cat logs/backend.pid)

# 查看前端进程
ps -p $(cat logs/frontend.pid)

# 查看所有相关进程
ps aux | grep -E "uvicorn|vite"
```

### 单独重启某个服务

```bash
# 只重启后端
kill $(cat logs/backend.pid)
cd backend && source venv/bin/activate && nohup uvicorn app.main:app --reload --port 4445 > ../logs/backend.log 2>&1 &

# 只重启前端
kill $(cat logs/frontend.pid)
cd frontend && nohup npm run dev > ../logs/frontend.log 2>&1 &
```

---

## 🔔 注意事项

1. **日志文件**: 日志会持续追加，定期清理 `logs/` 目录避免占用过多空间
2. **虚拟环境**: 后端使用虚拟环境，确保依赖隔离
3. **端口固定**: 前端固定使用 4444 端口，后端固定使用 4445 端口
4. **进程管理**: 脚本会保存进程ID到 `logs/*.pid` 文件，便于管理

---

## 📞 技术支持

如遇问题，请检查：
1. Python 版本 (需要 Python 3.8+)
2. Node.js 版本 (需要 Node.js 16+)
3. 端口是否被占用
4. 日志文件中的错误信息

---

## 📊 数据回填脚本

### backfill_concept_history.py - 回填历史概念板块数据

**功能**: 由于 AKShare 的概念板块接口只能获取当天数据，本脚本通过获取每个板块的历史K线来回填历史数据。

**位置**: `scripts/backfill_concept_history.py`

**使用方法**:

```bash
# 进入项目目录
cd /path/to/StockPro

# 激活虚拟环境
source backend/venv/bin/activate

# 回填最近30天数据（默认）
python scripts/backfill_concept_history.py

# 回填最近60天数据
python scripts/backfill_concept_history.py --days 60

# 自定义参数
python scripts/backfill_concept_history.py --days 30 --delay 0.5 --batch 30
```

**参数说明**:
| 参数 | 默认值 | 说明 |
|------|--------|------|
| --days | 30 | 回填最近多少天的数据 |
| --delay | 0.3 | 每次请求的延迟秒数 |
| --batch | 50 | 每批处理多少个板块 |

**注意事项**:
- 首次使用需要运行此脚本回填历史数据
- 回填30天约需 5-10 分钟
- 之后系统会每天15:30自动同步当天数据

**也可以通过网页端操作**:
1. 打开复盘中心页面
2. 点击"回填历史"按钮
3. 等待回填完成（页面会显示进度）

---

**最后更新**: 2026-01-25
