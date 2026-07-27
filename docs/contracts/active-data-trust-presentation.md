# Sprint Contract: Data Trust Presentation

> Status: Completed locally on 2026-07-17.

## Sprint Name

`data-trust-presentation`

## Goal

Remove the highest-risk misleading states identified by the local data-integrity audit so operators can distinguish current data, stale cache, unavailable comparisons, replay fixtures and unbound research coverage without triggering a data backfill.

## In Scope

- Give Home market modules independent freshness/error presentation and stop using stale THS cache as an unqualified strong-stock signal.
- Stop rendering structural short-line placeholder zeroes as percentage changes.
- Derive and display an effective Paper runtime state from the persisted status and heartbeat timestamp without mutating the stored state.
- Keep Review metrics unavailable until its context has loaded; a failed load must never render business zeroes.
- Separate Data Center's legacy K-line cache statistics from sealed research-snapshot readiness and avoid labelling sync success alone as backtest readiness.
- Add focused frontend tests for the corrected states.

## Out of Scope

- Provider calls, permission probes, market/factor backfills or any large data synchronization.
- Rebuilding the daily snapshot orchestration chain.
- Making Data GET routes strictly read-only; that follows in the next backend-focused slice.
- Changing Paper persisted status or rewriting acceptance fixtures.
- Remote deployment or production data changes.

## Deliverables

- Truthful loading, stale, unavailable and replay-state UI on Home, Paper, Review and Data.
- Small reusable frontend freshness helpers where needed.
- Updated product/progress documentation and regression coverage.

## Done Means

- A stale hotspot cannot appear as an unqualified current strong stock or current hot-sector list.
- Short-line count/ratio cards do not display a fabricated `+0.00%` comparison.
- A nominally running Paper instance with an expired heartbeat is visibly stale/offline and cannot be confused with a live worker heartbeat.
- Review load failure leaves metrics as `--`, not `0`.
- Data Center reports full PG daily-row counts separately from its limited coverage sample and labels research readiness from sealed snapshot evidence.
- Frontend checks, focused E2E coverage, the repository check script and clean service restarts pass, or a blocker is recorded.

## Verification

```bash
cd frontend
npm run check
npm run lint
npm run build
npm run test:e2e:mock
cd ..
./scripts/check.sh
```

Manual or QA checks:

- Inspect Home, Paper, Review and Data at desktop and 390px widths.
- Confirm source/timestamp/stale labels remain legible inside the dense financial operator layout.
- Confirm no sync, probe or Review assemble request is triggered solely for verification.

## Risks / Notes

- The repository contains substantial existing uncommitted roadmap work; edits must remain narrow and preserve it.
- Existing realtime cache APIs expose timestamps but incomplete source metadata. This sprint labels the known PG-cache boundary and does not invent provider provenance.
- Review currently assembles through a write-like POST on load. This sprint fixes its misleading empty values; separating read and assemble behavior is a later API slice.

## Handoff

- Next likely step: make GET routes read-only and connect current daily K-line publication to the sealed research snapshot chain.

## Completion Evidence

- Home now evaluates the hot-concept, THS-hot and short-line caches independently. The real local page labelled the June caches stale, withheld a current strong-stock claim and kept the July short-line timestamp visible without inventing percentage comparisons.
- Paper derives an effective presentation state from its persisted status and 15-minute heartbeat SLA. Historical recorded-replay instances remain stored as-is but render as `回放心跳陈旧`.
- Review load failure keeps all six headline metrics unavailable and removes save/seal actions until a context exists.
- Data Center separates PG full-table counts, limited coverage samples, cache-task success and sealed-snapshot readiness. Missing job/coverage statistics remain `--`.
- `npm run check`, production build, lint (0 errors), 23 mocked application E2E cases, 246 backend tests, Python compilation, clean local service restarts and the health endpoint passed. Eleven write-capable real-backend browser cases remained skipped by design.
- Desktop and 390px checks passed. A pre-existing React list-key warning originates in the shared `@bitpro/ui` `DataPanel` implementation and is not a StockPro data-state failure.
- No manual provider probe, backfill, Review assembly or remote action was run. During the first required backend restart, the existing local `ENABLE_SCHEDULER=true` setting reached its minute boundary and automatically ran the configured news task plus one realtime-cache task. The service was stopped and final verification runs with scheduler, realtime sync and strategy execution disabled through process-only environment overrides.
