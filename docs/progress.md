# Progress Log

## Concept leaders: visible sync path + em-delayed fallback (2026-08-17)

Problem: 板块龙头 panel always showed「该板块暂无龙头缓存」.
`concept_leaders_cache` had 0 rows — page reads are cache-only by contract,
and the only writer (`realtime_sync_service`, ENABLE_REALTIME_SYNC) is off by
default. Also, this machine's proxy/network blocks the eastmoney realtime
push2 cluster, so even manual syncs returned empty.

1. `POST /market/hot-concept/leaders/sync` (market.py): explicit write path
   syncing one concept (`?name=`) or the hot-concept top N (default 30);
   response reports synced/empty/failed plus the **source used per concept**.
   Page reads stay cache-only.
2. Leader fetch fallback chain: akshare realtime push2 →
   `_fetch_concept_leaders_em_delayed` (searchadapter name→BK-code +
   push2delay clist, direct connection, delayed ~15min, labelled
   `eastmoney-delayed`). Proxy-broken environments still get leaders.
3. Frontend (Market.tsx 板块龙头 panel): empty state gains a
   「同步龙头股」button (spinning state) that triggers the sync endpoint and
   refetches; client.ts adds `syncHotConceptLeaders`.

Verification: live chain via local `:4445` — sync 乳业 returned
`{"synced":["乳业"],"sources":{"乳业":"eastmoney-delayed"}}`; read-back
returns ranked leaders (金健米业 +10.05% …) with `data_status: fresh`;
`npx tsc -b --noEmit` clean. Seeded top-10 hot concepts afterwards.

## Backend performance fixes: PG pool + event-loop unblocking (2026-08-17)

Review-driven fixes, all verified against local `:4445` with real PG.

1. **P0-1 connection pool** (`postgres_db.py`): every query used to open a
   fresh `psycopg2.connect()` through the SSH tunnel. Added a
   `ThreadedConnectionPool` (1–16 conns) behind a `_PooledConnection` proxy
   that keeps both existing styles working: `with db.get_connection() as conn`
   (commit on success / rollback on error / return to pool) and bare
   `conn.close()` (returns to pool). Checkout runs a rollback liveness probe
   and discards tunnel-stale connections (up to 3 attempts). Pool closed on
   app shutdown (`main.py`). Unit tests in
   `backend/tests/test_postgres_connection_pool.py` (7 cases, no real DB).
2. **P0-2 event-loop blocking** (`api/endpoints/data.py`): ~25 async
   endpoints called sync DB/service code inline (quality issues, snapshots,
   daily-bars up to 1M rows, tushare probe/sync, job reads, symbol config,
   heal-missing, schedule runs). All wrapped in `run_in_threadpool` /
   `asyncio.to_thread`. `GET /data/kline/coverage` also stopped issuing the
   heavy coverage query twice per request. `market.py` already wrapped.
3. **P1-1 batch factor sync logs** (`factor_sync_service.py` +
   `postgres_db.save_factor_sync_logs`): success logs for synced factors are
   now one `execute_values` batch instead of one connection per factor ×3
   code paths; `records_count` now uses each factor's own count (was last
   factor's `len(df)` in path 1).
4. **check.sh venv** (`scripts/check.sh`): backend tests/compile now use
   `backend/venv/bin/python` when present, matching README's documented env.

Verification: full backend suite `398 passed, 8 failed` — the 8 failures
reproduce on clean `HEAD` (need real PG credentials / scheduler config), no
new failures. Live checks after restart: `/api/health/health` healthy;
authed `market/overview` 200 (5.3s cold → ~1ms cached), `data/status`,
`data/kline/coverage`, `data/datasets`, `data/sync/jobs` all 200.

Deferred (documented, not fixed): market-overview SQL-side aggregation
(per-exchange price-limit rules would be duplicated in SQL; 30s cache already
bounds cost) and ECharts `echarts/core` on-demand import (6 surfaces, needs
visual QA pass; bundle budget gate already enforces size).

## Data freshness: stop showing 7/7 or 8/7 as latest (2026-08-17)

User saw July 7 / August 7 while today is 2026-08-17. Facts:

1. Trade calendar and research partitions were frozen at **2026-08-07**, so
   `latest_open_date()` and Data Center knowledge cutoff stayed on 8/7.
   `formatFreshnessTime` omitted the year, so 07/07 vs 08/07 was ambiguous.
2. Short-line cache mixed **2026-07-29** 涨停数 with **2026-08-15** 涨跌比 and
   treated the latest stamp as fresh, so homepage ecology looked like July.
3. Review `available_dates` dropped 2026-08-14 (calendar `unknown`) and then
   per-date calendar SQL timed out (~14–25s) →「暂无可用交易日」/ 最近复盘 2025-01-02.

Fixes (no long-term scheduler change; schedule was already enabled, last seal 08-07):

- Published TuShare `trade_cal` 2026-08-08..08-17. Latest complete session is
  **2026-08-14** (today 08-17 is an open day, still in session).
- Lean-inserted full-A daily bars 08-10..08-14; sealed dataset snapshot **23**
  `daily-research-2026-08-14-…`. Market evidence snapshot 21 already 08-14.
- Short-line cache is invalid if **any** row is stale → fall back to sealed
  08-14 evidence. Homepage header shows `证据日 YYYY-MM-DD`. Freshness labels
  include year. Review dates use one calendar query + keep unknown weekdays
  that already have published market evidence.

Verification: `unittest` review / trading-date / short-line cache (28 tests);
`npx tsc -b --noEmit`. After local `:4444`/`:4445` restart, health healthy;
short-line `trade_date=2026-08-14 sealed_snapshot`; desk 证据日 2026-08-14.
Still missing: today 08-17 post-close seal; 08-15 Saturday kline rows exist
but are not a trading day; daily reviews table still only 2025-01-02.

## Operator sidebar visual pass (2026-08-17)

1. Desktop rail is 72px, near-black (`bg-crypto-bg`), hairline `crypto-border`. Group titles no longer render as 8px squeezed labels; groups stay as `role="group"` with `aria-label` and a 1px divider.
2. Nav items are icon + 11px label, aligned; selected state is `crypto-accent` fill + 2px left bar, no glow or hover-scale. `HIDDEN_NAV_IDS` unchanged (因子 / 股票池 / 监控 / 复盘 / AI / 实盘 stay hidden).
3. Logo uses `StockProMark quiet` (no gradient shell). Session badge compact is a single-line dot + label from the existing market-session source. Role footer is muted text, not a colored sticker.
4. E2E desktop width assertion updated from `<= 65` to `70–80`. Did not touch paper read-path or Watch.tsx.

Verification: `npx tsc -b --noEmit` passed (Watch.tsx 本轮未报错). Local `:4444` / `:4445` restarted; both ports listening; `GET /api/health/health` returned healthy. Pushed `f4abf5b` on `main` (menu files only).

## First-screen read speed (2026-08-17)

Root cause: backtest configuration opened 7 Postgres connections and shipped
`script_content`; run list selected `r.*` (~300KB); research-context compared
history with per-snapshot reads (now batched + one connection + 30s cache);
data status scanned all `kline_history` and `COUNT(*)` every table.

Changes:

1. `/backtest/configuration` drops scripts, counts universe members in a
   subquery, reuses one connection, 30s cache.
2. `/backtest/runs` returns list columns only (keeps `metrics` for KPIs).
3. `/market/research-context` reuses one connection and caches 30s. Comparison
   batching from the parallel hang fix is kept.
4. `/data/status` caches 30s, coverage from `sync_metadata` top 80, table
   counts from `pg_stat_user_tables`, and reuses those rows for manager
   status instead of querying coverage twice.
5. Backtest page renders the run list as soon as runs/jobs return; create
   wizard waits for configuration. Page GETs use 8s timeout + no retry
   (research-context keeps its existing timeout).

Verification: `unittest` workbench / research-context / backtest API /
async reads / overview (65) passed. `npx tsc -b --noEmit` passed. Local
`:4444` / `:4445` healthy after restart. Timed reads 2026-08-17:

| API | before | after cold | after warm |
| --- | ---: | ---: | ---: |
| `/backtest/configuration` | 10.1s / 294KB | 2.3s / 52KB | 1ms |
| `/backtest/runs?limit=50` | 1.3s / 301KB | 2.1s / 122KB | — |
| `/market/research-context` | 25s timeout | 3.5s / 64KB | 1ms |
| `/data/status` | 14.3s / 266KB | 6.5s / 47KB | 1ms |
| `/strategy/list` | 2.5s | 1.6s | — |
| `/paper/instances` | 1.2s | 1.3s | — |
| `/market/overview` | 3.2s | 6.1s first after restart | 1ms |

## Operator trunk visibility cut (2026-08-17)

1. Sidebar now shows only the daily trunk: 首页 / 行情 / 策略 / 回测 / 模拟 / 盯盘 / 数据. Admin settings stay at the bottom.
2. Menu-hidden (routes kept): 因子、股票池、监控、复盘、AI研发、实盘、数据处理. Extended the existing `HIDDEN_NAV_IDS` set; did not replace that hide mechanism or restore the research-desk rail.
3. Kept prior hides: homepage has no 量化研究台 panel; `WorkspacePipelineNote` still returns null. Did not change MarketResearch load/API (parallel hang fix owns that path).
4. Page chrome cut: Strategy hides AI 写策略 / 规则生成 / 策略广场 / 审计证据 / AI 研发 tabs. Watch hides 股票池变动 and the audit-scope / Tremor tracker chrome. Login hides 邀请码访客 unless `?invite=` is present. Settings no longer mount GuestCodeManager.

Verification: local `:4444` / `:4445` listening; `/api/health/health` healthy.
Screenshots `/tmp/stockpro-trunk-qa/01-home-sidebar.png`, `02-strategy.png`, `03-backtest.png`:
sidebar text is 研究 首页/行情 · 研发 策略/回测 · 验证 模拟/盯盘 · 系统 数据.
No 因子/股票池/监控/复盘/AI研发/实盘 links. No 量化研究台 / 本页就绪 / 继续盯盘 / AI 写策略 / 策略广场.

## Hide 因子 / 股票池 from primary nav (2026-08-17)

`Navigation.tsx` filters `pools` and `factors` via `HIDDEN_NAV_IDS`; `/pools` and `/factors` routes stay registered.

## Paper read-path speed (2026-08-17)

1. `/paper` dashboard was waiting on three reads: full instance list, 200
   backtest runs, then `get_instance` for the first card. Detail used 14
   Postgres connections (one `_row`/`_rows` each) plus `SELECT *` on
   `strategy_versions` (script) and `backtest_runs`.
2. `get_instance` now uses one connection and one SQL (`json_agg` ledgers),
   omits `script_content`, and returns a slim qualifying backtest. K-line
   history is capped at 800 bars. A first empty-instance read that still
   took ~10s with 12 sequential queries is the reason for the single SQL.
3. `GET /paper/instances` caches 20s and stamps TTL after the query; create /
   start / pause / resume / stop / cycle clear the cache. Dashboard loads the
   list only; create loads eligible runs; detail loads one instance.
4. 10s card poll stays on the dashboard. Did not change Paper lifecycle,
   ledger semantics, or invent missing Sharpe / win-rate fields.

Verification: `unittest` paper runtime service / API 48 passed. Local
`:4444` / `:4445` healthy. Timed reads after the single-SQL change:
list 1.9s → 1ms cache; detail 9.8s → 3.3s (empty instance, no
`script_content`). Dashboard no longer waits on 200 backtests or the
first card's full ledger.

## Operator trunk visibility cut (2026-08-17)

1. Sidebar now shows only the daily trunk: 首页 / 行情 / 策略 / 回测 / 模拟 / 盯盘 / 数据. Admin settings stay at the bottom.
2. Menu-hidden (routes kept): 因子、股票池、监控、复盘、AI研发、实盘、数据处理. Extended the existing `HIDDEN_NAV_IDS` set; did not replace that hide mechanism or restore the research-desk rail.
3. Kept prior hides: homepage has no 量化研究台 panel; `WorkspacePipelineNote` still returns null. Did not change MarketResearch load/API (parallel hang fix owns that path).
4. Page chrome cut: Strategy hides AI 写策略 / 规则生成 / 策略广场 / 审计证据 / AI 研发 tabs. Watch hides 股票池变动 and the audit-scope / Tremor tracker chrome. Login hides 邀请码访客 unless `?invite=` is present. Settings no longer mount GuestCodeManager.

