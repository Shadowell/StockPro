# Sprint 04 Contract: JoinQuant-Style Backtest Workbench

## Status

Completed on 2026-07-16. Accepted locally against PostgreSQL snapshot 10 and full run `50f68690-96a7-4b17-94f8-0c543c442b54`.

## Sprint Name

`joinquant-style-backtest-workbench`

## Goal

Build a local PostgreSQL-backed backtest workbench inspired by JoinQuant's edit -> configure -> quick run -> full backtest workflow. Users write ordinary Python strategy code while StockPro owns data loading, event execution, A-share matching, portfolio accounting, performance metrics, result charts and Paper-promotion evidence.

## Product Reference

- [JoinQuant getting-started guide](https://www.joinquant.com/help/api/guide)
- [JoinQuant API document](https://cdn.joinquant.com/help/img/JoinQuantAPI.pdf)

The reference determines workflow and metric presentation. StockPro keeps its own Strategy API, immutable PG snapshots and A-share execution rules.

## Dependencies

- Sprint 01 local PostgreSQL dataset snapshots.
- Sprint 02 immutable published factor snapshots.
- Sprint 03 immutable plain-Python strategy versions and normalized order intents.
- Stock-pool input may use a static universe until Sprint 05 adds pool snapshots.

## Execution Environment

- Frontend: local Vite service on `http://localhost:4444`.
- Backend: local FastAPI service on `http://localhost:4445`.
- Storage: local PostgreSQL through `DATABASE_URL`; no SQLite or local JSON result database.
- No remote-server migration, sync, deployment or production-data mutation is authorized.

## Verified Current State

Verified on 2026-07-16:

- `backend/app/api/endpoints/backtest.py` exposes run and results endpoints only.
- `backtest_runs` and `backtest_trades` exist but are not bound to immutable dataset, cost and runtime versions.
- `backend/app/services/strategy_lab_service.py` mixes strategy loading, Backtrader execution, data loading and metrics.
- `frontend/src/pages/Backtest.tsx` does not yet provide JoinQuant-style edit/configure/result drill-down.

## Page Workflow

### Strategy And Parameters

The Backtest page provides:

- Strategy selector and immutable version selector.
- Plain-Python editor using the exact saved `script_content`.
- Start date, end date, initial cash, daily/minute frequency, benchmark, dataset snapshot, universe/pool and cost model.
- Research protocol selector with hypothesis, train/validation/out-of-sample windows, embargo, capacity and Paper-promotion thresholds.
- `Validate`, `Quick Backtest` and `Run Full Backtest` actions.
- Progress, compile/runtime errors and logs without leaving the editor.

Quick Backtest validates syntax and behavior over a short configured range. It cannot be compared, promoted or presented as final evidence.

Full Backtest creates an immutable persisted run with all inputs, metrics, curves, orders, trades, positions, logs and custom `record()` series.

### Result Detail

Route: `/backtest/:runId`.

Top six cards:

1. Strategy total return.
2. Strategy annualized return.
3. Benchmark return.
4. Excess return.
5. Maximum drawdown.
6. Sharpe ratio.

Primary chart overlays strategy cumulative return, benchmark cumulative return and excess return. The maximum-drawdown interval is visibly marked.

Result tabs:

| Tab | Content |
| --- | --- |
| Overview | Core metrics, cumulative-return chart, drawdown chart and run manifest |
| Return Analysis | Full risk metrics, daily-return distribution, monthly heatmap and rolling metrics |
| Positions | Daily positions, cash, exposure, industry allocation and T+1 available quantity |
| Trades | Completed trades, holding period, realized P&L, fees and reasons |
| Orders | All intents/orders, partial fills, cancellations and A-share rejection reasons |
| Logs | Strategy logs, runtime logs, warnings and errors by simulated timestamp |
| Code And Params | Exact strategy code/hash, API version, parameters, snapshot, benchmark and cost model |
| Attribution | Symbol/industry contribution, benchmark excess and cost attribution |

## Metric Contract

JoinQuant-style metrics:

| Category | Metrics |
| --- | --- |
| Return | strategy return, annualized return, benchmark return, excess return, daily average excess return |
| Risk | maximum drawdown, maximum-drawdown interval, annualized volatility, downside volatility, Sortino |
| CAPM/relative | Alpha, Beta, information ratio, benchmark volatility, excess-return maximum drawdown, excess Sharpe |
| Trading | win rate, profit/loss ratio, daily win rate, profitable trades, losing trades |

StockPro-specific execution metrics:

- Total orders, completed trades, fill rate and rejection rate.
- Turnover, total commission, tax, transfer fee and slippage cost.
- Average holding days, average exposure and peak single-symbol weight.
- T+1, lot-size, suspension, limit-up and limit-down rejection counts.
- Data-quality warnings and fallback-source partitions used.

Every metric stores `metric_code`, value, unit, calculation version and input frequency. Missing or undefined metrics return `null` and an explanation, never numeric zero.

## Charts And Series

Persist and expose:

- Daily strategy NAV and return.
- Daily benchmark NAV and return.
- Daily excess NAV and return.
- Drawdown and excess drawdown.
- Cash, market value, gross/net exposure and position count.
- Custom `record()` series.
- Monthly return matrix calculated from daily NAV.

Chart data comes from persisted PG series and never recomputes by calling TuShare/AKShare on page load.

## A-Share Execution Rules

- In the initial daily model, day D close is available only after D's regular session. A signal created from it may first submit/match on D+1's next executable daily bar; same-bar close fill is prohibited.
- Every intent/order/fill records `signal_at`, `data_available_at`, `submitted_at`, `earliest_fill_at`, execution-price source and fill/reject reason.
- Buy quantity is a positive multiple of 100 shares.
- Odd-lot remainder may be sold but cannot exceed T+1 available quantity.
- Suspended securities do not match.
- Default model rejects buy at limit-up and sell at limit-down.
- Price limits come from persisted daily trade-rule data.
- Orders match against unadjusted executable prices; adjusted history may generate signals only.
- Corporate actions update position quantity/cash by their point-in-time effective rules; they must reconcile with adjusted history but may not rewrite an earlier run.
- Opening/closing auctions, intraday order-book queue priority and tick fills are unsupported in the initial daily model and are displayed as such.
- Commission, minimum commission, stamp duty, transfer fee and slippage are versioned.
- Every fee component reconciles to PG portfolio cash.
- Participation/ADV and configured price-impact limits produce capacity warnings; a run over its capacity limit cannot pass Paper promotion.

## Data Model

Extend `backtest_runs` with:

- `dataset_snapshot_id UUID NOT NULL`
- `pool_snapshot_id UUID NULL`
- `factor_snapshot_id UUID NULL`
- `universe_manifest JSONB NOT NULL`
- `universe_snapshot_id UUID NOT NULL`
- `corporate_action_snapshot_id UUID NOT NULL`
- `knowledge_cutoff_at TIMESTAMPTZ NOT NULL`
- `research_protocol_id UUID NULL`
- `cost_model_id UUID NOT NULL`
- `benchmark_code TEXT NOT NULL`
- `strategy_api_version TEXT NOT NULL`
- `input_hash TEXT NOT NULL`
- `run_mode TEXT NOT NULL CHECK (run_mode IN ('quick', 'full'))`
- `progress NUMERIC(5,2) NOT NULL DEFAULT 0`
- `promotion_status TEXT NOT NULL DEFAULT 'not_evaluated'`

Add:

| Table | Purpose |
| --- | --- |
| `backtest_experiments` | User hypothesis and grouped full runs |
| `backtest_matrix_cells` | Parameter combination -> full run mapping |
| `backtest_cost_models` | Versioned cost/slippage configuration |
| `research_protocols` | Hypothesis, universe/benchmark, train/validation/out-of-sample windows, embargo and promotion thresholds |
| `backtest_protocol_evaluations` | Protocol segment metrics, selected/rejected state and promotion evidence |
| `backtest_metrics` | Metric code/value/unit/calculation version |
| `backtest_daily_equity` | Strategy, benchmark, excess, cash, exposure and drawdown series |
| `backtest_orders` | Intent, risk decision, rejection and fill lifecycle |
| `backtest_daily_positions` | End-of-day positions and T+1 availability |
| `backtest_logs` | Timestamped strategy/runtime logs |
| `backtest_custom_records` | Persisted `record()` series |
| `backtest_attribution` | Symbol, industry, benchmark and cost contribution |
| `backtest_promotion_checks` | Paper promotion pass/fail evidence |

## API Contract

| Method | Path | Outcome |
| --- | --- | --- |
| `POST` | `/api/backtest/quick-runs` | Validate and execute short non-promotable run |
| `POST` | `/api/backtest/runs` | Queue immutable full backtest |
| `GET` | `/api/backtest/runs/{run_id}` | Status, progress, manifest and core metrics |
| `GET` | `/api/backtest/runs/{run_id}/metrics` | Full metric set with units/versions |
| `GET` | `/api/backtest/runs/{run_id}/series` | Requested persisted chart series |
| `GET` | `/api/backtest/runs/{run_id}/positions` | Daily PG position snapshots |
| `GET` | `/api/backtest/runs/{run_id}/orders` | Intents, orders, rejects and fills |
| `GET` | `/api/backtest/runs/{run_id}/trades` | Completed trades and realized P&L |
| `GET` | `/api/backtest/runs/{run_id}/logs` | Strategy/runtime logs |
| `POST` | `/api/backtest/compare` | Compare 2-8 completed full runs |
| `POST` | `/api/backtest/runs/{run_id}/evaluate-promotion` | Evaluate Paper entry checks |

## In Scope

- JoinQuant-style edit/configure/quick/full workflow.
- Full metric, chart and tab contracts above.
- Local PG persistence for every full run result.
- A-share broker simulation and cost model.
- Parameter matrices, comparison and Paper-promotion evidence.
- Local mocked and real-backend E2E.

## Out of Scope

- Remote deployment or production migration.
- Tick/Level-2 matching.
- Distributed worker cluster.
- Real broker fills.
- User modifications to the runtime framework.
- Final stock-pool UI; Sprint 05 owns it.

## Deliverables

- Local PG migration and repositories.
- Backtest task, broker simulation, metrics and attribution services.
- JoinQuant-style Backtest page and L3 result detail.
- Quick/full run distinction and comparison UI.
- Unit, integration, metric and E2E tests.
- Progress update.

## Acceptance Criteria

1. A user can select a plain-Python strategy version, configure parameters and start quick/full runs without editing framework code.
2. Every full run is bound to exact strategy code/hash, API version, PG dataset snapshot, optional factor snapshot, universe/pool, parameters, benchmark and cost model.
3. The result detail displays all six core cards and all eight result tabs.
4. Metric fixtures verify return, annualization, benchmark/excess, Alpha, Beta, Sharpe, Sortino, volatility, information ratio, drawdown and drawdown interval.
5. Missing metrics display `null` plus reason; no undefined metric becomes zero.
6. Unit fixtures prove lot size, T+1, suspension and price-limit handling.
7. Trade fees reconcile exactly to cash and attribution.
8. All charts and detail tabs load from persisted local PG data with zero provider calls.
9. Quick runs cannot be compared or promoted; full runs can.
10. A matrix of at least six combinations can run and compare 2-8 results.
11. Local frontend/backend real E2E completes editor -> full run -> result detail -> comparison.
12. No remote server or production data is accessed.
13. `./scripts/check.sh` passes.
14. A D-close signal cannot fill on D; its first possible fill is persisted as D+1 (or the later next tradable session) with timestamped evidence.
15. A run binds universe/corporate-action snapshots and cannot include a delisted, ST or ineligible symbol outside the historical manifest.
16. Paper promotion rejects an exploratory/full-sample-only result and accepts only a passing sealed out-of-sample protocol evaluation with capacity evidence.

## Testing Plan

| Layer | Coverage | Minimum additions |
| --- | --- | --- |
| Unit | A-share fills/timing, corporate actions, capacity, fees, every metric family and chart series | 34 tests |
| Repository | PG run manifest, metrics, series, logs and positions | 10 tests |
| Integration | Python strategy -> timestamped intents -> broker -> metrics/protocol -> PG | 9 tests |
| API | quick/full, detail tabs, compare and promotion | 10 tests |
| E2E mock | editor, configuration and result layout | 2 flows |
| E2E local real | full persisted run and detail drill-down | 1 flow |

## Verification

```bash
./scripts/check.sh
python3 -m unittest discover -s backend/tests
cd frontend && npm run test:e2e:mock
cd frontend && npm run test:e2e
```

Manual local acceptance:

- Start local PostgreSQL, backend `:4445` and frontend `:4444`.
- Open one strategy, run quick validation, then run a full two-year backtest.
- Inspect all result tabs and reconcile one trade manually.
- Verify a close-generated signal fills no earlier than the next tradable session and an over-capacity run cannot pass promotion.
- Restart the backend and confirm the same result detail loads from PG.

## Rollback Plan

- Keep existing `/api/backtest/run` as a compatibility wrapper during migration.
- New PG tables are additive; disable new routes/UI if rollback is required.
- Do not delete completed manifests, metrics or ledgers.
- No remote rollback is needed because this sprint is local-only.

## Risks / Notes

- JoinQuant-style presentation is a workflow reference, not permission to copy proprietary visual assets.
- Metric formulas must be versioned and tested; display names alone are insufficient.
- Future-data prevention and adjusted-price handling can materially invalidate results.
- The initial large frontend bundle warning may affect result-page usability and should be measured locally.

## Handoff

- Next contract: `sprint-05-market-stock-pool-loop.md`.
- Sprint 05 replaces static universes with reproducible stock-pool snapshots; the backtest result contract remains unchanged.
