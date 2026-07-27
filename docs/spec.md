# StockPro Product Spec

## Product Summary

StockPro is a locally operated B/S A-share strategy workstation. It provides research, factor development, strategy development, backtesting, live signal monitoring, paper trading and risk controls for a personal research workspace.

Sprint 09 `readonly-runtime-safety`, Sprint 10 `daily-publication-integrity` and Sprint 11 `bitpro-ashare-strategy-workbench` completed locally on 2026-07-17. The 2026-07-27 BitPro-parity work added workflow discovery, guest access, asynchronous PostgreSQL backtest jobs, the authenticated `stockpro-mcp-v1` Agent interface, complete Paper runtime evidence and a real-backend read-only twelve-page acceptance gate. Large synchronization, enabling the scheduler runtime, production scheduling and remote deployment still require separate explicit approval.

The current authorized delivery environment is local development only: React on `http://localhost:4444`, FastAPI on `http://localhost:4445`, and PostgreSQL through the local `DATABASE_URL`. Remote-server deployment and production-data changes are deferred to a separate explicit contract.

## Users

- Primary user: one owner operating a personal local strategy workstation.
- Future users: small research collaborators, only after a separate permissions contract.

## Core User Journeys

1. Review A-share market structure, concepts, limit-up ladders, money flow, news catalysts, and market sentiment.
2. Define or edit a Python strategy with parameters, versioning, declared data dependencies, and a standard output contract.
3. Run a backtest on Postgres-backed historical data and review return, drawdown, win rate, turnover, trades, and signal quality.
4. Review the current trading day after close, including index breadth, hot sectors, limit-up ladders, risk notes, and next-day plan.
5. Publish a strategy to live monitoring and inspect normalized signals with chart and research context.
6. Convert a signal into a paper order, pass risk checks, and track orders, trades, positions, and cash ledger.
7. Prepare broker adapter configuration in dry-run mode before any real trading integration is enabled.

## Product Priorities

1. Web-first B/S architecture with React + FastAPI + Postgres.
2. A-share-specific research rules: ST, exchange boards, lot size, T+1, limit-up/down, suspension, lunch break, concept rotation, and event catalysts.
3. Auditable strategy lifecycle from development to backtest to signal to order.
4. Local-first delivery with reproducible PostgreSQL migrations and checks; deployment is outside the current roadmap.
5. Explicit safety gates before any live trading path.
6. StockPro AI console visual system: fixed dark sidebar, grouped operator navigation, compact bordered cards, and a top market ticker/status bar consistent with the production server reference.

## Research Platform Operating Model

StockPro follows BitPro's operator-stage page hierarchy while adapting it for A-share research. The L1 sidebar contains 12 short, stable entries in workflow order:

1. Research workspace: Home (`/`), Market (`/market`), Stock Pools (`/pools`).
2. Strategy development: Factors (`/factors`), Strategy (`/strategy`), Backtest (`/backtest`), AI Lab (`/ai-lab`).
3. Execution validation: Paper (`/paper`), Watch (`/watch`), Monitor (`/monitor`), Review (`/review`).
4. System: Data (`/data`).

L2 tabs contain related views within one workflow stage; L3 routes or drawers contain object details such as a factor version, strategy version, stock-pool snapshot, backtest run or Paper instance. Market structure, sentiment, news, calendar and data-processing pages are migration surfaces into the matching L2 workspace rather than permanent standalone navigation entries.

Paper, Watch and Monitor remain separate because they represent execution, human observation and system health. A real-trading entry is not displayed or registered until a separate broker contract and safety review are complete.

The required lifecycle is:

1. Synchronize source-aware TuShare/AKShare datasets into Postgres.
2. Validate and freeze an immutable dataset snapshot.
3. Calculate and publish immutable point-in-time factor snapshots.
4. Build a reproducible stock-pool snapshot with reasons and evidence.
5. Create and validate a versioned strategy with declared data/factor dependencies.
6. Run task-based backtest experiments against explicit strategy, factor, pool and dataset versions.
7. Promote a passing strategy version into isolated Paper execution.
8. Audit signals, risk decisions, orders, trades, positions, cash and daily review records.

