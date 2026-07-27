# Progress Log

## BitPro-parity Runtime Evidence (2026-07-27)

1. Expanded the PostgreSQL Watch context from signals and alerts to the complete
   Paper evidence path: orders, trades, positions, risk decisions and runtime
   events, with instance links and bounded coverage counts.
2. Added per-instance Monitor health with heartbeat freshness, last cycle and
   errors, latest equity/drawdown, ledger difference, order/trade/risk counts and
   acceptance/seed/user purpose labels.
3. Separated persisted `source_updated_at` from `response_generated_at`; missing
   financial values stay unavailable while SQL counts remain truthful.
4. Added Watch order/trade/position/risk tables and Monitor strategy-health/risk
   detail panels without adding trading controls or provider requests.
5. Promoted Watch and Monitor in `stockpro-workflow-v1` only after the complete
   runtime evidence model and UI were verified.

Verification:

- Existing PostgreSQL evidence was read without running a Paper cycle or provider
  sync: 3 instances, 3 orders, 2 trades, 2 positions, 12 risk events and 105
  runtime events.
- Real Watch returned `stale` with latest persisted evidence at
  `2026-07-17T02:42:47.409905Z`.
- Real Monitor returned `critical`: two acceptance instances still marked
  running have stale heartbeats from 2024-12-23 and 2025-01-02; the stopped
  acceptance instance remains explicitly stopped.
- Focused backend API tests passed 13/13; focused mocked Playwright verified the
  execution-evidence and per-instance health workspaces.
- `./scripts/check.sh` passed the production build, lint with 7 existing warnings
  and 0 errors, deploy shell syntax, all 287 backend tests and Python compilation.
- Full mocked Playwright passed 33/33 applicable tests; 11 real-backend cases
  remained intentionally skipped without the explicit real-suite environment.

Next Sprint: daily PostgreSQL orchestration, freshness publication and final
cross-page BitPro-parity acceptance without enabling real-broker execution.

## StockPro Agent Tool Interface (2026-07-27)

1. Added the stable `stockpro-mcp-v1` local stdio interface with 20 PostgreSQL-backed read tools and three asynchronous backtest mutation tools.
2. Added PostgreSQL Agent tokens with one-time plaintext return, SHA-256 hash-only storage, administrator list/revoke controls and an in-product Agent access manager.
3. Added R/W scope enforcement, method/path tool allowlisting, mandatory mutation idempotency keys and PostgreSQL authorization/denial audit evidence. W tokens cannot call data synchronization, arbitrary Paper control or unlisted application routes.
4. Exposed A-share capability discovery, health, market evidence, strategy, backtest jobs/results, Paper, Watch, Monitor, Review and Data state without adding provider fetches or synthetic fallbacks.
5. Kept remote MCP and all real-broker diagnostics/mutations absent and explicitly reported `real_broker_available=false`.

Verification:

- Applied local PostgreSQL migrations `202607270003` and `202607270004` for Agent access and Agent-owned backtest jobs; no provider synchronization or historical backfill ran.
- Real Agent HTTP verification: R read `200`, R write `403`, R/W async job `202 -> success`, duplicate idempotency key `409`, out-of-contract data sync `403`, and revoked token `401`.
- Real stdio MCP handshake discovered 23 tools and successfully called `stockpro_capabilities` and `stockpro_health`; all acceptance tokens were revoked and no active token remains.
- Focused backend tests passed 13/13; TypeScript and focused lint passed; Playwright verified the administrator Agent Token manager and R/W evidence.

Next Sprint: close the remaining BitPro parity gaps in daily data orchestration and Paper/Watch/Monitor runtime evidence.

## BitPro-parity Asynchronous Backtest Jobs (2026-07-27)

1. Added PostgreSQL-owned backtest jobs and append-only transition logs with owner role/session, guest invitation usage, request payload, attempt lineage and immutable result linkage.
2. Added bounded local execution with persisted pending/running/cancelling/cancelled/success/failed/interrupted states, progress phases, cooperative cancellation, retry as a new attempt and startup interruption recovery.
3. Bound guest daily, concurrent and date-range quotas to the asynchronous lifecycle while retaining the existing synchronous routes during migration.
4. Replaced browser-blocking Backtest execution with `202` job creation and a polling task console that shows progress, status, errors, incremental logs, stop/retry controls and the sealed result entry.
5. Declared asynchronous jobs and the Backtest workflow stage available only after the PostgreSQL implementation and UI were verified.

Verification:

- Applied the local async-job migration; no provider synchronization or historical backfill ran.
- A real quick acceptance job returned `202/pending`, completed in about 0.6 seconds, persisted 13 phase logs and linked job `4cb5430f-b503-4af8-a458-6d182fdfbb1b` to sealed run `8fe78fc5-147b-45f2-8dfa-2ee73c063071`.
- Focused backend tests passed 6/6; TypeScript and focused lint passed; mocked Playwright verified the persisted task console, job logs and result evidence entry.
- Clean frontend/backend restart completed; ports `4444` and `4445` listened, health returned healthy and startup recovery found no interrupted jobs.

Next Sprint: authenticated `stockpro-mcp-v1` agent interface with capability discovery, read-only research tools and explicitly gated mutations.

## BitPro-parity Access Control (2026-07-27)

1. Added PostgreSQL-backed invitation codes, guest backtest usage and authentication audit evidence. Invitation plaintext is returned once; only its hash is stored.
2. Generalized the authenticated API boundary to administrator and guest principals. Guests can read all authenticated pages, while non-backtest mutations are rejected with `403`.
3. Added date-range, daily-run and concurrent-run quota reservation around all three supported backtest entrypoints. Rejections return `429` before the engine starts; attempts and outcomes remain attributable to the invitation and session.
4. Added guest login, role/permission/session introspection, immediate revocation, administrator invitation management and workflow capability reporting.
5. Added a persistent guest permission banner, frontend mutation gate and visible disabling of known write actions. Read-only explanation and navigation controls remain usable; backtest run controls remain available under quota.
6. Kept `stockpro-mcp-v1`, asynchronous backtest jobs and real-broker execution explicitly outside this Sprint.

Verification:

- Applied local PostgreSQL migrations only; no provider synchronization or historical backfill ran. `/api/health/storage` reported PostgreSQL healthy with all 26 migrations applied.
- Real API verification: guest login/read `200`, data synchronization write `403`, over-range backtest `429`, invitation revoke `200`, and the issued guest token then returned `401`.
- Focused authentication/router tests passed 9/9; TypeScript check passed; lint completed with the existing 7 warnings and 0 errors.
- Playwright verified invitation-prefilled guest login, 390×844 guest Data page, quota banner, disabled data/provider write controls, usable read-only explanation, administrator invitation manager and zero application console errors.
- `./scripts/check.sh` passed production build, lint with 7 existing warnings and 0 errors, deploy shell syntax, all 276 backend tests and Python compilation.

Next Sprint: asynchronous PostgreSQL backtest jobs with status, logs, cancellation, retry and guest concurrency ownership.

## BitPro-parity Workflow Foundation (2026-07-27)

