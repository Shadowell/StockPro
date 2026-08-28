# BitPro-first A股整仓重建设计合同

- 状态：2026-08-26 再次重置；用户否决页面映射式复刻，当前以 BitPro 原代码整仓直接移植
- 批准日期：2026-08-22
- StockPro 基线：`99adaaae1b1a7b87b2ce22e7475aa3f26d5a5440`
- BitPro 固定来源：`2e4b90c3f83672cb9c3fc2e31b772f6c52efacb1`（2026-08-26 当前 `main`；相对上一基线仅新增策略分析文档，应用树一致）
- 目标分支：`codex/bitpro-direct-port`
- 目标 worktree：`/Users/jie.feng/Dev/Github/Private/StockPro-bitpro-a-share`
- 上一轮生产应用合并 SHA：`4c7fe5194cae7abf6c07a8be005bbfb573b032d8`（仅作历史回滚证据）
- 上一轮生产部署 SHA：`381ec5429114a52af71aae7948834a3f6538f366`（不代表当前复刻完成）
- 上一轮成功部署：GitHub Actions run `32647137727`

## 1. 目标

在不修改当前 StockPro `main`、生产部署和 PostgreSQL/Paper 历史的前提下，
以 BitPro 固定提交的完整应用代码为新底座，把 StockPro 重建为传统金融量化平台。
新系统直接继承 BitPro 的页面结构、组件、导航、交互密度、任务审计、页面设计文档、
浏览器测试和真实截图验收标准，再把数字资产领域替换为 A 股领域。

产品主线固定为：

```text
策略 → 回测 → 模拟
```

StockPro 当前启用 A股、ETF 和指数；为中国期货、美国股票和美国期货预留领域接口，
但未完成真实数据、回测、Paper 和通道合同前不显示期货入口。

## 2. 已批准的核心决策

1. 采用 BitPro-first 整仓重建，不继续在旧 StockPro 页面上做近似改造。
2. 采用安全的 B2 路线：BitPro 底座导入后，在启动服务前先隔离数字资产执行能力。
3. PostgreSQL 保持唯一运行事实源；不把 StockPro 数据迁入 BitPro SQLite。
4. 现有 Paper 权益、累计盈亏、订单、成交、持仓、曲线、事件和运行起点不得归零。
5. 公共和新开发 API 只使用唯一的当前 `/api/*` 合同。
6. 不提供带版本号的 API 路径、旧入口、兼容 Router 或长期双合同。
7. 历史记录中的旧合同版本字段只作为只读审计元数据保留，不形成旧 API。
8. BitPro 继续定位数字资产；StockPro 承载传统金融，并预留期货领域。
9. 普通代码切片按仓库 GitHub Delivery Rule 自动交付；涉及生产数据迁移、Paper 重置或真实交易能力时必须停在安全门禁。
10. 行情页分钟 K 线可在本地分钟缓存空、不可用或 stale 时只读拉取 AKShare 分时数据作为显式
    fallback，实际来源可以是东财 `stock_zh_a_hist_min_em` 或新浪 `stock_zh_a_minute`；该路径不写库、
    不触发同步、不伪造盘口或逐笔成交，并必须在 API meta 与页面证据条标明来源和状态。
11. 行情页证券列表必须展示后端返回的全量股票，不再截断为 50 个；当 `instrument_definitions`
    为空时，`GET /api/v2/market/symbols` 可只读拉取 AKShare `stock_zh_a_spot_em` 沪深京 A 股
    列表作为展示兜底，东财不可用时可退到 AKShare `stock_info_a_code_name` 代码简称列表，
    但不得写库或替代管理员同步任务。
12. 行情资产类型必须隔离状态：股票切到 ETF/指数时清空旧标的和行情；指数只读 PostgreSQL
    指数缓存或 sealed `benchmark_bars`，ETF 缺定义时保持空态。交易时段默认 1m，盘后默认 1D；
    空盘口不计算 0 价差。
13. 数据中心 `/sync/assets` 覆盖全部活动 A 股并返回逐标的水位；顶部汇总与逐标的求和一致，
    页面用分页/虚拟化访问全量，统一维护模式不暴露逐标的危险删除。
