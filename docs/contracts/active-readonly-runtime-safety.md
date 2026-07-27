# Sprint Contract: Read-only Runtime Safety

> Status: Completed locally on 2026-07-17.

## Sprint Name

`readonly-runtime-safety`

## Goal

Make ordinary page reads and safe local startup observational: opening Review/Data or restarting for verification must not assemble reviews, install registries, recover Paper state with new events, or start scheduled/provider work implicitly.

## In Scope

- Load Review through its existing read-only GET and reserve POST assemble for the explicit rebuild action.
- Remove catalogue/registry/schedule installation side effects from Data GET services.
- Separate schema/bootstrap installation from application startup and make it an explicit, idempotent command or opt-in setting.
- Make scheduler, realtime sync and strategy execution disabled by default for local development; require explicit enablement.
- Make Paper recovery observational unless an interrupted runtime cycle genuinely needs a persisted terminal transition.
- Add database fingerprint and API contract tests proving GET requests do not change relevant rows or timestamps.

## Out of Scope

- Large provider syncs or historical backfills.
- Remote deployment, production settings or broker integration.
- Changing immutable research manifests or rebuilding accepted historical fixtures.

## Done Means

- Initial `/review` navigation issues GET only; POST assemble occurs only after the operator clicks rebuild.
- Repeated Data catalogue/dataset/snapshot/schedule GETs leave database fingerprints unchanged.
- A default backend startup cannot run periodic provider, realtime or strategy jobs.
- Restarting with no interrupted Paper cycles does not append recovery events or update instances.
- Focused API/service tests, full local checks and clean scheduler-disabled service restart pass.

## Verification

```bash
cd backend
python -m unittest tests.test_readonly_contracts tests.test_review_api tests.test_daily_review_service
cd ../frontend
npm run check
npm run test:e2e:mock
cd ..
./scripts/check.sh
```

## Handoff

- Next contract: prove the current daily publication path atomically seals all required datasets, records provider provenance and triggers factor readiness without provider calls from factor/backtest reads.

## Completion Evidence

- Review initial navigation uses `GET /review/{trade_date}`; browser coverage proves `POST /assemble` is sent only after the explicit rebuild action.
- Six authenticated Data/Review GET requests returned 200 while PostgreSQL row counts and SHA-256 fingerprints for nine registry, snapshot, review and Paper evidence tables remained identical.
- Default startup skips migrations, bootstrap, Paper recovery, scheduler, realtime sync and strategy execution; clean local restart logs and focused tests verified every gate.
- Focused backend contract suite passed 39 tests plus 10 subtests; frontend typecheck and 23 mocked application browser tests passed.