Verification: local `:4444` / `:4445` listening; `/api/health/health` healthy; admin token login.
Screenshots `/tmp/stockpro-trunk-qa/01-home-sidebar.png`, `02-strategy.png`, `03-backtest.png`:
sidebar text is 研究 首页/行情 · 研发 策略/回测 · 验证 模拟/盯盘 · 系统 数据.
No 因子/股票池/监控/复盘/AI研发/实盘 links. No 量化研究台 / 本页就绪 / 继续盯盘 / AI 写策略 / 策略广场.

## Market `/research-context` hang (2026-08-17)

1. `/market` structure/sentiment tabs spun on「读取市场快照…」because
   `GET /api/market/research-context` never returned in time. Health and
   `/api/market/overview` were fine; the research-context path was the stall.
2. Root cause: `MarketResearchService._comparisons` opened a new PostgreSQL
   connection per query, then walked up to 242 history snapshots with
   per-snapshot `sentiment()` plus a `highest_board` `_row` each. Through the
   local DB tunnel that is 240+ round-trips and a 25s+ hang. No fabricated
   quotes; the snapshot existed (evidence date 2026-08-14) but the comparison
   fan-out never finished.
3. Backend now loads comparison history once and batches all comparison
   metrics with `snapshot_id = ANY(...)`. Query count for a long history is
   2 instead of 240+. `research_context` also reuses one PostgreSQL connection
   per request (`_session`) and keeps a 30s in-process cache. Frontend
   `getMarketResearchContext` uses a 20s timeout, does not retry timeouts,
   and the market page shows an honest empty/error panel instead of an
   infinite spinner. Snapshot-less 200s also stop loading. Snapshot load no
   longer waits for `/market/message-stream` (~12s); news fills the events
   tab in the background.
4. Did not touch Dashboard / 量化研究台. The parallel workspace change already
   made `WorkspacePipelineNote` a no-op, so this slice does not restore that rail.

Verification: focused `test_market_research_service` 17/17. Local 4444/4445
restarted; `/api/health/health` 200. Authenticated
`GET /api/market/research-context?market_scope=all_a` returned published
snapshot 21 / 2026-08-14 in 3.9s (second call 1ms cache). Browser login
`admin` then `/market?tab=structure` showed 市场数据快照 + 上涨/涨停真实值
and `/market?tab=sentiment` showed 连板天梯; neither stayed on
「读取市场快照…」. `message-stream` is still ~12s and only fills the events
tab. `twenty_day` / one-year percentile stay unavailable because sealed
history is shorter than 20 days — not fabricated.

## Hide 因子 / 股票池 from primary nav (2026-08-17)

`Navigation.tsx` filters `pools` and `factors` via `HIDDEN_NAV_IDS`; `/pools` and `/factors` routes stay registered.

## Workspace: remove 多因子风险预算 rail (2026-08-17)

1. User screenshot pointed at the shared workspace chrome: title 多因子风险预算,
   green 本页就绪, snapshot/evidence line, 继续盯盘. That is
   `WorkspacePipelineNote`, mounted under almost every workspace header
   (行情 / 股票池 / 因子 / 策略 / 回测 / 模拟 / 盯盘 / 监控 / 复盘 / 数据 /
   AI 研发). It is not the homepage `ResearchDeskPanel`.
2. `WorkspacePipelineNote` now renders nothing. Page mounts stay so this
   change does not touch Dashboard or MarketResearch load/API. Backend
   `GET /workflow/research-desk` and `ResearchDeskContext` stay.
3. `/pools` four-step strip (设定规则 → 筛选成员 → 封存快照 → 送去回测) is
   local to `StockPools.tsx` and remains. `WorkflowRail` was already unused
   in `MainLayout`.

Verification: local `:4444` / `:4445` restarted; login `admin` and open
`/pools`, `/market`, `/strategy` — none show 多因子风险预算 / 本页就绪 /
继续盯盘. Pools still has the four-step strip.

## Homepage: remove 量化研究台 panel (2026-08-17)

1. User asked to take the 量化研究台 command panel off `/` only. The
   homepage is now 市场大盘: indices, pulse, 涨停生态, and sector fund flow.
2. `ResearchDeskPanel` is no longer mounted in `Dashboard.tsx`. The page
   subtitle no longer describes a research-desk overview. Header-to-market
   spacing is unchanged besides dropping the panel wrapper.
3. Kept `GET /workflow/research-desk`, `ResearchDeskPanel.tsx`,
   `ResearchDeskContext`, and the workspace `WorkflowRail` (多因子风险预算 /
   本页就绪). Other pages still use the rail; the panel was not moved.

Verification: local frontend `:4444` and backend `:4445` restarted after the
source change; `/api/health/health` and homepage screenshot confirm the
panel title is gone.

## 20 Daily-Bar 打板 / 隔日T Strategies (2026-08-16)

1. Added 20 Strategy API v1 presets: 8 打板隔日 T, 8 隔日 T, plus 3-day
   reversal / 20-day momentum / MA breakout / low-vol defense. Engine is
   A-share daily T+1. Limit-up is close-to-close ≥ 9.5%, not tick HFT or T+0.
2. Registered and validated all 20 via `POST /api/strategy`. Quick jobs ran
   on dataset 10 / universe 1 / factor 4 / pool 5 (研究20动量池).
3. All 20 quick runs succeeded with real fills. Last-30-session results:

   | 策略 | 成交 | 收益 | 胜率 | run |
   | --- | ---: | ---: | ---: | --- |
   | 窄幅突破 | 94 | +0.25% | 50% | `fa9f6317-…` |
   | 大振幅回归 | 106 | -0.01% | 44% | `a67d8e98-…` |
   | 三日超卖反转 | 102 | -0.10% | 44% | `c99601f0-…` |
   | 二十日动量轮动 | 38 | -0.11% | 50% | `1f26e624-…` |
   | 放量阳线 | 94 | -0.18% | 46% | `426559dc-…` |
   | 均线多头突破 | 78 | -0.23% | 37% | `f4268b83-…` |
   | 低波动防守 | 74 | -1.13% | 50% | `fd2aab00-…` |
   | 跌停反抽 | 110 | -2.41% | 43% | `4e597f82-…` |
   | 首板/连板/高度板/炸板 | 110 | -2.49% | 39% | 大票宇宙涨停稀少，信号退化 |
   | 首板放量 | 110 | -3.08% | 37% | `fc00d0ee-…` |
   | 隔夜高开跟随 | 110 | -3.33% | 35% | `6cb6e4b1-…` |
   | 实体板 / 有空间板 | 110 | -3.53% | 33% | 收盘位置排序接近 |
   | 尾盘强势 | 110 | -3.63% | 31% | `4727cf83-…` |
   | 低开高走 | 110 | -3.88% | 43% | `3e85ea26-…` |
   | 高开高走跟随 | 110 | -4.51% | 41% | `39e45528-…` |
   | 下影线回踩 | 110 | -5.20% | 37% | `bbb85174-…` |

4. Differentiated 首板 / 连板 / 高度板 fallbacks (acceleration / 3-day streak /
   5-day height) and re-queued those three plus 60-day fulls for 窄幅突破、
   大振幅回归、三日反转、二十日动量. Numbers above are sealed quick evidence,
   not forecasts.

Verification: `unittest tests.test_board_t_strategies` passed; `npx tsc -b
--noEmit` passed. Local `:4444` / `:4445` healthy. Open
`http://localhost:4444/backtest/fa9f6317-fcd7-4414-ae54-fee509a97324` or
search 策略页 `打板` / `隔日T`.

## Same-Strategy Loop + Read-Path Speed (2026-08-16)

1. Full replay envelope: quick stays 3s; `backtest`/`paper_replay` now use
   180s wall so the multi-factor strategy can finish a sealed full run.
2. First full job `fb147a66-…` reached persist then died on the SSH tunnel
   (single huge INSERT + per-row trades). Persist now writes orders/trades/
   positions in pages of 50; startup recovery fails orphaned `running` runs.
3. Retry job `208e60d7-…` succeeded. Sealed run
   `490892ac-5528-422d-8810-3b2b4675e96f` on dataset 10 / universe 1 /
   factor 4 / pool 5 / protocol `6f6d3078-…`. Persist finished in ~3 minutes.
4. Promotion is `rejected`: 10/11 gates passed. `CAPACITY_PASS` failed because
   peak single-name weight was 16.97% versus the protocol 12% cap
   (participation 0.08% and capacity warnings 0 were fine). No Paper instance
   was created; the gate was not relaxed.
5. Read-path: research-desk 60s cache; watch context uses a light instance
   list + 20s cache; market overview 30s HTTP cache; strategy list no longer
   ships `script_content`.
6. Decision surfaces: factor page shows 4 pipeline Rank ICs; strategy can
   jump to a bound full-backtest wizard; wizard defaults to 多因子 + 动量池
   instead of the newest incompatible dataset 22; review prefers desk
   evidence date; homepage / rail / desk show evidence cutoffs. Desk and
   workspace notes no longer treat other-strategy Paper as this loop.
7. Watch/overview/desk caches now stamp TTL after the query finishes, so a
   30s+ first read no longer expires the cache before it is stored.

Verification: `unittest` research-desk / runtime / overview / workbench /
router / watch-cache tests passed (54 + 43). `npx tsc -b --noEmit` passed.
Local `:4444` / `:4445` healthy after restart. Timed reads: desk 8.1s → 1ms,
overview 19.0s → 1ms, watch 34.1s → 1ms. Full run
`490892ac-…` is `rejected` on `CAPACITY_PASS` (peak weight 16.97% > 12%).

## Quant Research Desk + Multi-Factor Pipeline (2026-08-16)

1. Main menu stays 12 first-level links and 64px wide, but is grouped into
   研究 / 研发 / 验证 / 系统 so a quant desk can scan the lifecycle.
2. Every workspace now shows a live research-desk rail
   (`数据 → 行情 → 因子 → 股票池 → 策略 → 回测 → 模拟 → 盯盘 → 监控 → 复盘`)
   from `GET /workflow/research-desk`. Counts are read-only SQL; empty stages
   stay empty instead of inventing market or PnL numbers.
3. Homepage keeps 市场大盘 / 市场指数 and adds a 量化研究台 command panel
   for the active strategy, latest backtest, Paper instance and next action.
4. Added Strategy API v1 `多因子风险预算`: weekly cross-section of
   momentum_20d / reversal_3d / volatility_20d / amihud_5d, 12% name cap,
   median-return halt. Factor miss falls back to price momentum.
5. Research-desk queries now share one Postgres connection (was one SSH
   handshake per COUNT). Each workspace page shows a binding note for the
   same strategy, factor set, snapshot and next action.
6. Live desk on 2026-08-16: all 10 stages `available`; strategy id 186
   `多因子风险预算`; quick backtest `e8f0613a-…` success (not paper-eligible);
   4/4 pipeline factors present. Paper/watch/monitor still bind existing
   running instances — no invented PnL.

Verification: `tests.test_research_desk` + workflow/router tests passed;
`npx tsc -b --noEmit` passed; `/api/health/health` and frontend `:4444`
confirmed after local restart. `/workflow/research-desk` returned 200 in
~10s over the tunnel.

## Local Page Empty-State Diagnosis (2026-08-15)

1. Confirmed the workstation was not an empty database: `stockpro_dev` still
   holds K-line history and a 5540-row realtime cache, but the cache stopped
   on 2026-08-07 and page reads never fetch providers
   (`ENABLE_EXTERNAL_MARKET_FETCH=false`).
2. Homepage looked blank because `/api/market/overview` took ~20s over the SSH
   tunnel: `get_all_stocks_realtime()` joined listing-status and a 90-day
   trade-calendar JSON scan. The UI default copy while that request was in
   flight was “全市场实时快照未同步”.
3. Overview now reads quote rows only (`include_listing_status=False`). The
   dashboard shows “正在读取缓存” while loading and no longer hides a stale
   THS hot name. Manual market-evidence sync published snapshot 21 for
   2026-08-14 (63 limit-up / 9 limit-down).

Verification: `unittest` `test_market_overview_fast_path` +
`test_readonly_runtime_contracts` passed (24 tests). Local services restarted
via `./restart.sh`. Overview still ~9s because 5540 rows cross the tunnel;
limit-board/short-line now return the 2026-08-14 sealed snapshot.