1. Added the authenticated, read-only `stockpro-workflow-v1` capability contract with the canonical Strategy -> Backtest -> Paper -> Watch -> Monitor -> Review stage order.
2. Separated code capability from runtime/data availability and exposed truthful `available`, `partial`, `disabled` and `not_implemented` states for authentication, scheduler, provider access, asynchronous backtests and broker execution.
3. Added one shared lifecycle rail across Strategy, Backtest, AI Lab, Paper, Watch, Monitor and Review. The rail has stable loading/error states and links every stage through the same workflow vocabulary.
4. Renamed the first-level Paper entry to `模拟交易` and permanently labels the current execution scope as `仅模拟盘 / 实盘未接入`; no page shell implies that a real broker is connected.
5. Preserved the A-share domain boundary: calendar/session, long-only, T+1, 100-share lots, price limits, suspension/ST, corporate actions and A-share cost semantics remain explicit.

Verification:

- Clean frontend/backend restart completed; ports `4444` and `4445` listened and `/api/health/health` returned healthy.
- Authenticated `GET /api/workflow/capabilities` returned the six canonical stages, `paper_only`, broker disabled and scheduler disabled; unauthenticated access returned `401`.
- Focused backend contract/router tests passed 4/4 and focused mocked Playwright passed 1/1.
- Authenticated real-backend desktop Strategy and 390×844 Paper checks showed the same lifecycle rail, truthful execution badges and no application console error.
- `./scripts/check.sh` passed production build, lint with 7 existing warnings and 0 errors, deploy shell syntax, 274 backend tests and Python compilation.
- BitPro HTTP health remained available, but the supplied external administrator credentials returned `401`; authenticated BitPro data/action inspection remains pending valid access.

Next Sprint: admin/guest/agent capability-based access and guest backtest quotas.

## Research Workshop Page Hardening — BitPro Backtest Console (2026-07-27)

1. Reworked the Backtest landing page against the local BitPro backtest module: compact instance-console header, create action, mode/status counters, global sorting, list-local search, refresh/compare actions, and dense instance cards with return, Sharpe, drawdown, win rate, trade count, status, detail, and log actions.
2. Moved StockPro's immutable strategy, dataset, Universe, factor, stock-pool, cost-model, protocol, date, capital, benchmark, and parameter inputs into a three-step `strategy -> configuration -> evidence confirmation` wizard instead of exposing one oversized form above the instance list.
3. Preserved StockPro's A-share evidence contract rather than copying BitPro business code: each run keeps snapshot lineage, A-share T+1/lot/limit/suspension execution rules, acceptance/seed labels, missing-value states, comparison eligibility, quick/full distinction, and the existing eight-tab result detail.
4. Kept the parameter matrix in the confirmation step as an optional advanced experiment, while making the ordinary single-run path match BitPro's staged creation flow.
5. Fixed responsive card composition after desktop inspection and converted the wizard to a flex shell with independently scrolling content, so its footer actions remain visible at 390×844.

Verification:

- Clean frontend/backend restart passed; ports `4444` and `4445` listened and `/api/health/health` returned `healthy`.
- `npm run check`, lint, and production build passed.
- Focused mocked Playwright passed 3/3 Backtest workflow and result-detail cases.
- `./scripts/check.sh` passed the production build, lint with 7 existing warnings and 0 errors, deploy shell syntax, 272 backend tests, and Python compilation.
- Authenticated real-backend inspection loaded 11 persisted runs without creating a run or calling a provider.
- Desktop and 390×844 console/wizard screenshots were captured under `output/playwright/`; compact KPI alignment and the fixed mobile wizard footer were visually verified.

Next page: AI Research Lab.

## Dashboard Short-line Evidence Fallback (2026-07-27)

1. Fixed the empty Short-line panel caused by the API discarding every cache older than 36 hours even when a published market-evidence snapshot remained available.
2. The read-only endpoint now prefers a valid realtime cache and otherwise derives eight indicators from the latest sealed all-A snapshot: limit up/down, broken boards, highest board, advancing/declining counts, seal rate, and rise/fall ratio.
3. Historical values carry their snapshot ID, trade date, source, definition, unit, and `sealed_snapshot` state. The Dashboard labels them `历史快照` and never presents them as realtime monitoring.
4. Replaced internal metric/source identifiers with decision-oriented groups and reader-facing TuShare evidence labels. The expanded two-row layout keeps counts, board height, rates, breadth, definitions, and sources visible.

Verification:

- Clean frontend/backend restart passed; both ports listened and `/api/health/health` returned `healthy`.
- The real API returned 8 sealed indicators from snapshot #7 for trade date 2025-01-02.
- Focused backend tests passed 9/9; focused Dashboard browser tests passed 4/4.
- `npm run check` and focused Dashboard lint passed.
- `./scripts/check.sh` passed the production build, lint with 7 warnings and 0 errors, deploy shell syntax, 272 backend tests, and Python compilation.
- Authenticated desktop and 390px browser checks completed with zero console errors and no document-level horizontal overflow.

Next page: Strategy Development.

## Product Goal — BitPro-parity A-share Strategy Lifecycle (2026-07-27)

1. The user confirmed BitPro's strategy module as the complete behavioral and process baseline for StockPro strategy development.
2. The required journey is catalogue/search/filter -> strategy detail -> validation -> immutable create/version iteration -> backtest job and evidence -> Paper eligibility/configuration/lifecycle -> runtime evidence -> monitor/review.
3. StockPro changes the asset-domain adapter only: A-share symbols, boards, calendar/sessions, long-only default, T+1, 100-share lots, price limits, suspension/ST rules, corporate actions, A-share costs and liquidity/capacity controls replace crypto exchange, 24x7, spot/swap, leverage, funding and long/short assumptions.
4. The product specification and active page-hardening contract now make this parity goal testable across Strategy, Backtest, Paper, Monitor and Review. Real broker execution remains outside scope pending a separate contract and explicit authorization.

Verification:

- Read the current BitPro `bitpro-mcp-v1` capabilities and healthy service state, and inspected the live strategy catalogue shape, filters, statuses, version/config metadata and Paper linkage without performing any mutation.
- Documentation-only change; no frontend/backend restart or provider/database write was required.

## Data Integrity Remediation — Read-only Completion (2026-07-27)

1. Page GET paths are PostgreSQL-only and write-free. Removed hidden factor-library seed installation and legacy strategy-version creation from GET endpoints; provider fetches remain behind explicit synchronization actions.
2. Qwen capability is explicit. With no `QWEN_API_KEY`, AI analysis returns `503`, Strategy disables AI generation, and AI Lab distinguishes deterministic templates from AI.
3. Existing Sprint, QA, smoke, fixture and seed assets expose derived `data_purpose` labels without a schema migration. Strategy, Backtest, Pool, Paper and AI research surfaces display those labels.
4. Market auxiliary failures degrade independently. Empty news and calendar caches explain that absence is not evidence of no event; historical market evidence exposes stale freshness.
5. Watch exposes PostgreSQL source time and stale/empty/fresh state. Monitor no longer reports healthy without service-health evidence. Review no longer defaults to a hard-coded trade date.
6. Twenty-two primary read endpoint groups returned `200`; hashes for eleven key research/runtime tables were unchanged before and after the complete real-backend read sweep.

