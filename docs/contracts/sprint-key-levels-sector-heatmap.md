# Sprint 合同：个股关键价位模块 + A股板块热力图

- 状态：已完成（2026-08-28）；生产部署证据见 progress.md 与最终交付报告
- 基线分支：从 `origin/main`（`56b73cba`）派生 `codex/key-levels-sector-heatmap`
- 上游设计参考（只读）：`shy3130/tick-stock-panel` `backend/app/indicators/levels.py`（11 类关键价位纯函数）
- 领域边界：只读 PostgreSQL；无 Provider 调用；无业务写操作；不触碰 Paper；不注册真实下单

## 1. 目标

1. 把 tick-stock-panel 的「11 类关键价位」纯函数移植为 StockPro 的 numpy 实现，
   通过只读 API 暴露给行情页，个股 K 线可按分组叠加价位线。
2. 交付 A 股版「板块热力图」（行业维度）：矩形面积 = 板块标的数，
   颜色 = 窗口等权涨跌；右栏板块动量（领涨/领跌 + 强弱榜）；点击板块查看全部成员行情，
   点击成员联动行情页标的。

## 2. 范围

### In Scope

- `backend/app/domain/market/key_levels.py`：纯 numpy 关键价位模块（成交密集区/枢轴点/
  前高前低/布林/Keltner 三档/ATR 通道/缺口/斐波那契/整数关口），停牌坏 bar 过滤，
  输入输出全部可序列化；换手率不可得时筹码分布退化为无衰减量堆积并在 meta 标明。
- `GET /api/v2/market/key-levels`：复用 `get_klines_payload("1d")` 只读链路，返回
  分组价位点 + 紧凑摘要 + 数据状态；GET 不写库、不调 Provider。
- `GET /api/v2/market/sector-heatmap`：`instrument_definitions`(active CN stock + industry)
  × `all_stocks_realtime`(当日价/涨跌/成交额) × `stock_history`(5d/20d 窗口收盘) 一次聚合，
  返回板块聚合 + 成员明细 + 窗口与来源 meta；window=1d|5d|20d。
- 前端：`KeyPriceLevelsPanel`（分组开关 + 最近价位列表 + 摘要），
  `KlineChart` 新增可选 `priceLevels` markLine 渲染（不影响既有消费者），
  `AshareSectorHeatmap`（treemap + 板块动量 + 成员表，红涨绿跌跟随设置），
  均挂载在 `/market` 页面。
- 单元/合同测试：纯函数数值回归 + Fake Repository 端点合同。
- 文档：`docs/pages/行情.md`、`docs/progress.md`、本合同、`docs/contracts/active.md` 指针。

### Out Of Scope

- 概念板块热力图（ths 概念成员覆盖不足时再评估）。
- 盯盘/复盘/首页等其他页面的热力图挂载。
- 复权口径改造、连板/炸板个股级信号、盘中折算量比。
- 任何 Provider 实时取数、写库、Paper 变更。

## 3. 数据与语义合同

- 关键价位基于 `stock_history` 未复权日线（与现有 K 线同源同状态），
  `as_of_trade_date` 明确标注；不做前复权改造（缺口/整数关口用原始价口径）。
- 热力图窗口：`1d` = `all_stocks_realtime.change_percent`（缺实时回退日线相邻收盘）；
  `5d/20d` = `stock_history` 最近第 1/6/21 个交易日收盘比。板块等权平均，
  涨/跌/平家数同口径。所有成员必须携带名称与板块（board）。
- 响应固定携带 `data_status`、`unavailable_reason`、来源与交易日；空数据返回诚实空态，
  不伪造 0 值。

## 4. Done Means

- `export DATABASE_URL="$(./scripts/setup_isolation_db.sh --print-url)" && ./scripts/check.sh` 通过。
- 新增 pytest 全绿；前端 tsc/lint/build 通过。
- 本地 4444/4445 干净重启后浏览器冒烟：热力图可见并可点开板块成员；
  关键价位面板可切换分组并在 K 线上叠加价位线；console errors = 0。
- `docs/progress.md` 记录实现与验证；本合同记录验收结果与已知边界。

## 5. 验收记录（2026-08-28）

- 后端新增 `rebuild/tests/test_market_key_levels_heatmap.py` 17 项全绿；全量
  `./scripts/check.sh` 通过（前端类型/零告警 lint/production build/bundle、后端
  pytest、43 项 Mock E2E、diff whitespace）。
- 隔离库 `stockpro_bitpro_rebase_dev` 真实数据：key-levels 600519.SH 124 根日线、
  10 组价位有值；sector-heatmap 1d 窗口 110 行业、5550/5550 覆盖、5d 窗口 5547。
- 浏览器（Playwright Chromium，1440×900）：热力图渲染、板块点击成员表、窗口切换、
  关键价位分组开关与 K 线 markLine 叠加全部通过，console/page errors 与失败请求为 0。
- 已知边界：① 概念板块热力图未做（成员覆盖另评）；② 筹码分布无历史换手率，
  `turnover_source=unavailable` 时为无衰减量堆积；③ 缺口/整数关口等价位基于未复权价；
  ④ 热力图 5d/20d 窗口按"最近第 N 个有数据交易日"口径（停牌股窗口顺延）。
