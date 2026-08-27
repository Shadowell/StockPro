# Sprint Contract: Data Module Full-Market Sync And Daily Schedule

> Status: Active — implementation landed locally; the six-month download is operator-triggered and long-running.

## Goal

Make the Data Center usable for operators: download full-market daily K-lines
for the most recent six calendar months, keep signal/reference datasets on the same trusted path, and
run post-close daily updates automatically.

## In Scope

- Date-based full-market daily K-line backfill (TuShare `daily` by `trade_date`).
- Explicit `POST /api/v2/sync/history/sync-all` product entry for 180 calendar days.
- The API acknowledges the operator action immediately and persists per-trading-day progress;
  the final PostgreSQL upsert is atomic and idempotent.
- Wire Data Center “全量下载” and “定时同步” to the PG daily-reference schedule
  (`/schedules/daily`), not the legacy JSON schedule.
- Enable local `ENABLE_SCHEDULER` and allow manual `force` runs when schedule is
  disabled for one-shot recovery.
- Post-close orchestration continues to publish daily bars, auxiliary reference
  datasets, market evidence and factor schedule for the trading day.

## Out Of Scope

- Minute K-lines.
- Remote production deployment.
- Rewriting the sealed research snapshot schema.
- Replacing TuShare as the primary provider.

## Done Means

- Operator can start a full-market six-month daily download from Data Center.
- Enabling daily schedule persists to PostgreSQL and registers with APScheduler
  when `ENABLE_SCHEDULER=true`.
- “立即运行日终” can force one orchestration cycle.
- Verification covers API smoke + frontend typecheck + service restart/health.
