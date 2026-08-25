# StockPro 技术架构

> 更新日期：2026-08-24
> 目标环境：本地 B/S
> 核心约束：PostgreSQL only、读取不触发写操作、仅 Paper 模拟交易

## 1. 系统概览

```text
浏览器
  │
  │ http://localhost:4444
  ▼
React + Vite + TypeScript
  │
  │ /api 代理
  ▼
FastAPI :4445
  ├── 鉴权与权限
  ├── 市场/数据/因子/股票池
  ├── 策略运行时与回测任务
  ├── Paper/Watch/Monitor/Review
  ├── AI 与 MCP Agent
  └── APScheduler
          │
          ▼
PostgreSQL :55432
  ▲
  ├── TuShare（主要研究数据源）
  ├── AKShare（显式补充/整类回退）
  └── DashScope（可选 AI）
```

前端不直连数据库和外部数据源。研究、回测和 Paper 页面读取 FastAPI；后端负责鉴权、状态判断、Provider 适配、任务编排和持久化。

## 2. 前端

### 技术

- React 18 + TypeScript
- Vite 6
- React Router 7
- Tailwind CSS
- Zustand
- ECharts
- Monaco Editor
- Lucide 图标
- 项目共享主题与基础组件

### 页面结构

`frontend/src/App.tsx` 注册 13 个一级工作区、详情路由和历史兼容跳转。`MainLayout` 提供：

- 固定 64px 一级侧栏；
- 管理员/访客身份状态；
- 设置、退出、色彩方案；
- 页面内容容器与移动端导航；
- 全局任务进度和 Toast。

各页面拥有自己的标题、二级工作区标签、过滤器、表格/图表和详情界面。导航、业务状态和筛选控件使用不同视觉层级。

### API 调用

- 开发环境 `/api` 由 Vite 代理到 `http://127.0.0.1:4445`。
- Bearer Token 由统一客户端注入。
- 页面必须处理加载、空、部分缺失、过期、错误和权限不足。
- 前端不得通过 GET 页面加载隐式触发同步或其他写操作。

## 3. 后端

### 技术

- FastAPI + Pydantic 2
- SQLAlchemy / psycopg
- APScheduler
- pandas
- Backtrader 与 StockPro 自有策略运行时
- TuShare、AKShare、DashScope SDK
- Python MCP SDK

### 分层

```text
backend/app/
├── api/          # 路由、鉴权依赖、请求/响应边界
├── core/         # 配置、Token、安全和公共规则
├── db/           # PostgreSQL 连接、迁移、repository
├── models/       # API 与领域数据模型
├── services/     # 数据、研究、任务、回测、Paper、AI
└── main.py       # FastAPI 生命周期和路由装配
```

路由只负责 HTTP 边界和权限，业务规则在 services，持久化集中在 PG repository/migration。新功能不应在 service 中散落未经封装的 SQL，也不应增加 SQLite 或 JSON 文件数据库。

### API 域

所有接口使用单一 `/api` 前缀。当前注册的域（对照 `backend/app/api/api.py`）：

```text
health capabilities auth
market pools factors strategies
backtest paper
signals watch monitor
review data ai
```

已移除的 `workflow / stocks / charts / data-hub / data-dev / database / acceptance`
域不再存在。完整接口由 FastAPI OpenAPI 生成，域级说明见 [API 指南](api.md)。

## 4. 鉴权与权限

### Web Token

- 管理员账号来自环境变量。
- 登录后签发带有效期的 Bearer Token。
- 访客码由管理员创建，包含有效期、每日回测数、并发数和回测天数限制。
- 受保护业务路由统一要求已认证身份。

### Agent Token

- MCP Token 在 PG 中只保存 SHA-256 哈希。
- 明文仅在创建响应中出现一次。
- `R` 和 `W` 作用域限制工具集合。
- 写操作要求幂等键并保存调用审计。
- 远程 MCP 和真实券商能力不可用。

### Secrets

数据库密码、管理员密码、Token 密钥、Provider Token 和 AI Key 只存在于本地环境配置，不进入 Git、日志、API 示例或前端构建。

## 5. PostgreSQL

PostgreSQL 是唯一平台数据库，承载：

