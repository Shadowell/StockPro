# Sprint Contract: Standardize DB Layer & Trading Core

## Sprint Name

`standardize-and-trading-core`

## Goal

Standardize all raw SQL scattered across service files into proper `postgres_db.py` repository methods, implement sentiment persistence, and build out the V2 strategy-workbench trading infrastructure (portfolios, orders, positions, risk checks, broker adapters).

## In Scope

- Add `postgres_db.py` methods for paper_* tables (accounts, orders, positions, equity_curve, events)
- Add `postgres_db.py` methods for strategy_backtest_results
- Add `postgres_db.py` methods for data_hub_jobs, data_hub_quality_reports, data_dev_tasks, data_dev_logs
- Update `strategy_lab_service.py` to use postgres_db methods instead of raw SQL
- Update `data_hub_service.py` to use postgres_db methods instead of raw SQL
- Update `scheduler_service.py` to use postgres_db methods for data_dev tables
- Implement sentiment persistence (DB migration + postgres_db methods + wire up service)
- Implement V2 workbench tables: strategy_versions, strategy_parameters, strategy_signals
- Implement V2 workbench tables: backtest_runs, backtest_trades
- Implement trading infrastructure: portfolios, positions, orders, trades, cash_ledger
- Implement risk management: risk_rules, risk_events integration
- Implement broker adapter: broker_connections CRUD
- Add API endpoints for new V2 domain features

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
- New API endpoints for strategy versions, signals, portfolios, orders, risk, broker
- Updated `docs/progress.md`

## Done Means

- All service files use `postgres_db.py` repository methods (no raw SQL in services)
- Sentiment scores are computed and persisted to DB
- Paper trading uses repository methods for all DB operations
- V2 strategy versions, signals, and backtest tracking are implemented
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
- Verify strategy version creation and retrieval
- Verify portfolio/order CRUD through API

## Risks / Notes

- postgres_db.py is ~3000 lines; new methods should be organized clearly by domain
- Strategy_lab_service.py has complex backtrader integration; changes must not break backtest/paper flows
- V2 tables already exist from migrations; we're wiring code to them

## Handoff

- Next likely step: broker adapter live mode contract, HTTPS deployment
