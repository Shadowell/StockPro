# Active Contract: BitPro Subpage Parity

Status: complete.

## Goal

Align every StockPro first-level workspace and its internal pages with the
corresponding BitPro information architecture, module order, object navigation,
filter controls, detail views and operator-state semantics.

## Delivery Order

1. [complete] `/paper`: dashboard, preferred/all views, filter bar, instance cards,
   creation wizard and full BitPro-parity instance monitor.
2. [complete] `/strategy`, `/backtest`, `/ai-lab`: catalogue, experiment and detail flows.
3. [complete] `/watch`, `/monitor`, `/review`: observation, operations and review flows.
4. [complete] `/`, `/market`, `/pools`, `/factors`, `/data`: dashboard, inspection,
   catalogue, research and maintenance flows.
5. [complete] Cross-page desktop/mobile browser acceptance and documentation closeout.

## Adaptation Boundary

- BitPro is a read-only product and interaction reference.
- StockPro keeps its A-share APIs, PostgreSQL records, snapshots, T+1 rules,
  board-lot rules and paper-only execution boundary.
- BitPro business source is not copied. Shared visual primitives and interaction
  patterns are reimplemented against StockPro types and APIs.
- Crypto-only exchange, leverage, funding and 24x7 concepts are replaced by
  A-share market scope, trading calendar, capital scale and snapshot evidence.

## Truthfulness Rules

- Missing metrics remain unavailable and show the reason; they are not rendered
  as zero.
- Acceptance and seed records remain outside the default business view.
- Read-only page loads must not start a provider sync or Paper runtime cycle.
- Mutations retain the existing permission and confirmation boundaries.

## Verification

- Clean restart of frontend and backend after every source change.
- `./scripts/check.sh`.
- Focused mocked browser tests for each rebuilt workspace.
- Read-only real-backend browser pass for all twelve routes.
- Desktop and narrow-viewport visual inspection.

## Completed Evidence

- `/paper` now uses a dashboard → create/detail object flow. Its default
  dashboard contains preferred/all views, business/test isolation, filters,
  sorting, dense instance cards and card-level lifecycle actions.
- Paper cards expose persisted PnL, return, trades, security scope and heartbeat
  evidence. Sharpe, win rate and profit factor remain explicitly unavailable
  when the API does not provide them.
- The Paper instance monitor now contains the complete BitPro module sequence:
  runtime header/actions, nine KPI cards, strategy logic, read-only parameters,
  PostgreSQL diagnostic evidence, A-share positions, trades/events, snapshot-bound
  K-line review, Paper equity curve and risk state.
- Historical replay heartbeat uses processing time while retaining simulated
  trade time as evidence. Explicit sealed replay can bypass wall-clock staleness,
  successful cycles resolve prior stale-feed alerts, and list/detail APIs expose
  the same latest cycle and aggregate counts.
- Paper K-lines are read from the instance-bound sealed dataset snapshot; missing
  runtime statistics remain unavailable with a reason and are never replaced by
  qualifying-backtest values.
- `/ai-lab` now follows the three BitPro workspaces: autonomous AI trading,
  new-strategy research and existing-strategy optimization. The research
  workspace contains the four-stage proposal → backtest → result → simulation
  decision flow and integrates persisted candidate evidence.
- Strategy and backtest already satisfy the object catalogue, staged creation
  and detail-report contract and were retained rather than rewritten.
- Strategy detail and Paper instance detail now share the actual `@bitpro/ui`
  `DataPanel`, `MetricCard`, `StatusBadge` and `LogStream` primitives. Strategy
  detail exposes persisted version, validation, dependency, runtime-limit and
  source-code evidence; Paper diagnostics and system events use one continuous
  terminal timeline instead of per-entry cards.
- `/data` now opens on a concise operating summary with an explicit
  usable/stale/blocked conclusion, prioritized issues and four shared BitPro
  metrics. Research data, coverage maintenance, job history and provider
  permissions are separated into task-oriented sections instead of one long
  undifferentiated page.
- Primary product views do not expose database keys, UUID fragments or content
  hashes as user-facing facts. They use readable names, version numbers,
  localized workflow states, dates and binding summaries; internal identifiers
  remain available to backend audit and diagnostics only.
- Running Paper cards use BitPro's green breathing indicator. Heartbeat
  freshness is a separate amber operational warning and does not overwrite the
  lifecycle state.
- Monitor data health uses readable snapshot fields instead of raw JSON; Watch,
  Backtest, Stock Pools, Factors, AI Research and shared detail panels keep
  internal identifiers out of the reading layer.
- Desktop and 390px browser sweeps cover every primary route, all
  query-addressable secondary tabs, all factor workspaces, Backtest detail and
  Paper detail without console errors, failed API responses or page-level
  horizontal overflow.
