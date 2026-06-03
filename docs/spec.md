# StockPro Product Spec

## Product Summary

StockPro is a cloud-hosted B/S A-share strategy workstation. It provides research, strategy development, backtesting, live signal monitoring, paper trading, risk controls, and a broker-neutral live trading adapter path for a personal cloud workspace.

The production target is `root@47.79.36.92`, served at `http://47.79.36.92:4444` with React static assets behind Nginx and FastAPI on `127.0.0.1:4445`.

## Users

- Primary user: one owner operating a personal cloud strategy workstation.
- Future users: small research collaborators, only after a separate permissions contract.

## Core User Journeys

1. Review A-share market structure, concepts, limit-up ladders, money flow, news catalysts, and market sentiment.
2. Define or edit a Python strategy with parameters, versioning, declared data dependencies, and a standard output contract.
3. Run a backtest on Postgres-backed historical data and review return, drawdown, win rate, turnover, trades, and signal quality.
4. Publish a strategy to live monitoring and inspect normalized signals with chart and research context.
5. Convert a signal into a paper order, pass risk checks, and track orders, trades, positions, and cash ledger.
6. Prepare broker adapter configuration in dry-run mode before any real trading integration is enabled.

## Product Priorities

1. Web-first B/S architecture with React + FastAPI + Postgres.
2. A-share-specific research rules: ST, exchange boards, lot size, T+1, limit-up/down, suspension, lunch break, concept rotation, and event catalysts.
3. Auditable strategy lifecycle from development to backtest to signal to order.
4. Production deployment that follows the BitPro-style single-server main-branch flow.
5. Explicit safety gates before any live trading path.

## Technical Shape

- Frontend: React + Vite, deployed as static assets under `/opt/stockpro/frontend/dist`.
- Backend: FastAPI, deployed as `stockpro-backend` systemd service under `/opt/stockpro/backend`.
- Database: Postgres only for the cloud platform, using `DB_MODE=postgres` and `DATABASE_URL`.
- Public entry: Nginx on `:4444`, proxying `/api/` to FastAPI on `127.0.0.1:4445`.
- Deployment: GitHub Actions main-only, self-hosted runner label `stockpro-production`, SHA gate via `/opt/stockpro/deploy/last_deployed_sha`.
- Electron: optional shell only; not part of the core platform architecture.

## Current Architecture Notes

The repository still contains legacy SQLite service code used by older application modules. PG-only production disables those legacy API routes and background services by default; new cloud-platform work must use Postgres migrations and repositories. Legacy SQLite paths should be replaced module by module rather than expanded.

## Constraints

- Do not commit production secrets, `.env`, database files, private keys, or broker credentials.
- Do not enable live trading by default.
- Any real broker integration requires a separate contract and explicit confirmation.
- Production server changes that create users, databases, or credentials must be performed with auditable scripts and documented commands.

## Non-Goals

- Public SaaS multi-tenancy.
- Team permission model in the first cloud version.
- Kubernetes, Docker Swarm, or blue/green deployment.
- Real broker order submission in the initial PG/B/S migration.

## Acceptance Direction

The primary acceptance flow is: update the cloud contract, run Postgres migrations, deploy React/FastAPI through Nginx/systemd, verify health endpoints, then incrementally migrate research, strategy, backtest, signal, paper trading, and risk modules to Postgres.

## Open Questions

- Which broker adapter should be implemented first after dry-run support?
- Which A-share research dataset should become the first PG-backed research page?
- When should IP:4444 move to a domain with HTTPS?
