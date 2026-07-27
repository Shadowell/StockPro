# Active Contract: BitPro Subpage Parity

Status: active.

## Goal

Align every StockPro first-level workspace and its internal pages with the
corresponding BitPro information architecture, module order, object navigation,
filter controls, detail views and operator-state semantics.

## Delivery Order

1. [complete] `/paper`: dashboard, preferred/all views, filter bar, instance cards,
   creation wizard and instance monitor.
2. [complete] `/strategy`, `/backtest`, `/ai-lab`: catalogue, experiment and detail flows.
3. `/watch`, `/monitor`, `/review`: observation, operations and review flows.
4. `/`, `/market`, `/pools`, `/factors`, `/data`: dashboard, inspection,
   catalogue, research and maintenance flows.
5. Cross-page desktop/mobile browser acceptance and documentation closeout.

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
- `/ai-lab` now follows the three BitPro workspaces: autonomous AI trading,
  new-strategy research and existing-strategy optimization. The research
  workspace contains the four-stage proposal → backtest → result → simulation
  decision flow and integrates persisted candidate evidence.
- Strategy and backtest already satisfy the object catalogue, staged creation
  and detail-report contract and were retained rather than rewritten.