Verification:

- `./scripts/check.sh` passed: production build, lint with 8 warnings and 0 errors, 271 backend tests, and Python compilation.
- Mock browser regression passed 29 application tests with 11 write-oriented real-backend tests skipped; the final cross-page and AI capability checks passed.
- Authenticated read-only browser inspection covered all twelve primary routes with explicit stale, historical, acceptance, not-configured, critical and scheduler-offline states.
- Frontend and backend were cleanly restarted with migration, bootstrap, scheduler, realtime, strategy execution and external market fetch disabled; both ports and backend health passed.
- No migration, provider synchronization, historical backfill, strategy creation, backtest run, Paper mutation or immutable evidence regeneration ran.

Remaining data operation: refreshing the July 16–17 market caches, probing restricted provider endpoints and regenerating current sealed research evidence require explicit approval because they write PostgreSQL and may perform large external synchronization.

## Research Workshop Page Hardening — Market Research (2026-07-27)

1. Reviewed all six Market Research workspaces against the real PostgreSQL-backed snapshot: structure, sectors, sentiment/limit-up, events, calendar, and stock research.
2. Bound the embedded Stock terminal to the selected research trade date. Hot concepts and concept leaders now receive that date, while K-lines are additionally clipped in the browser to prevent a later cache row from leaking into a historical study.
3. In research mode, the displayed price and daily change come from the final two bars at or before the cutoff. Current fundamentals can still provide a security name, but can no longer override historical price evidence.
4. Replaced the ambiguous duplicated date with explicit `研究截止` and `K线至` labels, and normalized internal `SH_600000` identities to public `600000.SH` notation.
5. Market-terminal requests now degrade independently: a fundamentals failure does not blank a usable K-line chart, and a concept-leader failure leaves an honest empty/fallback state.

Verification:

- Clean frontend/backend restart passed; ports `4444` and `4445` listened and `/api/health/health` returned `healthy`.
- `npm run check` and focused Market/Market Research lint passed.
- Focused mocked Playwright passed the six-workspace and historical-cutoff regression.
- `./scripts/check.sh` passed the production build, lint with 7 warnings and 0 errors, deploy shell syntax, 271 backend tests, and Python compilation.
- Full mocked Playwright passed 30/30 application tests; 11 write-capable real-backend tests were skipped as designed.
- Authenticated real-browser inspection showed the 2025-01-02 research snapshot with 485 bars ending on 2025-01-02, zero console errors, and no document-level horizontal overflow.
- Desktop and 390px Stock-terminal screenshots were captured under `output/playwright/`; the mobile document width matched the viewport and exposed no 2026 market row.

Next page: Strategy Development.

## Data Integrity Remediation — Sprint A P0 Truthfulness (2026-07-27)

1. The persistent top bar now consumes explicit stock/index freshness states. Existing July 16-17 caches render stale with their source date instead of the former green available state.
2. Home overview separates response generation time from source update time and no longer invents neutral sentiment `50` or volume ratio `1.0` when evidence is absent.
3. The Market Stock terminal no longer generates an AI prediction, synthetic order book, spread, unsupported timeframe selection or zero price/change fallback. Daily and intraday chart GETs now read PostgreSQL only.
4. Concept-leader page reads return only the stored cache. A cache miss no longer calls a provider or writes a cache row.
5. Pool lists expose the latest successful generation's actual dataset, Universe, factor and market-evidence foreign keys. The page separates current-member evidence from prospective next-generation inputs.
6. Data distinguishes a persisted enabled schedule from the current process runtime. With `ENABLE_SCHEDULER=false`, the effective next run is unavailable and the page states that the configured time will not execute.

Verification:

- Clean scheduler/realtime/strategy/provider-disabled backend startup and frontend restart passed; both local ports and the health endpoint were available.
- Frontend TypeScript check passed after every runtime slice.
- 38 focused backend tests plus 13 subtests passed for market truthfulness, chart/provider-free reads, Pool lineage, schedule runtime state and startup/read-only safety.
- No migration, provider synchronization, historical backfill or immutable-record rewrite ran.

Next slice: finish the page-GET provider boundary and expose provider/runtime availability without enabling synchronization.

## Cross-page Product Copy Cleanup (2026-07-27)

1. Audited every primary routed page and shared strategy detail surface for development notes, internal API labels, database-mechanism explanations, provider-read disclaimers, debug terminology, future-work commentary, and low-value manifest/hash fields.
2. Removed the Strategy implementation-status strip shown in the user screenshot and applied the same product-copy standard to Market, Pools, Factors, Backtest, AI Lab, Paper, Watch, Monitor, Review, Data Center, and shared detail panels.
3. Retained data source, trade date, freshness, simulation mode, stale state, and the no-real-broker warning where they directly affect financial interpretation or action safety.
4. Replaced raw `sealed_pg_snapshot` / `recorded_replay` values with product labels and cleaned the built-in reference strategies without rewriting user-created strategy content.
5. Added cross-route browser assertions that reject the identified implementation-copy patterns and updated affected workflow tests.

Verification:

- Clean frontend/backend restart passed; ports `4444` and `4445` listened and `/api/health/health` returned `healthy`.
- `./scripts/check.sh` passed: frontend production build, lint with 9 existing warnings and 0 errors, deploy shell syntax, 260 backend tests, and Python compilation.
- Full mocked Playwright passed 29 application tests; 11 real-backend tests were skipped by mock mode as designed.
- Authenticated real-browser inspection confirmed the Strategy page no longer renders the screenshot strip or seeded API/framework commentary.
- Desktop and 390px browser snapshots passed with the cleaned built-in strategy names and descriptions.

Next page-hardening slice: Stock Pools.

## Data Integrity Remediation Started (2026-07-27)

1. Expanded the active Research Workshop Page Hardening slice to implement the accepted audit plan across all twelve primary routes.
2. Fixed delivery order: remove misleading presentation first, then harden synchronization boundaries, research evidence, cross-page data states and automated regression coverage.
3. Preserved the existing local-only safety boundary. No provider synchronization, historical backfill, scheduler enablement, migration execution or immutable evidence regeneration is authorized by this implementation step.

Next slice: global market freshness, the Market Stock terminal, Pool evidence binding and Data scheduler runtime truth.

## Research Workshop Page Hardening — Dashboard (2026-07-27)

1. Preserved the current explicit stale/unavailable market states and verified that expired THS, breadth, short-line, and sector caches do not become current signals.
2. Removed the Dashboard `DataPanel` composition that emitted a React missing-key warning and retained the same financial-operator hierarchy with a stable native section header.
3. Hot-sector fund-flow values now say `单位未记录` because the legacy cache stores a raw numeric value without unit metadata; the page no longer invites users to assume yuan, ten-thousand yuan, or hundred-million yuan.

Verification:

