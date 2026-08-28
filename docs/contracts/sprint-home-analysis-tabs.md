# Sprint 合同：首页分析板块 tab（连板梯队/概念/行业/市场环境/异动/个股）

- 状态：已完成（2026-08-28）；合并 `main` / 生产部署仍受当前部署限制约束
- 基线分支：`codex/key-levels-sector-heatmap`（上一 sprint `ef041d1a` 之上续作）
- 需求来源：用户要求把 tick-stock-panel 侧栏的 连板梯队/概念分析/行业分析/个股分析/
  市场环境/异动监控 六个入口移植到 StockPro 首页
- 领域边界：只读 PostgreSQL；无 Provider 调用；无业务写操作；不触碰 Paper

## 1. 目标

首页新增 `?tab=` 二级标签（仓库既有模式），把六个分析入口作为首页 tab：
总览（现状不动）· 连板梯队 · 概念分析 · 行业分析 · 市场环境 · 异动监控 · 个股分析。

## 2. 数据事实（隔离库实测 2026-08-28）

| 数据 | 表 | 本地最新 | 用途 |
|---|---|---|---|
| 个股连板梯队 | `lianban_ladder_history` | 2026-08-17（505 行） | 连板梯队 tab + 市场环境趋势 |
| 涨停/炸板/跌停池 | `limit_pool_members` × `market_evidence_snapshots` | 2026-08-21 | 连板梯队 tab 封单/开板 |
| 每日概念板块 | `daily_concept_sectors` | 2026-08-21（6227 行） | 概念分析 tab |
| 热门概念资金流 | `hot_concepts_realtime` | 2026-07-29 | 概念分析 tab 资金流 |
| 行业等权涨跌 | `stock_history` + `instrument_definitions.industry` | 2026-08-26 | 行业分析 tab（复用热力图口径） |
| RPS/六阶段/异动物化 | `sector_rps_results` / `market_phase_results` / `symbol_abnormal_metrics` | 空 | 页面显示诚实空态 + 缺失原因 |

遗留表属旧同步管道，读取时必须展示数据日期与 stale 提示，不冒充最新。

## 3. 范围

### In Scope

- 三个新只读端点（不写库、不调 Provider）：
  - `GET /api/v2/market/limit-ladder`：最新梯队按连板高度分组 + 最新 evidence snapshot
    涨停/炸板/跌停池（封单额/开板次数/连板数）+ 近 30 日梯队高度/宽度趋势；
    梯队日与池日分别标注。
  - `GET /api/v2/market/concept-analysis`：最新概念榜单 + 近 20 交易日 top/bottom 概念
    轮动矩阵 + 热门概念资金流（标注 hot 数据日期）。
  - `GET /api/v2/market/industry-analysis`：行业 1d/5d/20d 等权涨跌 + 家数 + 领涨成员
    （与热力图同口径，不引入 sector_realtime 东财 blob 第二口径）。
- 首页 6 个 tab 组件（lazy）：连板梯队、概念分析、行业分析、市场环境
  （组合 `/market/phase` + `/market/timeline` + ladder 趋势 + 领涨行业/概念）、
  异动监控（组合 `/market/movers` + `/monitor/events`）、个股分析
  （证券搜索 + 关键价位摘要 + 跳转行情页）。
- `?tab=` 状态进 URL，刷新/分享不丢 tab；默认 `总览` 不变。
- 桌面 + 390px、Loading/Empty/Stale/Error 状态、console errors = 0。
- 测试：聚合纯函数 + fake repo 服务合同测试；前端 check.sh 门禁。
- 文档：`docs/pages/首页.md`、progress.md、本合同、active 指针。

### Out Of Scope

- 本地物化 RPS/六阶段/异动 metrics 的补算（属同步管道任务）。
- 把 sector_realtime / hot_concepts 之外的第三口径引入行业分析。
- 涨停封单的盘中实时监控（无逐笔/盘口事实）。
- 复权口径改造。

## 4. Done Means

- `./scripts/check.sh` 全绿；新增 pytest 全绿。
- 隔离库浏览器验收：6 个 tab 真实渲染（本地空数据 tab 显示诚实空态与原因），
  桌面/390 无横向溢出，console errors = 0。
- 文档与合同更新完成；分支推送，合并 `main` 仍受当前部署限制约束。
