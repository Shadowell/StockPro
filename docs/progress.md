# Progress Log

## Snapshot (2026-06-26)

- Sprint: `ashare-research-professionalization`
- Focus: audit every primary page, verify usability, and define the route from current console pages to a professional A-share research workstation.
- Active contract: `docs/contracts/active-ashare-research-professionalization.md`
- Product direction: every page should have a clear A-share research/execution purpose, visible data readiness, and explicit trading constraints where decisions move toward orders.

## Latest Completed Work (2026-06-26)

1. Added cross-page usability coverage
- Added mocked E2E coverage that opens every primary protected route and verifies page title, core workflow anchors, and absence of React page errors.
- Expanded mocked market fixtures for daily K-line, intraday, fundamentals, and stock search so `/market` is tested as a real page instead of crashing on fixture shape.

2. Strengthened A-share professional anchors
- Added a shared `AshareGuardrailStrip` component.
- Added visible A-share guardrails to strategy, backtest, paper trading, and monitor pages: T+1, 100-share lots, limit-up/down, suspension, cost model, and broker isolation.
- Renamed the hidden `/market` surface header to `行情终端` and exposed `个股分析`, `板块龙头`, and `K线图表`.
- Made the data page's `A股数据维护面板` label visible instead of aria-only.

3. Documented audit and roadmap
- Added `docs/qa/2026-06-26-ashare-page-audit.md` with a page-by-page usability and A-share professionalism matrix.
- Added `docs/ashare-research-roadmap.md` with the full path from data foundation to research, candidate pools, strategy lifecycle, backtesting, paper trading, risk, and broker dry-run.
- Added `docs/superpowers/plans/2026-06-26-ashare-research-workstation.md` as the step-by-step development plan.
- Added `docs/contracts/active-ashare-research-professionalization.md` as the next sprint contract.
- Updated `docs/spec.md` with page professionalism acceptance rules.

## Verification Evidence (2026-06-26)

- `npm run check` from `frontend/` (pass).
- `npm run lint` from `frontend/` (pass with 7 existing warnings, 0 errors).
- `npm run test:e2e:mock -- --grep "primary pages expose"` from `frontend/` (pass).
- `npm run test:e2e:mock` from `frontend/` (pass: 9 passed, 5 real-backend tests skipped by mock mode).
- `./scripts/check.sh` (pass: frontend build, frontend lint with warnings only, deploy shell syntax, backend unit tests 17/17, backend compile).

---

## Snapshot (2026-06-25)

- Sprint: `stockpro-ai-console-style`
- Focus: align the local frontend with the production server StockPro AI dark console style.
- Active contract: `docs/contracts/active-stockpro-ai-console-style.md`
- Product direction: fixed grouped sidebar, compact dark cards, top A-share ticker/status bar, and dashboard-first market cards.

## Latest Completed Work (2026-06-25)

1. Rebuilt the application shell around the server reference style
- Added the `StockPro AI` brand block with a fixed 264px desktop sidebar.
- Reorganized navigation into `研究工坊`, `策略工厂`, `执行风控`, and `系统管理`.
- Moved `总览看板` into the `研究工坊` group and removed the empty `数据中台` group.
- Moved `管理后台` from the top business navigation area into a lower `系统管理` section.
- Renamed the backtest workspace navigation/title from `复盘中心` to `回测中心`.
- Added a separate `/review` `复盘中心` for daily market review.
- Added a compact desktop top bar with route title, four A-share indices, `已休市` status, language toggle, settings, and logout actions.

2. Aligned global visual tokens
- Updated the dark palette, borders, card surfaces, hover states, radius scale, and primary accent toward the production server screenshot.
- Added compatibility overrides so older purple accents read as the current blue console accent.
- Updated the admin login page to use the same StockPro AI console tone.

3. Tightened the dashboard first viewport
- Removed the old `量化交易中枢` module chain from the top of the dashboard.
- Made the first content block start directly with `市场指数`, followed by `短线指标` and `热门板块`.
- Locked the index order to `上证指数`, `深证成指`, `创业板指`, `科创50` in both the top ticker and dashboard cards.
- Added a hot-concept fallback so `热门板块` uses existing external market data when PG cache is empty, and displays TOP5 when no board is above 5%.