14. 资金流分钟 OHLCV 使用 AKShare 分时主源、60 秒服务缓存和 1 分钟页面刷新；失败/backoff
    保留最后成功快照并标 stale。分钟数据不可生成 tick/L2 大单、主动方向或 CVD。

## 3. 仓库、分支和导入边界

BitPro `App.tsx`、`MainLayout.tsx`、全部页面、组件、API、Service 和测试直接位于活动代码树，
不再以 `_quarantine` 副本或 Owner 页映射代替原实现。每个数字资产模块必须在原文件或原交互结构上
换成 A 股字段、数据源、风控与执行合同；真实下单在独立授权前不得注册。

### 3.1 隔离方式

- 从当前 StockPro `main` 创建 `codex/bitpro-a-share-rebase`。
- 使用独立 worktree，避免污染当前 StockPro 工作区和生产分支。
- 新分支的普通推送不得触发 StockPro 生产部署。
- 当前 StockPro `main` 在整个重建期间继续作为生产与回滚事实源。

### 3.2 BitPro 导入内容

从固定提交导入：

- `frontend/`
- `backend/`
- `packages/`
- `scripts/`
- `tests/`
- 页面设计、产品、架构、QA 与截图合同
- 策略、回测、Paper、信号、监控、复盘、数据和 AI 研发模块

不导入：

- BitPro 当前未提交的 `AGENTS.md`、`CLAUDE.md` 和工具缓存
- `.env`、密钥、Cookie、生产 SQLite、交易所账户配置
- 日志、缓存、媒体、任务产物和生产部署记录
- 任何真实 OKX/Binance 私有账户状态

StockPro 的仓库治理规则和 MIT 许可证继续生效。BitPro README 虽标注 Apache-2.0，
固定提交中没有实际许可证文件，因此不得把徽章说明冒充许可证正文。

### 3.3 导入历史

第一个迁移提交只记录 BitPro 应用底座来源，后续提交依次完成安全封锁、
PostgreSQL 接入和 A 股适配。最终 A 股产品可以删除不再需要的币圈运行模块，
但 Git 历史必须能够追溯其来源和替换过程。

## 4. 第一启动前的安全封锁

Wave 0 已完成并进入逐域恢复：后端启动入口已注册 BitPro 原页面所需的 `/api/v2/*`
A 股适配合同，但仍不启动数字资产交易所、SQLite、真实下单、调度器或 WebSocket。
策略域已恢复管理员显式写入：新增策略先通过 `stockpro.v1` AST 安全验证，编辑生成
`strategy_versions` 不可变新版本，删除操作改为归档并保留验证记录；普通页面读取仍不隐式写入。
静态门禁对私有交易所、SQLite、带版本号 API、实盘路由和加密后台任务五类可达面
全部计数为 0。BitPro 遗留模块保留为不可达适配来源，不能从当前入口导入或注册。

在任何前端、后端或 worker 启动前完成：

- 不注册数字资产实盘页面和真实下单路由。
- 禁用 OKX/Binance 私有 API、账户恢复和实盘订阅。
- 不加载 BitPro 数字资产策略 seed。
- 不恢复 BitPro 策略实例、任务或交易记录。
- 不使用 BitPro SQLite 作为运行数据库或失败回退。
- 不启动数字资产 K 线、资金费率、清算、链上和跨所后台任务。
- 未适配模块只能显示明确不可用状态，不能展示币圈数据或 mock 数据。
- 默认执行范围仅为 A 股 Paper。

任一数字资产私有调用在测试或运行期出现都视为阻断缺陷。

## 5. 产品页面和导航

### 5.1 导航

```text
总览： 首页
研究： 行情 / 股票池 / 因子
主线： 策略 / 回测 / 模拟

视觉合同：全站指标卡、KPI 卡和小型数据方块必须使用统一圆角表面，不保留直角拼接指标矩阵。
运行： 盯盘 / 信号 / 监控 / 复盘
能力： 数据 / AI研发
预留： 期货（默认隐藏）
```

不再压缩为七个一级入口。主线在视觉和顺序上保持突出，运行证据页面不得绕过主线门控。

### 5.2 页面映射

