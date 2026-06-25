# A-Share Page Audit

Date: 2026-06-26

Scope: all protected frontend routes in `frontend/src/App.tsx`, plus the admin login surface.

## Baseline

- `npm run check` passed before the audit changes.
- `npm run test:e2e:mock` passed before the audit changes: 8 passed, 5 real-backend tests skipped in mock mode.
- New coverage added: `primary pages expose usable A-share research workflow anchors`.

## Audit Summary

The application is usable as a StockPro AI console shell and already has a credible A-share direction in market overview, sentiment, daily review, data sync, strategy, backtest, and paper trading. The main gap is depth consistency: some pages are professional workflows, while others are still generic panels that need explicit data freshness, A-share constraints, and research-to-execution handoffs.

## Page Matrix

| Route | Current usability | A-share/professional fit | Priority gap |
| --- | --- | --- | --- |
| `/` 总览看板 | Usable. Shows indices, short-line indicators, hot sectors, and market cards. | Strong. Matches A-share dashboard first-screen needs. | Add data freshness badges per card and explain source fallback. |
| `/market` 行情终端 | Usable after mock coverage was expanded for K-line and fundamentals. | Medium. Now exposes `行情终端`, `个股分析`, `板块龙头`, `K线图表`. | Decide whether this hidden route remains a primary page or redirects into `/research/overview`. |
| `/research/overview` 市场概览 | Usable. Has hot concepts, THS hot list, limit-up ladder, component stocks, and Data Hub freshness. | Strong. Best current A-share research page. | Add northbound/money-flow caveats and concept strength scoring once data is reliable. |
| `/sentiment` 市场情绪 | Usable. Shows sentiment index, breadth, limit-up count, hot sectors, money-flow-like panels. | Strong direction, but needs data provenance. | Separate true money flow from proxy sector net inflow; show calculation formula. |
| `/news` 消息中心 | Usable. Message stream tabs cover abnormal moves, M&A, positive/negative news, CLS, Xueqiu, EastMoney. | Medium. Event categories fit A-share research. | Link catalysts to stock/sector pages and add duplicate/source confidence handling. |
| `/ai` 智能选股 | Usable. Search and AI analysis shell are present. | Medium. Covers technical, fundamental, news dimensions. | Add explicit disclaimer, data timestamp, and evidence trace back to K-line/news/fundamentals. |
| `/factors` 因子研究 | Usable. Has overview, definitions, ranking, sync. | Medium. Good skeleton for quant research. | Add IC/RankIC, neutralization, universe filters, and factor coverage diagnostics. |
| `/calendar` 交易日历 | Usable. Calendar/list/timeline views exist. | Medium. Event categories include IPO, reports, dividends, futures/options. | Add official trading-day calendar and market-session awareness. |
| `/strategy` 策略开发 | Usable. My strategies, strategy plaza, editor, AI strategy generation. | Improved. Now shows `A股策略约束`, `100股整数手`, `T+1`, and limit-up/suspension filtering. | Make these constraints executable validations, not only visible guidance. |
| `/backtest` 回测中心 | Usable. Can create/list backtest instances. | Improved. Now shows `A股回测约束`, costs, lot size, limit-up/suspension concerns. | Ensure backend backtest engine enforces all displayed constraints. |
| `/review` 复盘中心 | Usable. Daily review combines breadth, sectors, ladder, risks, notes. | Strong. Closest to A-share discretionary research workflow. | Add automated post-close summary snapshots and compare with previous day. |
| `/paper` 模拟/实盘交易 | Usable. Can create paper instances and inspect details. | Improved. Now shows `实盘前置约束`, `T+1 / 100股`, risk and PaperBroker isolation. | Add pre-trade risk API checks and make live mode visibly locked. |
| `/monitor` 运行风控 | Usable. Shows running accounts, equity, PnL, risk status. | Improved. Now shows `运行风控检查` and `涨跌停风险`. | Add actual alert rules: drawdown, stale signal, rejected order, limit risk. |
| `/data` 管理后台 | Usable. Shows data health, sync jobs, table stats, coverage matrix. | Strong data-ops foundation. Now has visible `A股数据维护面板`. | Add dataset freshness SLA and blocking status for backtest readiness. |
| `/data/processing` 管理后台 | Usable. Data assets, jobs, quality, features, legacy tools. | Medium. Good admin depth, but mixed operational surfaces. | Split legacy entry into a lower-risk maintenance area and add permissions/confirmation for destructive SQL. |
| `/admin-login` 登录 | Usable. Admin auth is configured through token flow. | Appropriate for single-owner workstation. | Add environment status hint only when login API returns 503. |

## Product Findings

- [HIGH] Data freshness is not consistently visible across research pages. Market overview has Data Hub freshness, but sentiment, AI, calendar, and trading pages do not yet show source timestamps.
- [HIGH] A-share constraints are now visible on strategy/backtest/paper/monitor, but backend enforcement still needs a shared validation layer.
- [HIGH] `/market` is a hidden but live route. It should either become a maintained行情终端 page or redirect to the research overview to reduce product drift.
- [MEDIUM] Some pages show professional terms but lack methodology: sentiment score, money flow proxy, AI score, and factor ranks need calculation explanations.
- [MEDIUM] Research-to-execution handoff is fragmented. A concept leader, AI stock, factor candidate, or news catalyst should be able to become a strategy candidate or paper-trade watch item.
- [MEDIUM] Admin/data tools are powerful but broad. SQL and destructive data actions should have clearer safety gates before production use.

## UI Audit Notes

Rules referenced: `a11y-semantic-html-first`, `a11y-icon-controls-labeled`, `interaction-keyboard-operable`, `forms-labels-and-autocomplete`, `nav-semantic-links`, `layout-empty-loading-error-states`, `layout-long-content-safety`, `copy-specific-action-labels`, `copy-actionable-error-messages`.

- Navigation uses semantic `NavLink` entries and primary page controls are mostly real buttons.
- Several icon-only controls already have `aria-label`; continue enforcing this in modal close, settings, search, and data-management controls.
- Many pages define empty states, but not all explain how to resolve missing data. Future fixes should make empty states actionable.
- Placeholder-only labels still exist in some compact search fields. They are acceptable for quick filters only when an `aria-label` exists; form fields that save data should keep visible labels.

## Recommended Next Slice

1. Add a shared `AshareConstraintPolicy` domain model in frontend and backend.
2. Use it in Strategy, Backtest, Paper, and Monitor to make T+1, 100-share lots, suspension, and limit-up/down checks executable.
3. Add per-page `DataReadinessBadge` components that show source, last update, cache freshness, and blocking gaps.
4. Add route-level E2E checks for empty/error states and not only happy-path anchors.