4. Added regression coverage
- Added E2E coverage for the StockPro AI shell, navigation groups, top ticker order, dashboard index order, and removal of the old module-chain header.
- Updated the dashboard realtime cockpit test so the dashboard defaults directly to the market cockpit instead of requiring a module button.
- Added backend fallback tests and frontend E2E coverage for the `热门板块` non-empty TOP5 path.
- Added E2E coverage that `/backtest` is `回测中心`, `/review` is the new `复盘中心`, and legacy `/pulse` redirects to `/review`.

5. Added daily review workflow
- Added `DailyReview.tsx` to summarize market temperature, breadth, turnover, hot sectors, limit-up ladders, risk notes, and next-day plans.
- Wired replay-note list/save API client helpers so the page can persist daily review logs through existing `/market/pulse/replay-notes` endpoints.

## Verification Evidence (2026-06-25)

- `npm run check` from `frontend/` (pass).
- `npm run lint` from `frontend/` (pass with 7 existing warnings, 0 errors).
- `npm run test:e2e:mock -- --grep "desktop shell matches|single api shell"` from `frontend/` (pass; covers `总览看板` under `研究工坊` and removal of `数据中台`).
- `npm run test:e2e:mock` from `frontend/` (pass: 8 passed, 5 real-backend tests skipped by mock mode).
- `npm run test:e2e:mock -- --grep "backtest center is separated"` from `frontend/` (pass).
- `python -m unittest tests.test_market_service_cache_only.HotConceptFallbackTests` from `backend/` (pass).
- `npm run test:e2e:mock -- --grep "hot concepts|realtime market cockpit"` from `frontend/` (pass: 2 passed).
- `./scripts/check.sh` (pass: frontend build, frontend lint with warnings only, deploy shell syntax, backend unit tests 17/17, backend compile).
- Real local API check: `/api/market/hot-concepts?limit=10` returned 10 rows after login.
- Local Playwright visual QA screenshot: `.codex-artifacts/stockpro-daily-review-center.png`.
- Local Playwright visual QA screenshot: `.codex-artifacts/stockpro-hot-concepts-fixed.png`.
- Local Playwright visual QA screenshot: `.codex-artifacts/stockpro-ai-style.png`.

---

## Snapshot (2026-06-12)

- Sprint: `standardize-and-trading-core` adjusted to single-router cleanup
- Focus: remove unused legacy pages, backup files, and parallel API routers while preserving the active market/research/strategy/backtest/paper workflows
- Active contract: `docs/contracts/active-standardize-and-trading-core.md`
- Product direction: one `/api` prefix, no `/api/v1` or `/api/v2`, no standalone V2 business routes

## Latest Completed Work (2026-06-12)

1. Removed unused frontend route surfaces
- Deleted legacy pages replaced by the new shell or route redirects: `Home`, `StockScreener`, `StrategyDev`, `StrategyExec`, `MarketPulse`, `LiveTrading`.
- Deleted old one-off components only referenced by those pages: `StockTable`, `AIAnalysisPanel`, `SectorMonitor`, `StrategyLabWorkflow`, `MarketCalendar`, `CalendarView`, `DataOverviewPanel`, `PresetTaskPanel`, and related helper-only files.
- Kept active pages for dashboard, market, research workbench, AI analysis, factor library, data center, strategy factory, backtest, paper trading, monitor, and trading calendar.

2. Removed redundant backend API surfaces
- Removed `backend/app/api/v2` source tree.
- Removed standalone `strategy_v2.py`, `stock_screener.py`, and `trading.py` endpoint routers from the active API registration.
- Removed tracked `.bak` / `.backup` source files.
- Preserved underlying Postgres repository methods and migrations so future paper/risk/broker capabilities can be wired into the main product flow instead of a parallel API.

3. Tightened frontend runtime logic
- Removed unused Zustand state for old stock table, hot sectors, and batch AI analysis.
- Removed client calls for `/stocks/filter`, `/sectors/hot`, `/ai/analyze`, `/screener/*`, and old Market Pulse-only replay APIs.
- Updated Data Hub feature service to refresh the current `/data-hub/features/screener` summary instead of navigating to the deleted `/screener` route.

