# Sprint 06 Contract: Paper, Watch And Monitor

## Status

Completed on 2026-07-16 after the recorded five-trading-day Paper acceptance and real-backend browser flow.

## Sprint Name

`paper-watch-monitor`

## Goal

Build a continuously running, auditable Paper execution loop and expose it through three separate operator pages: Paper for execution, Watch for human observation and Monitor for system health.

## Dependencies

- Sprint 01 source-aware market feeds and freshness policies.
- Sprint 02 published factor snapshots.
- Sprint 03 unified strategy runtime.
- Sprint 04 A-share broker simulation and risk decisions.
- Sprint 05 immutable pool snapshots.

## Verified Current State

Verified on 2026-07-15:

- `backend/app/api/endpoints/paper.py` exposes run, account, refresh and stop actions.
- `backend/app/api/endpoints/strategy.py` duplicates Paper-related actions under strategy routes.
- Existing schema already includes portfolios, positions, orders, trades, cash ledger, risk rules and risk events.
- Current Paper behavior is not a continuously scheduled strategy runtime with full signal-to-order audit.
- The current Monitor page mixes operator risk concepts without a shared health/alert model.

## In Scope

- Paper instance lifecycle: draft, starting, running, paused, stopping, stopped and failed.
- Start gate requiring a passing sealed research protocol, out-of-sample evaluation, universe/factor/dataset snapshots and capacity evidence.
- Scheduler/runner that consumes MarketDataFeed and unified strategy runtime.
- Standard Signal -> risk decision -> order -> fill -> position/cash/equity lifecycle.
- Paper L1 page: Instances, Signals, Orders, Positions, Account and Events.
- Watch L1 page: Strategy Signals, Pool Moves, Chart Linkage and Alerts.
- Monitor L1 page: Overview, Strategy Health, Data Health, Risk and Notifications.
- Explicit data staleness handling and no-new-entry safety gate.
- API consolidation so strategy-specific Paper endpoints become wrappers.

## Out of Scope

- Real broker connection and real order submission.
- Mobile push application.
- Tick-level matching.
- Multi-account user permissions.
- Automated strategy parameter changes while an instance is running.

## Data Model

Add or extend:

| Table | Purpose |
| --- | --- |
| `paper_instances` | Version, dataset/factor/universe/pool snapshots, protocol evaluation, capacity limits, feed configuration, status, heartbeat and runtime version |
| `paper_instance_events` | Append-only lifecycle, strategy, broker, risk, feed and operator events |
| `paper_equity_snapshots` | Timestamped cash, market value, exposure, NAV and drawdown |
| `alert_rules` | Versioned signal/data/risk/system alert definitions |
| `alerts` | Alert lifecycle, severity, source object, acknowledgement and escalation |
| `service_health_snapshots` | Service, status, latency, last success, error code and observed time |
| `notification_deliveries` | Alert -> channel delivery/acknowledgement result |

Existing `strategy_signals`, `orders`, `trades`, `positions`, `cash_ledger` and `risk_events` remain the execution ledger. Add `paper_instance_id` where required rather than creating parallel ledgers.

## Runtime Rules

- Each instance pins strategy version, dataset/factor/universe/pool snapshots, protocol evaluation, parameter values, capacity limits and feed configuration at start.
- Every cycle has an injected timestamp and idempotency key.
- A repeated Bar cannot produce a duplicate persisted signal or order.
- Feed staleness beyond configured SLA blocks new-entry signals; exits and valuation follow explicit safety policy.
- Provider fallback emits an instance event and alert.
- Risk rejection persists rule ID, rule version, input and message.
- A Paper order carries the strategy signal/data-availability timestamps and uses the same earliest-fill semantics as its accepted backtest configuration.
- Configured daily risk budgets include cash floor, single-symbol/industry exposure, turnover, drawdown and participation/ADV limits; a breach blocks new entries and produces an auditable reason.
- Stop is idempotent and leaves positions/cash intact for audit.
- Backend restart restores running/paused instances from persisted state without replaying processed Bars.

## API Contract

| Method | Path | Outcome |
| --- | --- | --- |
| `POST` | `/api/paper/instances` | Create pinned Paper instance |
| `POST` | `/api/paper/instances/{id}/start` | Start idempotently |
| `POST` | `/api/paper/instances/{id}/pause` | Pause new runtime cycles |
| `POST` | `/api/paper/instances/{id}/resume` | Resume from last processed cursor |
| `POST` | `/api/paper/instances/{id}/stop` | Stop idempotently |
| `GET` | `/api/paper/instances/{id}/events` | Return ordered audit events |
| `GET` | `/api/watch/alerts` | Return active signal/pool/risk alerts |
| `POST` | `/api/watch/alerts/{id}/acknowledge` | Persist acknowledgement |
| `GET` | `/api/monitor/health` | Return service/data/strategy health summary |

