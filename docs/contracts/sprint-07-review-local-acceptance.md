# Sprint 07 Contract: Review And Local Acceptance

## Status

Completed locally on 2026-07-16 after review, recovery, performance and real-backend acceptance.

## Sprint Name

`review-local-acceptance`

## Goal

Complete the operator loop by linking market evidence, stock-pool changes, strategy signals, Paper execution and performance on one trade-date timeline, then prove the platform survives real-backend E2E, provider failures and service restarts without two competing product paths.

## Dependencies

- Sprint 01-06 accepted.
- Local PostgreSQL, FastAPI `:4445` and Vite `:4444` are available.

## Verified Current State

Verified on 2026-07-15:

- `/review` already provides a daily market-review surface.
- Existing review data is not yet joined to immutable dataset/pool/strategy/Paper objects.
- Legacy routes remain registered as primary pages in `frontend/src/App.tsx`.
- Mocked E2E covers primary pages, while real-backend workflows are not yet the complete research-to-Paper journey.

## In Scope

- Review L1 page: Market Review, Pool Review, Strategy Review, Trade Review and Logs.
- Trade-date timeline joining source snapshots, pool changes, signals, risk, orders, fills, positions and equity.
- Links from every review conclusion to immutable evidence objects.
- Legacy route redirects and removal of duplicate L1 navigation entries.
- Final 12-page BitPro-style navigation implementation, including Factor Research.
- Real-backend end-to-end acceptance journey.
- Provider failure, stale data, backend restart and interrupted-job recovery drills.
- Performance budgets for initial page load and core APIs.
- Final documentation/progress reconciliation.
- Local PostgreSQL migration rehearsal and restart recovery.
- Daily backup manifest, weekly restore rehearsal and recovery evidence for local PostgreSQL.
- Research-validity audit for point-in-time availability, historical universe, corporate actions and out-of-sample promotion evidence.

## Out of Scope

- Real broker integration.
- Public SaaS, team accounts or permissions redesign.
- Native mobile application.
- Level-2/tick data.
- New strategy types or factor library expansion.
- Remote SSH, server deployment, production migration or production-data mutation.

## Review Data Contract

Add:

| Table | Purpose |
| --- | --- |
| `daily_reviews` | Trade date, status, author, summary and next-day plan |
| `daily_review_items` | Typed item referencing snapshot/pool/strategy/signal/order/risk/equity objects |
| `daily_review_metrics` | Named metric, value, comparison window, source object and calculation version |
| `qa_drill_runs` | Drill type, environment, started/finished time, status and evidence |
| `backup_runs` | Backup type, scope, manifest/hash, started/finished time, status, encrypted location reference and restore evidence |

Review records store references and summaries, not copied mutable source payloads. Deleted/archived product objects remain resolvable as audit records.

## Navigation Contract

Final L1 order:

1. Home
2. Market
3. Stock Pools
4. Factors
5. Strategy
6. Backtest
7. AI Lab
8. Paper
9. Watch
10. Monitor
11. Review
12. Data

Compatibility redirects remain for one release cycle. After that cycle, routes may be removed only when access logs and tests show no internal links depend on them.

## Performance Budgets

- Authenticated application shell usable within 2.5 seconds on the local reference machine.
- Cached Home, Market, Paper and Monitor API summaries return within 500 ms p95.
- L3 object detail APIs return within 800 ms p95 for reference data volumes.
- No page request triggers a whole-market upstream provider call.
- Frontend initial entry chunk warning must be documented and reduced where it blocks the shell budget.

## Failure Drills

Required drills:

1. TuShare unavailable with allowed AKShare fallback.
2. Both providers unavailable with last-good snapshot retained.
3. Stale realtime data while Paper holds positions.
4. Backend restart with running Paper instance.
5. Interrupted dataset sync and interrupted backtest task.
6. Notification delivery failure.
7. Database migration rollback rehearsal in a disposable local database.
8. Restore the latest local database backup into a disposable database; reconcile sealed dataset/factor snapshots, one completed backtest and one Paper ledger.
9. Attempt a promotion using a full-sample-only result and verify the gate rejects it; verify a historical cutoff cannot read a late disclosure/revision.

## Deliverables

- Review schema, service and page workspaces.
- Final Navigation/App route consolidation and compatibility redirects.
- Cross-object audit links.
- Real-backend E2E suite for the primary journey.
- Failure-drill scripts or repeatable test harnesses.
- Performance measurement and targeted fixes.
- Updated roadmap, spec, progress and QA findings.