| BitPro 页面 | 新 StockPro 页面 | A股替换内容 |
| --- | --- | --- |
| 首页 | `/` | 指数、宽度、涨跌停、板块、自选、策略与 Paper 摘要 |
| 行情 | `/market` | 股票/ETF/指数搜索、K线、盘口、指标和详情 |
| 策略 | `/strategy` | 当前策略合同、因子、股票池、不可变版本和 AI 研发 |
| 回测 | `/backtest` | A股撮合、参数矩阵、Walk-forward 和 Paper 晋级门控 |
| 模拟盘 | `/paper` | BitPro InstanceDashboard 结构与现有 PostgreSQL Paper 账本 |
| 盯盘 | `/watch` | 股票、策略、价格、指标、异动规则与 K线联动 |
| 信号中心 | `/signals` | 信号审计、确认、告警与通知投递 |
| 监控 | `/monitor` | 组合 KPI、策略健康、任务、告警与通知 |
| 复盘 | `/review` | A股交易日级市场、策略、Paper 和风险复盘 |
| 数据 | `/data` | TuShare/AKShare、快照、质量、同步和扩展交换 |
| 因子库 | `/factorlab` | 注册定义、不可变版本、物化值、封存快照和研究 Trial ledger |
| AI研发 | `/ai-lab` | 策略研发、优化和门控后的候选保存 |
| 套利中心 | `/strategy`（旧 `/arbitrage` 跳转） | A 股策略家族与价差研究，不保留跨所/资金费率语义 |
| 基本面 | `/onchain` | sealed 估值、公告时点财务、股东与分红证据 |
| 订单流 | `/market`（旧 `/orderflow` 跳转） | A 股盘口、成交额、交易日与来源证据 |
| ARC Console | `/ai-lab`（旧 `/arc` 跳转） | A 股 AI 研究任务、证据与失败状态 |
| 交易/Paper | `/paper`（旧 `/trading`、`/live` 跳转） | A 股模拟盘现金账本；不注册真实下单 |
| 数字资产实盘 | 不注册 | 无真实交易入口 |

FactorLab 统计必须实时来自 PostgreSQL，不维护“默认 26/100 个”等第二口径。研究任务只接受
有效 `factor_versions` 和包含这些版本的 sealed `factor_snapshots`；coverage、fold、20bps/40bps
失败写入 rejected Trial，`orders_created=0`、`paper_mutated=false`。

### 5.3 页面继承标准

- 直接继承 BitPro `MainLayout`、页面头部、指标卡、工具栏、筛选器、表格、
  详情页、弹窗和响应式规则。
- 优先复用 BitPro 对应组件，不再以截图为参考重新创作相似页面。
- 只替换领域字段、数据源和交易语义，不随意降低信息密度。
- 所有页面覆盖 Loading、Empty、Partial、Stale、Error 和权限不足。
- 真实数据为空时展示诚实空态，不为视觉效果创建业务记录。
- 固定 BitPro 前端树的每个源文件必须由 `frontend-parity.json` 证明为字节级一致或带固定
  源哈希的 A 股适配；未分类、源漂移、目标缺失或空适配契约均阻断完成审计。

### 5.4 首页市场驾驶舱（GitHub #60/#61/#62/#63/#64/#65）

首页使用唯一只读 `GET /api/v2/market/dashboard` 合同，`overview` 保持原基础层子合同，禁止在页面内为同一市场事实维护第二套
榜单或聚合逻辑。服务端优先从 PostgreSQL 的实时/盘后股票事实读取同一有效股票池；指数优先使用真实
指数缓存，缓存为空时读取封存 `benchmark_bars`，不能复用任意股票点位。响应必须同时表达指数、宽度、
八档涨跌分布、MA5/20/60 与 60 日新高低、CNY 成交额、百分比换手率、倍数口径量比以及涨幅/跌幅/
成交额/活跃换手四榜，并为每个模块携带交易日、快照、可用时间、知识截止时间、状态和缺失输入。

半年历史同步必须把真实沪深300历史、`stk_limit` 涨跌停价格、涨跌停/炸板/连板梯队、六阶段、
行业与概念成员快照、5/10/20/60 日 RPS 和最新日 3/10/30 日异动 metrics 与股票历史原子提交，并绑定
sealed market evidence snapshot。行业主源为 `stock_basic.industry`；概念主源为 TuShare `ths_index/ths_member`，
AKShare 东方财富接口只作为明确回退。当前成员用于历史回看时必须显示 membership bias。