## Page Ownership

- Paper answers: what did the strategy execute and what does the simulated account hold?
- Watch answers: what needs the owner's attention now?
- Monitor answers: are data, runtimes, queues and risk services healthy?

No page may expose a control that bypasses persisted risk decisions.

## Deliverables

- Paper runner/scheduler and recovery service.
- Ledger integration and API consolidation.
- Paper, Watch and Monitor page workspaces.
- Alert, health and notification persistence.
- Staleness, idempotency, restart and risk tests.
- Five-trading-day acceptance runbook and progress updates.

## Acceptance Criteria

1. A Paper instance pins all immutable inputs and rejects start when they are missing or invalid.
2. The reference strategy processes new Bars continuously and does not buy the universe immediately at startup.
3. Replaying the same runtime cycle produces no duplicate signals, orders, trades or ledger entries.
4. Every order has a linked signal and risk decision; rejected orders retain the rejecting rule/version.
5. Cash plus positions reconcile to equity snapshots for every processed cycle.
6. Data older than SLA blocks new entries and creates both an event and visible alert.
7. Backend restart resumes from the persisted cursor without replaying completed Bars.
8. Paper, Watch and Monitor expose their separate ownership and cross-link the same instance/event IDs.
9. The reference instance completes five trading days with no unexplained ledger difference.
10. No real-broker balance, credential or submission path is reachable.
11. `./scripts/check.sh` passes.
12. Starting Paper fails when the strategy has no passing out-of-sample protocol evaluation, immutable universe snapshot or capacity evidence.
13. Paper replay proves that a close-generated daily signal cannot execute on the same bar and that a participation-limit breach blocks a new entry.

## Testing Plan

| Layer | Coverage | Minimum additions |
| --- | --- | --- |
| Unit | state machine, idempotency, stale feed, alert rules | 14 tests |
| Ledger | orders, timing, fills, T+1 positions, capacity limits and cash/equity reconciliation | 14 tests |
| Recovery | restart, cursor resume, duplicate Bar prevention | 5 tests |
| API | lifecycle, events, alert ack, health | 8 tests |
| E2E | start instance -> signal -> order -> alert -> monitor -> stop | 2 mocked + 1 real-backend flow |

## Verification

```bash
./scripts/check.sh
python3 -m unittest discover -s backend/tests
cd frontend && npm run test:e2e:mock
```

Manual acceptance:

- Start reference instance before market data replay.
- Inject normal, stale, suspended and price-limit fixtures.
- Confirm Paper ledger, Watch alert and Monitor health show the same event chain.
- Restart backend and verify cursor recovery.

## Rollback Plan

- Keep all new execution records append-only.
- Feature-flag the continuous runner and stop active instances before rollback.
- Existing Paper account read endpoints remain available as compatibility reads.
- Never map Paper accounts to live broker credentials during rollback or recovery.

## Risks / Notes

- Background runner concurrency can duplicate work unless database-level cursors and idempotency constraints are used.
- Five trading days may be executed with recorded/replay market feed when calendar time would delay acceptance; the mode must be clearly labeled.
- Monitor health must distinguish provider staleness from strategy failure.

## Handoff

- Next contract: `sprint-07-review-local-acceptance.md`.
- Sprint 07 subsequently completed the review and local-acceptance roadmap after instance `076c217f-9b5c-4b18-8fb3-fcd2a127a171` completed the five-day recorded replay with zero ledger difference.

## Completion Evidence

- Added pinned Paper instances, append-only cycles/events/equity, alert/notification/health persistence and database-level idempotency constraints in migrations `202607160019` and `202607160020`.
- The runner separates close signals from next-session fills, enforces 100-share lots, T+1 availability and versioned risk checks, blocks stale-feed entries and restores persisted cursors on startup.
- Full backtest `ac808202-72da-474e-9336-b075956e0506` binds Dataset `10`, Factor `4`, Universe `1` and Pool `4`; all five promotion checks passed before Paper creation.
- Recorded sessions `2024-12-16` through `2024-12-20` created five signals, one next-day filled order/trade and zero ledger difference. Replaying `2024-12-19` reused the cycle; stale `2024-12-23` was blocked with an alert.
- A separate low-participation instance retained a rejected order, rejecting risk event and risk alert. The accepted order links one signal and five versioned risk decisions.
- Added Paper (6 tabs), Watch (4 tabs) and Monitor (5 tabs), 35 focused unit/API tests, mocked browser coverage and a passing real-backend operator flow.