- Clean frontend/backend restart passed; both ports listened and `/api/health/health` returned `healthy`.
- `npm run check` and focused `Dashboard.tsx` lint passed.
- Focused mocked Playwright passed 3/3 Dashboard cases.
- Authenticated desktop and 390px browser inspection completed with zero console errors and no page-level horizontal overflow.

Next page: Market Research.

## Research Workshop Page Hardening — Stock Pools (2026-07-27)

1. Split `我的股票池` into a real versioned-rule catalogue instead of showing the condition-builder under every tab. Factor, condition, sector, and event creation retain their own rule inputs.
2. Replaced blind first-item snapshot mixing with compatibility-aware generation binding. Factor pools inherit Dataset/Universe from the sealed factor snapshot; sector/event pools require same-date market evidence.
3. Current member evidence is distinct from the prospective inputs for the next generation. Factor pools no longer display an unrelated market-evidence snapshot.
4. Pool, snapshot, configuration, market-evidence, and member requests degrade independently. A market-evidence failure leaves existing pools inspectable and blocks only affected generation actions.
5. Member symbols render in canonical public notation such as `600519.SH`; expired validity windows are visible instead of looking current.
6. Added truthful loading, member-error, no-generation, empty-catalogue, and empty-snapshot states. Type-specific selectors cannot default to an incompatible rule type.

Verification:

- Clean frontend/backend restart passed; ports `4444` and `4445` listened and `/api/health/health` returned `healthy`.
- `npm run check` and focused `StockPools.tsx` lint passed.
- Focused backend Stock Pool tests passed 27/27.
- Focused mocked Playwright passed 2/2 Stock Pool cases, including a 390px optional-market-evidence failure.
- Authenticated browser inspection covered all six tabs with zero console errors.
- Desktop and 390px screenshots were captured under `output/playwright/`; the mobile page width matched the viewport.

Next page: Dashboard.

## Research Workshop Page Hardening — Factor Research (2026-07-27)

1. Replaced the five equal-width headline cells with three decision-oriented areas: factor asset readiness, evaluation maturity, and the current immutable research batch.
2. Research date, dataset snapshot, historical Universe, and knowledge cutoff now have separate labels. The 2025-01-02 batch is explicitly marked as a historical sample instead of appearing current.
3. Factor library, compute-run, correlation, metric, and value requests now degrade independently; an optional correlation failure no longer blanks usable factor data.
4. Added truthful empty states for factor filters, runs, correlations, and values, plus request-race protection when switching factors.
5. Normalized the public factor-value API symbol format from internal `SH_600030` notation to the documented `600030.SH` notation while preserving invalid stored identities for diagnosis.
6. Reused the shared `@bitpro/ui` status semantics and retained the StockPro financial operator tokens without copying BitPro business layouts.

Verification:

- Clean frontend/backend restart passed; ports `4444` and `4445` listened and `/api/health/health` returned `healthy`.
- `npm run check` passed.
- Focused mocked Playwright passed 2/2 factor-research cases, including optional-correlation failure at 390px.
- Focused backend tests passed 26/26.
- Authenticated real-backend inspection covered all six factor workspaces with zero browser console errors.
- Real factor-value API returned canonical symbols including `600030.SH` and `600519.SH`.
- Desktop and 390px browser screenshots were captured under `output/playwright/`; the mobile document width matched the 390px viewport.
- Repository-wide lint remains blocked by four pre-existing unused-variable errors in `StockPools.tsx` and `Strategy.tsx`; no Factor Research lint error remains.

Next page: Stock Pools.

## Market Research KPI Presentation (2026-07-27)

1. Replaced the six manually styled Market Structure metrics with the shared `@bitpro/ui` `MetricCard` primitive and kept the A-share convention: up/limit-up in red, down/limit-down in green, highest board in amber, and seal rate in blue.
2. Removed the raw English display suffixes (`stocks`, `boards`, `percent`); counts now use compact tabular numbers and the rate retains only `%`.

Verification:

- `npm run check` passed.
- Focused mocked Market Research Playwright coverage passed, including unit-free values and semantic card colour classes.
- `./scripts/check.sh` passed the production build, lint (9 existing warnings, 0 errors), deploy shell syntax, 260 backend tests and Python compilation.
- Authenticated browser inspection covered desktop and 390px mobile layouts with the current published snapshot.

## Persistent Top Market Ticker (2026-07-27)

1. Moved the lazy-page `Suspense` boundary into the `MainLayout` content viewport so route bundle loading no longer replaces the operator shell.
2. Changed the admin guard to validate once when entering the protected workspace instead of returning to `checking` on every pathname or query-string change.
3. Added a browser regression that switches Strategy → Backtest → Paper and proves the top ticker remains the same DOM node while `/api/market/overview` request count stays unchanged.

Verification:

- `npm run check` passed.
- `npm run lint` passed with 9 warnings and 0 errors.
- The focused ticker lifecycle browser test passed.
- Full mocked Playwright passed 28 application tests; 11 write-capable real-backend tests were skipped as designed.

## Snapshot (2026-07-17)

- Sprint: no active sprint; BitPro-style A-share Strategy Workbench completed locally
- Focus: maintain the Strategy → Backtest → Paper operator workflow on immutable PostgreSQL evidence.
- Latest contract: `docs/contracts/active-bitpro-ashare-strategy-workbench.md`
- Delivery boundary: local UI/API/runtime behavior only; no large provider sync, historical backfill or remote deployment.
- Next: user-selected product work; real broker access, production scheduling, large synchronization and remote deployment remain explicitly disabled.

## BitPro-style A-share Strategy Workbench (2026-07-17)

1. Reviewed all BitPro first-level workspaces and translated its reusable operator patterns—instance consoles, layered filters, explicit creation steps, runtime detail and evidence tabs—without copying its business-page code or cryptocurrency fields.
2. Strategy now exposes PG strategy/version provenance, real record and Strategy API v1 counts, a latest-modified time and distinct loading/error/empty states. The editor states the daily, T+1, 100-share, price-limit and suspension boundary.
3. Backtest now exposes its sealed PG and provider-free read boundary, searchable status/mode filters, return/drawdown/Sharpe/time sorting, creation/completion timestamps and Pool evidence. Existing A-share costs, six headline metrics and eight evidence tabs remain intact.
4. Paper is now a Paper-only runtime console with aggregate portfolio KPIs, instance filters, heartbeat SLA degradation, real signals/orders/positions/trades, equity history, cycle replay, capacity limits and complete strategy/dataset/universe/factor/pool/protocol/backtest lineage.
5. The current PG sample proves the stale-state correction: an instance persisted as `running` with its last heartbeat on 2025-01-02 renders `回放心跳陈旧`, while its recorded signals, order, trade, position, equity snapshots and events remain inspectable.
6. No provider sync, backfill, broker connection, remote change or production action was performed.

Verification:

- Cleanly restarted frontend `:4444` and backend `:4445`; both ports listened and `GET /api/health/health` returned `healthy`.
- Authenticated read-only probes returned 2 strategies, 11 backtests (10 success / 1 failed) and 3 Paper instances with 9 signals, 3 orders and 2 trades; the latest Paper trade date is 2025-01-02.
- `npm run check` passed.
- `npm run lint` passed with 9 warnings and 0 errors.
- `npm run test:e2e:mock` passed 27 application tests; 11 write-capable real-backend tests were skipped as designed.
- `./scripts/check.sh` passed the production build, lint, deploy shell syntax, 260 backend tests and Python compilation.

