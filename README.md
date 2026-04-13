# StockPro AI

> A 股智能投研平台 —— 实时行情、量化选股、AI 研报、策略盯盘、模拟交易一站式解决

![Version](https://img.shields.io/badge/version-2.0-blue)
![Python](https://img.shields.io/badge/python-3.11+-green)
![React](https://img.shields.io/badge/react-18.3-blue)
![Vite](https://img.shields.io/badge/vite-6.3-purple)
![FastAPI](https://img.shields.io/badge/fastapi-0.104+-009688)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 亮点特性

- **全市场实时行情** — 大盘指数、板块轮动、涨跌家数、连板天梯，10-30 秒级数据刷新
- **AI 智能选股** — 接入通义千问大模型，从技术面/基本面/消息面三维度生成深度分析研报
- **策略在线开发** — 内置 Monaco Editor + Python 运行时，在浏览器中编写、测试和保存量化策略
- **策略实时盯盘** — 三槽位并行执行策略，命中信号自动推送，联动 K 线验证
- **因子研究平台** — 因子定义、计算、排名全流程管理，支持自定义量化因子
- **7×24 消息聚合** — 财联社/雪球/东财等多源快讯，按标签分类实时推送
- **复盘工具** — 概念板块轮动热力追踪，颜色编码连续出现的强势板块
- **模拟交易** — 账户概览、限价/市价委托、持仓与成交记录管理
- **跨设备策略同步** — 策略以独立 Python 文件存储于 Git，克隆即用

---

## 功能模块

### 1. 总览看板

首页看板，聚合大盘指数（上证/深证/创业板/科创 50）、涨幅冠军板块、市场情绪指数、成交金额、异动预警等核心指标，搭配短线指标（连板梯队/短线强度）和热门板块实时监控，帮助用户一眼掌握全市场概貌。

![总览看板](docs/screenshots/01-dashboard.png)

### 2. 市场概览

热门概念板块、同花顺热榜、连板天梯三维度板块轮动分析。支持按日期回看历史数据，点击概念可展开查看成分股龙头和分时 K 线。

![市场概览](docs/screenshots/02-market-overview.png)

### 3. 市场情绪

市场情绪量化仪表盘：0-100 情绪指数、涨跌家数与比值、涨停/跌停/炸板统计、连板高度、成交金额、量比、平盘家数等全维度数据，辅以板块涨幅 TOP10 和连板梯队分布图。

![市场情绪](docs/screenshots/03-sentiment.png)

### 4. 消息中心

7×24 实时快讯聚合，支持按异动/并购重组/利好/利空/财联社/雪球/东财等来源标签筛选，可一键同步、刷新或暂停推送。

![消息中心](docs/screenshots/04-news.png)

### 5. 智能选股

输入股票代码或名称，由千问大模型从技术面、基本面、消息面多维度进行深度分析，输出专业投资建议和风险提示。内置常用股票快捷入口。

![智能选股](docs/screenshots/05-ai-screener.png)

### 6. 因子研究

量化因子管理平台，包含因子概览、因子定义、因子排名、数据同步四大功能标签页。支持一键初始化因子、同步实时/技术因子，并展示因子总数、数据记录数、覆盖股票数等统计。

![因子研究](docs/screenshots/06-factor-library.png)

### 7. 交易日历

交割日、结算日、期权、期货等交易事件日历。支持月视图/列表视图切换，可按近期/未来/当月/全部筛选事件。

![交易日历](docs/screenshots/07-calendar.png)

### 8. 策略开发

内置 Python 策略编辑器（Monaco Editor），可在线编写、测试和保存量化选股策略。预置放量突破等策略模板，支持自定义参数，运行后直接查看选股结果。

![策略开发](docs/screenshots/08-strategy-dev.png)

### 9. 策略执行

支持同时挂载三个策略槽位，实时运行量化选股策略并展示筛选结果。左侧为命中股票列表，右侧联动 K 线图表，便于快速验证策略信号。

![策略执行](docs/screenshots/09-strategy-exec.png)

### 10. 复盘中心

每日热门概念板块轮动复盘工具。以颜色标识相同板块的连续轮动，支持按最低涨幅、每日展示数量、历史天数进行筛选，可回填历史数据并导出。

![复盘中心](docs/screenshots/10-market-pulse.png)

### 11. 模拟/实盘交易

模拟与实盘交易下单界面，包含账户概览（总资产、可用资金、持仓市值、盈亏）、买入/卖出下单、限价/市价委托切换，以及持仓、委托、成交三大记录面板。

![模拟/实盘交易](docs/screenshots/11-trading.png)

---

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                   Frontend · React 18.3                      │
│  Vite 6.3 · TypeScript 5.8 · TailwindCSS 3.4 · Zustand 5   │
│  ECharts 6 · Monaco Editor · React Router 7 · Axios          │
│  Electron 40 (桌面端可选)                                     │
└────────────────────────────┬────────────────────────────────┘
                             │ Vite /api proxy → :8000
┌────────────────────────────▼────────────────────────────────┐
│                  Backend · FastAPI 0.104+                     │
│  Python 3.11 · Pydantic 2 · AkShare · DashScope              │
│  APScheduler · Backtrader · SQLAlchemy 2 · httpx              │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ RealtimeSync │  │  Scheduler   │  │ StrategyExecution │  │
│  │   10-30s 轮询 │  │  定时任务调度  │  │   策略并行执行     │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬──────────┘  │
│         └─────────────────┼───────────────────┘              │
│                    ┌──────▼──────┐                            │
│                    │   SQLite    │                            │
│                    │  本地持久化   │                            │
│                    └─────────────┘                            │
└────────────────────────────┬────────────────────────────────┘
                             │
            ┌────────────────┼────────────────┐
            ▼                ▼                ▼
        AkShare          千问大模型        Supabase
       (行情数据)        (AI 分析)       (云端存储·可选)
```

### 后端服务拓扑

| 服务 | 职责 | 默认状态 |
|------|------|---------|
| `RealtimeSyncService` | 大盘指数/全市场行情/板块数据轮询 | 自动启动 |
| `SchedulerService` | APScheduler 定时任务（概念/热榜/情绪等） | 自动启动 |
| `StrategyExecutionService` | 用户策略并行执行与信号推送 | 自动启动 |
| `FactorSyncService` | 量化因子计算与同步 | 按需调用 |
| `MAConvergenceService` | 均线粘合选股算法 | 按需调用 |
| `DataSyncService` | 历史数据回补与增量同步 | 按需调用 |

### 实时数据同步频率

| 数据类型 | 同步间隔 | 来源 |
|---------|---------|------|
| 大盘指数（上证/深证/创业板等） | 10 秒 | AkShare |
| 全市场股票实时行情快照 | 30 秒 | AkShare |
| 热门概念板块涨幅排名 | 2 分钟 | AkShare |
| 概念龙头股明细 | 5 分钟缓存 | AkShare |
| 连板股票梯队分布 | 2 分钟 | AkShare |
| 市场情绪指标 | 2 分钟 | 计算聚合 |

---

## 策略库

项目内置 7 个量化选股策略，存放在 [`strategies/`](strategies/) 目录：

| 策略 | 说明 | 执行间隔 |
|------|------|---------|
| 主板涨幅 TOP10 | 实时获取主板涨幅前 10 股票 | 60s |
| 放量突破策略 | 近 20 天无涨停 + 当日放量 1.75 倍的主板股 | 300s |
| 涨停板监控 | 主板涨停股票，按成交额排序 | 30s |
| 平底放量突破首板 | 放量突破 + 低开高走，适合做首板 | 300s |
| 连板股监控 | 2 板及以上的连板股票 | 60s |
| 热门股票 TOP20 | 东方财富热门股票排行榜 | 120s |
| 平底均线图突破 | MA5/10/20/30 四线粘合后的突破机会 | 600s |

在新设备上克隆项目后，策略会在后端启动时自动导入。也可手动运行：

```bash
python scripts/init_strategies.py          # 仅导入缺失的策略
python scripts/init_strategies.py --force   # 覆盖已有同名策略
```

策略脚本规范和自定义方法详见 [strategies/README.md](strategies/README.md)。

---

## 快速开始

### 环境要求

| 工具 | 最低版本 |
|------|---------|
| Python | 3.11+ |
| Node.js | 18+ |
| npm | 9+ |

### 1. 克隆项目

```bash
git clone https://github.com/Shadowell/StockPro.git
cd StockPro
```

### 2. 启动后端

```bash
cd backend
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 创建环境变量文件（按需填写，仅 QWEN_API_KEY 为必须项）
cat > .env << 'EOF'
QWEN_API_KEY=your-qwen-api-key
QWEN_STOCK_MODEL=qwen-plus
AKSHARE_TIMEOUT=30
BACKEND_CORS_ORIGINS=["http://localhost:9999"]
EOF

uvicorn app.main:app --reload --port 8000
```

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

### 4. 访问应用

打开浏览器访问 **http://localhost:9999**

> 前端开发服务器端口 `9999`（在 `vite.config.ts` 中配置），通过 Vite proxy 将 `/api` 请求转发到后端 `:8000`。

---

## 环境变量

### 后端 (`backend/.env`)

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `QWEN_API_KEY` | 是（AI 功能） | `""` | 通义千问 API Key |
| `QWEN_STOCK_MODEL` | 否 | `qwen-plus` | AI 分析使用的模型 |
| `AKSHARE_TIMEOUT` | 否 | `30` | AkShare 请求超时（秒） |
| `BACKEND_CORS_ORIGINS` | 否 | `["http://localhost:5173"]` | 允许的跨域来源，JSON 数组或逗号分隔 |
| `SUPABASE_URL` | 否 | `""` | Supabase 项目 URL |
| `SUPABASE_KEY` | 否 | `""` | Supabase anon key |
| `SUPABASE_SERVICE_KEY` | 否 | `""` | Supabase service role key |
| `ENABLE_SCHEDULER` | 否 | `true` | 启用 APScheduler 定时任务调度 |
| `ENABLE_REALTIME_SYNC` | 否 | `true` | 启用实时行情数据同步 |
| `ENABLE_STRATEGY_EXECUTION` | 否 | `true` | 启用策略执行引擎 |
| `ENABLE_EXTERNAL_MARKET_FETCH` | 否 | `true` | 启用外部行情数据拉取 |
| `ENFORCE_OPERATION_ALLOWLIST` | 否 | `false` | 启用 API 操作白名单（生产环境安全限制） |
| `DB_MODE` | 否 | `local` | 数据库模式：`local`（SQLite）/ `supabase` |
| `LOCAL_DB_PATH` | 否 | 自动 | 自定义 SQLite 数据库文件路径 |

### 前端 (`frontend/.env`)

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VITE_API_URL` | `/api/v1` | 后端 API 基础路径 |
| `VITE_DEV_API_PROXY_TARGET` | `http://127.0.0.1:8000` | Vite 开发代理目标地址 |

---

## 项目结构

```
StockPro/
├── backend/
│   ├── app/
│   │   ├── main.py                       # FastAPI 入口、中间件、生命周期
│   │   ├── core/config.py                # Pydantic Settings 配置
│   │   ├── api/
│   │   │   ├── api.py                    # 路由注册中心
│   │   │   └── endpoints/                # 16 个 API 路由模块
│   │   │       ├── market.py             #   大盘/板块/连板/情绪
│   │   │       ├── charts.py             #   K 线/分时图
│   │   │       ├── ai.py                 #   AI 分析
│   │   │       ├── strategy.py           #   策略 CRUD & 执行
│   │   │       ├── factors.py            #   因子管理
│   │   │       ├── stock_screener.py     #   均线粘合选股
│   │   │       ├── sectors.py            #   板块数据
│   │   │       ├── stocks.py             #   个股数据
│   │   │       ├── analysis.py           #   数据分析
│   │   │       ├── database.py           #   数据库管理
│   │   │       ├── batch_import.py       #   批量导入
│   │   │       ├── data_hub.py           #   数据中台
│   │   │       ├── data_dev.py           #   数据开发
│   │   │       ├── preset_tasks.py       #   预置任务
│   │   │       ├── admin.py              #   管理接口
│   │   │       └── health.py             #   健康检查
│   │   ├── services/                     # 18 个业务服务
│   │   │   ├── realtime_sync_service.py  #   实时数据同步
│   │   │   ├── scheduler_service.py      #   定时任务调度
│   │   │   ├── strategy_execution_service.py  #  策略执行引擎
│   │   │   ├── market_service.py         #   市场数据
│   │   │   ├── ai_service.py             #   AI 分析
│   │   │   ├── chart_service.py          #   图表数据
│   │   │   ├── factor_sync_service.py    #   因子同步
│   │   │   ├── ma_convergence_service.py #   均线粘合算法
│   │   │   ├── sentiment_service.py      #   市场情绪计算
│   │   │   └── ...                       #   其余 9 个服务
│   │   └── db/local_db.py               # SQLite ORM & 数据访问层
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx                       # 路由定义（11 条路由，懒加载）
│   │   ├── pages/                        # 13 个页面组件
│   │   ├── components/                   # 26 个通用 UI 组件
│   │   ├── stores/useStore.ts            # Zustand 全局状态管理
│   │   ├── api/client.ts                 # Axios 请求封装
│   │   └── types/index.ts               # TypeScript 类型定义
│   ├── tests/e2e/                        # Playwright E2E 测试
│   └── package.json
│
├── strategies/                           # 量化策略脚本库
│   ├── manifest.json                     # 策略清单
│   ├── *.py                              # 7 个策略 Python 脚本
│   └── README.md                         # 策略开发指南
│
├── scripts/                              # 运维脚本
│   ├── init_strategies.py                # 策略导入工具
│   └── backfill_concept_history.py       # 概念板块历史回补
│
└── docs/                                 # 文档
    ├── technical_architecture.md
    ├── api.md
    ├── DATA_ARCHITECTURE.md
    └── screenshots/                      # 模块截图
```

---

## 技术栈

### 前端

| 技术 | 版本 | 用途 |
|------|------|------|
| React | 18.3 | UI 框架 |
| Vite | 6.3 | 构建工具与开发服务器 |
| TypeScript | 5.8 | 类型安全 |
| TailwindCSS | 3.4 | 原子化 CSS |
| Zustand | 5.0 | 轻量状态管理 |
| ECharts | 6.0 | K 线图/柱状图/仪表盘等可视化 |
| Monaco Editor | 0.52 | 浏览器内 Python 代码编辑器 |
| React Router | 7.12 | SPA 路由 |
| Axios | 1.13 | HTTP 客户端 |
| Lucide React | 0.511 | 图标库 |
| Electron | 40.0 | 桌面客户端打包（可选） |
| Playwright | 1.57 | E2E 自动化测试 |

### 后端

| 技术 | 版本 | 用途 |
|------|------|------|
| FastAPI | 0.104+ | Web 框架 |
| Uvicorn | 0.24+ | ASGI 服务器 |
| Pydantic | 2.5+ | 数据验证与配置管理 |
| AkShare | 1.12+ | A 股实时/历史行情数据 |
| DashScope | 1.14+ | 通义千问大模型 SDK |
| APScheduler | 3.10+ | 定时任务调度 |
| Backtrader | 1.9+ | 回测引擎 |
| SQLAlchemy | 2.0+ | ORM 与数据库访问 |
| pandas | 2.1+ | 数据处理 |
| httpx | 0.25+ | 异步 HTTP 客户端 |
| Supabase | 2.0+ | 云端存储（可选） |

---

## API 概览

后端运行后可访问 http://localhost:8000/docs 查看完整的 Swagger 交互式文档。

### 核心接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/market/overview` | 大盘指数概览 |
| `GET` | `/api/v1/market/short-line-indices` | 短线指标（连板/强度） |
| `GET` | `/api/v1/market/hot-concepts` | 热门概念板块排名 |
| `GET` | `/api/v1/market/hot-concept/leaders` | 概念龙头股明细 |
| `GET` | `/api/v1/market/limit-up-ladder` | 连板天梯 |
| `GET` | `/api/v1/market/sentiment` | 市场情绪指标 |
| `GET` | `/api/v1/charts/daily/{symbol}` | 日 K 线数据 |
| `GET` | `/api/v1/charts/realtime/{symbol}` | 分时数据 |
| `POST` | `/api/v1/ai/analyze-stock` | AI 个股深度分析 |
| `GET` | `/api/v1/strategy/list` | 获取策略列表 |
| `POST` | `/api/v1/strategy/save` | 保存策略 |
| `POST` | `/api/v1/strategy/execute` | 执行策略 |
| `GET` | `/api/v1/factors/overview` | 因子概览 |
| `POST` | `/api/v1/factors/sync` | 同步因子数据 |
| `GET` | `/api/v1/stock-screener/ma-convergence` | 均线粘合选股 |
| `GET` | `/api/v1/sectors/hot` | 热门板块 |
| `GET` | `/api/v1/health` | 健康检查 |

---

## 开发指南

### 添加新的 API 端点

1. 在 `backend/app/api/endpoints/` 下新建路由文件
2. 在 `backend/app/api/api.py` 中注册路由
3. 如需业务逻辑，在 `backend/app/services/` 下新建服务

### 添加新的前端页面

1. 在 `frontend/src/pages/` 下新建页面组件
2. 在 `frontend/src/App.tsx` 中添加 `React.lazy()` 导入和 `<Route>` 定义
3. 在 `frontend/src/components/Navigation.tsx` 中添加导航入口

### 添加新的量化策略

1. 在 `strategies/` 下编写 Python 脚本（参考现有策略格式）
2. 在 `strategies/manifest.json` 中添加条目
3. 运行 `python scripts/init_strategies.py` 导入，或等后端重启自动加载

详见 [strategies/README.md](strategies/README.md)。

### 运行 E2E 测试

```bash
cd frontend
npx playwright install    # 首次需安装浏览器
npm run test:e2e          # 运行完整 E2E 测试
npm run test:e2e:report   # 查看测试报告
```

---

## 部署

### Docker（推荐）

```bash
# 后端
cd backend
docker build -t stockpro-backend .
docker run -p 8000:8000 --env-file .env stockpro-backend

# 前端（构建静态文件后用 Nginx 等托管）
cd frontend
npm run build
# dist/ 目录即为构建产物
```

### 手动部署

```bash
# 后端：使用 gunicorn + uvicorn worker 获取更好的并发性能
pip install gunicorn
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000

# 前端：构建后部署到任意静态文件服务器
cd frontend && npm run build
```

### Electron 桌面客户端

项目已集成 Electron 40，可打包为桌面应用：

```bash
cd frontend
npm run electron:build
```

---

## 常见问题

**Q: 启动后页面显示"加载失败"？**
检查后端是否在运行，以及 `frontend/.env` 中的 `VITE_DEV_API_PROXY_TARGET` 是否指向正确的后端地址（默认 `http://127.0.0.1:8000`）。

**Q: 短线指标没有数据？**
确保后端服务已启动且处于 A 股交易时段（9:30-15:00）。非交易时段会展示上一交易日缓存数据。

**Q: 概念龙头股加载慢？**
首次查询从 AkShare 远程拉取并缓存到本地 SQLite，后续查询直接读取缓存（<100ms）。

**Q: AI 分析功能不可用？**
检查 `backend/.env` 中的 `QWEN_API_KEY` 是否正确配置。需要在[阿里云百炼](https://bailian.console.aliyun.com/)申请 API Key。

**Q: 如何切换到 Supabase 云端存储？**
在 `backend/.env` 中设置 `DB_MODE=supabase` 并配置 `SUPABASE_URL` 和 `SUPABASE_KEY`。

**Q: 策略在新设备上看不到？**
克隆项目后重启后端即可自动导入，或手动运行 `python scripts/init_strategies.py`。

---

## 许可证

MIT License

---

## 贡献

欢迎提交 Issue 和 Pull Request！