Dashboard 返回各模块交易日/快照一致性警告和固定的 `provider_calls=0`、`writes_performed=false`、
`paper_mutated=false`；5 秒单航班只缓存只读 PostgreSQL 结果。页面 GET 不临时重算、调用 Provider 或写库。

趋势模块在确认历史不足 60 个交易日时保持 `blocked`/`null`；停牌、无价、负数或明显坏数据不进入宽度
分母和排行榜。页面读取不得触发 Provider、同步、重算、Paper 或任何业务写入；桌面和 390px 验收必须
检查证据状态、榜单点击行情跳转、console errors 与横向溢出。

## 6. 统一当前 API 合同

### 6.1 唯一入口

- 全系统只提供 `/api/*`。
- BitPro 导入代码中的带版本号路径全部迁移到 `/api/*`。
- 不保留旧路径别名、兼容跳转、兼容 Router 或第二套 Service。
- 前端、Agent、MCP、测试和文档必须在同一切片迁移到当前合同。
- 同一业务能力只有一个 endpoint、一个 Application Service 和一个 PostgreSQL 事实源。

### 6.2 历史元数据

历史表中已有的合同版本字段可以继续存在，用于解释旧策略、回测和 Paper 证据。
它们只读，不对应旧 API，也不能阻止当前页面读取历史记录。新写入全部使用当前合同；
公共页面和文档不再用版本号命名产品 API。

## 7. PostgreSQL 数据架构

### 7.1 数据流

```text
BitPro 页面与组件
    ↓
/api/* 当前唯一合同
    ↓
A股 Application Service
    ↓
PostgreSQL Repository
    ↓
StockPro 当前表和历史记录
```

BitPro 页面使用其成熟 ViewModel；适配层从现有 PostgreSQL 对象生成 ViewModel，
不复制业务记录。

### 7.2 核心对象映射

| BitPro 读模型 | PostgreSQL 事实 |
| --- | --- |
| 策略实例 | `paper_instances` + `portfolios` |
| 策略成交 | `trades` |
| 权益采样 | `paper_equity_snapshots` |
| 回测结果 | `backtest_runs` + metrics/orders/trades |
| 信号 | `strategy_signals` |
| 告警与投递 | `alerts` + `notification_deliveries` |
| 因子 | factor definitions/versions/runs/snapshots |
| 股票池 | stock pool rules/generations/snapshots |
| 复盘 | `daily_reviews` + items/metrics |

不创建同义 SQLite 表，也不把 PostgreSQL 错误降级为 SQLite。

### 7.3 隔离开发库

- 从当前 PostgreSQL 创建一致性备份。
- 恢复到独立数据库 `stockpro_bitpro_rebase_dev`。
- 重建 worktree 只连接隔离库。
- 所有迁移先在副本执行并生成前后对账。
- 生产切换前再用最新生产快照完成一次完整演练。

### 7.4 迁移规则

数据库改动只允许：

- 新表
- 新列
- 新索引
- 新视图
- 可回填映射表

禁止破坏式改名、删除表、覆盖字段、清空记录或为了适配整数 ID 重建 UUID。

## 8. Paper 连续性门禁

当前设计基线为：

- 37 个迁移
- 67 个策略版本
- 79 个回测
- 15 个 Paper 实例
- 61 个 Paper 订单
- 47 个 Paper 成交
- 23 个持仓
- 428 个权益快照
- 681 个运行事件
- 1 份复盘

每个涉及 Paper 的提交都必须前后核对：Paper 实例 ID、策略版本 ID、初始资金、
当前权益、累计盈亏、订单、成交、持仓、可用数量、权益曲线首尾时间、事件数量、
运行起点和生命周期状态。

模拟盘、盯盘与监控对同一实例必须消费同一 PostgreSQL snapshot ViewModel；`size/amount`、
equity/cash、mark/notional、trade timestamp/fee/IDs 在三个页面保持可对账。sealed 日线空时只允许
回退持仓 mark，并必须显示来源和时间；该只读适配不得修改 Paper 表。

禁止清空、重置、归档后只显示新实例、用初始资金覆盖缺失权益、
或为截图创建演示 Paper。无法证明连续性时不得进入下一阶段。