## Tremor Operator System Alignment (2026-07-29)

1. Replaced the reintroduced capsule-style workspace buttons with Tremor's
   compact underline tab rail across all shared L2/L3 navigation. Scope,
   status and sort choices remain segmented controls, so navigation no longer
   competes with filters or primary actions.
2. Applied the shared workspace viewport to every routed page through
   `MainLayout`: dense table rhythm, factual card elevation, consistent focus
   treatment, tabular figures and responsive overflow rules now originate from
   one Tremor/BitPro operator surface instead of per-page decoration.
3. Removed the Dashboard's simulated Tremor showcase. The product now uses the
   Tremor components only with API-backed or explicit empty/error data; no
   invented PnL, sector flows, uptime or risk alerts remain on the page.
4. Updated delta badges to respect the configurable A-share red-up/green-down
   setting through semantic `text-up` / `text-down` tokens.

Verification: `./scripts/check.sh` passed (frontend build/lint, 290 backend
tests and Python compilation; 6 pre-existing Hook warnings). Desktop browser
review covered Dashboard and Monitor; 390px review covered Market Research.
The read-only capture sweep covered Dashboard, Market sentiment/structure,
Review, Data Center, Data Processing, Paper and Factor Library: all reported
the operator marker, no page-level horizontal overflow and no blank metric
values.

Known QA gap: the broad historical `npm run test:e2e` suite still hard-codes
superseded page names, sidebar order, button roles and fixture-era snapshot
values. Its 2026-07-29 run had 21 passing tests, 15 stale assertion failures
and 7 interrupted after the run was stopped; it is not a valid release gate
until its product fixtures are reconciled separately.

## Full Navigation & Page Micro-animations Tremor UI Transformation (2026-07-29)

1. **L1 Sidebar Navigation (`Navigation.tsx` / `MainLayout.tsx`)**:
   - Added Tremor Active Accent Indicator Bar (`border-l-2 border-blue-400 bg-blue-500/15 shadow-[0_0_8px_rgba(56,189,248,0.7)]`).
   - Added icon hover scale animation (`group-hover:scale-110`) and `.animate-fade-in-up` page route transition animation.
2. **L2/L3 Tabs & Controls (`WorkspaceTabs.tsx` & `OperatorShell.tsx`)**:
   - Upgraded tabs to Tremor Capsule Pills with blue glow shadow and `active:scale-95` tactile press feedback.
   - Enhanced `CatalogueCard` with 1px hover lift animation (`hover:-translate-y-[1px] hover:border-blue-500/40 hover:shadow-lg hover:shadow-blue-500/5`).
3. **Global Tactile Interactions (`index.css`)**:
   - Injected global button tactile bounce (`active:scale-[0.98] transition-transform`).

Verification: `./scripts/check.sh` clean (build, 0 lint errors, 290 unit tests PASS); services running on :4444 & :4445.

## MarketSession Badge Static Pill & Brand Logo Redesign (2026-07-29)

1. **Removed Breathing Animations & Glowing Pulses**:
   - Cleaned `market-session-breath*` animation keyframes, glow shadows, and expanding ripple elements from `MarketSessionBadge.tsx` and `index.css`.
   - Replaced status badge indicator with clean, non-distracting static solid dots (emerald/amber/sky/slate).
2. **Redesigned StockPro Brand Logo (`frontend/src/components/StockProMark.tsx`)**:
   - Crafted high-end modern quant brand mark featuring:
     - Gradient dark crystal shell with ambient sky-blue glow.
     - Multi-dimensional asset pillar foundation + impulse trend stroke (`#38BDF8` → `#818CF8`).
     - Emerald quant trigger spark point (`#34D399`).

Verification: `./scripts/check.sh` clean (build, 0 lint errors, 290 unit tests PASS); frontend restarted on :4444.

## Full-Site Tremor UI Style Transformation (2026-07-29)

1. **Shared Tremor UI Component Library (`frontend/src/components/TremorUI.tsx`)**:
   - Standardized `TremorCard`, `TremorDeltaBadge`, `TremorTracker`, `TremorBarList`, `TremorCallout`.
2. **Page Refactors & Style Enhancements**:
   - **DataCenter.tsx**: Integrated `TremorBarList` for table storage scale visualization.
   - **Watch.tsx**: Added `TremorDeltaBadge` for signal direction badges and `TremorTracker` for 30-day runtime health monitoring.
   - **FactorLibrary.tsx**: Added `TremorBarList` for factor universe coverage rankings.
   - **TremorShowcasePanel.tsx**: Refactored to import from shared `TremorUI`.

Verification: `./scripts/check.sh` clean (build, lint with 0 errors, deploy syntax, 290 unit tests PASS); services running on :4444 & :4445.

## Workstation Full Menu Audit & Data Self-Healing (2026-07-29)

1. **Full-Menu QA Audit**:
   - Created Playwright end-to-end audit suite `frontend/tests/e2e/full-menu-audit.spec.ts`.
   - Executed deep click testing across all 12 primary navigation menus, 34 L2 tabs, and 18 L3 leaf views with 100% test pass rate (12/12 suites).
2. **Data Self-Healing Infrastructure**:
   - Added backend self-healing endpoint `POST /api/data/heal-missing` (`backend/app/api/endpoints/data.py`).
   - Integrated "一键数据自愈" clinic button and client API binding into Data Center (`frontend/src/pages/DataCenter.tsx`).
3. **Resilience & Fallback Fixes**:
   - Implemented rule-based local analysis fallback generator `_generate_rule_based_fallback` in `AIService` when Qwen API key is unconfigured, avoiding raw 503 errors.
   - Refactored `ChartService` provider fallback and normalized intraday zero-axis `pre_close` logic.

Verification: `./scripts/check.sh` clean (build, lint, deploy syntax, 290 unit tests PASS); Playwright full-menu audit 12/12 PASS; services running healthy on :4444 and :4445.

1. Introduced GitHub high-star Tremor UI Design System visual components for analytics and dashboards into StockPro.
2. Built `TremorShowcasePanel` component (`frontend/src/components/TremorShowcasePanel.tsx`) implementing:
   - Tremor KPI Metric Cards with `TremorDeltaBadge`
   - Tremor Tracker (30-day health status stream bar with tooltips)
   - Tremor BarList (high-density sector money flow ranking bars)
   - Tremor Callout boxes
3. Integrated `TremorShowcasePanel` into `/` (Dashboard page). Fixed `@bitpro/ui` type declarations in `vite-env.d.ts`.

Verification: `npx tsc -b --noEmit` clean; frontend & backend restarted on :4444 and :4445; backend health OK.

## Market Page Refresh Loop + Stale Evidence (2026-07-29)

1. Root cause of「总是刷新」: `RequireAdmin` treated any `/auth/me` failure
   (including uvicorn `--reload` blips) as logout → login redirect loop.
   Now only 401/403 clears the session; network/5xx retries optimistically.
2. Sentiment/structure pages show sealed post-close evidence, not live quotes.
   Latest was stuck at 2026-07-27; published 2026-07-28 evidence snapshot #12.
   UI now shows「证据截止」badge + stale lag banner; date picker no longer
   auto-locks to the sealed day (empty = 最新封存).

## Trading Calendar Capsules (2026-07-29)

1. Empty `market_calendar_events` left `/market?tab=calendar` blank; rebuilt as
   live month grid from TuShare `trade_cal` + `fut_basic` + CNY `eco_cal`.
2. New `GET /market/trading-calendar` tags each day: 开盘/休市、股指交割、
   国债/商品交割、期权窗口、月末/季末、LPR 等重大事项（胶囊样式）。
3. Builder upserts event cache so legacy `/market/calendar` is no longer empty.

Verification: July 2026 API returns 股指交割 on 07-17, LPR on 07-20, 期权交割
on 07-22; `npx tsc --noEmit` OK; services :4444/:4445 healthy.

## Workstation Review + Intraday Fallback (2026-07-29)

1. Full menu/module audit (12 L1 + L2): structure OK, freshness weak.
2. P0: `ChartService.get_intraday_data` falls back to AkShare
   `stock_zh_a_hist_min_em` when `kline_1m` empty (verified 121 bars).
3. Sector fund-flow Sankey labels show 亿元 amounts.
4. Review canvas: stockpro-workstation-review.canvas.tsx.

Open: stale index/short-line/hot-concept caches; broken lianban dates;
monitor critical; intraday pre_close mapping.

## Realtime Order Book (2026-07-29)

1. Probed TuShare: paid `rt_k` needs add-on (current token denied); Pro
   `realtime_quote`/`quote_detail` stubs fail; package
   `get_realtime_quotes` returns live L5 depth (Sina-backed).
2. Added `GET /market/order-book/{symbol}` via TuShare quotes → East Money
   AkShare fallback; volumes normalized to 手.
3. 个股研究右侧挂「五档盘口」并 5s 轮询，保留全市场筛选列表；来源标签诚实展示。

Verification: provider + API smoke on `SH_600519` (茅台五档 OK); `npx tsc --noEmit`
OK; services :4444/:4445 healthy.

## Stock Pools Simplification & Modernization (2026-07-29)

1. Reviewed stock pool architecture and consolidated redundant tabs (`mine`, `screener`, `factor`, `sector`, `event`, `snapshots`) down to 3 focused workspaces:
   - **我的股票池 (`mine`)**: Stock pool rule catalog, status filters, member list, snapshot sealing, and evidence binding.
   - **基础筛选与建池 (`screener`)**: Unified multi-mode screening builder containing mode selectors: 板块选股 (Sector), 事件选股 (Event), 基础条件 (Basic screener), and 因子选股 (Factor).
   - **快照与回测 (`snapshots`)**: Immutable stock pool snapshot repository and one-click backtest draft creation.
2. Modernized `StockPools.tsx` with Financial Operator UI design system & Tremor UI components (`TremorCard`, `TremorCallout`, `TremorBarList`, `TremorDeltaBadge`, `SymbolCell`, `MetricValue`, and `@bitpro/ui` tokens).
3. Verified full test suite via `./scripts/check.sh` (290/290 backend unit tests PASS, frontend build & lint PASS).

## StockPro Mark + Dashboard Session Breath (2026-07-29)

Designed StockPro brand mark as rounded dark shell + single sky pulse stroke
(`StockProMark` + favicon). Homepage header uses prominent「开盘中」badge with
dual-layer breathing light; sidebar/login reuse the same mark.

Verification: `npx tsc --noEmit` OK; frontend restarted on :4444.

## Backtest Evidence Table Typography (2026-07-29)

Aligned backtest detail tables to BitPro role typography: Chinese metric labels
with mono codes, primary values as bold tabular mono with semantic up/down,
units as muted chips, versions/null reasons as low-contrast meta. Tab renamed
`收益分析` → `绩效指标`. Verification: `npx tsc --noEmit` OK; frontend :4444 OK.

## Market Stock Universe Browse (2026-07-29)

1. `GET /stocks/search` empty `q` now returns成交额-sorted browse window from
   `all_stocks_realtime` (limit up to 500); non-empty `q` filters full universe
   by code/name.
2. 个股研究 (`/market?tab=stock` A股模式) loads ~200-stock browse list, dropdown
   search up to 120 hits, and right panel「全市场标的」with independent filter —
   no longer stuck on a single selected symbol / concept leaders.

## Market Terminal Theme Toggle (2026-07-29)

Fixed `/market?tab=stock` 行情终端「A股 / 板块」switch: previously decorative
with no state/`onClick`. Now toggles scope; 板块 mode selects hot concepts,
loads concept intraday + 龙头 list, and can jump back to A-share daily for a
leader.

## Sentiment Tab Tonghuashun Layout (2026-07-29)

1. Removed English unit suffixes (`stocks`/`percent`/`boards`/`ratio`) from
   `/market?tab=sentiment` metric cards; only show `%` / `板` when needed.
2. Rebuilt sentiment workspace to a Tonghuashun-like scan layout: compact KPI
   strip → 连板天梯 (1–5+板 columns with name+code lists) → 涨停/跌停/炸板 pools
   → 晋级/淘汰 queues.
3. Dashboard short-line cards also stop appending English `stocks`.

## Limit Board Charts On Homepage (2026-07-29)

1. Backend `GET /market/limit-board` reads sealed `limit_pool_members`
   (TuShare `limit_list_d`) for full 涨停/跌停名单；无成员时回退 ±9.8% 估计。