## BitPro UI Contract

- All routed pages, including admin login, render inside the shared financial operator theme; trading, monitoring, and data-admin surfaces must follow `~/.codex/skills/financial-operator-ui/SKILL.md`.
- Prefer the installed `@bitpro/ui` primitives and theme tokens for generic panels, metrics, and statuses. StockPro owns its business composition and must not copy BitPro business-page source.
- Reuse the existing `MainLayout`, grouped fixed sidebar, top A-share status ticker, dark design tokens and Lucide icons.
- Primary pages are dense operator workspaces: compact title/status, KPI strip, segmented filters, chart/table split panels, drill-down drawers and linkable object details.
- Color, typography, spacing, borders, radii, buttons, status tags and up/down semantics remain consistent across all pages.
- Do not add gradients, marketing hero layouts, decorative oversized cards, emoji icons, placeholder dashboards or a parallel component system.
- All data panels implement loading, empty, stale, error and permission-denied states and expose data date, source/snapshot and version.

## Daily Data Sync Contract

- Reuse the existing APScheduler service with a PG-backed daily schedule; default local run time is 17:30 Asia/Shanghai.
- The job checks `trade_cal`, acquires a PostgreSQL advisory lock, and incrementally fetches the current trade date rather than reloading all history.
- Required order is daily bars, adjustment factors, daily valuation/turnover, suspension, price limits and benchmark indices; security/calendar metadata refreshes only when due.
- TuShare is primary. An allowed AKShare fallback is applied and recorded per whole dataset/date item, never silently mixed by row.
- Data lands in unsealed partitions, passes quality gates, then publishes one atomic dataset snapshot. Partial days cannot trigger factor calculations.
- The last five trading days are reconciled for provider corrections. Corrections produce new partitions/snapshots without mutating sealed history.
- Retries, watermarks, schedules and run state persist in PostgreSQL; startup recovery resumes missed/failed trading dates idempotently.
- Each daily orchestration date has one persisted run ledger with its calendar decision, K-line job, sealed dataset snapshot and optional market-evidence snapshot; the UI reports this ledger rather than inferring completion from a process-local timer.

## Research Validity Contract

- Every research fact has both `trade_date` and `available_at`: `trade_date` is when the market fact occurred, while `available_at` is the earliest simulated time at which StockPro may expose it. Data snapshots additionally pin `knowledge_cutoff_at`.
- A backtest, factor run or pool must bind an immutable universe snapshot: historical listing/ST/suspension/delisting status, symbol/name mapping, industry classification and, where applicable, benchmark constituent history.
- Corporate actions are first-class point-in-time data. Cash dividends, rights issues, splits/consolidations and adjustment factors must reconcile with position quantity, cash and executable unadjusted prices.
- Financial data may be used only from its recorded disclosure/availability time, never merely because its report period is earlier than the simulated date.
- Each data definition records entitlement/use scope, rate/permission state, permitted cache/export behavior and source contract version. Restricted or unlicensed data cannot enter a publishable snapshot.

## Research Protocol And Promotion Contract

- Every promotable factor/strategy experiment references a versioned research protocol: hypothesis, universe, benchmark, train/validation/out-of-sample windows, embargo/gap rule, metrics, costs and rejection criteria.
- Parameter/factor searches persist all candidates, including rejected variants and selection rationale. A candidate selected on a full sample cannot be labelled out-of-sample.
- Promotion to Paper requires a sealed full backtest, an untouched out-of-sample result, liquidity/capacity checks and explicit passing promotion checks. Quick runs and exploratory factor analyses are never promotable evidence.
- The platform presents research status as `exploratory`, `validated`, `rejected` or `paper_eligible`; it must not imply investment suitability.

## Local Recovery Contract

- Local PostgreSQL has a recorded daily backup, a weekly restore rehearsal into a disposable database and a `backup_run` audit record; initial targets are RPO <= 24 hours and RTO <= 2 hours.
- A restore rehearsal must verify snapshot manifests, factor snapshots, backtest evidence and Paper ledgers, not only that PostgreSQL starts.
- Secrets remain outside the repository. Backup artifacts must be access-controlled and excluded from source control.