## 9. A股领域与期货预留

### 9.1 当前 A股语义

- 明确交易所身份与 A股交易日历、集合竞价、午休和盘后
- T+1 可卖数量、100 股整数手及清仓零股
- 涨跌停、停牌、ST、退市和上市阶段
- 未复权成交价与复权研究数据边界
- 佣金、过户费、印花税、滑点、流动性和容量
- 日线信号最早下一可交易日成交

### 9.2 期货预留合同

统一 instrument contract 预留：`asset_class`、`market`、`exchange`、`currency`、
`tick_size`、`lot_size`、`contract_multiplier`、`margin_rate`、`expiry_date`、
`last_trade_date`、`settlement_type`、`session_calendar` 和 `shortable`。

预留适配器：`cn_futures_ctp`、`us_futures_broker`。股票现有记录默认映射股票类别，
期货字段保持 `null`，不填假值。期货页面、同步、回测和执行在独立合同完成前全部隐藏。

## 10. 错误与安全边界

- 页面读取不得自动迁移、同步、恢复或执行策略。
- Provider 不可用时显示来源、时间和错误原因。
- 行情和指标缺失保持不可用，不转成业务零。
- Paper 读取失败不能回退为初始资金。
- 模型失败不能生成 mock 分析。
- 已删除的旧 API 调用直接失败，并由测试定位消费者。
- 数字资产私有调用、实盘订阅或交易所账户读取必须 fail-closed。
- 用户代码不能直接访问 Provider、数据库、文件写入、网络或券商。
- 新系统默认且唯一可执行环境是 A股 Paper。
- 设置中心所有配置域必须返回真实 2xx/4xx 状态，不允许 502/404 被前端标成“已配置”；AI Provider
  由服务端环境管理，未开放的浏览器写操作显式禁用。
- MCP Agent 主认证名为 `X-StockPro-MCP-Token` / `STOCKPRO_MCP_API_TOKEN`，旧 BitPro 名只作迁移
  兼容；Token 只存 PostgreSQL SHA-256，飞书 Webhook 只存加密值，所有管理路由要求 admin。

## 11. 实施顺序

1. 安全基线、备份、隔离数据库、分支和 worktree。
2. BitPro 固定应用底座导入提交。
3. 数字资产执行封锁与唯一 `/api/*` 骨架。
4. PostgreSQL repository、认证与公共读模型。
5. 登录和 MainLayout。
6. 首页与行情。
7. 策略、因子和股票池。
8. 回测与任务系统。
9. Paper 与连续性对账。
10. 盯盘、信号、监控和复盘。
11. 数据中心与 AI 研发。
12. 期货隐藏预留。
13. 全页面、权限、性能、截图和恢复验收。
14. 最新生产快照演练与切换前确认。
15. 合并 `main`、Actions 部署和生产验收。

当前第 8 步已恢复 A 股日线撮合、费用和指标内核；异步任务持久化、取消/恢复、
策略隔离 worker、sealed 输入解析、结果原子写入与 BitPro 回测 UI 单任务入口已经接通。
策略读合同将版本、验证、回测和 Paper 按 `strategy_version_id` 关联；详情不得从名称或模板猜测逻辑，
样例策略明确展示未实现退出/调仓等缺口，并使用关联 Paper 实例 ID 打开实例控制台。
当前写合同为 `/api/v2/backtest/run_job`、`/job/{id}`、`/jobs`、`/job/{id}/cancel|resume`
和 `/configuration`；历史结果在全部子证据写完后才切换为 success+sealed，不提供物理删除。
回测读合同分开返回 `fill_count`、`closed_trade_count` 和 `order_count`；列表与详情使用同一事实口径，
单日或零闭合样本 fail-closed 为 `metric_status=insufficient_sample`，不得输出正向研究判决。
管理员批量回测、运行中 Paper 去重、sealed 配置绑定、原子批量持久化，以及访客单任务
PostgreSQL 区间/并发/每日配额压力，以及 18 个唯一策略的批量真实任务、失败修复、跨重启恢复
验收现已完成；该步骤仅剩生产部署证据，因此在最终部署观察前仍不能视为关闭。