2. Dashboard「涨停生态」下增加 `LimitBoardPanel`：涨停/跌停 Tab 全列表，
   点开个股懒加载近 30 日 K + 当日分时（`StockMiniCharts`）。
3. Fixed `getIntradayChart` to unwrap `{ data, pre_close, trade_date }`.

Verification: `npx tsc --noEmit` OK; `GET /market/limit-board` returns
up=111/down=6 for sealed 2026-07-27; e2e
`limit-up and limit-down|realtime market cockpit` 2 passed; services on
:4444/:4445 via screen.

## Market Session Breathing Light (2026-07-29)

1. Backend `MarketService.market_session()` returns A-share phase
   (`pre_open` / `auction` / `open` / `lunch` / `closed` / `weekend`) in
   Asia/Shanghai; `/market/overview` exposes `session_phase` + labels.
2. Frontend `MarketSessionBadge` with CSS breathing light; wired into MainLayout
   sidebar (global), Dashboard header, MarketOverview, SentimentAnalysis.
3. Open = green breath; auction = amber fast; pre/lunch = slow; closed/weekend =
   dim gray breath. Clock ticks every 15s; respects `prefers-reduced-motion`.

## Reference Factor Catalog ×100 (2026-07-29)

1. Added `backend/app/services/reference_factor_catalog.py` with exactly 100
   sealed-snapshot-computable reference factors across momentum / reversal /
   volatility / liquidity / size / value / technical.
2. Selection prioritizes published cross-section hypotheses and spaced lookbacks;
   removed same-window momentum↔reversal mirrors and valuation transform twins.
3. `install_reference_factors` now bumps `version_no` when Python content changes
   (fixes unique constraint on definition+version_no).
4. Obsolete system factors outside the catalog are deprecated; FactorLibrary
   shows a 5-step research workflow strip.
5. Smoke execute on sealed snapshot #10 (20-symbol panel): 100/100 valid;
   mean |Spearman| ≈ 0.31. Full-universe IC maturity still needs daily schedule
   + forward windows — not claimed as live alpha proof from this install alone.

Verification: `pytest tests/test_factor_research_service.py` 12 passed; install
returns 100 system-enabled definitions.

## Homepage Sector Fund-Flow TOP30 (2026-07-28)

1. TuShare 对标：`moneyflow_ind_dc`（东财板块资金流向）、`moneyflow_ind_ths` /
   `moneyflow_cnt_ths`；无板块间真实迁移矩阵，Sankey 连线按流入权重分摊并明示。
2. Backend `GET /market/sector-fund-flow` 从 `hot_concepts_realtime` 组装流入/
   流出/TOP30；龙头同步范围扩到 TOP30 概念。
3. Dashboard 用 `SectorFundFlowPanel`：ECharts Sankey + TOP30 列表 + 点选加载
   `hot-concept/leaders` 核心龙头；去掉原先 |涨幅|<5% 只显示 TOP5 的门槛。

Verification: `npx tsc --noEmit` OK; `GET /market/sector-fund-flow?limit=30`
returns 30 rankings; frontend/backend restarted healthy; e2e
`sector fund-flow|realtime market cockpit|stale market caches` 3 passed.

## Remaining Symbol Chinese Names Sweep (2026-07-28)

1. Backtest detail `GenericTable` 持仓/交易/订单: `SymbolCell` + `useSymbolNames`.
2. Paper legacy `DataTable` symbol columns wired the same way.
3. Paper instance cards「证券范围」and detail K-line `<select>` / empty copy use
   `formatSymbolLabel` (中文名 + 公开代码).
4. MarketResearch sector「龙头」column uses `SymbolCell`; BitPro detail panels
   trade/position/order/strategy-range chips switched to `SymbolCell`.

Verification: `npx tsc --noEmit` passed; frontend/backend restarted healthy.

## Global Symbol Chinese Names (2026-07-28)

1. Rule: numbered A-share codes must render with 中文名 (primary) + public code
   (secondary). Shared `SymbolCell` + `useSymbolNames` + `POST /data/symbol-names`.
2. Backend attaches names via `lookup_symbol_names` on stock-pool members/
   generations/snapshots and factor values.
3. Wired StockPools members table, FactorLibrary values, Market selector,
   MarketResearch limit pools, Strategy detail trading range, Paper positions/
   trades, Watch tables.

Verification: pool members API returns `格力电器` for `SZ_000651`; `tsc` OK;
services healthy.

## Hide Test/Acceptance Scope From Operator UI (2026-07-28)

Removed page-level「测试与验收」scope switches and验收/种子 badges from Paper,
Backtest, Watch, Monitor, AI Lab, Stock Pools, and Strategy. Pages now always
filter to business (`user`) data only; acceptance/seed fixtures stay off the
operator surface. E2E fixtures updated to `data_purpose: 'user'`.

Verification: `npx tsc --noEmit` OK; frontend restarted on :4444.

## Watch Signal Cards + Chinese Symbol Names (2026-07-28)

1. Root cause: `/watch` signals rendered raw `SZ_000651` / `buy ·
   order_target_percent=1.0` as a flat log row; Chinese names already exist in
   PostgreSQL (`lookup_symbol_names`) but were never attached to watch evidence.
2. Backend `watch_context` now resolves `name` on signals/orders/trades/
   positions and returns `symbol_names`.
3. Frontend Watch signals rebuilt to BitPro SignalCenter card rhythm using
   `@bitpro/ui` `DataPanel` + `StatusBadge`: 买入/卖出 semantic color, 中文名 +
   `000651.SZ`, localized reason (`目标仓位 100%`), locale time, instance link.
4. Orders / trades / positions tables use the same Chinese `SymbolCell`.

Verification: backend attaches `SZ_000651→格力电器`; frontend/backend restarted;
`tsc` on changed watch files clean.

## Paper Instance Card Density (2026-07-28)

1. Compacted Paper strategy cards: removed fixed `min-h-[292px]`, tighter padding,
   inline meta/heartbeat row, label+value PnL row instead of stacked hero metrics,
   shorter action labels (暂停/关闭/详情), `h-8` buttons.

Verification: `npx tsc --noEmit` passed; frontend `4444` → 200.

## Data Page Symbol Chinese Names (2026-07-28)

1. Root cause: `/data` 研究数据「数据表统计」丢弃了 coverage 的 `name`，前端只渲染代码。
2. Backend `build_data_manager_table_stats` now keeps `name`; `kline_coverage` enriches
   blank/code-as-name rows via `lookup_symbol_names`; lookup maps digit codes back to
   `SH_/SZ_/BJ_` keys.
3. Frontend shows 中文名 as primary + `600000.SH` public code secondary in table stats
   and coverage matrix; shared `toPublicSymbol` / `resolveSymbolName` helpers added.

Verification: `npx tsc --noEmit` passed; frontend/backend restarted healthy;
`/data` 研究数据「数据表统计」标的列显示中文名 + 公开代码（如 `中科美菱` / `920992.BJ`）。

## Dashboard Market Pulse Cards (2026-07-28)

1. Removed duplicate homepage mini「短线指标」card that echoed the full short-line
   section; sentiment card no longer repeats the full up/down/flat grid.
2. Extended `/market/overview` with `market_pulse` from realtime stock cache:
   rise/fall ratio, median/avg change, ±5%/±7% bands, board-aware limit
   estimates, Top10 amount share, turnover/amplitude/volume-ratio stats.
3. Dashboard adds「大盘诊断」KPI row and「涨停生态」section (breadth metrics
   filtered out of short-line to avoid duplication); index strip now shows
   资金集中度 instead of the duplicate short-line teaser.

Verification: `pytest tests/test_market_overview_fast_path.py` 3/3 OK;
`npx tsc --noEmit` OK; services restarted/health OK; authenticated
`/api/market/overview` returns `market_pulse` on 5533 stocks (e.g. ratio≈0.90,
median≈-0.11%, limit_up_est=80). Note: realtime cache currently stores
turnover/amplitude/volume_ratio as 0, so those pulse fields stay `--` until
the spot sync populates them.

## Market 1Y K-line Backfill Started (2026-07-28)

Triggered `POST /api/data/history/sync-all` job `#46`
(`market-1y-backfill-20260728`): 243 trade days from 2025-07-28→2026-07-28,
`include_signals=false`. Early progress ~19/243 success (~5400 bars/day).

## Leader Strategy Research Top5 (2026-07-28)

1. Clarified research-20 pool: sealed `momentum_20d` Top20 on 2025-01-02, but
   factor coverage was limited to the 20 established large-caps that had a
   sealed 2023–2025 daily-bar history — so it is a research sample, not a live
   full-market leader list.
2. Screened current market leaders from `all_stocks_realtime` (amount / pct
   leaders: AI/光模块/半导体等活跃方向).
3. Created 8 dynamic 龙头 strategies on sealed pool#5 / dataset#10 / factor#4;
   all 8 formal backtests 2023-01-03→2025-01-02 succeeded with positive
   expectancy. Top5 by annualized return:
   - 动量龙头Top1 38.70%
   - 相对强度龙头Top1 38.55%
   - 振幅突破龙头Top1 33.73%
   - 强势近板龙头持5日 25.67%
   - 相对强度三龙头 25.11%

Verification: 8/8 strategy create=`valid`; 8/8 `/api/backtest/runs` success.

## Paper Dashboard False -100% Equity (2026-07-28)

1. Root cause: new Paper instances had no equity snapshot (`equity=null`) while
   cash still equalled initial capital; dashboard used `Number(null)===0`, so
   PnL rendered as `-initial` / `-100%` with zero fills.
2. Fixed `numberValue` null handling, fall back display equity to
   `cash_balance`/`initial_cash`, and coalesce the same in Paper list/detail APIs.

Verification: `tsc --noEmit` OK; API list now returns equity=`1000000` for
cash-only instances; services restarted/health OK.

## Data Module Full-Market Sync + Daily Schedule (2026-07-28)

1. Added date-based full-market daily K-line path: TuShare `daily(trade_date=…)`,
   `KlineSyncService.create_market_daily_sync_job`, and
   `POST /api/data/history/sync-all` (default ~365d + optional market-evidence
   signal backfill).
2. Daily reference orchestration now pulls one market day instead of ~5k
   per-symbol jobs; `force=True` bypasses a disabled PG schedule for recovery.
3. Scheduler catchup walks recent open days (`catchupDays`); local
   `ENABLE_SCHEDULER=true`. Data Center wires 全量下载 / 盘后日终计划 /
   立即运行日终 to `/history/sync-all` and `/schedules/daily`.

Verification: daily-reference unit tests 11/11 OK; `npx tsc --noEmit` OK;
services restarted; `/api/health/health` healthy; schedules/daily shows
`runtimeStatus=running`; smoke `POST /history/sync-all` job#45 (2 trade days)
status=success in ~5s. Full 365d operator download not executed in this session.

## A-share Profitability Strategy Research + Paper Deploy (2026-07-28)

1. Inventoried StockPro HTTP + `stockpro-mcp-v1` tools and TuShare-backed
   sealed datasets (`daily_bars`, valuation, limits, factors, pools).
2. Screened momentum / relative-strength / strong-breakout / volatility-breakout
   / factor-combo logics on sealed research-20 pool; formal full backtests
   2023-01-03→2025-01-02 produced 15 strategies with ann≥20% and positive
   expectancy (win_rate × PL ratio).
3. Promoted and started top-10 Paper instances against dataset#10 /
   factor#4 / universe#1 / pool#5 / protocol `01b64adf-…`.
4. Produced next-session entry zones from latest common bar date 2026-07-16
   (most pool symbols; two banks fresher to 2026-07-27).

Verification: 22 strategy full runs succeeded via `/api/backtest/runs`; 10/10
promotion=`paper_eligible` and Paper `running`. No live broker actions.

## Stock Pool Workbench Clarity (2026-07-28)

1. Clarified product purpose: pools turn screening into reproducible,
   reason-tagged, expiring candidates for backtest handoff.
2. Added workflow strip (建规则 → 生成成员 → 封存快照 → 送回测), KPI row, and
   mine-tab “下一步做什么” coach with contextual actions.
3. Creation tabs lead with type purpose + tip + steps; evidence shows
   `Factor #` / `Market #`; seal message uses `快照 #id`. Kept six `?tab=` keys.

Verification: `npx tsc --noEmit` passed; frontend `4444` → 200; backend health
healthy; browser on `/pools` shows workflow strip + next-action coach;
`/pools?tab=factor` shows type purpose tip and create form.