## Daily Publication And Page Integrity (2026-07-17)

1. Hardened the managed daily path so trade calendar, due security master, all auxiliary datasets and Universe evidence must pass their publication gates before daily bars can seal or factors can run. Fixture tests cover open, closed, locked, disabled, already-sealed and partial-failure outcomes.
2. Publication payloads and Data now expose requested/actual source, fallback reason, response hash, availability/cutoff, dataset snapshot, factor status/snapshot and optional market-evidence status. Restricted optional evidence does not invalidate an already sealed core snapshot.
3. Factor and backtest services remain sealed-snapshot-only and provider-free. RankIC now computes Pearson correlation over ranked series, removing the undeclared SciPy runtime dependency without changing Spearman semantics.
4. External market fallback is false by default, so Home/Market cache misses return explicit unavailable states instead of making provider calls. Market cache rows now say `PG 缓存；上游来源未记录` when legacy rows lack provenance.
5. Corrected remaining misleading presentation states: absent highest-board and monthly returns stay unavailable, Monitor does not convert a failed health load into three zero counters, Strategy no longer advertises a fabricated paused count, and AI Lab/Watch/Monitor expose source, state, evidence time and truthful error/empty behavior.
6. Twenty-six authenticated GET dependencies across all twelve first-level pages returned 200 and left SHA-256 fingerprints of 23 PG tables unchanged. Mock browser coverage passed 26 application tests; `./scripts/check.sh` passed build, lint with zero errors, 260 backend tests and Python compilation.

## Read-only Runtime Safety (2026-07-17)

1. Review navigation and date changes now call the observational GET context endpoint. Timeline persistence is restricted to the explicit `重建时间线` POST action, and the UI states that read, rebuild, save and seal have different mutation semantics.
2. Removed catalogue/registry/schedule bootstrap from Data GET paths. Missing daily configuration returns a disabled `configured=false` default without creating a row, and Data distinguishes uninitialized, disabled and failed states.
3. Added one explicit `backend/bootstrap_runtime.py` entrypoint. Default startup now skips migrations, bootstrap, Paper recovery, scheduler, realtime sync and strategy execution; each state is visible in startup logs.
4. Paper recovery only marks genuinely running cycles failed and records one warning per affected instance. A restart with no interrupted cycle emits no event.
5. Six authenticated Data/Review GETs returned 200 while row counts and SHA-256 fingerprints for nine PG tables remained unchanged. Focused backend tests passed 39 tests plus 10 subtests; frontend typecheck and 23 mocked application browser tests passed after a clean scheduler-disabled restart.

## Data Trust Presentation (2026-07-17)

1. Home now loads overview, hot concepts, THS hot rank and short-line cache independently. Module failures are visible, timestamps are evaluated against a 36-hour SLA, stale THS data cannot become a current strong-stock signal and structural zero comparisons are replaced by `未提供可比快照`.
2. Paper keeps persisted runtime state unchanged but applies a 15-minute heartbeat SLA in presentation. Missing or expired recorded-replay heartbeats render as `回放心跳陈旧` with the actual heartbeat time.
3. Review no longer converts an absent context into business zeroes. Load failure leaves six metrics at `--`, uses an explicit failure/empty state, disables inputs and withholds save/seal actions.
4. Data Center reports PG daily-table rows separately from limited coverage samples, exposes partial API-load failures and uses sealed snapshot evidence—not cache-task success—to label research readiness. Missing success and coverage statistics remain unavailable instead of becoming 100% or 0.
5. Added focused mocked browser coverage for all four corrected states and 390px usability. No manual provider probe, historical backfill, Review assemble verification or remote change was performed. The first required backend restart inherited `ENABLE_SCHEDULER=true` and automatically reached one news/realtime-cache schedule boundary; final verification runs with scheduler, realtime sync and strategy execution disabled through process-only overrides.

Verification:

- Cleanly restarted frontend `:4444` and backend `:4445`; both listened and `GET /api/health/health` returned `healthy`.
- `npm run check` and the production build passed.
- `npm run lint` passed with 9 warnings and 0 errors.
- `npm run test:e2e:mock` passed 23 application tests; 11 write-capable real-backend tests were skipped as designed.
- `./scripts/check.sh` passed the frontend checks, deploy shell syntax, 246 backend tests and Python compilation.
- Playwright desktop and 390px inspection confirmed truthful labels and no document-level horizontal overflow. The shared `@bitpro/ui` `DataPanel` still emits a pre-existing React list-key warning.

## Snapshot (2026-07-16)

- Sprint: Financial Operator UI Unification completed locally
- Focus: maintain the accepted A-share research-to-review platform under one BitPro-style dark, dense operator UI contract.
- Active contract: none; latest completed contract is `docs/contracts/active-financial-operator-ui.md`
- Product plan: `docs/ashare-research-roadmap.md`
- Delivery boundary: local Vite `:4444`, FastAPI `:4445` and PostgreSQL only; no remote deployment.

## Financial Operator UI Unification (2026-07-16)

1. Installed the sibling BitPro package as the local `@bitpro/ui` dependency and imported its stylesheet once at the frontend entrypoint. The application root now applies `BitProTheme` to every protected route and the admin login without copying BitPro business-page code.
2. Reworked the shared shell into a 232px dense desktop sidebar, 48px A-share market strip, flattened workflow groups and a compact mobile navigation surface. All 13 business routes expose one shared financial-operator page surface.
3. Unified near-black backgrounds, low-contrast cards, thin borders, blue actions, tabular numeric typography, table density, controls, focus states, scrollbars and responsive spacing through one StockPro theme layer. The configurable red-up/green-down and green-up/red-down schemes now propagate into `@bitpro/ui` tokens.
4. Adopted `DataPanel`, `MetricCard` and `StatusBadge` on the market dashboard and shell. The top strip no longer fabricates fallback index values or a market-open/closed claim: unavailable data renders explicit placeholders and snapshot status.
5. Added route-matrix E2E coverage for `/`, Market, Pools, Factors, Strategy, Backtest, AI Lab, Paper, Watch, Monitor, Review, Data, Data Processing and Admin Login, plus document-overflow and 390px mobile-shell assertions.
6. Preserved existing business APIs and PostgreSQL behavior. The dashboard's established TOP5 fallback remains visible when no hot concept reaches the strong-move threshold.

Verification:

- Cleanly restarted frontend `:4444` and backend `:4445`; both ports listened and `GET /api/health/health` returned `healthy`.
- `npm run check` passed.
- `npm run lint` passed with 9 existing warnings and 0 errors.
- `npm run test:e2e:mock` passed: 18 application tests passed and 11 real-mode tests skipped as designed.
- `./scripts/check.sh` passed: frontend production build, lint, deploy shell syntax, 246 backend tests and Python compilation.
- Desktop and 390px mobile screenshots were inspected; the document had no horizontal overflow.

