# Sprint Contract: Daily Publication Integrity

> Status: Completed locally on 2026-07-17.

## Sprint Name

`daily-publication-integrity`

## Goal

Prove and harden the single managed post-close path from a TuShare trade-calendar decision through source-labelled PostgreSQL partitions, one sealed dataset snapshot and factor scheduling, without allowing factor, pool, strategy or backtest reads to call a provider.

## In Scope

- Verify the exact daily dataset order, calendar gate, advisory lock, retry ledger and terminal states.
- Require every published partition to retain requested source, actual source, fallback reason, response hash, availability time and knowledge cutoff.
- Ensure factor scheduling occurs only after the dataset and universe manifests are sealed.
- Treat optional market evidence independently so its restriction/failure cannot masquerade as failed core publication.
- Add deterministic fixture-based orchestration tests for open day, closed day, lock, partial failure and idempotent sealed rerun.
- Surface the persisted run/snapshot/factor evidence on Data without inferring readiness from a cache job.

## Out of Scope

- Large provider synchronization, historical backfill or unrestricted live probing.
- Remote deployment or production schedule enablement.
- Recalculating accepted immutable snapshots.

## Done Means

- An open-day fixture proves all required reference partitions precede one sealed dataset snapshot and factor trigger.
- A missing/failed required dataset cannot seal a snapshot or trigger factors.
- Closed, locked, disabled and already-sealed outcomes are deterministic and persisted/returned truthfully.
- Factor/backtest read tests fail if a provider adapter is reached.
- Data UI shows run date, terminal status, snapshot IDs, watermark, source/fallback evidence and unavailable states.

## Verification

```bash
cd backend
venv/bin/python -m pytest -q tests/test_daily_reference_sync_service.py tests/test_reference_dataset_sync_service.py tests/test_factor_research_service.py tests/test_backtest_api.py
cd ../frontend
npm run check
npm run test:e2e:mock
cd ..
./scripts/check.sh
```

## Handoff

- Next contract: standardize the remaining twelve first-level pages on explicit source, freshness, snapshot/version, loading, empty, stale, error and permission-denied states.

## Completion Evidence

- Deterministic orchestration tests cover open, closed, locked, disabled, already-sealed and required-partition failure paths. Required calendar, security-master, auxiliary and Universe evidence must pass before daily bars can seal or factors can start.
- Daily/reference publication payloads now expose requested/actual source, fallback reason, response hash, availability and knowledge cutoff; Data shows the persisted dataset/factor/market-evidence result rather than inferring completion.
- Factor and backtest orchestrators are contract-tested provider-free. RankIC no longer depends on an undeclared SciPy installation.
- All page-compatible external market fallback is disabled by default. A 26-GET authenticated page probe returned 200 and left fingerprints of 23 PG cache/research/execution tables unchanged.
- Watch, Monitor and AI Lab now separate loading, error and legitimate empty states. Missing Monitor counts, Market ladder values, Strategy statuses and monthly returns are no longer styled or displayed as zero.
- `./scripts/check.sh` passed production build, lint with zero errors, 260 backend tests and source compilation; 26 mocked application browser tests passed with 11 write-capable real-backend tests intentionally skipped.