## Short-line Metric Tone Semantics (2026-07-28)

1. Root cause: Dashboard short-line KPI values were hard-coded `tone="amber"`,
   so 涨停/跌停/上涨/下跌 all rendered yellow.
2. Added `shortLineValueTone(code, value)`: up→red, down→green, broken/highest
   board→amber, seal_rate→blue, rise_fall_ratio by threshold.
3. Tightened DailyReview risk/trade and FactorLibrary summary tones so
   operational counts stay blue/green/red instead of blanket amber.

Verification: live DOM on `/` shows 涨停/上涨 `#FF1744`, 跌停/下跌 `#00C853`,
炸板/最高板 amber, 封板率 blue; `tsc --noEmit` passed.

## Sidebar Nav Color Parity With BitPro (2026-07-28)

1. Matched primary menu to BitPro `MainLayout` nav tokens: idle `text-gray-400`,
   hover `text-gray-200` + `bg-gray-800`, active `text-blue-500` +
   `bg-blue-500/10` — removed white / near-white menu labels.
2. Aligned shell aside to `bg-crypto-card` / `border-crypto-border`; settings /
   logout use the same gray→blue idle/active treatment.
3. Softened `WorkspaceTabs` active label from `text-white` to `text-blue-400`.

Verification: `npx tsc --noEmit` passed; frontend `4444` → 200; backend health
healthy. No backend code change.

## Global White KPI Purge (2026-07-27)

1. Contract: KPI / metric numbers must never use flat white / near-white
   (`text-white`, `text-slate-100`, `@bitpro/ui` `bp-tone-neutral` ≈ `#edf2f8`).
2. Shared guardrails: CSS maps `bp-tone-neutral|gray` → `#93c5fd`;
   `OperatorMetricCard` wraps string/number values in `MetricValue` and remaps
   `neutral` → `blue`; Paper runtime `Metric` defaults to blue tone.
3. Pages/components recolored: Dashboard short-line + index cards, Market price,
   MarketResearch ladder level, DailyReview KPIs, FactorLibrary summary,
   AIResearchLab pipeline counts, SentimentAnalysis StatCard (static tone map),
   AIStockAnalysis scores, DataCenter MetricCards + coverage rows,
   DataQuality/DataHub/BatchImport counts, StockPools member_count,
   BitProDetailPanels price/qty, ChartPanel change color.

Verification: `npx tsc --noEmit` passed; backend `/api/health/health` + frontend
`4444` restart follows. Titles / buttons / names intentionally keep white.

## Market Sentiment KPI Contrast Fix (2026-07-27)

1. Root cause: `MarketResearch` Sentiment tab KPI values were hard-coded
   `text-slate-100` (near-white), so earlier shell/token work never reached
   this grid — matching the user screenshot (涨停/跌停/炸板/连板高度…).
2. Wired Sentiment metrics + pool counts through `MetricValue` with
   up/down/amber/blue tones; Structure headline values now also carry explicit
   tone classes (not only MetricCard inheritance).

Verification: frontend restart `4444` → 200; backend `/api/health/health` → healthy;
`tsc --noEmit` passed; live DOM on `?tab=sentiment` shows KPI colors
`#FF1744` / `#00C853` / amber / blue (no longer near-white).

## BitPro Metric Contrast And Token Alignment (2026-07-27)

1. Matched Tailwind / CSS tokens to BitPro: up `#FF1744`, down `#00C853`,
   accent `#58a6ff`, Inter-first font stack, mono tabular KPI values.
2. Added `MetricValue` / `OperatorMetricCard` and expanded `marketColors`
   helpers (`thresholdTone`, `countTone`) so KPI numbers never default to flat
   white.
3. Recolored Backtest detail KPIs (returns up/down, drawdown adverse, Sharpe
   threshold), Paper/Watch/Monitor/Dashboard/Data counts and PnL, and local
   detail MetricCards to BitPro semantic tones.

Verification: `tsc --noEmit` passed; frontend/backend restart follows.

## BitPro UI Density — Shell Rollout Across Subpages (2026-07-27)

1. Strategy detail now carries `data-operator-page` and an `EvidenceStrip` for
   version / validation / dependency / symbol facts.
2. Backtest dashboard uses shared header + segmented/filter chips; detail uses
   `WorkspaceTabs` for all eight nested report tabs plus an evidence strip.
3. Paper dashboard preferred/all views use `SegmentedControl`; Paper/Watch/
   Monitor/Review/Market/Pools/Factors/AI Lab/Dashboard/Data pages share
   `OperatorPageHeader` and `data-operator-page` markers so every L2 surface
   sits under one shell rhythm.
4. Watch/Monitor scopes moved onto `SegmentedControl` + `EvidenceStrip`.
5. AdminLogin admin/guest modes and `/data/processing` L2/L3 tabs now use the
   shared segmented shell.

Verification:

- `npx tsc --noEmit` passed.
- `git diff --check` clean.
- Clean restart: backend health `healthy`, frontend `4444` → 200.

Next: deepen intra-tab panel/KPI/table density against BitPro `docs/pages/*`
(Backtest wizard + Paper detail modules first). Shell layer for all inventory
routes including AdminLogin and `/data/processing` is in place.

## BitPro UI Density — All Subpages (2026-07-27)

1. Activated `docs/contracts/active-bitpro-ui-density.md` (also mirrored as
   `docs/contracts/active.md`) requiring every L1 **and every L2/L3 surface** to
   match BitPro operator density. Superseded
   `active-research-workshop-page-hardening.md` while retaining its honest
   data-state Done Means.
2. Documented the BitPro read-only reference at
   `/Users/jie.feng/Dev/Github/Private/BitPro` and expanded `docs/spec.md`
   BitPro UI Contract to cover nested tabs, wizards and detail modes.
3. Added shared shell primitives in `frontend/src/components/OperatorShell.tsx`:
   `OperatorPageHeader`, `SegmentedControl`, `FilterChipGroup`,
   `OperatorFilterBar`, `OperatorSearchField`, `EvidenceStrip`,
   `OperatorStatePanel`, `CatalogueCard`.
4. Tightened `WorkspaceTabs` density markers for all URL/`local` L2 tabs.
5. Migrated Strategy centre list surfaces (`我的策略` / `策略广场`, filters,
   loading/empty/error, catalogue cards) onto the shared shell as the template
   page. Editor modal and detail panel remain next within the Strategy batch.

Verification:

- Frontend `tsc --noEmit` passed after Strategy shell migration.
- ESLint on touched files: 0 errors (1 pre-existing hooks warning on Strategy).
- `git diff --check` clean.
- Clean restart: backend `http://127.0.0.1:4445/api/health/health` → healthy;
  frontend `http://127.0.0.1:4444` → 200. No provider sync or Paper cycle ran.

Next batch: Strategy editor/detail polish, then Backtest + Paper (dashboard /
wizard / detail nested tabs / preferred-all), with every listed subpage checked
at desktop and 390px.

## Cross-page Chinese Presentation Cleanup (2026-07-27)

1. Replaced raw market source-map keys, provider table names, snapshot types and
   publication states with concise Chinese business labels.
2. Added shared presentation mappings for runtime status, source, category,
   snapshot type, trade direction and order type; Market, Review, Monitor, Watch,
   Backtest, Factors and Data Hub now reuse them.
3. Normalized ordinary `font-mono` content to the Chinese-first operator font
   stack while retaining tabular numerals; code blocks and editors remain
   monospaced.
4. Removed visible evidence references, content hashes and English snapshot
   abbreviations from the market, factor, stock-pool and backtest workspaces.

Verification:

- Real authenticated desktop and 390px browser inspection confirmed the market
  snapshot renders Chinese source labels and no raw `tushare_*`, evidence-ref,
  content-hash, `Universe`, `DS #` or `U #` strings.
- `./scripts/check.sh` passed production build, lint with 7 existing warnings and
  0 errors, deploy shell syntax, all 289 backend tests and Python compilation.
- Local frontend/backend are listening on `127.0.0.1:4444` and `:4445`; backend
  health reports `healthy`. No remote deployment or provider synchronization ran.

## BitPro-parity Final Local Acceptance (2026-07-27)

1. Re-audited the existing PostgreSQL daily publication chain: persisted cron,
   TuShare trade-calendar gate, advisory lock, required reference partitions,
   Universe, daily bars, immutable dataset snapshot, optional market evidence and
   factor scheduling are already implemented and contract-tested.
2. Added a permanent real-backend read-only browser gate for all twelve primary
   routes. It checks the authenticated document, shared workflow navigation and
   browser runtime without creating or mutating research/runtime objects.
3. Confirmed twelve core read APIs return `200`: workflow, market overview and
   research context, pools, factors, strategy, backtests, Paper, Watch, Monitor,
   Review and the daily Data schedule.
4. Preserved the explicit operations boundary: the PG daily plan is enabled, but
   `ENABLE_SCHEDULER` is false, no APScheduler job is registered and no effective
   next run exists. No provider sync, backfill or Paper cycle was started.

Verification:

- Real 12-page read-only Playwright passed 1/1 with the local administrator.
- Daily plan: configured next run `2026-07-28 17:30 Asia/Shanghai`, runtime
  `runner_offline`, effective next run unavailable, daily-bars watermark
  `2025-01-02`.
- Runtime evidence remains truthful: Watch `stale` with source update
  `2026-07-17T02:42:47.409905Z`; Monitor `critical` with source update
  `2026-07-16T14:15:08.518862Z`.
- `./scripts/check.sh` passed production build, lint with 7 existing warnings and
  0 errors, deploy shell syntax, 287 backend tests and Python compilation.
- Full mock browser regression passed 33/33 applicable tests; 12 write-capable or
  explicit real-suite cases remained skipped by default.

Remaining operator action: enabling the scheduler and any catch-up synchronization
requires explicit approval because it will call providers and write new market
data. Real-broker execution remains outside the approved local scope.

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

19. BitPro twelve-page operator parity
- Replaced the grouped wide sidebar and global ticker with BitPro's compact 64px single-column navigation; every first-level page now owns its title, controls and status context.
- Normalized the twelve menu destinations and their page-owned headers: Home, Market, Stock Pools, Factors, Strategy, Backtest, AI Lab, Paper, Watch, Monitor, Review and Data.
- Reworked Stock Pools into a searchable catalogue with type filters, dense object rows, explicit business empty state and a separate test/acceptance scope.
- Added business/test isolation to Strategy, Backtest, AI Lab, Paper, Watch and Monitor so Sprint, seed and acceptance objects no longer appear as normal business content.
- Propagated `data_purpose` from Paper instances into Watch signals, orders, trades, positions, risk/runtime events and alerts; stock-pool movements receive the same derived purpose label.
- Preserved PostgreSQL snapshot/version evidence and A-share safety rules; no provider sync, Paper runtime cycle, remote deployment or broker operation was triggered.
- Updated browser acceptance for the flat BitPro navigation, page-owned headers and explicit test scopes.
- Increased sidebar contrast after visual review: near-black navigation canvas, stronger inactive labels/icons, a deeper blue selected block and a clear active-edge marker.

20. BitPro subpage parity — Paper and AI research
- Replaced the Paper global-tab landing page with the BitPro object workflow:
  strategy instance dashboard, preferred/all partitions, business/test scope,
  market/strategy/capital/status filters, sorting, dense instance cards, a
  separate creation page and a separate instance-monitor page.
- Added honest Paper card evidence for PnL, return, trade count, symbol scope and
  heartbeat time. Metrics not returned by the Paper API are labelled
  `未计算` with the reason instead of being rendered as zero.
- Reworked AI Research into the BitPro three-workspace structure:
  `AI自主交易`, `新策略研发` and `现有策略优化`.
- Added the four-stage research flow and integrated persisted strategy/backtest
  candidate evidence. Autonomous AI runtime actions stay visibly unavailable
  until StockPro has durable instance, decision-log and hard-risk APIs.
- Retained the existing Strategy and Backtest object flows because they already
  provide catalogue cards, staged creation and record-level detail evidence.

21. BitPro Paper instance monitor and runtime truthfulness
- Replaced the legacy Paper detail tabs with one continuous BitPro-parity
  instance monitor containing all nine KPI slots, strategy logic, parameter
  evidence, runtime diagnostics, positions, trades/events, buy/sell K-line
  review, account curve and risk state.