## Agent Tool Interface Contract

- External Agents discover the stable `stockpro-mcp-v1` contract through the local stdio MCP resource/tool before calling application APIs.
- Agent tokens use `X-StockPro-MCP-Token`, are stored in PostgreSQL as SHA-256 hashes, return plaintext once, and can be revoked immediately from the administrator settings panel or API.
- Scope `R` grants only the listed research, strategy, backtest, Paper, Watch, Monitor, Review and Data reads. Scope `W` grants only the listed asynchronous backtest create/cancel/retry tools.
- Every W call requires a unique `Idempotency-Key`; duplicate keys are rejected before the underlying mutation. Method/path allowlisting prevents a W token from guessing data-sync, strategy mutation, Paper control or other application routes.
- Agent reads preserve the same data source, freshness, snapshot, null and missing-reason semantics as the corresponding page APIs. MCP never creates synthetic market data or converts missing values to zero.
- Remote MCP and all real-broker diagnostics/mutations are absent. The capability response reports `real_broker_available=false`.

## Factor Platform Contract

- Factor authors write metadata plus a plain Python `calculate(context, data)` function against `StockPro Factor API v1`; new factors require no framework/route edits or backend restart.
- Factor definitions, code versions, dependencies, lookback, universe snapshot, direction, preprocessing and knowledge cutoff are immutable versioned inputs.
- Daily calculation starts only from a sealed dataset snapshot and publishes long-form PG values plus an immutable `factor_snapshot_id`.
- Forward-return diagnostics mature through append-only evaluation rows against later sealed dataset snapshots; source factor values, source metrics and factor snapshot hashes are never rewritten.
- Diagnostics include coverage/missing/outliers, IC/RankIC/ICIR, Q1-Q5 and long-short returns, turnover, rank autocorrelation/decay, exposures and correlation. Promotable conclusions additionally bind the research protocol and untouched out-of-sample window.
- Strategies and backtests read point-in-time published values by factor snapshot and never recompute factors or call providers during execution.
- `/factors` is a stable L1 workspace for Factor Library, Compute Runs, Single-Factor Analysis, Multi-Factor Analysis, Correlation/Exposure and Factor Values.

## Strategy Authoring Contract

- BitPro's strategy module is the product and workflow baseline for StockPro strategy development. StockPro must preserve the same operator journey and state semantics across strategy catalogue/search/filter, strategy detail, code/config editing, validation, creation or version iteration, backtest job submission and result review, Paper configuration and lifecycle control, runtime evidence, monitoring and review.
- The adaptation boundary is the traded asset, not a separate StockPro workflow. Cryptocurrency exchanges, symbols, 24x7 sessions, spot/swap fields, leverage, funding and long/short assumptions are replaced by A-share security identities, exchange boards, trading calendar and sessions, long-only default, T+1 sellability, 100-share lots, price limits, suspensions, ST/universe rules, corporate actions, commissions, transfer fees, stamp duty and A-share liquidity/capacity controls.
- Equivalent BitPro stages, actions, statuses, filters, task progress, evidence tabs, error/empty states and audit lineage use consistent concepts and interaction order. StockPro may add A-share-only evidence or safety gates, but must not invent a parallel strategy lifecycle where the BitPro module already defines one.
- Strategy creation follows validate -> create immutable version -> backtest -> evidence review -> Paper eligibility -> isolated Paper execution -> monitor/review. Editing an existing strategy creates a child version and preserves the strategy identity and history; it never silently mutates accepted backtest or Paper evidence.
- Backtest and Paper remain distinct lifecycle stages but use the exact accepted strategy version and configuration. Every downstream object keeps the strategy/version, dataset, Universe, factor, pool, protocol and cost-model lineage needed to reproduce it.
- BitPro is a behavioral reference, not a source-copy dependency. Reuse shared `@bitpro/ui` primitives and vocabulary where appropriate, but keep StockPro's A-share domain implementation, API contract and business composition independent.
- Real broker promotion and order submission are not implied by workflow parity. They remain absent until a separate broker contract, safety review and explicit authorization are complete.
- Clients discover lifecycle support through the versioned `stockpro-workflow-v1` capability contract before presenting a stage as usable. Code capability, runtime service state and data availability are separate states.
- The operator shell presents one canonical Strategy -> Backtest -> Paper -> Watch -> Monitor -> Review rail. Until a broker contract is implemented, first-level copy says Paper/模拟交易 and explicitly marks real trading unavailable.