## Latest Planning Work (2026-07-16)

1. Expanded the BitPro-style hierarchy from 11 to 12 L1 pages by making `/factors` a first-class professional Factor Research workspace.
2. Added the BitPro UI contract: reuse the current dark `MainLayout`, compact operator density, shared tokens/Lucide icons, real-data states and no parallel visual system.
3. Added Sprint 02 for factor definitions/versions, daily DAG calculation, partitioned PG values, diagnostics, schedules and immutable factor snapshots.
4. Shifted strategy, JoinQuant-style backtest, pool, Paper and local acceptance contracts to Sprint 03-07 and reconciled their dependencies/handoffs.
5. Defined plain-Python strategy authoring: strategies implement lifecycle functions only and never require framework, registry, route or restart changes.
6. Defined JoinQuant-style backtest configuration, six core KPI cards, full risk/trading metrics, charts and eight result tabs backed by persisted PG evidence.
7. Defined daily data synchronization by reusing the existing APScheduler at local 17:30: PG advisory lock, trade-calendar gate, incremental dataset order, five-day correction window, quality gate, atomic snapshot publication, retries and factor trigger.
8. Kept factor and backtest reads point-in-time: they consume sealed dataset/factor snapshots and perform no provider calls during execution.
9. Added research-validity controls: `available_at`/`knowledge_cutoff_at`, historical Universe Snapshots, corporate-action reconciliation and source entitlement states.
10. Added protocol-bound factor/backtest evaluation: hypothesis, train/validation/out-of-sample windows, embargo, rejected candidates, capacity evidence and Paper-promotion gates.
11. Added daily-close execution timing, isolated Python worker quotas, and local PostgreSQL backup/restore acceptance targets (RPO <= 24h, RTO <= 2h).
12. Rebased the source contract on a 5,000-credit TuShare account: introduced a module catalogue and entitlement probes; mapped 5,000-credit `limit_list_d`/`kpl_list` to post-close market evidence; explicitly excluded 6,000/8,000-credit THS/DC heat, THS flow and `limit_step` products; and defined a source-labelled market-temperature/ladder workspace for Sprint 05.

## Latest Implementation Work (2026-07-16)