第 9 步的 Paper 生命周期已接通 `paper_eligible` 回测门禁与 `/api/v2/live/instances|candidates`
以及 `/live/start|pause|resume|stop` 兼容路径。所有状态切换必须保留现有 Paper 账本与可见历史，
`clear_metrics` 永久拒绝；自动周期推进、盯盘持仓联动和跨重启运行验收仍未完成。
Paper 账户持仓响应保留 `positions.name` 与统一证券代码，盯盘持仓卡不得只显示代码。
复盘评分只使用满足窗口交易日、权益点、闭合交易和数据水位四项门槛的回测；样本不足策略单独分组，
不得以 0 收益、0 回撤或默认 50 分进入好坏榜。
盯盘持仓联动已恢复真实只读证据；剩余阻断收敛为显式周期推进、周期失败恢复与长期运行验收。
显式周期推进、失败原子回滚、多日连续推进、服务重启续跑和双请求并发互斥现已在隔离库完成；
该步骤剩余门禁为最终生产部署观察，不得用本地/隔离库证据代替生产运行证据。

第 13 步的本地全页面、权限、双视口、错误边界、依赖、bundle、116 项活动后端测试、25 项
Playwright Mock E2E、真实 16 路由只读矩阵和 Paper 连续性门禁均已完成。第 14–15 步仍需基于
当前提交生成切换前 manifest，经最终确认后合并 `main`，再由 GitHub Actions 部署并核对生产 SHA、
39 项迁移、服务健康与真实页面；本地通过不能替代这些证据。

当前切换前 completion audit 已基于当前 HEAD 的 32 张真实双视口截图通过且无 blocker；允许进入
第 14–15 步的功能分支推送、`main` 合并与 Actions 部署，但 Goal 仍须等生产 SHA、迁移、健康、
Paper 连续性和生产页面复验后才能关闭。

生产认证启用前的安全门禁已补齐：管理员和访客登录共享按真实来源 IP 计算的 15 分钟 10 次
失败预算，额度耗尽返回 429，成功登录清空来源预算；Nginx `X-Real-IP` 优先于可伪造的
`X-Forwarded-For` 链。会话 Cookie 固定 HttpOnly、Secure（生产配置）与 SameSite=Strict。
应用入口必须注册统一 `AppError` handler，认证拒绝按合同返回 401/403/429，禁止泄漏为 500。
生产明文管理员密码只允许保存到本机 macOS 钥匙串，不进入仓库、服务器 `.env` 或日志；服务器
只保存 Argon2 哈希与独立 HMAC 签名密钥。
BitPro 版式直接继承不等于保留数字资产品牌：活动 HTML 标题、登录门禁、Logo 字母和用户可见
产品文案统一机械替换为 StockPro / A股；不改变原布局、组件节奏或交互结构。
最终 DEPLOY-001 同时绑定生产 manifest SHA 与浏览器 canary SHA；即使旧 canary 自身通过，SHA
不同也必须失败，禁止用旧页面证据证明新部署。

数据中心不再保留 BitPro 三标的默认清单。当前 A 股适配必须每日全量同步 TuShare `stock_basic`
（L/P/D，退市 `T*` 独立命名空间）、最近开放交易日 `daily` 与 `daily_basic`，单事务写入
`instrument_definitions`、`stock_history` 和 `all_stocks_realtime`。所有活动页面的证券标识采用
中文名称主标签、标准代码次标签；同步任务使用 PostgreSQL 唯一 running 台账避免并发重复。
逐标的水位必须从同一活动证券分母计算；当前生产 5,550/5,550 有 1D 数据，顶部 active 记录数
与逐标的 `row_count` 求和一致。

每个页面切片遵循：

```text
页面骨架 → 当前 API → PostgreSQL → 写操作 → 数据状态 → 响应式 → 文档 → 真实截图
```

## 12. BitPro 标准与 A股专项验收

### 12.1 直接继承的 BitPro 标准

- 18 份页面设计文档、9 组页面 E2E
- 28 张产品手册截图索引、12 张生产页面截图合同
- 页面错误边界、API 压力和导航性能
- 策略分页、筛选和详情
- 生产真实数据截图，不使用请求拦截或 DOM 注入

### 12.2 StockPro 专项门禁

