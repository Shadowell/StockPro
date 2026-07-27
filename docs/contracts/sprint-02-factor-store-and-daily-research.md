# Sprint 02 Contract: Factor Store, Daily Compute And Research

## Status

Completed on 2026-07-16 after local PostgreSQL, API, scheduler, immutability and browser acceptance.

## Sprint Name

`factor-store-daily-compute-research`

## Goal

Build a professional point-in-time factor platform for A shares: users write only factor Python, the platform schedules daily calculation after data snapshots are sealed, PostgreSQL stores versioned values and diagnostics, and the BitPro-style Factor Research page exposes factor quality, returns, decay, turnover and exposures. Strategies and backtests consume immutable factor snapshots instead of recalculating factors during a run.

## Product References

- [JoinQuant factor documentation](https://joinquant.com/help/api/help?name=factor)
- [JoinQuant factor-code example](https://www.joinquant.com/factor/factor/edit?factorId=3c6df7f2ec5b72f8fb7f64e138b6c4b5)
- [Quantopian Alphalens](https://github.com/quantopian/alphalens)

These references define expected research concepts such as point-in-time factor values, IC, quantile returns, turnover and rank autocorrelation. StockPro owns its calculation API, PostgreSQL schema, UI and A-share rules.

## Dependencies

- Sprint 01 sealed daily dataset snapshots and quality gates.
- Local PostgreSQL through `DATABASE_URL`.
- Daily bars, adjustment factors, corporate actions, trading calendar, daily valuation/turnover fields, point-in-time universe/industry/benchmark membership and benchmark data.

## Execution Environment

- Frontend: local Vite service on `http://localhost:4444`.
- Backend: local FastAPI service on `http://localhost:4445`.
- Storage and scheduling state: local PostgreSQL only.
- No remote-server migration, deployment or production-data mutation.

## Architecture Boundary

```text
sealed dataset snapshot
  -> factor dependency graph
  -> user factor Python + fixed Factor API v1
  -> raw cross-sectional values
  -> versioned preprocessing
  -> quality checks and diagnostics
  -> sealed factor snapshot
  -> factor page / stock pools / strategy / backtest
```

Every stage records input IDs, code/config versions, calculation time, `knowledge_cutoff_at` and content hash. Published results are append-only.

## Factor Authoring Contract

Users edit only metadata and a Python calculation function:

```python
FACTOR_META = {
    "name": "momentum_20d",
    "category": "momentum",
    "frequency": "daily",
    "lookback": 21,
    "direction": 1,
}

def calculate(context, data):
    close = data.history("close", 21)
    return close.iloc[-1] / close.iloc[0] - 1
```

The returned object is a `pandas.Series` indexed by normalized stock code. Creating a factor must not require editing framework services, a registry, routes or database SQL, and must not require restarting the backend.

`StockPro Factor API v1` provides point-in-time data access and cross-sectional helpers:

- `history`, `get_fundamentals`, `get_security_info`, `get_universe`.
- `winsorize`, `fill_missing`, `standardize`, `neutralize`, `rank`.
- rolling/time-series helpers with a declared lookback.
- `context.trade_date`, `context.knowledge_cutoff_at`, `context.dataset_snapshot_id`, `context.universe_snapshot_id` and universe metadata.

User factor code cannot call TuShare/AKShare, the network, subprocesses, unrestricted filesystem or database APIs. Future dates and undeclared dependencies fail validation.

## Definition And Version Contract

Each immutable factor version records:

- Name, stable code, category, description, owner and status.
- Direction, frequency, declared lookback and output unit.
- Universe rule, immutable universe snapshot and dependency dataset/field list.
- Python content, content hash and Factor API version.
- Preprocessing version: missing-value policy, winsorization, standardization and optional industry/log-market-cap neutralization.
- Research status: exploratory, validated, rejected, paper_eligible, deprecated or failed.

Initial categories are momentum, reversal, volatility, liquidity, size and technical. Value, quality and growth definitions may be added only after point-in-time financial disclosure data passes the Sprint 01 quality contract.

## PostgreSQL Storage Contract

Add:

| Table | Purpose |
| --- | --- |
| `factor_definitions` | Stable factor identity, category, owner and lifecycle state |
| `factor_versions` | Immutable code, dependencies, preprocessing and hashes |
| `factor_compute_runs` | Dataset/universe/version inputs, knowledge cutoff, state, timing, counts and errors |
| `factor_daily_values` | Symbol/date raw value, processed value, rank, percentile, quantile and quality flags |
| `factor_daily_metrics` | Coverage, distribution, IC/RankIC, quantile returns, turnover and decay metrics |
| `factor_correlations` | Pairwise factor correlation by date/window/universe |
| `factor_snapshots` | Immutable published calculation manifest for strategy/backtest use |
| `factor_snapshot_items` | Factor version, trade-date range, value hash and metric hash |
| `factor_schedule_runs` | Daily scheduling, dependency, retry and publication audit |
| `factor_research_protocols` | Hypothesis, universe/benchmark, train/validation/out-of-sample windows, embargo, metrics and rejection rules |
| `factor_evaluation_runs` | Protocol-bound factor candidates, selected/rejected state, rationale and result hashes |
| `factor_metric_evaluations` | Append-only maturity run against a later sealed dataset snapshot |
| `factor_matured_metrics` | Immutable forward IC/RankIC, quantile and long-short evidence without rewriting the source run |

`factor_daily_values` uses monthly range partitioning on `trade_date`. Required indexes include:

- Unique `(factor_version_id, trade_date, symbol, compute_run_id)`.
- B-tree `(factor_version_id, trade_date, symbol)`.
- B-tree `(trade_date, factor_version_id, processed_value DESC)`.
- BRIN on `trade_date` for range scans.

Bulk values are loaded into an unsealed compute run, checked, then atomically published. Corrections create a new run and snapshot; published values are never updated in place.

## Daily Schedule Contract

The local scheduler executes after the relevant daily dataset snapshot is sealed:

1. Resolve the trading date and eligible active factor versions.
2. Build and validate the dependency DAG.
3. Calculate raw values using only data available at that simulated date.
4. Apply the versioned preprocessing pipeline within the frozen universe.
5. Persist values and distribution/coverage checks.
6. Append matured 1/5/20-day forward-return diagnostics from a later sealed dataset snapshot without rewriting the original calculation or its snapshot hash.
7. Seal and publish a factor snapshot when all required quality gates pass.

Idempotency key:

`factor_version_id + trade_date + dataset_snapshot_id + universe_snapshot_id + knowledge_cutoff_at + preprocessing_version`.

Retries reuse or supersede the failed draft run but never duplicate a published snapshot. A missed trading day is visible as failed/pending, not silently skipped.

## Diagnostics Contract

Persist and display:

- Coverage, missing rate, outlier rate, mean, standard deviation, skewness and kurtosis.
- Pearson IC and Spearman RankIC for 1/5/20-day forward returns, IC mean and ICIR.
- Q1-Q5 mean/cumulative returns and direction-aware long-short return.
- Quantile turnover, rank autocorrelation and factor decay.
- Industry and size exposures before/after neutralization.
- Factor-to-factor correlation matrix and rolling stability.
- Universe membership, ST/suspension exclusions and data-quality flags.
- Evaluation protocol, train/validation/out-of-sample label, candidate-selection state and rejection rationale for any promotable conclusion.

Forward-return metrics remain pending until their horizon matures. Pending and undefined values are `null` with a reason, never zero.

## Research-Control Contract

Exploratory factor analysis is not promotion evidence. Any factor status above `exploratory` must bind a sealed `factor_research_protocol` that declares the hypothesis, historical universe/benchmark, train/validation/out-of-sample windows, embargo gap, forward horizons, costs and pass/fail thresholds.

The platform stores every candidate from a parameter/factor search, including rejected candidates and selection rationale. It must not select the highest full-sample IC/return and call that result out-of-sample. A factor can become `paper_eligible` only after its untouched out-of-sample evidence, turnover/capacity and correlation/exposure constraints are all persisted.

## BitPro-Style Page Contract

Route: `/factors`; detail route: `/factors/:factorId`.

L2 workspaces:

1. Factor Library.
2. Compute Runs.
3. Single-Factor Analysis.
4. Multi-Factor Analysis.
5. Correlation And Exposure.
6. Factor Values.

The page uses the existing BitPro/StockPro `MainLayout`, dark tokens and Lucide icon system: fixed grouped sidebar, compact page header/status bar, dense KPI strip, segmented filters, chart/table split panels and drill-down drawers. It must not introduce gradients, marketing hero blocks, decorative cards, oversized text, emoji icons or a parallel visual system.

Factor Library columns include factor code/name, category, active version, last calculation date, coverage, RankIC, ICIR, long-short return, turnover, decay, research state and publication state. The detail header shows coverage, IC, RankIC, ICIR, long-short return and turnover; charts show quantile cumulative returns, IC time series/heatmap, distribution, decay/autocorrelation, exposures and correlations. Every view shows dataset snapshot, knowledge cutoff, universe snapshot, factor version, protocol label, last calculation time and stale/error state.

## API Contract

| Method | Path | Outcome |
| --- | --- | --- |
| `POST` | `/api/factors` | Create definition and initial Python draft |
| `POST` | `/api/factors/{id}/versions` | Create immutable code/config version |
| `POST` | `/api/factor-versions/{id}/validate` | Validate dependencies, code and future-data rules |
| `POST` | `/api/factor-compute-runs` | Queue explicit factor/date/snapshot calculation |
| `GET` | `/api/factor-compute-runs` | List state, progress, inputs and errors |
| `POST` | `/api/factor-schedules/run-daily` | Idempotently execute the local daily schedule |
| `GET` | `/api/factors/{id}/metrics` | Return versioned diagnostics and chart series |
| `GET` | `/api/factors/{id}/values` | Return paged point-in-time values/ranks/flags |
| `POST` | `/api/factor-snapshots` | Validate and seal a factor manifest |
| `GET` | `/api/factor-snapshots/{id}` | Return immutable factor/version/date manifest |
| `GET` | `/api/factor-snapshots/{id}/values` | Read point-in-time factor values from one sealed manifest without provider calls |
| `POST` | `/api/factor-metrics/mature` | Append forward evidence from a later sealed dataset snapshot |
| `POST` | `/api/factor-research-protocols` | Create immutable factor evaluation protocol |
| `POST` | `/api/factor-evaluation-runs` | Evaluate candidates against an explicit protocol |
| `POST` | `/api/factors/{id}/promote` | Promote only from matching sealed out-of-sample evidence |

## In Scope

- Dynamic factor authoring and validation.
- Daily local scheduler, dependency DAG, retries and idempotency.
- PG schema, partitions, repositories, value publication and snapshots.
- Diagnostics above and BitPro-style Factor Research UI.
- Ten reference price/volume/size factors using real local PG data.
- Point-in-time API consumed later by strategies, stock pools and backtests.
- Protocol-bound evaluation, rejected-candidate evidence and out-of-sample promotion gates.

## Out of Scope

- Intraday/tick factors.
- Paid proprietary factor data.
- Remote scheduling or server deployment.
- Automatic factor mining or AI publication without validation.
- Fundamental factors before disclosure-date-safe financial data is available.
- Real trading decisions.

## Deliverables

- Additive PostgreSQL migration with partition/index setup.
- Factor runtime, validation, schedule, diagnostics and snapshot services.
- Ten reference definitions and deterministic fixtures.
- `/factors` library/detail workspaces in the BitPro design system.
- API, repository, scheduler, future-data and frontend tests.
- Progress update.

## Acceptance Criteria

1. A factor is created by saving metadata plus one Python `calculate` function; framework code and routes do not change and the backend does not restart.
2. A sealed Sprint 01 dataset snapshot produces ten reference factor versions for the same trade date.
3. Running the same idempotency key twice creates one published result with identical hashes.
4. Published values and snapshots are immutable; corrections create a new run/snapshot.
5. Future-data access and undeclared dependencies fail validation.
6. Coverage, distribution, IC/RankIC, ICIR, quantile return, turnover, decay and exposure fixtures match expected values.
7. Pending forward horizons remain null with an explicit reason.
8. The `/factors` page exposes all six workspaces, real PG data, source/version metadata and explicit empty/stale/error states.
9. A sealed factor snapshot can be queried point-in-time without a provider call or recalculation.
10. Scheduler restart/retry does not duplicate published values.
11. No remote server or production data is accessed.
12. `./scripts/check.sh` passes.
13. A late financial/corporate-action fact is unavailable to a factor run whose `knowledge_cutoff_at` precedes it.
14. A full-sample-selected candidate cannot be marked `paper_eligible` without a distinct sealed out-of-sample evaluation and recorded rejected variants.

## Testing Plan

| Layer | Coverage | Minimum additions |
| --- | --- | --- |
| Unit | factor loader, preprocessing, DAG, availability cutoff, protocol splitting and metrics | 30 tests |
| Repository | partitions, bulk insert, immutability, protocols, idempotency and snapshots | 13 tests |
| Scheduler | trading calendar, retries, missed days and recovery | 7 tests |
| API | authoring, validation, runs, metrics, values and snapshots | 10 tests |
| Frontend | dense library/detail, filters, charts and failure states | 8 tests |
| E2E local real | dataset seal -> daily compute -> analysis -> snapshot | 1 flow |

## Verification

```bash
./scripts/check.sh
python3 -m unittest discover -s backend/tests
cd frontend && npm run test:e2e:mock
cd frontend && npm run test:e2e
```

Manual local acceptance:

- Start local PostgreSQL, backend `:4445` and frontend `:4444`.
- Seal the reference dataset/universe, run the daily factor schedule twice and verify one published result.
- Evaluate one factor through train/validation/out-of-sample windows and confirm a full-sample-only candidate cannot be promoted.
- Open the factor library and one detail page; reconcile one symbol value and one RankIC period against a fixture.
- Restart the backend and confirm schedules, values and charts reload from PostgreSQL.

## Rollback Plan

- Factor tables and routes are additive and feature-flagged.
- Disable scheduling before rollback; keep published values/snapshots readable for audit.
- Do not delete or rewrite sealed factor snapshots.
- No remote rollback is required because this sprint is local-only.

## Risks / Notes

- Point-in-time correctness is more important than factor count; disclosure-date-safe fundamental factors are deferred deliberately.
- Long-form PG storage is appropriate for the local daily universe and simplifies audit/query. Reassess columnar storage only after measured volume proves a bottleneck.
- Python isolation uses the same restricted-runtime principles as the strategy engine.
- Factor direction, preprocessing and universe choices materially affect results and must remain versioned inputs.

## Handoff

- Next contract: `sprint-03-stable-python-strategy-runtime.md`.
- Sprint 03 consumes sealed factor snapshots through a stable point-in-time API and must not recompute factor definitions inside strategy execution.
