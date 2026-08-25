# StockPro

StockPro is a local, web-based A-share research and strategy-validation workstation. It connects market research, factor analysis, stock pools, versioned Python strategies, PostgreSQL-backed backtests, paper execution, watch, runtime monitoring, and daily review in one auditable workflow.

StockPro is designed to preserve evidence: every research result identifies its trade date, source, dataset snapshot, factor or pool snapshot, strategy version, and execution outcome.

> **Current boundary**: research first, paper trading only. No live-broker order submission; futures stay hidden as a reserved domain. Production runs from `main` via GitHub Actions.

[中文](README.md) · [Documentation](docs/index.md) · [Product specification](docs/spec.md) · [API guide](docs/api.md)

## Main capabilities

- A-share market structure, breadth, sentiment, limit-up ecology, sectors, events, calendar, and per-stock research with explicit freshness and source labels.
- Versioned factor definitions, compute runs, values, snapshots, and single/multi-factor diagnostics.
- Reproducible stock-pool snapshots with explicit selection reasons.
- Browser-based Python strategy authoring with immutable versions and validation.
- Asynchronous backtests bound to sealed data, factor, pool, protocol, and cost evidence, with A-share rules built in (trading calendar, T+1, 100-share lots, limit up/down, suspensions, fees).
- Isolated paper instances with signals, risk decisions, orders, trades, positions, cash, equity, heartbeats, and cycle evidence.
- Watch / Monitor / Daily Review workspaces for operations.
- PostgreSQL data centre: sources (TuShare primary, AKShare explicit fallback), freshness, coverage, quality, permissions, jobs, schedules.
- Optional Qwen/DashScope AI research tasks, plus a local authenticated `stockpro-mcp-v1` Agent interface.

## Workspaces

The sidebar exposes 13 top-level workspaces. Strategy → Backtest → Paper is the only execution trunk. Live trading, on-chain, arbitrage, and ARC are not registered as routes.

| Workspace | Route | Purpose |
| --- | --- | --- |
| Home | `/` | Market overview |
| Market | `/market` | Structure, sentiment, events, calendar, and stock research |
| Pools | `/pools` | Rules, generation runs, snapshots, and backtest handoff |
| Factors | `/factors` | Catalogue, compute, diagnostics, correlation, and values |
| Strategy | `/strategy` | Catalogue, source code, parameters, versions, validation |
| Backtest | `/backtest` | Jobs, results, orders, trades, metrics, and evidence |
| Paper | `/paper` | Simulated execution, portfolio, and risk |
| Watch | `/watch` | Human observation of signals and execution evidence |
| Signals | `/signals` | Signal payloads, paper lineage, delivery audit |
| Monitor | `/monitor` | Strategy, data, risk, and notification health |
| Review | `/review` | End-of-day conclusions and next-session plan |
| Data | `/data` | Datasets, sync, quality, providers, schedules |
| AI Lab | `/ai-lab` | AI research tasks with evidence bindings |

Admin login lives at `/admin-login`.

## Local quick start

Requirements: Python 3.11+, Node.js 18+, npm 9+, Docker Compose (for the isolated golden-path database).

```bash
cp backend/.env.example backend/.env
# Edit backend/.env: change the admin password and token secret;
# add TUSHARE_TOKEN / QWEN_API_KEY only when you need real data or AI.

./scripts/setup_isolation_db.sh                                  # create stockpro_bitpro_rebase_dev
export DATABASE_URL="$(./scripts/setup_isolation_db.sh --print-url)"
./scripts/setup_isolation_db.sh --migrate                        # apply migrations

python3 -m venv backend/venv
backend/venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend install
./restart.sh                                                     # start backend + frontend
```

Open:

- Web: `http://localhost:4444`
- Backend health: `http://localhost:4445/api/health`
- OpenAPI: `http://localhost:4445/docs`

Admin credentials come from `ADMIN_USERNAME` / `ADMIN_PASSWORD` in `backend/.env`. Keep `.env`, keys, databases, logs, and broker credentials out of Git.

`restart.sh` never applies migrations, syncs data, or deploys a server. Use `./stop.sh` to stop local services. See [docs/deployment.md](docs/deployment.md) for the full manual.

## Verification

`./scripts/check.sh` requires `DATABASE_URL` to end with `/stockpro_bitpro_rebase_dev`; it exits with setup instructions otherwise.

```bash
export DATABASE_URL="$(./scripts/setup_isolation_db.sh --print-url)"
./scripts/check.sh        # frontend tsc/lint/build + backend pytest + compile checks
```

Real-backend E2E additionally needs local services running: `npm --prefix frontend run test:e2e:real`.

## Safety

StockPro is a research and simulation tool, not investment advice. Paper results do not represent executable real-world fills. AI output requires independent review against data dates and model availability.

## License

StockPro source code is licensed under the [MIT License](LICENSE).

The MIT License applies only to source code and documentation that this repository is authorized to license. Market data, AI services, third-party APIs, dependencies, and their outputs remain subject to their respective licenses, terms, data permissions, rate limits, and redistribution rules.