- Strategy authors write ordinary Python functions, following the platform-owned `StockPro Strategy API v1`.
- The minimum strategy implements `initialize(context)` and `handle_data(context, data)`; optional lifecycle functions include `before_trading_start`, `after_trading_end` and `on_strategy_end`.
- Strategy code is stored as immutable versions in `strategy_versions.script_content`.
- Creating or changing a strategy must not require editing framework files, registering a class, adding a route or restarting FastAPI.
- The platform owns data access, simulated clock, scheduling, order APIs, A-share matching, risk, persistence and metrics.
- Backtest and Paper Replay execute the exact same strategy code through the same API version.
- User strategy code cannot directly access TuShare, AKShare, PostgreSQL, filesystem writes, network or broker services.
- The fixed runtime enforces a declared package allowlist plus CPU, wall-time, memory, output/event and log quotas. A timeout/resource violation becomes a persisted failed run; it never falls back to another strategy.
- Every saved version pins `stockpro.v1`, its content hash, dependency manifest and versioned runtime limits; changing code always creates a child row and PostgreSQL rejects in-place content mutation.
- The initial third-party package allowlist is empty; deterministic `math`, safe builtins and platform APIs are injected by the worker. Unsupported calls and wall-clock class methods fail validation before execution.
- A strategy replay reads sealed PostgreSQL dataset/factor snapshots only. Factor values are invisible before the factor snapshot knowledge cutoff and may only be forward-filled after that cutoff.
- Quick, backtest and Paper Replay modes share one isolated event loop and persist event ordinal, simulated timestamp, data-availability timestamp and deterministic hashes for every intent and custom record.

## Backtest Execution-Timing Contract

- A daily-bar strategy receives day D's close only after D's regular session ends. An order created from that event is queued no earlier than the next tradable session on D+1; same-bar close fill is prohibited.
- Every intent/order/fill records `signal_at`, `data_available_at`, `submitted_at`, `earliest_fill_at`, price source and fill/reject reason.
- The initial daily model uses the next executable unadjusted bar price; opening/closing auction participation, intraday execution and order-book queue priority are explicitly unsupported until their own data/model contract exists.
- Adjusted price history may generate a signal, but corporate-action-adjusted position/cash and unadjusted executable price must reconcile before an order can fill.
- Capacity is reported from configured participation/ADV limits and impact assumptions. A run that exceeds its stated capacity cannot pass promotion.

## Backtest Presentation Contract

The Backtest workflow follows JoinQuant's edit -> configure -> quick run -> full backtest model while using StockPro's local PG data and A-share execution rules.

- Core result cards: strategy return, annualized return, benchmark return, excess return, maximum drawdown and Sharpe ratio.
- Full metrics: Alpha, Beta, Sortino, information ratio, strategy/benchmark volatility, excess maximum drawdown, excess Sharpe, win rate, profit/loss ratio, daily win rate, profitable/losing trades, turnover and total cost.
- Result charts: strategy/benchmark/excess cumulative return, drawdown interval, daily returns, monthly heatmap, positions/exposure and attribution.
- Result detail tabs: Overview, Return Analysis, Positions, Trades, Orders, Logs, Code And Params, Attribution.
- Undefined metrics remain `null` with an explanation; they are never replaced with numeric zero.
- Quick backtests are diagnostic only. Only full backtests persist complete PG evidence and may be compared or promoted to Paper.

## Market Data Source Policy

