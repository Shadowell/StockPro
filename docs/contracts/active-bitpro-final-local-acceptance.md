# Sprint Contract: BitPro-Parity Final Local Acceptance

> Status: Completed locally on 2026-07-27.

## Goal

Prove the complete local A-share workflow is usable across all twelve primary
pages and that daily publication readiness, stale evidence and disabled runtime
state remain truthful without starting synchronization or a real broker.

## In Scope

- Read-only authenticated checks of all twelve primary routes.
- Read-only checks of workflow capability, Watch, Monitor, Review and Data
  publication/schedule evidence.
- Verification that the PG daily publication plan reports configured time,
  effective runtime state, watermark, last run and snapshot lineage separately.
- Regression coverage for loading, empty, stale, error and permission states.
- Final reconciliation of specification, progress and remaining operator actions.

## Out of Scope

- Enabling `ENABLE_SCHEDULER`.
- Provider synchronization, catch-up or historical backfill.
- Paper cycle execution or mutable acceptance fixture creation.
- Real broker integration, remote deployment or production changes.

## Contract

1. A configured cron time is not an effective next run unless the scheduler is
   online and the managed job is registered.
2. Historical acceptance evidence remains stale until a separately authorized
   synchronization or runtime operation produces newer persisted evidence.
3. Route availability does not imply data freshness.
4. Final acceptance uses read-only HTTP/browser navigation and database queries.
5. Any action that would call a provider or execute a Paper cycle requires
   separate explicit authorization.

## Done Means

- All twelve routes load through the authenticated local application shell.
- Core read APIs return 200 and expose source/freshness/evidence timestamps.
- The daily plan truthfully reports its offline runner and historical watermark.
- Full repository checks and applicable browser regressions pass.
- Remaining gaps are operator/environment actions rather than hidden code paths.
