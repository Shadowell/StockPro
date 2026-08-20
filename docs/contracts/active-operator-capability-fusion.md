# Sprint 合同：主线优先的操作台能力融合

- 状态：已完成
- 日期：2026-08-20
- 外部参考：`shy3130/tickflow-stock-panel` 的页面组织与公开功能
- 产品主线：策略 → 回测 → 模拟
- 交付边界：B/S、PostgreSQL、研究优先、仅 Paper 模拟；实盘继续只做预检与留痕

## 1. 目标

在不建立第二套策略、回测、模拟或数据事实源的前提下，吸收外部开源项目中适合 StockPro 的市场看板、自选、指数、选股、因子回测、参数优化、Walk-forward、个股/财务/板块分析、连板梯队、监控、复盘、数据扩展和首次配置能力。

所有新增能力必须归属于 StockPro 现有页面和对象，并回答它如何服务“策略 → 回测 → 模拟”主线。

## 2. 不可破坏约束

1. 正式策略只使用 `StockPro Strategy API v1` 和不可变策略版本。
2. 快速回测、因子诊断、参数优化和 AI 实验不能绕过完整回测的 11 项 Paper 晋级门控。
3. Paper 继续使用现有 PostgreSQL 账户、信号、风控、订单、成交、持仓、权益和事件账本；任何页面改造不得重置历史。
4. PostgreSQL 是唯一事实存储；Parquet/CSV/Excel/JSON 只用于导入、导出、缓存或离线交换。
5. TuShare 为稳定研究主源，AKShare/其他来源只能显式补充或整类回退；禁止静默混源。
6. 页面读取不得隐式同步、迁移、bootstrap、恢复 Paper 或执行策略。
7. 缺失、过期、部分可用、无权限和错误必须分别显示；禁止用 0、默认分数或响应时间伪装事实。
8. 直接复用外部代码前必须逐项检查许可证和归属；默认按 StockPro 架构重新实现功能与交互。

## 3. 一级信息架构

| 分组 | 页面 | 路由 | 角色 |
| --- | --- | --- | --- |
| 总览 | 首页 | `/` | 市场与主线状态驾驶舱 |
| 主线 | 策略 | `/strategy` | 策略、选股、信号、因子/股票池输入与 AI 研发 |
| 主线 | 回测 | `/backtest` | 快速诊断、完整回测、因子验证、优化与 Walk-forward |
| 主线 | 模拟 | `/paper` | Paper 实例、账户、持仓、信号、风控、订单、成交和复盘 |
| 补充 | 行情 | `/market` | 市场结构、情绪、板块、自选、指数、事件和个股 |
| 补充 | 盯盘 | `/watch` | 业务信号、规则、提醒和执行证据 |
| 补充 | 数据 | `/data` | 数据集、同步、质量、来源、指标、扩展和导入导出 |

兼容路由继续保留。`/ai-lab`、`/pools`、`/factors`、`/monitor`、`/review`、`/live`、`/data/processing` 不作为一级导航；其能力逐步融合到上表 Owner 页面后再决定重定向或保留详情直链。

## 4. 页面能力归属

| 外部参考能力 | StockPro Owner | 交付方式 |
| --- | --- | --- |
| Dashboard | 首页 | 高密度市场驾驶舱 + 策略/Paper/数据状态 |
| Watchlist / Indices | 行情 | 自选与指数二级标签 |
| Screener / Custom Signals | 策略 | 预览候选；封存股票池后才能进入正式回测 |
| Factor Backtest / Optimizer / Walk-forward | 回测 | 复用现有快照、协议、成本与门控 |
| Stock / Financial Analysis | 行情个股详情 | 日线、分时、盘口、财务、关键价位和 AI 证据 |
| Concept / Industry / Limit Ladder / Regime | 行情 + 首页摘要 | 保留来源口径与公式版本 |
| Signal Monitor | 盯盘 | 策略、个股、价格、异动规则与通知 |
| Runtime Monitor | 隐藏 `/monitor` | 系统和数据健康，不混入业务信号 |
| Review | 首页/模拟入口 + `/review` | 市场、策略、Paper 统一盘后复盘 |
| Data / Extensions / Onboarding | 数据 + 首次向导 | 文件/JSON/HTTP 导入、导出与能力检测 |
| Branding / Dev | 不进入产品 | 只保留开发用途 |

## 5. 有序交付

1. **Foundation**：导航、页面 Owner、兼容路由和共享上下文。
2. **Strategy**：选股器、条件信号、股票/ETF、因子/股票池入口与 AI 研发归位。
3. **Backtest**：因子验证、参数优化、Walk-forward 和交易 K 线证据。
4. **Paper/Watch**：四类监控规则、通知与信号→风控→订单→成交链。
5. **Dashboard/Market**：高密度首页、自选、指数、板块、连板和个股分析。
6. **Data**：扩展数据注册、CSV/Excel/JSON/HTTP 导入和多格式导出。
7. **Review/Onboarding**：统一复盘、通知和首次配置向导。
8. **Acceptance**：全路由、全数据状态、权限、桌面/移动端、生产部署和 SHA 验证。

每一步必须作为独立可回滚切片，运行相关测试、`./scripts/check.sh`、本地服务重启和真实浏览器验收后再提交。

## 6. 总体验收

1. 一级导航明确呈现策略 → 回测 → 模拟，其他页面为补充。
2. 每项吸收能力只有一个 Owner 页面，没有平行实现。
3. 策略、回测和 Paper 的版本、门控、账本与历史保持连续。
4. 页面显示真实来源、交易日、知识截止时间、新鲜度和缺失原因。
5. 管理员/访客、加载/空/过期/错误/部分缺失/权限不足、1440px/390px 均通过浏览器验收。
6. `./scripts/check.sh`、Mock E2E、真实后端主线 E2E 和生产 smoke 全部通过。
7. 生产仅由 `main` push 的 GitHub Actions 部署；服务器 SHA、服务状态、内外健康和关键页面一致。

## 7. 当前切片

Acceptance：八阶段全部完成。最终验证为 62/62 Mock 浏览器、424 个后端测试、生产构建/预算/编译、真实本地与生产只读浏览器、37/37 生产迁移、部署 SHA/服务/域名健康和 Paper 历史连续性。生产首次就绪检查如实为 2/4：管理员安全与 PostgreSQL 就绪，TuShare 主源和封存快照尚未配置；这不会被伪装为功能完成度。ETF 因缺独立快照、Universe、成本与 Paper 语义明确保留为未支持。
