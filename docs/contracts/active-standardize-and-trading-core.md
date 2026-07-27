# Sprint Contract: Standardize DB Layer & Trading Core

> Status: Superseded on 2026-07-15 by the A-share Sprint 00-07 contract set; that roadmap completed locally on 2026-07-16 and has no active successor contract.

## Sprint Name

`standardize-and-trading-core`

## Goal

Standardize all raw SQL scattered across service files into proper `postgres_db.py` repository methods, implement sentiment persistence, and build out the single-router strategy workbench plus paper-trading infrastructure (portfolios, orders, positions, risk checks, broker adapters).

## In Scope

- Add `postgres_db.py` methods for paper_* tables (accounts, orders, positions, equity_curve, events)
- Add `postgres_db.py` methods for strategy_backtest_results
- Add `postgres_db.py` methods for data_hub_jobs, data_hub_quality_reports, data_dev_tasks, data_dev_logs
- Update `strategy_lab_service.py` to use postgres_db methods instead of raw SQL
- Update `data_hub_service.py` to use postgres_db methods instead of raw SQL
- Update `scheduler_service.py` to use postgres_db methods for data_dev tables
- Implement sentiment persistence (DB migration + postgres_db methods + wire up service)
- Implement workbench tables: strategy_versions, strategy_parameters, strategy_signals
- Implement workbench tables: backtest_runs, backtest_trades
- Implement trading infrastructure: portfolios, positions, orders, trades, cash_ledger
- Implement risk management: risk_rules, risk_events integration
- Implement broker adapter: broker_connections CRUD
- Add API endpoints only through the single `/api` router and the product domains already in use (`/strategy`, `/backtest`, `/paper`, `/monitor`)
- Remove standalone V2 or unused business routers instead of keeping parallel flows

## Out of Scope

- Real broker order submission (separate contract)
- HTTPS/domain provisioning
- Multi-user auth system (app_users)
- Concept intraday kline (separate contract)
- Dragon tiger / northbound typed getters (low priority)

## Deliverables

- New migration for sentiment tables
- Updated `postgres_db.py` with ~40+ new repository methods
- Updated `strategy_lab_service.py` using repository methods
- Updated `data_hub_service.py` using repository methods
- Updated `scheduler_service.py` using repository methods
- Updated `sentiment_service.py` with persistence
- New single-router API endpoints for strategy versions, signals, portfolios, orders, risk, broker when they have a product workflow
- Updated `docs/progress.md`

## Done Means

- All service files use `postgres_db.py` repository methods (no raw SQL in services)
- Sentiment scores are computed and persisted to DB
- Paper trading uses repository methods for all DB operations
- Strategy versions, signals, and backtest tracking are implemented in the current strategy/backtest/paper flow
- Portfolio, order, position, and trading infrastructure is functional
- Risk rules are checked on order placement
- Broker connections can be created and managed in dry-run mode

## Verification

```bash
./scripts/check.sh
python3 -m pytest backend/tests/ -v --tb=short 2>/dev/null || python3 -m unittest discover -s backend/tests
```

Manual or QA checks:

- Verify paper account creation/listing/stop works via API
- Verify backtest results save and list via API
- Verify sentiment endpoint returns persisted data
- Verify strategy version creation and retrieval through the current strategy flow
- Verify portfolio/order CRUD only after it is wired into the paper-trading workflow

## Risks / Notes

- postgres_db.py is ~3000 lines; new methods should be organized clearly by domain
- Strategy_lab_service.py has complex backtrader integration; changes must not break backtest/paper flows
- Workbench/trading tables already exist from migrations; wire them into product workflows before exposing public API routes

## Handoff

- Next likely step: broker adapter live mode contract, HTTPS deployment