- TuShare is the primary source for stable research datasets: security master, trading calendar, historical bars, adjustment factors, daily valuation data, suspension, price limits, financial statements, index benchmarks and licensed money-flow datasets.
- AKShare supplements datasets without a suitable TuShare shape, including public full-market snapshots, concept/industry boards, hot rankings, limit pools, public news, announcements and dragon-tiger lists.
- Every normalized dataset must preserve source, trade date, collection time, schema version and fallback reason.
- Missing or stale data must remain explicit. APIs and pages must not replace unavailable facts with hard-coded values or numeric zeroes.
- Backtest/factor data is stored in PostgreSQL only. Sprint 01 persists security master, trading calendar, unadjusted daily bars, adjustment factors, daily valuation/turnover, suspension, price limits and benchmark index bars.
- Backtests may only read persisted PG dataset snapshots. They must not trigger external provider calls while an experiment is running.
- Backtests must also bind the applicable universe, corporate-action and research-protocol manifests; `trade_date` alone is insufficient evidence of point-in-time availability.

## TuShare 5,000-Credit Module Contract

- The implementation baseline is a TuShare account with at least 5,000 credits. The Data workspace maintains an endpoint catalogue with module, fields, schedule, storage policy, entitlement state and latest contract-probe result for every admitted endpoint; a failed/unauthorised probe is `restricted` or `unsupported`, never an empty successful dataset.
- The first delivery admits all A-share research endpoints confirmed by the account probe to require no more than 5,000 credits. They are organised as Reference & Calendar, A-share Price & Valuation, Corporate Actions & Financial Disclosure, Index & Industry, Capital Flow & Dragon-Tiger, Limit-up Ecology, Fund/ETF & Convertible Bond, Macro & Cross-market Context, and Research Events. Minute, news, announcement and other individually licensed products remain separate entitlements even when the account has 5,000 credits.
- Confirmed 5,000-credit short-line endpoints are `limit_list_d` and `kpl_list`. `limit_step`, `limit_cpt_list` and `dc_hot` require 8,000 credits; `ths_hot` and the THS money-flow endpoints require 6,000 credits. The platform must expose these as unavailable at this entitlement instead of promising their data.
- Market snapshots retain the actual source and timing. An AkShare fallback is category-wide and explicit. `stock_hot_rank_em` is EastMoney popularity, not a THS ranking; only a real THS endpoint may use a THS label.

## Market Intelligence Contract

- The Market `Sentiment/Limit` workspace is a transparent market-observation product, not a trading signal or black-box investment rating. It presents raw facts and, only when complete, a versioned `market_temperature` built from breadth, limit-up ecology, momentum continuity, loss/risk and liquidity/participation.
- The first-screen KPIs are rising/falling/flat counts, limit-up/down/broken-board counts, sealing rate, highest consecutive board, red-market ratio, rise/fall ratio, new highs and new lows. Every KPI exposes its scope, trade date/capture time, source, freshness and comparison window; unavailable values remain unavailable.
- Limit ecology contains the 1/2/3/4/5+ board ladder, maximum streak, first-board/multi-board counts, broken-board rate, yesterday-limit-up premium and promotion/elimination rates. With 5,000 credits the ladder is derived from `limit_list_d` and labelled accordingly; an entitled `limit_step` source may later supersede it without changing history.
- Sector/theme views lock one classification system per panel, and show return, breadth, limit-up/ladder participation, leader/laggard and permitted money-flow evidence. They never describe a web-derived flow as exchange-level capital flow.

## Delivery Contracts

The research-platform roadmap is delivered in strict dependency order. Only one contract may be Active at a time.

| Sprint | Contract | Status | Exit capability |
| --- | --- | --- | --- |
| 00 | `sprint-00-product-contract-and-page-hierarchy.md` | Completed | Product boundary, 12-page hierarchy and source policy frozen |
| 01 | `active-sprint-01-data-trust-and-snapshots.md` | Completed | A sealed 20-stock, two-year daily-data snapshot passes quality gates |
| 02 | `sprint-02-factor-store-and-daily-research.md` | Completed | Daily factors publish immutable PG values, diagnostics and snapshots |
| 03 | `sprint-03-stable-python-strategy-runtime.md` | Completed | Plain Python runs unchanged through backtest and Paper Replay |
| 04 | `sprint-04-joinquant-backtest-workbench.md` | Completed | JoinQuant-style local PG backtest results and experiment evidence |
| 05 | `sprint-05-market-stock-pool-loop.md` | Completed | Market evidence becomes an immutable pool snapshot and backtest input |
| 06 | `sprint-06-paper-watch-monitor.md` | Completed | Five-day auditable Paper run across execution, watch and health views |
| 07 | `sprint-07-review-local-acceptance.md` | Completed | Full local research-to-review E2E, resilience drills and final route migration |
| 08 | `active-data-trust-presentation.md` | Completed | Stale, unavailable, replay and research-readiness states cannot masquerade as current facts |
| 09 | `active-readonly-runtime-safety.md` | Active | Page reads and safe local startup cannot mutate runtime or research state |