1. Added the TuShare 5,000-credit A-share catalogue (86 endpoints), persisted capability probes/raw pulls and a source-labelled post-close market-evidence snapshot. `limit_list_d`/`kpl_list` are permitted; 6,000/8,000-credit and independently authorized interfaces remain explicit restricted states.
2. Added the local PostgreSQL research-data registry, source-entitlement records, source-fetch audit runs, content-addressed immutable partition rows, blocking quality issues, dataset watermarks and immutable sealed dataset manifests.
3. Corrected new K-line collection to request unadjusted daily bars and record the actual provider (`tushare` or `akshare`) plus an explicit fallback reason. Existing historical cache is intentionally not assumed trustworthy until re-synchronized through this path.
4. Added Data Center views for the 5,000-credit endpoint catalogue, current-account probe result, research datasets, quality-gate state and sealed snapshot list. The UI does not fabricate a usable snapshot when one has not been published.
5. Applied eight additive local migrations. With an authenticated local TuShare account, verified `stock_basic` and `limit_list_d`, synchronized two A-share daily bars for one trading date, sealed a source-labelled immutable PG snapshot, read its frozen rows back through the snapshot API, and confirmed that a sealed manifest rejects mutation. The same controlled date also published TuShare `limit_list_d` U/D/Z and `kpl_list` evidence with a derived 6-board maximum and 58 limit-up count. Sprint 01 remains active: full reference-data normalization and factor/backtest snapshot-only reads are next.
6. Added actual-provider provenance to the data-job API (`actualSource` and `fallbackReason`) and restarted the local backend in test mode. The authenticated local API now reports the two controlled daily-bar job items as actual `tushare` records, with no fallback reason.
7. Added a PG-backed daily-reference schedule and per-date run ledger. The sole managed post-close pipeline uses TuShare `trade_cal`, a PostgreSQL advisory lock, single-date K-line sync, quality-gated snapshot publication and then optional post-close market evidence. The Data page now shows its cron, watermark and latest ledger state; legacy independent daily K-line/evidence timers and the pre-snapshot factor timer are no longer registered.
8. Added normalized `security_master` and `trade_calendar` PG partitions. A real `stock_basic` initial pull persisted 5,865 distinct security identities, including a preserved `T*.SH` retired-code namespace so it cannot overwrite a live code. The first pull correctly failed on that collision, retained a blocking quality record, then succeeded after the canonical-key fix. Daily publication now seals `daily_bars`, `security_master` and `trade_calendar` together when invoked by the managed pipeline.
9. Added documented single-day TuShare normalization for `adj_factor`, `daily_basic`, `suspend_d`, `stk_limit` and four benchmark `index_daily` series. Null valuation facts remain null, a valid empty suspension day can be published, and IPO/no-limit sentinels are represented as `has_price_limit=false` while preserving source values. A real 2025-01-02 run published 5,414 adjustment factors, 5,369 valuation rows, 17 suspension rows, 6,967 price-limit rows and four benchmark bars. It also exposed and corrected the `920xxx.BJ` exchange-suffix precedence bug. Managed job 39 then sealed snapshot 6 with all eight required daily/reference datasets.
10. Completed Sprint 01 with normalized corporate-action availability, an immutable all-A historical universe, generic sealed-snapshot dataset reads and a two-year research baseline. Managed job 40 sealed snapshot 7 with all ten daily/reference datasets plus Universe snapshot 1 (5,336 members). Historical job 41 synchronized 20 established A shares from 2023-01-03 through 2025-01-02; snapshot 8 sealed 9,700 TuShare bars (485 per symbol) with the nine reference datasets. A held PG advisory lock made a concurrent trigger return `locked`, the snapshot-only loader returned all 9,700 rows without a provider adapter, null valuation facts survived serialization, and the manifest hash remained stable across service instances.
11. Completed Sprint 02 with a dynamic `StockPro Factor API v1`, immutable definitions/versions, strict AST capability validation, snapshot-only data access, cross-sectional preprocessing, ten PG-stored reference factors and one post-seal daily scheduler. Dataset snapshot 9 produced ten published runs and sealed factor snapshot 3; repeating the same schedule reused the same run/snapshot hashes.
12. Added append-only forward metric maturity: later sealed dataset snapshots can add 1/5/20-day IC, RankIC, quantile and long-short evidence without changing source values, metrics or factor snapshot hashes. Research promotion now requires a sealed protocol, matching sealed factor snapshot, untouched out-of-sample pass, persisted metrics, selection rationale and rejected variants.
13. Rebuilt `/factors` and `/factors/:factorId` as six BitPro-style PG-backed workspaces for library, runs, single/multi-factor analysis, correlation/exposure and point-in-time values. Desktop and 390px mobile acceptance showed real snapshot/version/cutoff metadata, pending metrics as pending rather than zero, and no browser console errors.
14. Exposed point-in-time sealed factor snapshot value reads, future-maturity evaluation and promotion gates through the unified `/api` router. A real PostgreSQL mutation probe exposed and then fixed a partition-trigger table-name bug; published factor values and sealed manifests now reject updates/deletes at the database layer.
15. Completed Sprint 03 with immutable `stockpro.v1` strategy versions, stable AST validation, an isolated lifecycle worker and one deterministic replay path shared by quick, backtest and Paper Replay modes. The platform injects data, factor, scheduling, order, log and record APIs; a new strategy changes only its Python version row and never a framework registry or route.
16. Added timestamped normalized intents, custom records, replay manifests and persisted runtime failures. PostgreSQL rejects in-place version-content mutation; the worker rejects provider/database/network/filesystem access, unsupported APIs, future/wall-clock access and non-serializable state. Replay requests cannot enlarge versioned CPU/wall/memory/output/log/intent/record quotas.
17. Migrated generated and reference strategies to ordinary `initialize`/`handle_data` code, removed silent fallback execution and integrated save/validate/quick-run evidence into the BitPro-style Strategy page. Factor values are exposed only after their sealed knowledge cutoff, and daily intent timestamps remain explicit for Sprint 04 D+1 matching.
18. Completed Sprint 04 with a deterministic A-share daily broker, D-close to D+1 matching, 100-share lots, T+1 availability, suspension/price-limit handling, corporate-action reconciliation, versioned costs, capacity evidence and 41 persisted JoinQuant-style metrics. Successful runs and their child evidence are immutable in PostgreSQL; undefined metrics retain a null reason.
19. Added explicit historical backtest-reference construction. The accepted local snapshot 10 combines 9,700 unadjusted bars with 9,700 adjustment factors, 9,700 price-limit facts, 60 company-action rows, 731 calendar rows and 485 CSI 300 benchmark bars. Backtests and result pages read the sealed snapshot without provider calls.
20. Rebuilt `/backtest` and `/backtest/:runId` as a BitPro-style research workspace with immutable configuration selectors, exact Python code, quick/full distinction, six KPI cards, eight evidence tabs, 2-8 run comparison and a 1-24-cell parameter matrix. A real 3x2 matrix completed all six cells with 485 daily points per run.
21. Bound promotion to a sealed research protocol and explicit train/validation/out-of-sample evaluations. Full run `50f68690-96a7-4b17-94f8-0c543c442b54` produced 41 metrics with zero capacity/data-quality warnings, no same-day fills and passed all five Paper-eligibility checks; a direct mutation of its metric evidence was rejected by PostgreSQL.
22. Completed Sprint 05 with PG-backed factor, sector, event, screener and manual stock-pool generators. Rules, inputs, ordered members, reasons, evidence, validity and immutable snapshots are versioned; a failed generation remains evidence while an identical input can be retried safely.
23. Consolidated Market into Structure, Sector Rotation, Sentiment/Limit, Events, Calendar and Stock workspaces. The source-aware context exposes 12 KPIs, null-safe market temperature, 1/2/3/4/5+ ladder, limit pools, comparisons, sector missing states and fact/inference evidence references.
24. Added the six-workspace Stock Pools page and direct snapshot-to-experiment handoff. Real snapshots `1`-`3` cover factor (10 members), sector (8) and event (20); experiment `29f03da1-f5b3-40ba-a725-c7111249e521` references snapshot `1` without copying symbols.
25. Completed Sprint 06 with a pinned, restart-safe Paper state machine, exactly-once cycle runner, signal-to-risk-to-fill ledgers, stale-feed entry block, versioned alerts, notification acknowledgement and service health. Factor Snapshot `4` and Pool Snapshot `4` bind qualifying full backtest `ac808202-72da-474e-9336-b075956e0506`.
26. Recorded Paper instance `076c217f-9b5c-4b18-8fb3-fcd2a127a171` across five trading days. The first cycle did not trade, the accepted order filled after its close signal, a repeated cycle was reused, every equity point reconciled at zero and a stale sixth session created a visible data alert. A separate instance proved participation-limit rejection.
27. Rebuilt Paper, Watch and Monitor into separate BitPro-style workspaces with 6/4/5 tabs and shared object links. Added 35 focused service/API checks, mocked operator coverage and a real-backend Paper/Watch/Monitor browser flow.
28. Completed Sprint 07 with immutable daily review records, metrics and cross-object references. The sealed 2025-01-02 review contains 14 ordered items across market, pool, strategy, risk, order, trade and performance, and every reference resolves back to its PostgreSQL source object.
29. Finalized the BitPro-style 12-page hierarchy and added the controlled AI Research Lab. Review now owns five workspaces: Market, Pools, Strategy, Trades and Logs; compatibility routes remain redirects rather than duplicate navigation entries.
30. Added audited local PG backup/restore and local acceptance services. APScheduler registers a daily 02:30 Asia/Shanghai custom-format backup; a disposable restore reconciled dataset, factor, backtest, Paper, review and migration manifests before teardown.
31. Passed one complete nine-drill resilience batch covering provider fallback, last-good retention, stale positions, restart cursor recovery, interrupted jobs, notification failure, disposable migration rollback, backup restore and research-validity gates. Five API p95 measurements all passed: 69.11/7.42/33.21/16.42/11.58 ms against 500/500/500/800/800 ms budgets.
32. Removed the implementation-specific TuShare credit-tier wording from the Data Center product UI. The page now presents interface support, verified access and restricted/independently-authorized states without exposing the configured points baseline as a headline.
33. Corrected post-close market evidence so each all-A snapshot derives rise, fall, flat, red-market ratio and rise/fall ratio from the source-labelled TuShare daily feed. Historical comparisons now select one latest immutable snapshot per trade date, so a same-date correction cannot masquerade as a prior trading day. A rebuilt 2025-01-02 snapshot published 924 rises, 4,383 falls and 60 flat securities alongside the existing limit-up ecology. The local cache still has only one distinct evidence date, so comparison cards remain unavailable until daily orchestration backfills at least 20 trading-day snapshots.

## Latest Verification (2026-07-16)

