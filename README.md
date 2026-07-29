# StockPro

StockPro 是一个面向 A 股研究与策略验证的本地 B/S 量化工作台。它把市场研究、因子、股票池、Python 策略、回测、模拟交易、盯盘、运行监控和每日复盘放在一条可追溯的工作流中。

StockPro 的重点不是“给出一只必涨股票”，而是让每个研究结论都能回答：用了哪一天的数据、来自哪个数据源、绑定了哪个快照和策略版本、经过了哪些验证、最终如何形成信号与模拟成交。

> 当前交付边界：本地运行、研究优先、仅模拟交易。项目没有开放真实券商下单能力，也不会随代码提交自动部署到远程服务器。

[English](README.en.md) · [文档中心](docs/index.md) · [产品规格](docs/spec.md) · [API 指南](docs/api.md)

## StockPro 能做什么

### 市场研究

- 查看主要指数、市场宽度、成交额、涨跌停、炸板、连板梯队与市场情绪。
- 研究概念和行业板块、资金流、热门股票、新闻事件与交易日历。
- 按股票代码或名称进入个股研究，联动日线、分时、盘口、基本面和 AI 分析。
- 明确展示交易日、数据来源、采集时间、新鲜度和缺失原因，避免把过期或缺失数据伪装成实时数据。

### 因子与股票池

- 管理因子定义、代码版本、计算记录、因子值与不可变因子快照。
- 进行单因子、多因子、相关性、覆盖率和有效性分析。
- 内置 100 个参考因子目录，用于研究定义与分类；实际可计算、已发布的因子以页面状态和 PostgreSQL 记录为准。
- 根据规则生成股票池，记录入选原因，并封存为可复现的股票池快照。

### 策略与回测

- 在浏览器中编写和验证普通 Python 策略，保存不可变策略版本。
- 绑定数据、因子、股票池、研究协议和成本模型后提交异步回测任务。
- 查看收益、基准、回撤、风险指标、月度表现、持仓、订单、成交、日志与参数证据。
- 遵循 A 股约束：交易日历、T+1、100 股整数手、涨跌停、停牌、ST/板块范围、手续费与印花税。

### 模拟执行与复盘

- 将验证后的策略版本晋级到隔离的 Paper 模拟实例。
- 审计信号、风控决策、委托、成交、持仓、现金、权益曲线、心跳和运行周期。
- 通过“盯盘”观察业务信号，通过“监控”查看运行与数据健康。
- 记录收盘后市场结论、风险事项和次日计划，形成每日复盘。

### 数据与 AI

- 使用 PostgreSQL 管理证券主数据、交易日历、行情、估值、停复牌、涨跌停、因子、回测和模拟盘证据。
- TuShare 作为稳定研究数据的主要来源；AKShare 作为明确标注的数据补充或整类回退，禁止静默混源。
- 数据中心提供同步任务、数据集、质量结果、覆盖率、Provider 权限与日终调度状态。
- AI 研发用于个股与研究对象分析；未配置通义千问密钥时，页面只提供明确的不可用或本地降级状态，不伪造外部模型结果。
- 提供本地 `stockpro-mcp-v1` Agent 接口，使用哈希 Token、读写作用域、幂等键和审计记录约束访问。

## 12 个一级工作区

| 工作区 | 路由 | 主要用途 |
| --- | --- | --- |
| 首页 | `/` | 市场总览、研究状态与关键任务 |
| 行情 | `/market` | 市场结构、情绪、事件、日历与个股研究 |
| 股票池 | `/pools` | 规则、生成记录、快照与回测衔接 |
| 因子 | `/factors` | 因子目录、计算、分析、相关性与因子值 |
| 策略 | `/strategy` | 策略目录、代码、参数、版本和验证 |
| 回测 | `/backtest` | 异步任务、实验结果和完整证据 |
| 模拟 | `/paper` | Paper 实例、模拟订单、成交、持仓与风控 |
| 盯盘 | `/watch` | 信号与执行证据的人工观察面 |
| 监控 | `/monitor` | 策略、数据、风险与通知健康状态 |
| 复盘 | `/review` | 当日市场结论、风险与次日计划 |
| 数据 | `/data` | 数据集、同步、质量、Provider 和调度 |
| AI 研发 | `/ai-lab` | AI 研究任务、对象分析与证据绑定 |

市场情绪、新闻、日历等旧入口会跳转到对应工作区的二级页面。管理登录入口为 `/admin-login`。

## 研究到模拟执行的完整链路

```text
数据同步与质量检查
        ↓
封存数据快照
        ↓
计算并发布因子快照
        ↓
生成股票池快照
        ↓
创建不可变策略版本
        ↓
异步回测与证据评审
        ↓
Paper 模拟执行
        ↓
盯盘 / 监控 / 每日复盘
```

因子、股票池、回测和 Paper 运行均绑定显式版本或快照。回测运行期间不调用外部行情 Provider，也不会用新数据覆盖已封存的研究证据。

## 技术架构

