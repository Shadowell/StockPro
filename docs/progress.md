# Progress Log

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
- Updated GitHub Actions deployment to keep main-only SHA-gated deploy and remove SQLite seed/import step.
- Enforced PG-only production deploy: `DB_MODE` must be `postgres` and `ENABLE_LEGACY_SQLITE_MODULES` must be `false`.

4. SQLite removed from default production runtime
- Changed backend default `DB_MODE` to `postgres`.
- Added lazy legacy SQLite proxy so importing `app.db.local_db` no longer creates a SQLite database file.
- Gated legacy SQLite API routes behind `ENABLE_LEGACY_SQLITE_MODULES`.
- Gated legacy scheduler/realtime/strategy background services behind `ENABLE_LEGACY_SQLITE_MODULES`.

5. Documentation updated
- Rewrote `docs/deployment.md` for `47.79.36.92:4444`, Postgres `stockpro_prod`, and BitPro-style single-server deployment.
- Updated README environment/deployment notes for `DB_MODE=postgres` and PG-only production.

6. Production server initialized and deployed
- Installed PostgreSQL on `47.79.36.92`.
- Created `stockpro_prod` and `stockpro_app` with a server-local generated password.
- Created root-only `/opt/stockpro/backend/.env` with `DB_MODE=postgres` and legacy SQLite modules disabled.
- Deployed React static frontend + FastAPI backend through Nginx/systemd.
- Moved old `/opt/stockpro/data/stockpro.db` to `/opt/stockpro/legacy-backups/stockpro-sqlite-disabled-20260603120645.bak`.

## Verification Evidence (2026-06-03)

- `python3 -m unittest tests/test_postgres_migrations.py` from `backend/` (pass, 2/2)
- `PYTHONPATH=backend python3 -m unittest backend.tests.test_local_db_lazy` (pass, 1/1)
- `PYTHONPATH=backend python3 -m unittest backend.tests.test_api_router_modes` (pass, 2/2)
- `./scripts/check.sh` (pass: frontend build, frontend lint, deploy shell syntax, backend unit tests 5/5, backend compile)
- Remote deploy: `bash /opt/stockpro/deploy/deploy.sh` (pass, no pending migrations on second deploy)
- Remote health: `curl http://47.79.36.92:4444/api/v1/health/health` (pass)
- Remote storage health: `curl http://47.79.36.92:4444/api/v1/health/storage` (pass: `db_mode=postgres`, `applied_migrations=1`)
- Remote service state: `stockpro-backend` active, `postgresql` active, no `.db`/`.sqlite` files remain under `/opt/stockpro`

## Known Gaps (2026-06-03)

1. Legacy modules still use SQLite-specific services and need phased migration to Postgres repositories before their API routes are re-enabled in production.
2. PG-only production currently exposes health/storage foundations first; existing research/strategy pages will need PG-backed APIs before they are production-functional.
3. IP-only HTTP remains the production entry for now; HTTPS/domain should be added before real broker integration.

## Recommended Next Steps (2026-06-03)

1. Migrate the first research/strategy module from legacy SQLite access to Postgres repositories.
2. Add PG-backed APIs for strategy versions, backtest runs, signals, portfolios, and paper orders.
3. Add HTTPS/domain before broker integration.

---

## Snapshot (2026-05-28)

- Workspace: `/Users/jie.feng/wlb/StockPro`
- Focus: full-stack smoke test, API/page auto-fix, E2E alignment with current 11 routes
- Verification: `./scripts/check.sh`, Playwright real-backend (7/7), mocked pages (2/2), manual API sweep (19/19)

## Latest Completed Work

1. Fixed `/api/v1/stocks/filter` 500 error
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
- Fixed `/api/v1/admin/task-status` 500 by adding missing scheduler methods:
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

- `python3 -m py_compile app/services/scheduler_service.py app/db/local_db.py app/api/endpoints/data_dev.py` (pass)
- `python3 -m py_compile app/services/batch_import_service.py app/api/endpoints/batch_import.py app/db/local_db.py` (pass)
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
3. Add integration test for `stocks/search`, `data-dev/tasks`, and `batch-import/historical-data` with temp SQLite.