## Acceptance Criteria

1. A selected trade date displays market, pool, strategy, Paper and performance events in timestamp order.
2. Every review item links to a resolvable immutable source object or explicitly reports an unavailable archived object.
3. The full journey works without copying a symbol: Market -> Pool -> Snapshot -> Backtest -> Promotion -> Paper -> Watch/Monitor -> Review.
4. The sidebar exposes exactly 12 L1 pages in the contracted order.
5. All listed legacy routes redirect to one current fact entry; no duplicate navigation entry remains.
6. Real-backend E2E passes for the complete journey using controlled reference data.
7. All nine failure drills produce expected state, operator message and audit evidence.
8. Backend restart loses no sealed snapshot, completed run, Paper cursor, ledger entry or review link.
9. Core summary and detail APIs meet the stated p95 budgets on the target reference volume.
10. Real trading remains disabled and unreachable.
11. `docs/spec.md`, roadmap, active/completed contracts and `docs/progress.md` report the same final state.
12. `./scripts/check.sh` passes.
13. The latest successful backup is no more than 24 hours old, and a restore rehearsal completes within two hours with matching manifests/ledgers.
14. The final journey exposes every immutable universe, corporate-action, availability-cutoff and research-protocol input needed to reproduce a result.

## Testing Plan

| Layer | Coverage | Minimum additions |
| --- | --- | --- |
| Unit | review metrics, timeline ordering, reference resolution | 8 tests |
| Integration | cross-object review assembly and archive behavior | 5 tests |
| E2E mock | all 12 pages and legacy redirects | 3 flows |
| E2E real | complete research-to-review journey | 1 full flow |
| Resilience | nine defined failure drills, including restore and research-validity gates | 9 scenarios |
| Performance | shell and four core API summaries | 5 measurements |

## Verification

```bash
./scripts/check.sh
cd frontend && npm run test:e2e:mock
cd frontend && npm run test:e2e
```

Local manual acceptance:

- Run migrations on a disposable Postgres database.
- Seed or synchronize the reference dataset.
- Complete the contracted primary journey.
- Run restart and provider-failure drills.
- Restore the latest backup into a disposable database and reconcile the defined evidence objects before marking local acceptance complete.
- Inspect review links and audit events after recovery.

## Rollback Plan

- Keep legacy route redirects during the first consolidated release.
- Navigation rollback does not roll back data models or audit records.
- Review tables are additive and remain readable if the page is feature-disabled.
- Migration rollback must be rehearsed against a disposable local database.
- If a failure drill reveals ledger or snapshot corruption, block release rather than accepting a documented known issue.

## Risks / Notes

- End-to-end reliability is only proven with real backend and Postgres; mocked E2E is insufficient for final acceptance.
- Performance results must include reference row counts and local-machine conditions.
- A backup that has not been restored successfully is not accepted evidence of recoverability.
- Route removal is a product migration, not a cleanup task; redirects and internal links need explicit verification.

## Completion Evidence

- Migration `202607160021_review_local_acceptance.sql` added immutable daily review items/metrics plus persisted QA drill and backup-run evidence.
- The sealed 2025-01-02 review contains 14 timestamped references across market, pool, strategy, risk, order, trade and performance; every reference resolves to its original PostgreSQL object and the sealed review rejects mutation.
- The sidebar exposes exactly 12 L1 workspaces in the contracted order. Review exposes five workspaces and compatibility routes redirect to the current fact entry.
- A custom-format local PG backup was restored into a disposable database; dataset, factor, backtest, Paper, review and migration manifests all reconciled before the disposable database was dropped. APScheduler registers the daily local backup at `30 2 * * *` Asia/Shanghai.
- One complete acceptance batch passed all nine required failure/recovery drills. The five measured API paths passed their p95 budgets: Market 69.11 ms, Paper 7.42 ms, Monitor 33.21 ms, Review 16.42 ms and Backtest 11.58 ms.
- `./scripts/check.sh` passed with 242 backend tests, frontend production build, lint with 0 errors and Python compilation. Mocked Playwright passed 16 application cases; the real-backend suite and its dedicated complete research-to-review flow passed locally.
- Real broker submission remains absent and unreachable; no server deployment was performed.

## Handoff

- This contract completes the current Sprint 00-07 roadmap.
- Any real broker adapter, commercial data license or multi-user capability requires a new roadmap and explicit contract.