- 身份、访客码、Agent Token 与审计；
- 证券主数据、交易日历和 Provider 数据；
- 数据分区、质量报告、快照和调度状态；
- 因子定义、版本、运行、指标、值和快照；
- 股票池、成员和快照；
- 策略身份、不可变版本、参数和验证；
- 回测任务、实验、指标、时间序列、订单、成交和日志；
- Paper 实例、周期、信号、风控、订单、成交、持仓、现金与权益；
- Watch 告警、Monitor 状态和 Review 记录。

数据库结构由显式迁移维护。后端普通启动默认不运行迁移和 bootstrap。

## 6. 数据与研究证据

```text
Provider 响应
  → 标准化
  → PG 未封存分区
  → 质量门
  → 不可变数据快照
  → 因子快照 / 股票池快照
  → 策略版本
  → 回测证据
  → Paper 证据
```

每层保存上游标识、时间语义、来源和哈希。封存后不原地改写；Provider 更正产生新分区和新快照。

回测、因子和 Paper Replay 只读取持久化快照，不在运行中访问外部 Provider。这既保证可复现，也避免回测结果受当前网络和最新数据影响。

## 7. 策略运行时

平台定义 `StockPro Strategy API v1`：

- 用户实现 `initialize(context)`、`handle_data(context, data)` 和可选生命周期函数；
- 平台注入数据、模拟时钟、订单和记录 API；
- 代码版本、参数、依赖和资源限制固定；
- 禁止直接网络、数据库、文件写入和券商访问；
- 回测与 Paper Replay 共用同一事件和撮合语义；
- 每个事件保存模拟时间、数据可用时间、顺序和确定性证据。

回测采用任务模式。任务提交与执行分离，状态和日志持久化，支持取消和显式重试。

## 8. Paper 运行时

Paper 实例绑定固定策略版本和研究输入。一次周期的典型链路：

```text
读取封存行情
  → 策略事件
  → 信号/订单意图
  → A 股可交易性与风控
  → 模拟委托
  → 模拟成交
  → 持仓/现金/权益
  → 周期与心跳证据
```

Watch 读取业务证据，Monitor 汇总运行健康。两者都是观察面，不直接修改真实账户。Paper adapter 与任何未来 broker adapter 必须保持隔离。

## 9. 调度与后台任务

APScheduler 用于日终数据同步、备份和其他受控任务。计划、下次运行、运行记录和结果保存到 PG。

安全要求：

- 调度由环境开关和 PG 配置共同控制；
- 任务需要幂等和并发锁；
- 交易日判断先于 Provider 请求；
- 部分成功不能发布完整数据快照；
- 启动不自动补跑未知范围的大任务；
- 页面读取不能注册或执行任务。

## 10. 本地运行与可观测性

- `restart.sh` 启动 PostgreSQL、FastAPI 和 Vite，并做健康检查。
- 日志写入 `logs/backend.log` 与 `logs/frontend.log`。
- `/api/health` 检查进程，`/api/health/storage` 检查 PG。
- `./scripts/check.sh` 是统一静态检查和测试入口；运行前需将 `DATABASE_URL`
  指向隔离库（见[本地运行手册](deployment.md#7-隔离库)）。

浏览器验收需同时关注：

- 控制台错误；
- 失败的 API 请求；
- 加载/空/过期/权限状态；
- 桌面和窄屏溢出；
- 用户界面是否泄露内部 ID、哈希或工程标签。

## 11. 扩展边界

### 可以在当前架构内扩展

- 新数据集与 Provider adapter；
- 新因子、研究协议和诊断；
- 新策略版本与回测指标；
- 新 Paper 风控规则；
- 只读 Agent 工具。

### 需要单独合同和安全审查

- 真实券商连接、订单、撤单、资金与持仓；
- 公网 MCP 或公开 API；
- 多租户、注册、计费和团队权限；
- 自动远程部署和生产数据库迁移；
- 商业数据再分发。

## 12. 架构原则

1. PostgreSQL 是事实存储，页面状态不是事实来源。
2. 读取无副作用，写操作显式、可审计、可恢复。
3. 缺失保持缺失，过期保持过期，不用 0 或 mock 掩盖。
4. 每个研究结果固定版本、快照、时间和来源。
5. A 股规则位于共享执行边界，不在各页面重复实现。
6. UI 与工作流规则集中维护，不在业务页面内建立互相冲突的实现。
7. 本地运行与远程部署严格分离。