- A股交易时段、交易日历、T+1、整手、涨跌停、停牌、ST 和退市
- 成本、滑点、容量和无未来数据
- 快速诊断不得晋级 Paper，完整回测门控
- Paper 历史连续性
- TuShare 主源与 AKShare 显式整类回退
- PostgreSQL 唯一事实源
- 期货入口隐藏，数字资产私有 API 零调用
- 管理员与访客，1440px 与 390px
- Loading / Empty / Partial / Stale / Error / 权限不足

### 12.3 性能

- 侧栏和页面骨架不被懒加载 fallback 替换。
- 核心请求和可选请求分层。
- 大表分页或虚拟化，图表按需加载。
- 首屏不并发读取全部详情。
- 前端 bundle 预算不得弱于当前 StockPro。
- 后端任务支持恢复、取消和审计。

## 13. 切换、回滚和生产验收

切换前必须使用最新生产数据库快照重新演练，对账所有策略、回测、Paper、信号和复盘，
在独立端口运行新系统，完成全部真实浏览器验收和新旧页面对照截图，证明旧 StockPro
仍可使用原数据库启动，并取得最终生产切换确认。

切换只允许合并到 `main` 后由 GitHub Actions 部署，并核对 Actions、部署 SHA、迁移、
服务、内外健康和关键页面。失败时回滚应用 release，不回滚、不清空数据库。

## 14. 完成标准

1. BitPro 完整产品外壳成为 StockPro 底座。
2. 所有启用页面使用真实 A股数据和 PostgreSQL。
3. 全系统只有当前 `/api/*`。
4. 不存在 SQLite 业务事实和长期双写。
5. 现有 Paper 历史完全连续。
6. 数字资产实盘、私有 API、链上和币圈后台任务不可达。
7. 期货扩展点存在但入口隐藏。
8. BitPro 页面标准与 A股专项门禁全部通过。
9. 页面文档和真实截图来自最终部署版本。
10. 生产 SHA、服务健康、迁移和真实页面完成验收。

以上十项已于 2026-08-23 全部验收。生产迁移为 37→38，pre/post 同环境对账无业务记录
差异；systemd、Nginx、内外健康接口和 storage health 正常。公开站点 8 个关键路由使用
正常管理员登录完成真实浏览器 canary，无请求拦截，console errors 为 0。生产 manifest、
canary 和 final completion audit SHA-256 分别为
`c5f419cd46c2413d9c98f1458c24ba73aa219a16b18e4c1d940aff68a6891b41`、
`11718b497a1319c92381f5a1e1caa3dcd1bfaf4908ec2cd6f7c8be826f52a50a` 和
`188d9f9bbfd0e6f855615441f8325a6f41e188cd692b86845364271bff868b1c`。

## 15. 明确非目标

- 在本合同中实现真实股票或期货交易。
- 在本合同中接入 CTP、IBKR、QMT 或 PTrade 下单。
- 保留 BitPro 数字资产能力作为 StockPro 隐藏功能。
- 同时维护旧 StockPro UI 和新 BitPro UI。
- 为兼容旧消费者保留旧 API 入口。
- 用 mock、seed 或合成行情填充最终生产截图。

## 16. 实施计划索引

- [总控计划](../superpowers/plans/2026-08-22-bitpro-first-a-share-rebuild.md)
- [Wave 0：隔离导入与安全封锁](../superpowers/plans/2026-08-22-bitpro-rebuild-00-foundation-import.md)
- [Wave 1：Shell、当前 API 与 PostgreSQL](../superpowers/plans/2026-08-22-bitpro-rebuild-01-shell-api-postgres.md)
- [Wave 2：研究工作区](../superpowers/plans/2026-08-22-bitpro-rebuild-02-research-workspaces.md)
- [Wave 3：策略、回测、模拟](../superpowers/plans/2026-08-22-bitpro-rebuild-03-mainline.md)
- [Wave 4：盯盘、信号、监控、复盘](../superpowers/plans/2026-08-22-bitpro-rebuild-04-operations.md)
- [Wave 5：数据、AI研发、期货预留](../superpowers/plans/2026-08-22-bitpro-rebuild-05-data-ai-futures.md)
- [Wave 6：最终验收、切换与回滚](../superpowers/plans/2026-08-22-bitpro-rebuild-06-acceptance-cutover.md)