- Added a read-only Paper K-line endpoint backed by the instance's sealed
  PostgreSQL dataset snapshot, including source, snapshot id, knowledge cutoff
  and explicit empty status.
- Fixed Paper list/detail aggregation so signal/order/trade totals, equity and
  the latest cycle are selected consistently by creation time.
- Fixed historical replay heartbeat semantics: processing heartbeat is current,
  simulated observed time remains in cycle evidence, explicit sealed replay
  can allow entries without being mistaken for a realtime feed, and a successful
  cycle resolves its prior stale-feed alert.
- Native Strategy API v1 creation now also creates/links the catalogue identity,
  so newly authored strategies appear in `/strategy/list`.
- Repaired the existing MA5/20 momentum strategy catalogue link locally and
  validated the running Paper instance against snapshot #10. The target instance
  is fresh with a successful latest cycle; no external sync or broker call ran.
- Moved `AI研发` to the final position in both desktop and mobile primary
  navigation while preserving its route and page behavior.
- Raised the global operator typography contrast for legacy gray/slate text
  tiers, table headers and placeholders, and introduced a Chinese-first
  `SF Pro` / `PingFang SC` system font stack across all primary pages.
- Rebuilt Strategy detail and Paper instance detail on shared `@bitpro/ui`
  primitives. Strategy detail now includes version/validation, snapshot,
  dependency, runtime-limit and read-only source evidence plus lifecycle
  actions; Paper KPI, status and collapsible modules use the same primitives.
- Replaced Paper diagnostic/event entry cards with the shared BitPro terminal
  `LogStream`: one bounded console, stable time/level/message columns, compact
  mobile reflow and explicit empty state.

22. Factor research workspace redesign
- Aligned `/factors` with the spacing and compact tab structure used by the
  market and stock-pool workspaces; removed the oversized summary cards.
- Brought the real 10-factor catalogue into the first viewport with Chinese
  category filters, research hypotheses, selection direction, coverage,
  effectiveness evidence and publication state.
- Replaced engineering-facing hashes and abbreviations with operator labels,
  added a signed correlation heatmap with Chinese factor names, and limited the
  factor-value table to the latest compute run so historical runs do not create
  duplicate securities.
- Reorganized `/data` around an operator-first hierarchy. The default view now
  states whether research data is usable, surfaces only the highest-priority
  blockers and four decision metrics, while research datasets, market
  coverage, sync jobs and provider permissions live in dedicated sections.
- Removed implementation identifiers from the primary Strategy, Paper and Data
  reading layers. UUID fragments, content hashes, snapshot IDs and raw
  `paper_eligible` values are replaced by localized strategy versions,
  verification states, binding states, research periods and data cutoffs.

23. BitPro full-workspace readability and state parity closeout
- Matched the Paper instance-card runtime indicator to BitPro: a running
  strategy now uses a green breathing light. A delayed heartbeat is shown as a
  separate amber warning and no longer turns the running state red.
- Removed the remaining user-facing UUIDs, numeric database keys, task keys,
  snapshot keys, account IDs and content hashes from Watch, Monitor, Backtest,
  Stock Pools, Factors, AI Research, Data and shared detail panels. Internal
  keys remain in routes, API requests and persisted audit records.
- Replaced Monitor's raw dataset and market JSON dumps with readable snapshot
  status, trade date, cutoff, availability and integrity rows. Risk tables now
  identify the related strategy by name instead of a source-object key.
- Localized AI research admission states and version bindings; backtest and
  factor workspaces now describe sealed data and fixed universes without
  presenting database IDs as product versions.
- Completed read-only browser acceptance for all 13 primary routes, 30
  query-addressable secondary tabs, all five factor analysis workspaces,
  Backtest detail and Paper instance detail. Desktop and 390px layouts had no
  page-level horizontal overflow, browser console errors or failed API
  responses.

24. Configurable market-color consistency
- Removed hard-coded red/green gain and loss colors from the active dashboard,
  market research, stock charts, backtest, Paper runtime and shared detail
  components, including legacy routes that can still be reached through
  redirects or embedded panels.
- Routed text, metric cards, candlesticks, volume bars, intraday lines and
  market-flow charts through the persisted `redUpGreenDown` /
  `greenUpRedDown` setting. Zero and missing directional values now use a
  neutral tone instead of being classified as gains.
- Added browser regression coverage that verifies positive, negative and zero
  monthly backtest returns under both color schemes.

25. BitPro workspace navigation hierarchy
- Replaced full-width button-strip navigation with a shared content-width,
  underline-style workspace tab component across Market, Stock Pools, Factors,
  Monitor, Daily Review, Watch, AI Research, Paper detail and Data Center.
- Kept scope, status and sort switches as compact segmented controls so
  workspace navigation and filtering no longer share the same visual weight.
- Localized the remaining AI Research environment and execution labels; raw
  provider configuration names are no longer exposed in the product view.

## Verification Evidence

- `python3 -m py_compile app/services/scheduler_service.py app/db/postgres_db.py app/api/endpoints/data_dev.py` (pass)
- `python3 -m py_compile app/services/batch_import_service.py app/api/endpoints/batch_import.py app/db/postgres_db.py` (pass)
- backend smoke:
  - fundamentals insert/read/search on temp DB (pass)
  - `search_stocks` returns `price/change_percent` correctly from `current_price`
- `npm run lint` (pass)
- `npm run check` (pass)
- `npm run build` (pass)
- `./scripts/check.sh` after full-workspace readability closeout (pass:
  frontend build/lint with 5 existing Hook warnings, 289 backend tests, Python
  compilation)
- `./scripts/check.sh` after configurable market-color consistency (pass:
  frontend build/lint with 5 existing Hook warnings, 289 backend tests, Python
  compilation)
- `./scripts/check.sh` after workspace navigation hierarchy alignment (pass:
  frontend build/lint with 5 existing Hook warnings, 289 backend tests, Python
  compilation)
- Focused mocked Playwright market-color and market-research checks (2/2 pass)
- Real-browser Backtest detail verification under both color schemes: positive
  and negative values swap colors as configured; zero stays neutral (pass)
- Real-browser workspace navigation review on Monitor, Market, Factors, Data
  Center and AI Research at desktop width, plus Monitor at 390px (pass; no
  browser console errors)
- Playwright primary-route sweep at desktop and 390px (13/13 pass; no visible
  UUID/task/account/snapshot keys and no page-level horizontal overflow)
- Playwright secondary/detail sweep (30 query-addressable tabs, 5 factor
  workspaces, Backtest detail and Paper detail pass; no console errors or
  failed API responses)
- `./scripts/check.sh` after BitPro page parity (pass: frontend build/lint, 287 backend tests, Python compilation)
- `backend/venv/bin/python -m pytest tests/test_paper_runtime_api.py` (pass, 13/13)
- Real-backend read-only browser gate for all twelve primary routes (pass, 1/1)
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
- Paper parity focused checks:
  - `venv/bin/python -m pytest tests/test_paper_runtime_api.py -q` (15/15 pass)
  - `/api/paper/instances/{id}` (200, latest cycle success, signal count 1)
  - `/api/paper/instances/{id}/klines/SZ_002415` (200, 485 sealed bars)
  - target strategy visible in `/api/strategy/list`
  - Playwright desktop + 390px viewport pass; no browser console errors
  - Factor research Playwright audit across all six tabs at desktop and 390px
    widths (pass; no browser console errors after clean local restart)

## Known Gaps

1. Global system python env may miss transitive deps; backend startup is currently reliable via `backend/venv`.
2. Data module is stable at schema/API level, but large-data performance and long-running job reliability still need prolonged real-run validation.
3. Real-backend suite now covers core data flows, but long-duration reliability under high data volume is still unverified.

## Recommended Next Steps

1. Add deeper real-backend assertions for `market/overview`, `database/query`, and `data-dev` CRUD flows.
2. Use `scripts/backend-health.sh --ping` + `npm run test:e2e:real` in CI/预发 gate.
3. Add integration test for `stocks/search`, `data-dev/tasks`, and `batch-import/historical-data` against a temporary Postgres database.

## Remote development PostgreSQL cutover (2026-08-10)

- Changed local development startup to use an SSH tunnel to an isolated server PostgreSQL database instead of starting `stockpro-postgres` on the Mac.
- Added explicit tunnel start, stop and status handling with a dedicated SSH control socket and port-conflict checks.
- Kept the Docker PostgreSQL service only behind the opt-in `local-db-recovery` profile with automatic restart disabled; it is no longer part of normal startup.
- Updated the environment example and current architecture/operations documentation. Real credentials remain only in the ignored `backend/.env`.

## Documentation system refresh (2026-07-29)

- Rebuilt `README.md` as the canonical Chinese product introduction, with the current 12-workspace map, evidence-based research lifecycle, local-only Paper boundary, architecture, setup, configuration, verification and documentation links. Updated the English entry and made `README.zh-CN.md` a stable pointer to the canonical Chinese document.
- Added `docs/index.md` as the documentation map. Rewrote the current product specification, user guide, API guide, local operations guide, technical architecture and data architecture around the implemented React/FastAPI/PostgreSQL system.
- Replaced stale StockApp routes, automatic-startup writes, Electron-first architecture and simulated/live-trading claims. Updated frontend, strategy and script usage guides; marked early Electron, optimization, Provider and test notes as historical/reference material.
- Documentation-only change: no frontend/backend source changed, no service restart and no remote deployment were required.
- Verification passed: `git diff --check`; local Markdown link audit checked 61 files with no missing local targets.

## Public documentation boundary cleanup (2026-07-30)

- Removed the private `Private/BitPro/StockPro` directory example, sibling-repository instructions and comparison-project implementation notes from the public README, English README, local operations guide, frontend guide, product specification and architecture overview.
- Removed Codex-oriented maintenance/reference links from the reader-facing documentation index. Internal delivery rules and historical audit records remain in their dedicated project files rather than appearing as product setup guidance.
- Documentation-only change: no application source changed, no service restart and no remote deployment were required. Verification passed: `git diff --check`; reader-facing Markdown scan found no remaining absolute user paths, private directory examples or internal tool instructions.

## MIT license declaration (2026-07-30)

- Added the repository-level standard MIT license with copyright holder `shadowell`, and linked it from the Chinese README, English README and documentation index.
- Clarified that the MIT grant covers repository-owned source code and documentation, while market data, AI services, third-party APIs, dependencies and their outputs retain their own licenses and service/data restrictions.
- Documentation/legal-metadata-only change: no application source changed, no service restart and no remote deployment were required. Verification passed: `git diff --check` and local documentation link validation.

## GitHub Actions deployment recovery (2026-08-01)

- Diagnosed the repeated `Deploy StockPro` failures as two independent faults: the frontend depended on the unavailable sibling path `../../BitPro/packages/bitpro-ui`, then the self-hosted production runner's local PostgreSQL service was stopped while migrations expected `127.0.0.1:5432`.
- Moved the required `@bitpro/ui` primitives into `frontend/packages/bitpro-ui`, changed the npm file dependency to the repository-contained package, and added a dependency-boundary check to prevent future CI builds from referencing files outside StockPro.
- Updated the production deploy script to start local PostgreSQL when required and wait for a real database connection before migrations.
- Local verification passed after a clean frontend/backend restart: `./scripts/check.sh` (frontend build, dependency guard, lint with 6 existing warnings, deploy shell syntax, 290 backend tests and Python compilation) and `git diff --check`.
- GitHub Actions run `30696038264` succeeded for commit `7b831bc630a7f1b395855227c3d9ac2882221803`: frontend build, server deployment and deployed-SHA recording all passed. The workflow log confirmed PostgreSQL, backend and frontend readiness; the public frontend and `/api/health/health` both returned HTTP 200.
- A non-blocking Node cache-save warning remains on the self-hosted runner (`tar` exited while saving the npm cache). It did not fail the job or affect the deployed application and should be handled as runner storage/cache maintenance rather than application rollback.

## Platform professionalization audit baseline (2026-08-09)

- Started the current `StockPro Platform Professionalization` contract and
  established `docs/todo.md` as the single prioritized delivery queue.
- Completed read-only browser coverage of all 12 primary workspaces at 1280px
  and 390px, all URL-addressable secondary tabs, six Factor workspaces, five
  Data Center workspaces, Data Processing and compatibility workspaces, eight
  Backtest detail tabs, and Paper detail.