Sprint 00-08 is complete. Sprint 09 continues the local data-integrity remediation by enforcing read-only page and startup boundaries; it does not expand into broker, deployment, multi-user or commercial-data work.

## Technical Shape

- Frontend: local React + Vite on `http://localhost:4444`.
- Backend: local FastAPI on `http://localhost:4445`.
- Database: local PostgreSQL only, using `DATABASE_URL`.
- Scheduling: the existing backend APScheduler with schedule/run state persisted in PostgreSQL.
- Deployment: explicitly outside Sprint 01-07.
- Electron: optional shell only; not part of the core platform architecture.

## Current Delivery Boundary

- All Sprint 01-07 implementation and verification runs locally.
- PostgreSQL is required for persisted data, strategy versions, backtest inputs and results; SQLite/file fallbacks are not allowed.
- Local migrations must run against a development database that can be recreated independently of any server database.
- Do not SSH to, migrate, deploy or mutate the known remote server during this roadmap.
- Deployment requires a separate approved sprint after local acceptance.

## Current Architecture Notes

The runtime is Postgres-only. New and migrated modules must use Postgres migrations plus repository/adapter methods; do not add local file database fallbacks or versioned API prefixes.

### Paper Runtime Observation And Health

- Watch reads Paper signals, orders, trades, positions, risk decisions, runtime
  events, alerts and stock-pool snapshots from PostgreSQL. It is read-only and
  links each execution or risk record back to its Paper instance.
- Monitor reports health per Paper instance, including lifecycle state,
  heartbeat age, last processed trade date, latest cycle/error, equity, drawdown,
  ledger difference, order/trade counts and rejected risk decisions.
- `source_updated_at` is computed from persisted evidence.
  `response_generated_at` only records API response generation and cannot make
  stale evidence fresh.
- Missing prices, heartbeats, cycles, equity and drawdown remain null. Only
  explicit database counts may be zero.
- A running instance with a missing or older-than-36-hour heartbeat is critical;
  stopped and acceptance/seed records are labelled rather than presented as live.
- Watch and Monitor never expose real-broker controls. Broker integration remains
  subject to a separate contract and safety review.

## Constraints

- Do not commit production secrets, `.env`, database files, private keys, or broker credentials.
- Do not enable live trading by default.
- Any real broker integration requires a separate contract and explicit confirmation.
- Production server changes that create users, databases, or credentials must be performed with auditable scripts and documented commands.

## Non-Goals

- Public SaaS multi-tenancy.
- Team permission model in the first cloud version.
- Kubernetes, Docker Swarm, or blue/green deployment.
- Real broker order submission in the initial PG/B/S migration.

## Acceptance Direction

The primary acceptance flow is: recreate a local PostgreSQL database, run migrations, start FastAPI and Vite, seal reference data/factor snapshots, then complete the local research -> strategy -> backtest -> Paper -> review journey and restart/failure drills. No server deployment is part of this roadmap.

## Page Professionalism Acceptance

Every primary page must expose its role in the A-share workflow, show data readiness for data-driven panels, and either enforce or clearly mark A-share constraints: T+1, 100-share lots, limit-up/down, suspension, ST/universe filtering, cost model, trading sessions, and broker isolation.

## Open Questions

- Which point-in-time fundamental datasets should be admitted after price/volume factors pass acceptance?
- Which broker adapter, if any, should receive a separate post-local-acceptance contract?