4. Removed visible instruction banners
- Removed the Data Hub V1 explanatory banner from the data-processing page.
- Removed the legacy compatibility advisory banner from the data-processing legacy tab.
- Added E2E coverage to ensure those explanatory strings do not return.

## Verification Evidence (2026-06-12)

- `npm --prefix frontend run build` (pass)
- `python3 -m compileall backend/app` (pass)
- `./scripts/check.sh` (pass after allowing local Postgres access; frontend build, frontend lint with warnings only, deploy shell syntax, backend unit tests 15/15, backend compile)
- `npm --prefix frontend run test:e2e:mock` (pass: 3 active mock tests, 5 real-backend tests skipped by mode)
- Static scans found no runtime source references to `api_router_v2`, `app.api.v2`, `/api/v2`, `/strategy-v2`, `strategy_v2`, `stock_screener`, `trading.router`, old screener client calls, or deleted page/component names.
- Backup-file scan found no remaining tracked `*.bak`, `*.backup`, or `*~` files.
- Static scan found no remaining `Data Hub V1`, `当前以`, or legacy compatibility advisory text in frontend source.

## Remaining Work (standardize-and-trading-core sprint)

- Wire any still-needed portfolio/order/risk/broker capabilities into the active `/paper`, `/strategy`, `/backtest`, or future `/monitor` workflows before exposing them again.
- Continue PG repository cleanup in `data_hub_service.py` and `strategy_lab_service.py`.
- Browser E2E against real backend remains useful after the local backend is restarted with production-like environment variables.

---

## Snapshot (2026-06-03)

- Workspace: `/Users/jie.feng/wlb/StockPro`
- Focus: cloud B/S deployment foundation, Postgres migration runner, BitPro-style production deploy upgrade
- Active contract: `docs/contracts/active-cloud-bs-pg-deploy.md`
- Production target: `root@47.79.36.92`, public entry `http://47.79.36.92:4444`
- Deployment status: live on `47.79.36.92:4444` with Postgres `stockpro_prod`

## Latest Completed Work (2026-06-03)

1. Product and sprint direction updated
- Replaced template-oriented `docs/spec.md` with StockPro cloud B/S product spec.
- Added active sprint contract for React + FastAPI + Postgres deployment foundation.

2. Postgres foundation added
- Added `backend/app/db/postgres_migrations.py` migration runner.
- Added initial PG schema under `backend/postgres/migrations/202606030001_strategy_workbench_core.sql`.
- Added backend unit tests for migration sorting, skipping applied migrations, and recording applied versions.
- Added `psycopg[binary]` dependency and `DATABASE_URL` config support.

3. Deployment upgraded toward PG-only production
- Updated `deploy/deploy.sh` to validate `.env`, install dependencies, compile backend code, run PG migrations, restart systemd, reload Nginx, and health-check services.
- Updated `deploy/setup-server.sh` and added `deploy/setup-postgres.sh`.
- Updated Nginx config with WebSocket proxy headers.
- Updated GitHub Actions deployment to keep main-only SHA-gated deploy and remove old local-file seed/import steps.
- Enforced PG-only production deploy through required `DATABASE_URL`.

4. Local-file database runtime removed from production
- Changed backend default storage to Postgres.
- Removed local-file database route/service toggles from the current runtime.
- Moved research, data, and strategy surfaces toward Postgres repositories.

5. Documentation updated
- Rewrote `docs/deployment.md` for `47.79.36.92:4444`, Postgres `stockpro_prod`, and BitPro-style single-server deployment.
- Updated README environment/deployment notes for PG-only production.

6. Production server initialized and deployed
- Installed PostgreSQL on `47.79.36.92`.
- Created `stockpro_prod` and `stockpro_app` with a server-local generated password.
- Created root-only `/opt/stockpro/backend/.env` for Postgres runtime settings.
- Deployed React static frontend + FastAPI backend through Nginx/systemd.
- Archived old local database files outside the active runtime path.

## Verification Evidence (2026-06-03)