- Final `./scripts/check.sh` passed: frontend production build, lint with 9 warnings and 0 errors, deploy shell syntax, 242 backend tests and Python compilation.
- Final `cd frontend && npm run test:e2e:mock` passed: 16 application cases passed and 11 real-mode cases skipped as designed.
- Final real-backend Playwright coverage passed after the corrected resolver assertion; the dedicated full flow proved that all 14 sealed review references resolve to their immutable PG objects and the page exposes all five review workspaces plus exactly 12 L1 entries.
- Authenticated local `GET /api/data/jobs` returns actual provider provenance for the controlled TuShare daily-bar sync. The backend is running locally on `:4445` with the scheduler, realtime sync and strategy execution disabled for this validation.
- Authenticated daily-orchestration smoke tests passed: 2025-01-04 exited as `not_trading_day` from TuShare `trade_cal` without a K-line job; the controlled 2025-01-02 two-symbol run created K-line job 37, sealed dataset snapshot 3 and published market evidence.
- The reference-data integration check passed: a controlled 2025-01-02 managed run created K-line job 38 and sealed a three-partition snapshot containing `daily_bars`, `security_master` and `trade_calendar` before publishing market evidence.
- The expanded reference-data integration check passed: managed K-line job 39 sealed snapshot 6 with eight partitions (`daily_bars`, security/calendar, adjustment factors, valuation, suspensions, price limits and benchmark bars). Targeted normalization/snapshot/orchestration tests pass 16/16.
- Sprint 01 final verification passed: `./scripts/check.sh` completed the frontend build, lint (7 existing warnings, 0 errors), shell checks, 39 backend tests and Python compilation; mocked Playwright passed 9 with 5 real-backend cases skipped. `git diff --check` passed. The accepted immutable historical manifest is snapshot 8 with hash `eb606ebd3f7531c39a7acebbaf012ff202c34b20d20f7cfd3f48d194d85c0a49`.
- Sprint 02 final verification passed: `./scripts/check.sh` completed the frontend build, lint (7 existing warnings, 0 errors), shell checks, 51 backend tests and Python compilation. Mocked Playwright passed 10 with 5 real-backend cases skipped. Real PG checks returned 20 point-in-time `momentum_20d` values from sealed factor snapshot 3, rejected a published-value update, and reused the same sealed daily schedule twice.
- Sprint 03 final verification passed: focused Strategy runtime tests passed 27/27; `./scripts/check.sh` completed frontend build, lint (7 existing warnings, 0 errors), shell checks, 78 backend tests and Python compilation. Mocked Playwright passed 11 with 5 real-backend cases skipped; the real-backend/browser suite passed 7/7, including plain-Python save, validation, sealed-snapshot replay, intent inspection and a console-error-free editor. A real reference replay processed 13 events into 11 intents and 11 records; separate real probes confirmed backtest/Paper hash parity, immutable-version rejection and persisted wall-time/memory failures.
- Sprint 04 final verification passed: `./scripts/check.sh` completed frontend build, lint (6 existing warnings, 0 errors), shell checks, 138 backend tests and Python compilation. Mocked Playwright passed 12 with 8 real-mode cases skipped; the dedicated real-PG/browser backtest case passed. API fixtures add 13 contract checks, focused broker/reference/API tests pass 72/72, the full matrix passes 6/6 and real comparison returns two 485-day persisted series.
- Sprint 05 final verification passed: focused market/pool/backtest coverage passed 53/53; mocked Playwright passed 13/13; the dedicated real-PG/browser market-to-pool case passed. Repeated generation/sealing preserved hashes, and PG rejected snapshot/member/rule mutation. The full local check passed with 7 lint warnings and 0 errors.
- Sprint 06 focused verification passed: 35 Paper lifecycle/risk/recovery/API tests, frontend production build, mocked Playwright 14/14 application cases, and the dedicated real-backend execution/observation/health flow. Real PostgreSQL evidence contains six unique cycles, one next-day fill linked to five risk decisions, zero maximum ledger difference, one stale-data alert and one participation rejection.

## Verification Evidence (2026-07-16)

- `git diff --check` passed; roadmap links resolve and all Sprint 00-07 contracts remain in dependency order.
- `./scripts/check.sh` passed after the supplement: frontend build, lint with 7 existing warnings and 0 errors, deploy shell syntax, 17 backend tests and Python compilation.
- No runtime code, PostgreSQL state or remote server changed in this planning slice.

## Snapshot (2026-07-15)

- Sprint: `data-trust-and-snapshots`
- Focus: build source-aware, quality-gated and immutable TuShare/AKShare research datasets before strategy and page consolidation.
- Active contract: `docs/contracts/active-sprint-01-data-trust-and-snapshots.md`
- Product plan: `docs/ashare-research-roadmap.md`

## Latest Planning Work (2026-07-15)

1. Replaced the page-readiness roadmap with an implementation-oriented A-share platform plan.
2. Reworked the target navigation against BitPro's operator-stage hierarchy: 11 L1 pages, L2 page tabs and L3 object details.
3. Kept Market, Strategy, Backtest, Paper, Monitor and Review as stable short routes; added A-share Stock Pools plus Watch and a controlled AI Lab, while keeping real trading hidden.
4. Defined page modules, route migration, source mapping, freshness targets and failure behavior for TuShare and AKShare.
5. Defined the target research lifecycle: data snapshot -> stock-pool snapshot -> strategy version -> experiment -> Paper -> review.
6. Split the roadmap into seven ordered contracts: Sprint 00 completed, Sprint 01 active and Sprint 02-06 planned.
7. Limited the active sprint to dataset provenance, quality and immutable snapshots; unified strategy execution now starts in Sprint 02.
8. Marked the previous parallel and umbrella active contracts as superseded.

## Verification Evidence (2026-07-15)

- Documentation links and referenced current source adapters inspected.
- TuShare/AKShare interface names checked against current official documentation and the existing `tushare_provider.py` adapter.
- `git diff --check` passed after the BitPro-style page hierarchy update.
- All seven Sprint contracts contain status, scope, deliverables, pass/fail acceptance, verification, rollback and handoff sections; only Sprint 01 is Active.
- `./scripts/check.sh` passed: frontend build, lint with 7 existing warnings and 0 errors, deploy shell syntax, 17 backend tests, and Python compilation.
- No runtime code or database state changed in this planning slice.

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

18. Dashboard market metric repair and Top 30 hot sectors
- Fixed Home/Dashboard market cards so missing realtime cache is shown as unavailable instead of being rendered as neutral `50` or `0`.
- `/market/short-line-indices` now filters stale all-zero cache through `MarketService` instead of returning old placeholder rows directly.
- Realtime market-cache sync now falls back from EastMoney/EM spot data to Sina spot data when the local proxy blocks EM, preserving source-aware PG cache behaviour.
- Normalized `SH_`/`SZ_`/`BJ_` stock codes are now handled in market volume split calculations, so Shanghai/Shenzhen/Beijing turnover rows no longer show `0` after a successful sync.
- Dashboard hot sectors now request and render Top 30 instead of the previous small Top 5/8 slice.

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
- `venv/bin/python -m pytest tests/test_market_overview_fast_path.py tests/test_market_cache_sync_fallback.py` (pass, 4/4)
- `npm run build` (pass)
- Manual `/api/data/realtime/sync` after EM proxy failure: stocks 5528, indices 4, short_line 3; `/api/market/overview` returned fresh sentiment, turnover split and breadth.
- Manual `/api/market/hot-concepts?limit=30` returned 30 items.

## Known Gaps

1. Global system python env may miss transitive deps; backend startup is currently reliable via `backend/venv`.
2. Data module is stable at schema/API level, but large-data performance and long-running job reliability still need prolonged real-run validation.
3. Real-backend suite now covers core data flows, but long-duration reliability under high data volume is still unverified.

## Recommended Next Steps

1. Add deeper real-backend assertions for `market/overview`, `database/query`, and `data-dev` CRUD flows.
2. Use `scripts/backend-health.sh --ping` + `npm run test:e2e:real` in CI/预发 gate.
3. Add integration test for `stocks/search`, `data-dev/tasks`, and `batch-import/historical-data` against a temporary Postgres database.
