# Sprint Contract: BitPro-Parity Runtime Evidence

> Status: Completed on 2026-07-27.

## Goal

Complete the A-share Paper observation and operations-health slice so Watch and
Monitor expose the same usable evidence flow as the BitPro reference while
remaining PostgreSQL-backed, Paper-only and explicit about stale acceptance data.

## In Scope

- Watch signal, order, trade, position and risk-event observation.
- Per-Paper-instance heartbeat, latest cycle, equity, drawdown and risk health.
- Persisted source timestamps separated from response-generation timestamps.
- Explicit fresh, stale, empty, stopped, failed and unavailable presentation.
- Runtime evidence links back to the owning Paper instance.
- Workflow capability promotion for Watch and Monitor after verification.

## Out of Scope

- Real broker accounts, orders or positions.
- Provider synchronization, historical backfill or Paper cycle execution.
- Trading controls from Watch or Monitor.
- Copying BitPro business implementation or cryptocurrency-specific behavior.

## Contract

1. Watch and Monitor read persisted PostgreSQL evidence only.
2. Missing price, equity, drawdown, heartbeat or cycle evidence remains null and
   must not be rendered as zero.
3. Counts produced by SQL aggregation may truthfully be zero.
4. `source_updated_at` is the latest persisted evidence timestamp;
   `response_generated_at` is never presented as evidence freshness.
5. Running instances with missing or expired heartbeats are not healthy.
6. Acceptance and seed records remain visible but are labelled by `data_purpose`.
7. Every order, trade and risk event retains its instance and source identifiers.
8. Watch and Monitor remain read-only workflow stages.

## Done Means

- Watch displays persisted orders, trades, positions and risk decisions.
- Monitor displays per-instance runtime and risk health with truthful freshness.
- Empty, stale and failed states are visible in both pages.
- API, frontend and real-backend checks pass after clean service restarts.
- `docs/spec.md`, `docs/progress.md` and workflow capabilities match the result.