- `python3 -m unittest tests/test_postgres_migrations.py` from `backend/` (pass, 2/2)
- `PYTHONPATH=backend python3 -m unittest backend.tests.test_api_router_modes` (pass, 2/2)
- `./scripts/check.sh` (pass: frontend build, frontend lint, deploy shell syntax, backend unit tests 5/5, backend compile)
- Remote deploy: `bash /opt/stockpro/deploy/deploy.sh` (pass, no pending migrations on second deploy)
- Remote health: `curl http://47.79.36.92:4444/api/health/health` (pass)
- Remote storage health: `curl http://47.79.36.92:4444/api/health/storage` (pass: Postgres migrations reported)
- Remote service state: `stockpro-backend` active, `postgresql` active, no local database files remain under `/opt/stockpro`

## Snapshot (2026-06-10)

- Sprint: `standardize-and-trading-core` active
- Latest work: Added V2 trading infrastructure repository methods in `postgres_db.py`

## Latest Completed Work (2026-06-10)

1. V2 trading infrastructure repository methods added to `postgres_db.py`
- Portfolios: `create_portfolio`, `get_portfolio`, `list_portfolios`, `update_portfolio`
- Positions: `upsert_position`, `get_positions`, `get_position`
- Orders: `create_order`, `get_order`, `list_orders`, `update_order`
- Trades: `insert_trade`, `list_trades`
- Cash Ledger: `insert_cash_ledger_entry`, `list_cash_ledger`
- Risk Rules: `create_risk_rule`, `get_risk_rule`, `list_risk_rules`, `update_risk_rule`
- Risk Events: `insert_risk_event`, `list_risk_events`
- Broker Connections: `create_broker_connection`, `get_broker_connection`, `list_broker_connections`, `update_broker_connection`
- Added `get_backtest_run` method

2. V2 API endpoints created and registered
- `strategy_v2.py`: strategy versions CRUD, signals CRUD, backtest runs CRUD + trades list
- `trading.py`: portfolios CRUD, positions list, orders CRUD, trades list, cash ledger, risk rules CRUD, risk events, broker connections CRUD
- Both registered in `api.py` under `/strategy-v2` and `/trading` prefixes
- Added `get_backtest_run` method to `postgres_db.py`

3. Verification
- `postgres_db.py` compiles clean
- All new endpoint routes load successfully (35 routes total)
- `./scripts/check.sh`: frontend build OK, deploy syntax OK, backend compile OK
- Backend unit tests: 8/10 pass (2 pre-existing failures due to missing `dashscope`)

## Remaining Work (standardize-and-trading-core sprint)

- Wire V2 service layer to use new postgres_db methods and API endpoints

## Known Gaps (2026-06-10)

1. Current fusion needs continued real-data validation across research, market, strategy, backtest, and paper trading flows.
2. PG-only production should keep all new work on shared Postgres repositories.
3. IP-only HTTP remains the production entry for now; HTTPS/domain should be added before real broker integration.
4. V2 trading API endpoints implemented but no frontend integration yet.

## Recommended Next Steps (2026-06-10)

1. Wire frontend to new V2 trading API endpoints
2. Continue `data_hub_service.py` raw SQL refactoring
3. Clean remaining raw SQL in `strategy_lab_service.py`
4. Add HTTPS/domain before broker integration

---

## Snapshot (2026-05-28)

- Workspace: `/Users/jie.feng/wlb/StockPro`
- Focus: full-stack smoke test, API/page auto-fix, E2E alignment with current 11 routes
- Verification: `./scripts/check.sh`, Playwright real-backend (7/7), mocked pages (2/2), manual API sweep (19/19)

## Latest Completed Work

1. Fixed `/api/stocks/filter` 500 error
- Root cause: `database_data_service.get_filtered_stocks_from_db()` returned fields (`close`, `amount`) incompatible with `StockFilterResponse` schema (`current_price`, `market_cap`).
- Fix: prefer `all_stocks_realtime` cache and map to `StockBase` fields; fallback to `stock_history` with correct mapping.

2. Page title alignment
- `LiveTrading` page title updated to `模拟/实盘交易`.
- E2E routes updated: removed `/analysis`, `/screener`; updated `/ai` and `/trading` titles.

3. E2E config
- Playwright default base URL/port aligned to Vite dev server (`4444` / backend `4445`).