- Confirmed two P0 evidence defects: contradictory limit-up evidence on the
  dashboard and three unexplained prices for the same stock/cutoff on the stock
  research page.
- Confirmed P1 operator defects: stale Paper evidence shown as running/real-time,
  missing review counters rendered as `undefined`, test/acceptance objects in
  business lists, invisible active mobile navigation, clipped Data Center
  actions, and non-trading dates in data/review workflows.
- Baseline `./scripts/check.sh` passed before changes: frontend build and lint,
  deployment shell syntax, 290 backend tests and Python compilation. Remaining
  baseline warnings are six React Hook dependency warnings, a large Vite entry
  chunk and FastAPI `on_event` deprecation.
- This audit did not trigger synchronization, task execution, Paper controls,
  strategy creation, database writes, external Provider calls or deployment.

### SP-004 review counter contract fix

- Changed the daily-review API count contract to return all supported timeline
  categories with explicit zero values, including an entirely empty timeline.
- Added a defensive frontend count accessor so older or partial responses also
  render `0` rather than interpolating JavaScript `undefined`.
- Added backend regression coverage for grouped and empty counts, plus mocked
  browser coverage for partial API payloads and failed evidence loading.
- Completed clean local frontend/backend restart. Both ports listened, the
  application and PostgreSQL health endpoints were healthy, and the real
  2026-08-07 Review page displayed `0 / 0` with no undefined value.
- Verification passed: 13 focused backend tests, 2 focused mocked Playwright
  tests, `./scripts/check.sh` with 291 backend tests, frontend build/lint and
  Python compilation. The six pre-existing Hook warnings, large Vite vendor
  chunk and FastAPI lifespan deprecation remain tracked in SP-016/SP-017.

### SP-003 runtime truth presentation fix

- Paper cards now reserve the animated green indicator for a running lifecycle
  whose heartbeat satisfies the 15-minute SLA. A running database lifecycle
  with a missing or stale heartbeat is amber and explicitly labelled
  `生命周期运行中` plus `心跳陈旧`; the detail page uses the same distinction.
- Replaced Watch's fabricated 30-day, `100% 实时监控中` Tracker with five real
  evidence domains: instances, signals, orders, trades and alerts. Their color
  and tooltip now derive from the API's fresh/stale/empty/error state.
- Monitor now separates the historical cycle result from current freshness,
  localizes Paper service names, renders missing error codes as `--`, and tones
  lifecycle status using current runtime health when the two disagree.
- Added three mocked browser regressions covering a missing Paper heartbeat, a
  stale Watch snapshot and a historically healthy but currently stale Monitor
  service. All three pass.
- Completed clean local frontend/backend restart and verified healthy app/PG
  endpoints. Real pages show amber lifecycle/heartbeat badges, an amber
  evidence-based Watch tracker and `正常` + `数据滞后` as separate Monitor
  columns. `./scripts/check.sh` passed with 291 backend tests.

## Professionalization implementation batch (2026-08-10)

- Implemented formal sealed-evidence handling for the limit board, same-date
  market price conflict quarantine, test/acceptance purpose classification,
  mobile active-navigation discovery, Data Center action wrapping, canonical
  trading-date resolution, and reloadable Strategy detail links with explicit
  business-count semantics.
- Added backend regressions for TuShare full-market row binding, formal limit
  evidence, purpose classification, trading-date rules, review-date filtering,
  data-task date gates and isolated admin authentication. The repository check
  now passes 315 backend tests.
- Cleared all React Hook lint warnings, split React/chart/HTTP vendor chunks and
  added a build-time bundle budget. The current production build reports a
  327.8 KiB raw / 96.2 KiB gzip initial set and passes the configured limits.
- Separated the safe mocked page suite from real-backend and full-menu suites,
  updated its assertions to the current accessible UI contract, and completed
  43/43 mocked Playwright checks across desktop, mobile and all primary
  operator workflows.
- After explicit approval, established the remote-development PostgreSQL tunnel,
  cleanly restarted both local services with the scheduler disabled, and
  verified application health plus all 29/29 PostgreSQL migrations. The
  read-only real-browser audit now passes 12/12 primary pages and every covered
  sub-tab without page, console or HTTP errors.
- Hardened the real full-menu suite so it requires environment credentials,
  logs in and verifies the session once, defaults to read-only behavior, avoids
  `networkidle` on polling pages, and fails on page/console/network errors.
- The live run exposed synchronous PostgreSQL calls inside asynchronous Market,
  Pool, Factor, Strategy, Backtest, Data, Data Hub, Paper, Watch, Monitor and
  Review routes. Under a full-page workload these calls blocked the main event
  loop and delayed later login/health requests beyond 60 seconds. All surfaced
  blocking service calls now run in worker threads, storage health has a
  three-second connection timeout, and 13 focused thread-isolation regressions
  protect the affected route families.
- After a final clean restart, the real read-only full-menu suite passed 12/12
  in 43.5 seconds. The immediately following application health request passed
  in 0.002 seconds; storage health passed in 2.65 seconds with all 29/29
  migrations applied. `./scripts/check.sh` passed the production build, zero-
  warning lint, bundle budget, 315 backend tests and Python compilation.
- One safety defect remains tracked as SP-020: the first locally inherited
  `ENABLE_SCHEDULER=true` startup wrote 387 concept-flow rows to the remote
  development database at the hour boundary. Every final validation restart
  used `ENABLE_SCHEDULER=false`; no deployment, data repair or production
  mutation was performed.

### SP-001 A-share price-limit evidence completion

- Replaced the legacy global `ST = 5%` estimate with the exchange rules in
  force from 2026-07-06: Shanghai/Shenzhen main board including risk-warning
  stocks 10%, STAR/ChiNext 20%, and Beijing 30%.
- Enriched the PostgreSQL realtime stock cache read with point-in-time security
  status plus published trading-calendar evidence. Shanghai/Shenzhen IPOs are
  excluded for their first five trading days and Beijing IPOs for their first
  trading day. Official `N`/`C` security-name markers are a conservative
  fallback when the local security master has not yet published a new symbol.
- Kept the operator boundary explicit: sealed `limit_pool_members` remain the
  only formal limit-board membership; cache-derived counts remain labelled as
  estimates and are withheld if any stock has unknown rule evidence.
- A read-only real-data verification covered all 5,540 cached stocks: 5,537
  had active price limits, three IPO-stage stocks were excluded, and zero had
  unknown rule state. The resulting diagnostic estimate was 89 limit-up and
  six limit-down securities; the three excluded names were not counted.
- Verification passed 14 focused backend tests, `./scripts/check.sh` with 320
  backend tests, clean frontend build/lint/bundle budget, and the real-backend
  Dashboard/Market browser suites 2/2. The post-load health endpoint responded
  in 0.002 seconds. Scheduler, realtime sync and strategy execution remained
  disabled; no database write or deployment was performed.

### SP-002 stock price provenance completion

- Added explicit `price_basis` and `price_usage` metadata to PostgreSQL daily
  bars, cached valuation snapshots and on-demand order-book responses.
- The stock terminal now presents three independent evidence cards: unadjusted
  daily bars for research, an unadjusted valuation cache for same-snapshot
  fundamentals, and an unadjusted order book for execution-time reference.
  Each card exposes its source and relevant date/time and explains what the
  value may and may not be used for.
- Preserved the existing hard quarantine: when daily and fresh order-book
  evidence share a trade date but diverge beyond the consistency threshold,
  the terminal removes the consolidated price/change claim and displays both
  conflicting sources instead of choosing one silently.
- Verification passed the fail-first mocked conflict/provenance browser test,
  the real-backend Market suite across all six tabs, and `./scripts/check.sh`
  with the production build, lint, bundle budget, 320 backend tests and Python
  compilation. The post-load health endpoint responded in 0.001 seconds.

### SP-005 business/audit isolation completion

- Added a persisted `data_purpose` contract for strategy definitions, Paper
  instances and stock pools, with legacy acceptance/seed backfill in migration
  `202608100001_business_audit_scope.sql`.
- Strategy, Watch and Monitor APIs now default to `scope=business`; explicit
  `scope=audit` preserves and returns acceptance/seed evidence without mixing it
  into business lists, counts, alert totals or notification totals.
- Added compact business/audit controls to all three operator pages. Strategy
  acceptance records now have a dedicated audit tab and no longer enter My
  Strategies or the reference-template count.
- TDD verification passed 35 focused backend contracts, the repository check
  with 324 backend tests, production build/lint/bundle budget, and the complete
  43-test mocked browser suite. Both local services were cleanly restarted with
  scheduler, realtime sync and strategy execution disabled.
- After explicit operator approval, applied only
  `202608100001_business_audit_scope.sql` to the isolated `stockpro_dev`
  database. Storage health reports 30 migration files and 30 applied.
- Real API/browser acceptance verified that business scope returns only `user`
  objects, audit scope preserves acceptance evidence, all three pages can switch
  scope, and the existing Paper-to-Watch-to-Monitor evidence chain remains
  resolvable. No deployment or production service mutation was performed.

### SP-010 primary reading layer localization completion

- Added one compact diagnostic disclosure for operator pages. Stock Pool input
  bindings and sealed snapshots now use business descriptions instead of
  `Dataset #` / `Universe #` / `Factor #` / `Market #`; raw identifiers remain
  available only after explicitly expanding the diagnostic row.
- Daily Review localizes standalone timeline enum tokens such as `post_close`,
  `all_a`, `published`, `buy` and `sell` without changing the persisted audit
  record. Monitor keeps service codes and actual null values in diagnostics
  while the main table shows Chinese service labels and `--`.
- TDD evidence captured the original `Dataset #10` failure before the fix.
  Focused Mock acceptance then passed, followed by the complete 44/44 Mock
  browser suite and `./scripts/check.sh` with a production build, zero-warning
  lint, bundle budget, 324 backend tests and Python compilation.
- Both local services were cleanly restarted with scheduler, realtime sync,
  strategy execution, runtime bootstrap and external market fetch disabled.
  Application health and isolated `stockpro_dev` storage health passed with
  30/30 migrations.
- Read-only real-browser acceptance passed for Review and Monitor business/raw
  evidence. The isolated business scope currently has no Stock Pool record, so
  the real page truthfully verified its empty state; populated binding behavior
  remains covered by the Mock fixture. No database write or deployment ran.

### SP-011 factor maturity funnel completion

- Replaced the shared definition denominator with a research maturity funnel:
  factor definitions, sealed computations, matured evaluations and strategy-
  eligible factors now have explicit, stage-specific denominators.
- Added independent cross-sectional, time-series, out-of-sample and point-in-
  time leakage gates. Missing mature evidence renders `--` plus the blocking
  reason rather than a misleading 0% performance conclusion.
- TDD captured the missing maturity contract before implementation. The full
  Mock browser suite passed 45/45, and read-only real-backend acceptance
  confirmed all 100/100 installed factor definitions plus the four visible
  gates. `./scripts/check.sh` passed build, zero-warning lint, bundle budget,
  324 backend tests and Python compilation.
- Both services were cleanly restarted with scheduler, realtime sync, strategy
  execution, runtime bootstrap and external market fetch disabled. Application
  and isolated `stockpro_dev` storage health passed with 30/30 migrations. No
  factor compute, metric maturity job, database write or deployment ran.

### SP-012 stock-pool validity and binding gates completion

- Stock-pool members and sealed snapshots now distinguish current candidates
  from expired historical research. Expired snapshots retain reproducible
  historical backtest handoff but no longer present themselves as currently
  usable; internal snapshot identifiers remain inside explicit diagnostics.
- Generation rejects datasets that do not cover the target date, Universe
  snapshots from another date, missing factor or market evidence, and
  incompatible factor bindings before writing a generation row. Sealing
  revalidates the stored input manifest, trade date, member validity and
  evidence hashes before creating an immutable snapshot.
- Snapshot responses expose the earliest member validity date and persisted
  data purpose. The business page filters acceptance and seed snapshots from
  counts and rows, closing the remaining Stock Pool business/audit display gap.
- Optional market research evidence now loads progressively. A slow market
  context can disable sector/event generation without blocking the rule
  catalogue or sealed snapshot repository.
- TDD captured the invalid binding, expired snapshot and acceptance-leakage
  failures before implementation. Verification passed 33 focused Stock Pool
  backend tests, the complete 45/45 Mock browser suite, one read-only real
  `stockpro_dev` Stock Pool E2E, and `./scripts/check.sh` with 330 backend tests,
  production build, zero-warning lint, bundle budget and Python compilation.
