# StockPro

StockPro is a local, web-based A-share research and strategy-validation workstation. It connects market research, factor analysis, stock pools, versioned Python strategies, PostgreSQL-backed backtests, paper execution, watch, runtime monitoring, and daily review in one auditable workflow.

StockPro is designed to preserve evidence: every research result should identify its trade date, source, dataset snapshot, factor or pool snapshot, strategy version, and execution outcome.

> Current boundary: local operation, research first, paper trading only. StockPro does not expose live-broker order submission, and pushing source code does not deploy a server.

[中文](README.md) · [Documentation](docs/index.md) · [Product specification](docs/spec.md) · [API guide](docs/api.md)

## Main capabilities

- A-share market structure, breadth, sentiment, limit-up ecology, sectors, events, calendar, and stock research.
- Versioned factor definitions, compute runs, values, snapshots, and single/multi-factor diagnostics.
- Reproducible stock-pool snapshots with explicit selection reasons.
- Browser-based Python strategy authoring with immutable versions and validation.
- Asynchronous backtests bound to sealed PostgreSQL data, factor, pool, protocol, and cost evidence.
- Isolated Paper instances with signals, risk decisions, orders, trades, positions, cash, equity, heartbeats, and cycle evidence.
- Dedicated Watch, Monitor, and Daily Review workspaces.
- PostgreSQL data centre with source, freshness, coverage, quality, permission, job, and schedule states.
- Optional Qwen/DashScope analysis and a local authenticated `stockpro-mcp-v1` Agent interface.

## Workspaces

| Workspace | Route | Purpose |
| --- | --- | --- |
| Home | `/` | Market and research overview |
| Market | `/market` | Structure, sentiment, events, calendar, and stock research |
| Pools | `/pools` | Rules, generation runs, snapshots, and backtest handoff |
| Factors | `/factors` | Catalogue, compute, diagnostics, correlation, and values |
| Strategy | `/strategy` | Catalogue, source code, parameters, versions, and validation |
| Backtest | `/backtest` | Jobs, results, orders, trades, metrics, and evidence |
| Paper | `/paper` | Simulated execution, portfolio, and risk |
| Watch | `/watch` | Human observation of signals and execution evidence |
| Monitor | `/monitor` | Strategy, data, risk, and notification health |
| Review | `/review` | End-of-day conclusions and next-session plan |
| Data | `/data` | Datasets, sync, quality, providers, and schedules |
| AI Lab | `/ai-lab` | AI research tasks with evidence bindings |

## Local quick start

Requirements: Python 3.11+, Node.js 18+, npm 9+, and Docker Compose.

```bash
cp backend/.env.example backend/.env
# Edit backend/.env; change the admin password and token secret.

docker compose up -d postgres
python3 -m venv backend/venv
backend/venv/bin/python -m pip install -r backend/requirements.txt
(cd backend && venv/bin/python bootstrap_runtime.py)
npm --prefix frontend install
./restart.sh
```

Open:

- Frontend: `http://localhost:4444`
- Backend: `http://localhost:4445`
- OpenAPI: `http://localhost:4445/docs`

Use `./stop.sh` to stop the local frontend and backend. `./restart.sh` never deploys a remote server.

## Verification

```bash
./scripts/check.sh
```

See [docs/index.md](docs/index.md) for the maintained documentation set and [docs/deployment.md](docs/deployment.md) for local operations.

## Safety

StockPro is a research and simulation tool, not investment advice. Keep `.env`, API keys, databases, backups, logs, and broker credentials out of Git. AI output and simulated fills require independent review.