4. Full verification pass
- 11 frontend pages: all render with data, no API 4xx/5xx on page load.
- 19 core backend endpoints: all return 200 via direct backend and frontend proxy.

## Module Completion

| Module | Route | Status | Evidence |
|---|---|---|---|
| Dashboard | `/` | Usable | Page + API pass |
| Market Overview | `/market` | Usable | Page + API pass |
| Sentiment | `/sentiment` | Usable | Page + API pass |
| News Center | `/news` | Usable | Page + tab E2E pass |
| AI Screener | `/ai` | Usable | Page + API pass |
| Factor Library | `/factors` | Usable | Page + API pass |
| Calendar | `/calendar` | Usable | Page + API pass |
| Strategy Dev | `/strategy-dev` | Usable | Page + API pass |
| Strategy Watch | `/strategy-exec` | Usable | Page + API pass |
| Review Center | `/pulse` | Usable | Page + API pass |
| Sim/Live Trading | `/trading` | Usable | Page pass |

## Next Step

- Consider adding `.env.example` with `VITE_DEV_API_PROXY_TARGET=http://127.0.0.1:8012` when port 8000 is occupied by other local services.

---

## Historical Log (2026-04-02)

1. DataDev backend unblock
- Added `data_dev_tasks` / `data_dev_logs` table init into local DB bootstrap.
- Wired `StockScreener` route and sidebar entry.
- Added `/screener` into Playwright route coverage.

3. Data schema and usability fixes
- Unified `stock_fundamentals` schema with actual read/write usage.
- Added compatibility column migration (`ALTER TABLE ... ADD COLUMN`) for old local DBs.
- Fixed stock search to read `current_price` instead of non-existent `price`.
- Fixed Data Quality check to use `current_price`.
- Fixed THS freshness check to support `ths_hot_history`.
- Updated SQL workbench fundamentals template query.

4. Backfill task behavior alignment
- `batch-import/historical-data` now validates and honors `task_type` (`history|fundamentals|all`).
- Removed misleading `indicators` option from daily backfill UI (it was not supported in that endpoint flow).

5. E2E dual-mode support
- Added `MOCK_API` gated test strategy:
  - `app.spec.ts` runs in mocked mode only.
  - `real-backend.spec.ts` runs in real-backend mode only.
- Added npm scripts:
  - `test:e2e:mock`
  - `test:e2e:real`

6. Backend startup guardrail
- Added health script: `scripts/backend-health.sh`
- Checks:
  - required python dependencies
  - critical backend module `py_compile`
  - optional health endpoint ping (`--ping`)

7. Real-backend regression fix
- Fixed `/api/admin/task-status` 500 by adding missing scheduler methods:
  - `SchedulerService.get_status()`
  - `SchedulerService.fetch_and_save_all_stocks_history()`
- Extended real-backend E2E to assert `admin/task-status` endpoint.

8. Backend test-mode startup toggle
- Added runtime feature flags:
  - `ENABLE_SCHEDULER`
  - `ENABLE_REALTIME_SYNC`
  - `ENABLE_STRATEGY_EXECUTION`
- Backend can now start in lightweight test mode to avoid startup noise and external sync interference during E2E.

9. Offline market-overview path for E2E
- Added runtime flag:
  - `ENABLE_EXTERNAL_MARKET_FETCH`
- In `MarketService.get_market_overview`, when this flag is `false`:
  - no fallback to external market API
  - return cache-only stocks/indices
- Also guarded external fetch in:
  - `MarketService._get_cached_all_stocks`
  - `MarketService.get_all_sectors`
  - `MarketService.get_stock_fundamentals` (returns `external_fetch_disabled` if local data missing)

10. Database endpoint status-code correctness
- Fixed `database` endpoint exception handling to preserve `HTTPException` status codes.
- `/database/query` non-SELECT validation now returns `400` correctly (instead of being converted to `500`).
- `/database/table/{table_name}` now preserves `404` when table is missing.

11. Batch import task usability fix
- Removed unsupported `indicators` task from `BatchImportPanel` (backend rejects it in `/batch-import/historical-data`).
- Kept MA import in its dedicated card flow to avoid task-type mismatch and user confusion.