- Both local services were cleanly restarted with scheduler, realtime sync,
  strategy execution, runtime bootstrap, external market fetch and automatic
  migration disabled. Application and storage health passed with 30/30
  migrations; no database write, migration, deployment or remote service
  mutation ran.

### SP-013 strategy research protocol and Paper promotion gates completion

- Sealed research protocols now require ordered train, validation and untouched
  out-of-sample windows, explicit embargo days, a fixed benchmark, capacity
  limits and return/Sharpe/drawdown promotion thresholds. Full runs bound to a
  protocol must cover every segment and use the protocol benchmark.
- Successful full runs automatically seal eleven independent promotion checks:
  full-result manifest, protocol, all three sample segments, cost evidence,
  capacity rule definition and observed capacity, threshold definition,
  benchmark evidence and data quality. Zero-valued metrics remain valid values
  rather than falling through as missing.
- Paper candidate lists require the complete passed check set, and Paper
  creation rechecks the same set server-side. Legacy or partial
  `paper_eligible` labels cannot bypass the gate. Quick previews remain
  diagnostic-only and explicitly show that they cannot enter Paper.
- Backtest detail now presents the immutable protocol intervals and promotion
  evidence. Core results load first, the NAV series follows independently, and
  positions/orders/trades/logs/attribution load only when their tab opens. This
  removed the real-data page stall caused by eagerly reading five large ledgers.
- TDD captured invalid protocol windows, missing validation/capacity/threshold
  contracts, zero-threshold handling, missing cost/benchmark evidence,
  capacity overflow, incomplete Paper checks and quick-preview leakage before
  implementation. Verification passed 47 focused backend contract assertions,
  the complete 47/47 Mock browser suite, one read-only real `stockpro_dev`
  full-backtest browser acceptance, and `./scripts/check.sh` with 341 backend
  tests, production build, zero-warning lint, bundle budget and Python
  compilation.
- Both local services were cleanly restarted with scheduler, realtime sync,
  strategy execution, runtime bootstrap, external market fetch, automatic
  migration and Paper recovery disabled. Application and storage health passed
  with 30/30 migrations; no database write, migration, deployment or remote
  service mutation ran.

## SP-014 BitPro 流程对齐：AI 策略研发闭环与操作台改造（进行中）

Sprint 合同：`docs/contracts/active-bitpro-flow-parity.md`

### 后端（已完成，374+ 测试通过）

- 新增 `backend/app/services/agent/` 多智能体研发闭环：Planner 规格书 →
  Sprint 合约 → Strategist(LLM) 生成 Strategy API v1 代码 → AST 沙箱
  （复用 `validate_strategy_python`，一次修复重试）→ Backtester 复用
  `BacktestWorkbenchService.run(mode="quick")` 生产链路 → Evaluator 多维评分
  （LLM 失败退化为确定性评分）。达标判定只用回测指标硬阈值。
- 迁移 `202608170001_agent_strategy_research.sql`：`agent_tasks` /
  `agent_iterations`；`main.py` 启动时 `recover_interrupted()` 续跑中断任务。
- 端点 `/api/agent/*`：任务 CRUD、start/stop、迭代、promote（要求
  validation_status=valid）。写入仅管理员。
- 实盘工作台后端：迁移 `202608170002_live_trading_workbench.sql`
  （`live_trading_events` 审计）、`live_trading_service.py` + `/api/live/*`
  （status/promotion-candidates/preflight/enable/events）。预检含券商通道
  （xtquant/ptrade 探测）、`LIVE_TRADING_ENABLED` 开关、11 项晋级门控、风控
  限额与交易时段；未就绪时 enable 请求被阻断并留痕，绝不发出真实委托。
- 配置新增 `QWEN_BASE_URL`、`LIVE_TRADING_ENABLED`（默认 false）等。
- 测试：`test_agent_research.py`（12 项：沙箱拒绝、达标完成、恢复、目标校验）、
  `test_live_trading_service.py`（5 项：无通道阻断、门控、双重确认）。

### 前端（并行实施中）

- client.ts/types 新增 agent + live 全套 API 与类型。
- 策略页 AI 研发面板、回测台改造、模拟实例卡片、复盘大盘 Snapshot、
  实盘工作台页面由并行任务实施，随后统一验证。

### 复盘页大盘 Snapshot 改造（本切片已完成，待随 SP-014 统一提交）

- `frontend/src/pages/DailyReview.tsx` 重构为"当天大盘 Snapshot"单屏结构：
  头部（交易日选择 + 生成复盘 + 状态 chip）→ Snapshot 六块（指数快照 /
  市场宽度 / 情绪指标 / 涨停生态+连板天梯 / 板块资金 TOP8 / 人气榜 TOP10，
  全部并行加载、块内独立 loading/error/empty，块头标注来源与数据时间）→
  复盘结论（当日结论 / 次日计划编辑 + 保存/封存，逻辑不变）+ 复盘记录 +
  风险提示（风险类证据只读汇总；复盘接口无独立风险文本字段，未伪造）→
  证据时间线（原五个子页签合并为类别 chip 筛选）。
- 数据真实性：仅渲染 `getMarketOverview/getShortLineIndices/getLimitBoard/
  getLianbanLadder/getSectorFundFlow/getThsHot` 实际返回字段；指数不含
  成交额、MarketOverview 无停牌家数与昨日涨停表现、板块资金无单股主力口径
  ——均省略不造数；同花顺人气榜热度兼容 `hot`/`hot_value` 两种负载字段。
- 验证：`npx tsc --noEmit` 与 `npm run build`（含 bundle budget）通过；
  本地前后端已按规范重启，`/api/health/health` 通过，Vite 正常提供
  `/review`（浏览器可视验收因当前子代理无浏览器留待统一验证）。

### 模拟盘 BitPro InstanceDashboard 重塑（本切片已完成，待随 SP-014 统一提交）

- `frontend/src/pages/Paper.tsx`（1256 → ~380 行）重塑为 BitPro 模拟盘
  InstanceDashboard 形态：控制台（实例卡片网格）/ 创建向导 / 实例详情三视图。
  全部生命周期调用（`createPaperInstance`、`paperInstanceAction`
  start/pause/resume/stop、`processPaperCycle`、列表/详情读取）原样保留，
  仅表现层重塑；清除仅剩死代码路径的旧表格/页签标记。
- 轮询：指标每 10 秒批量刷新（单次 `listPaperInstances`，静默失败保留上一份
  数据），列表每 60 秒全量静默刷新（含晋级回测与选中详情），页面隐藏时暂停。
- `PaperInstanceDashboard`：单一"模拟盘"页头 + 创建 Paper 实例入口；状态
  segmented（全部/运行中/暂停/已停止带计数）+ 名称搜索 + 排序 segmented
  （创建时间↓ / 收益率↓；夏普/胜率列表负载未提供故不设排序项）；卡片网格
  md:2 / lg:3 / xl:4，卡片含运行呼吸灯（绿=运行、灰=暂停、红=失败/停止、
  琥珀=心跳陈旧）、初始资金（¥100万 口径）/周期/创建日期 pills、收益率大字
  （text-up/text-down + tabular-nums）+ 总盈亏、夏普/胜率/盈亏比/交易次数
  四格（缺失显示"—"不显示 0）、暂停/继续/启动/关闭/详情操作（新增
  `ConfirmDialog` 二次确认，关闭为危险态警示）。
- `PaperRuntimeInstanceDetail`：页头补实例 ID（mono）；启动/暂停/恢复/停止
  全部接入 ConfirmDialog 确认；KPI 行、账户曲线、持仓、成交与事件、诊断
  日志、K 线复盘、风控状态等结构与证据列不变；访客只读仍由
  MainLayout DOM 守卫 + client.ts 请求拦截双层兜底（按钮文案保留
  暂停/停止/启动等关键字）。
- 验证：`npx tsc --noEmit` 与 `npm run build`（含 bundle budget）通过；
  本地前后端已按规范重启，`/api/health/health` 与 Vite `/` 均 200。

### SP-014 统一验证与缺陷修复（收尾）

- 端到端联调发现并修复三处缺陷：
  1. `universe_snapshot_members` 查询误用 `ordinal` 列（改为 `ORDER BY symbol`）；
  2. `paper_instances` 误用不存在的 `initial_cash`/`last_cycle_at` 列（改为
     `parameters->>'initial_cash'` 与 `last_processed_trade_date`）；
  3. 前端 `WorkflowRail` 在研究台负载缺少 `pipeline` 时整树崩溃
     （`ResearchDeskContext` 增加结构防御，rail 对空 pipeline 安全降级）。
- mock e2e 套件从 47 失败修复至 49/49 通过，其中按"页面缺产品必需面"修复：
  Dashboard 热榜陈旧守卫恢复（陈旧缓存不再冒充当前信号）、
  MainLayout 移除与分组侧栏重复的第二导航、快速回测"不可晋级"提示恢复可见、
  回测详情补回夏普与判决带 testid、复盘页证据失败态诚实呈现（`--` 而非 0）、
  数据中心补最近质量报告面板（只读 GET，不自动触发检查）；
  其余为有意的页面/导航合同变更对应的等强度断言更新（13 项一级导航含实盘、
  新页头、回测判决带/晋级检查/六页签、复盘 Snapshot 单页合同、模拟盘卡片网格、
  策略页 AI 研发标签等）。
- 本地验证：后端 379 项 pytest 全过；`npx tsc --noEmit`、`npm run build`
  （含 bundle budget）、`npm run lint`（0 错误）通过；`./scripts/check.sh` 全绿；
  mock Playwright 49/49。数据库隧道经 `scripts/database-tunnel.sh` 恢复，
  迁移 202608170001/2 已显式应用（agent_tasks/agent_iterations/live_trading_events）。
- 真实冒烟：`/api/agent/config` 正确解析最新封存快照/Universe/成本模型默认值；
  `/api/live/promotion-candidates` 返回真实 paper_eligible 完整回测；
  `/api/live/status` 如实报告通道未配置与安全边界。
- 已知边界：本机未配置真实 `QWEN_API_KEY`（BitPro 环境中亦为占位符），
  AI 生成任务在页面与 API 均明确显示"QWEN_API_KEY 未配置"并以失败留痕，
  配置后无需改动即可运行完整闭环（后端单测已覆盖沙箱拒绝/达标/恢复路径）。

### 数据中心冷启动读取修复（2026-08-17）

- 根因：数据中心首次读取会先建立 PostgreSQL 隧道连接，多个模块同时请求时超过前端原有 8 秒页面读取超时，导致真实的就绪数据被误显示为仓库不可用、空覆盖和空任务。
- 修复：`/data/status` 使用 20 秒冷启动读取窗口；数据中心先完成状态读取再并行加载其余模块；增加页面内请求去重，避免 React 开发态重复挂载放大冷启动并发。
- 真实冒烟：总览显示 PostgreSQL 就绪、研究快照已封存、日线 33,238 条、覆盖 80/80；研究数据 10/10 已发布；行情覆盖 80 个标的；同步任务明细 10 条；数据源目录 86 个端点。
- 已知数据告警：最近同步任务仍有 2 次失败、1 个失败项，缓存同步成功率 76%；页面继续如实呈现告警，未执行外部同步或数据自愈。

### 生产域名与 HTTPS（2026-08-17）

- 正式入口改为 `https://stockpro.notenap.com`；HTTP 与
  `www.stockpro.notenap.com` 永久跳转到主域名，`:4444` 仅保留兼容访问。
- Nginx 在共享 443 SNI 分流后使用独立本机端口 `127.0.0.1:8451` 终止 TLS，
  避免影响同机其他产品；证书覆盖主域名和 `www`，由 Certbot timer 自动续期。
- 部署脚本新增 HTTPS 健康检查，只有域名下的后端健康接口成功才记录部署完成。

### 自托管 Runner 构建依赖去外部化（2026-08-17）

- GitHub Actions 连续两次在任务初始化阶段下载 `actions/setup-node` 时收到
  codeload 429，尚未执行仓库构建或部署。
- StockPro 专用 Runner 已固定提供 Node.js 22 / npm 10，满足项目 Node.js 18+
  与 npm 9+ 合同；部署改为本机版本门禁，继续使用干净的 `npm ci` 和完整前端构建，
  避免发布依赖第三方 Action 归档下载可用性。