| 层 | 技术 | 本地地址 |
| --- | --- | --- |
| 前端 | React 18、TypeScript、Vite、Tailwind CSS、ECharts | `http://localhost:4444` |
| 后端 | FastAPI、Pydantic、SQLAlchemy、APScheduler、Backtrader | `http://localhost:4445` |
| 数据库 | PostgreSQL 16 | `127.0.0.1:55432` |
| 数据源 | TuShare 优先，AKShare 显式补充 | 由数据中心管理 |
| AI | 通义千问 / DashScope，可选 | 由 `QWEN_API_KEY` 启用 |
| Agent | 本地 stdio MCP，协议 `stockpro-mcp-v1` | 不提供公网传输 |

前端采用紧凑的金融操作台风格：固定一级菜单、页面内二级标签、统一状态语义、中文优先，并支持切换“红涨绿跌 / 绿涨红跌”。

## 快速开始

### 环境要求

- macOS 或 Linux 开发环境
- Python 3.11+
- Node.js 18+ 与 npm 9+
- Docker Desktop 或可用的 Docker Compose
- 可选：`tmux`，用于让一键启动的前后端服务稳定驻留

### 首次初始化

```bash
git clone https://github.com/Shadowell/StockPro.git
cd StockPro

cp backend/.env.example backend/.env
# 编辑 backend/.env，至少修改管理员密码和 Token 密钥；
# 需要真实数据或 AI 时，再填写 TUSHARE_TOKEN / QWEN_API_KEY。

docker compose up -d postgres

python3 -m venv backend/venv
backend/venv/bin/python -m pip install -r backend/requirements.txt
(cd backend && venv/bin/python bootstrap_runtime.py)

npm --prefix frontend install
./restart.sh
```

打开：

- Web：`http://localhost:4444`
- 后端健康检查：`http://localhost:4445/api/health/health`
- OpenAPI：`http://localhost:4445/docs`

管理员账号和密码取自 `backend/.env` 的 `ADMIN_USERNAME`、`ADMIN_PASSWORD`。不要把真实密钥或 `.env` 提交到 Git。

### 日常运行

```bash
./restart.sh             # 清理旧进程，启动 PG、后端和前端，并执行健康检查
./stop.sh                # 停止本地前后端
tail -f logs/backend.log
tail -f logs/frontend.log
```

`restart.sh` 不会自动执行数据库迁移/bootstrap，也不会连接或部署远程服务器。数据库结构变化后显式运行：

```bash
(cd backend && venv/bin/python bootstrap_runtime.py)
```

更完整的说明见 [本地运行手册](docs/deployment.md)。

## 配置原则

从 `backend/.env.example` 创建本地配置。关键开关：

| 配置 | 作用 | 建议 |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL 连接 | 本地默认端口 `55432` |
| `TUSHARE_TOKEN` | TuShare 数据权限 | 按实际积分和接口权限配置 |
| `QWEN_API_KEY` | 通义千问分析 | 不使用 AI 时可留空 |
| `ENABLE_SCHEDULER` | 日终调度 | 仅在理解任务范围后启用 |
| `ENABLE_REALTIME_SYNC` | 实时轮询 | 默认关闭，避免启动即访问外部源 |
| `ENABLE_STRATEGY_EXECUTION` | 策略定时执行 | 默认关闭，按需显式启用 |
| `ENABLE_EXTERNAL_MARKET_FETCH` | 页面读取时外部取数 | 建议关闭，优先读取已持久化数据 |
| `RUN_*_ON_STARTUP` | 启动期写操作 | 默认关闭，初始化和恢复均显式执行 |

数据同步会产生外部 API 调用与数据库写入。先在数据中心确认数据日期、权限、覆盖范围和预计任务量，再执行全市场同步。

## 验证

项目统一检查入口：

```bash
./scripts/check.sh
```

常用单项检查：

```bash
npm --prefix frontend run check
npm --prefix frontend run lint
npm --prefix frontend run build
(cd backend && venv/bin/python -m pytest)
```

真实后端 E2E 需要本地前端、后端和 PostgreSQL 都可用。测试结果和已知缺口记录在 [开发进度](docs/progress.md)。

## 安全与使用边界

- StockPro 是研究和模拟验证工具，不构成投资建议。
- 当前没有真实券商下单入口；Paper 模拟结果不代表真实可成交结果。
- AI 输出必须结合数据日期、来源和模型可用状态人工复核。
- 不提交 `.env`、数据库、备份、日志、浏览器产物、私钥、API Token 或券商凭证。
- GitHub push 只交付源码，不等于部署；服务器变更必须由用户在当前会话中明确授权。

## 文档

- [文档中心](docs/index.md)：所有当前文档与历史材料的入口
- [产品规格](docs/spec.md)：产品边界、工作流与验收规则
- [用户指南](docs/user_guide.md)：按页面完成研究到模拟盘
- [API 指南](docs/api.md)：鉴权、接口域、写操作和 OpenAPI
- [技术架构](docs/technical_architecture.md)：系统组件与运行边界
- [数据架构](docs/DATA_ARCHITECTURE.md)：快照、质量、来源与调度
- [本地运行手册](docs/deployment.md)：安装、启动、日志与排障
- [策略开发](strategies/README.md)：策略版本和脚本约定
- [开发进度](docs/progress.md)：实现与验证历史
- [Sprint 合同](docs/contracts/)：历史范围、验收标准和决策记录

## License

项目保留原仓库许可证约定。使用市场数据、AI 服务和第三方接口时，还需遵守相应 Provider 的授权、频率和再分发规则。