12. Database manager export completion
- Implemented CSV export for:
  - selected table preview data
  - SQL query result data
- Added empty-result disable states and reused a safe cell-stringify path.

13. Real-backend E2E deepening
- Extended `real-backend.spec.ts` from smoke checks to functional assertions:
  - `market/overview` response structure
  - `database/query` success + non-SELECT rejection
  - `data-dev` task CRUD + run + logs flow
- Switched real-backend suite to serial mode for deterministic shared-db mutations.

14. Data Hub V1 one-time refactor (功能重构)
- Added unified backend capability set under `/data-hub/*`:
  - dataset registry and freshness
  - job orchestration (create/list/detail/rerun/cancel)
  - quality governance report run/query
  - feature service for screener/factors
- Added local DB tables:
  - `data_hub_jobs`
  - `data_hub_quality_reports`
- Marked legacy endpoints with deprecation hints:
  - `/batch-import/*`
  - `/data-dev/*`
  - `/database/*`

15. Legacy-to-hub compatibility bridge
- `batch-import/historical-data` now internally dispatches to Data Hub job orchestration (`import_daily_data`) while preserving old response shape.
- `data-dev/tasks/{id}/run` now dispatches into Data Hub orchestration (`run_data_dev_task`) and returns `job_key`.

16. Frontend information architecture refactor
- Reworked Data Center page into Data Hub workflow tabs:
  - 数据资产 (`DataHubDatasetPanel`)
  - 生产任务 (`DataHubJobsPanel`)
  - 质量治理 (`DataQualityPanel` via data-hub quality API)
  - 特征服务 (`DataHubFeaturePanel`)
  - 兼容入口（保留旧模块入口并给出迁移提示）
- Reworked sidebar navigation into product modules:
  - 数据中台 / Research Lab / Strategy Factory / Execution & Risk

17. Research-side data source migration
- Stock Screener now prefers `/data-hub/features/screener` and displays snapshot date.
- Factor Library overview/stats/ranking now prefer `/data-hub/features/factors` and display snapshot version/date.

## Verification Evidence

- `python3 -m py_compile app/services/scheduler_service.py app/db/postgres_db.py app/api/endpoints/data_dev.py` (pass)
- `python3 -m py_compile app/services/batch_import_service.py app/api/endpoints/batch_import.py app/db/postgres_db.py` (pass)
- backend smoke:
  - fundamentals insert/read/search on temp DB (pass)
  - `search_stocks` returns `price/change_percent` correctly from `current_price`
- `npm run lint` (pass)
- `npm run check` (pass)
- `npm run build` (pass)
- `npm run test:e2e` (pass, 2/2)
- `npm run test:e2e` after dual-mode (pass, 2 passed + 3 skipped)
- `scripts/backend-health.sh` (pass)
- `npm run test:e2e:real` with backend on `:8001` (pass, 4/4)
- `npm run test:e2e` latest (pass, 2 passed + 4 skipped)
- `npm run test:e2e:real` with backend test mode (`ENABLE_* = false`) (pass, 4/4)
- `npm run test:e2e:real` with full offline flags (`ENABLE_* = false`, `ENABLE_EXTERNAL_MARKET_FETCH=false`) (pass, 4/4)
- `python3 -m py_compile app/api/endpoints/data_dev.py app/api/endpoints/database.py` (pass)
- `npm run lint` (pass, latest)
- `npm run check` (pass, latest)
- `npm run test:e2e:real` after deep assertions (pass, 7/7)
- `npm run test:e2e` latest (pass, 2 passed + 7 skipped)

## Known Gaps

1. Global system python env may miss transitive deps; backend startup is currently reliable via `backend/venv`.
2. Data module is stable at schema/API level, but large-data performance and long-running job reliability still need prolonged real-run validation.
3. Real-backend suite now covers core data flows, but long-duration reliability under high data volume is still unverified.

## Recommended Next Steps

1. Add deeper real-backend assertions for `market/overview`, `database/query`, and `data-dev` CRUD flows.
2. Use `scripts/backend-health.sh --ping` + `npm run test:e2e:real` in CI/预发 gate.
3. Add integration test for `stocks/search`, `data-dev/tasks`, and `batch-import/historical-data` against a temporary Postgres database.
