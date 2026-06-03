# Sprint Contract: Cloud B/S Postgres Deployment Foundation

## Sprint Name

`cloud-bs-pg-deploy-foundation`

## Goal

Move StockPro's active direction to a cloud-hosted B/S strategy workstation deployed to `root@47.79.36.92` with React, FastAPI, Nginx, systemd, and Postgres foundations.

## In Scope

- Update product spec and deployment documentation for Web-first React + FastAPI + Postgres.
- Add Postgres migration runner and initial strategy-workbench schema.
- Add production environment shape for `DB_MODE=postgres` and `DATABASE_URL`.
- Upgrade BitPro-style deployment scripts and GitHub Actions to run migrations before service start.
- Disable legacy SQLite routes/background services by default in Postgres production.
- Keep Electron as optional shell only.

## Out of Scope

- Full replacement of every legacy SQLite data service.
- Team accounts, SaaS tenancy, billing, or permissions.
- Real broker API integration or live order submission.
- HTTPS/domain provisioning.

## Deliverables

- Updated `docs/spec.md`.
- Updated `docs/deployment.md`.
- Updated `.github/workflows/deploy.yml`.
- Updated `deploy/deploy.sh`, `deploy/setup-server.sh`, `deploy/stockpro.nginx`.
- New Postgres setup and migration files.
- Verification through `./scripts/check.sh`.

## Done Means

- Repository documents `47.79.36.92:4444` as the production entry.
- Postgres migrations are idempotent and runnable through a Python module.
- Deployment script validates `.env`, installs dependencies, applies migrations, restarts systemd, reloads Nginx, and checks health.
- Production config rejects SQLite mode and documents legacy SQLite migration gaps.

## Verification

```bash
./scripts/check.sh
```

Manual or QA checks:

- Review deployment docs for no committed secrets.
- Production server has PostgreSQL installed, `stockpro_prod` created, and `/opt/stockpro/backend/.env` configured with server-local secrets.
- Verify `curl http://47.79.36.92:4444/api/v1/health/health` and `/api/v1/health/storage` after deployment.

## Risks / Notes

- Legacy pages still have SQLite-specific service paths, but those routes/background services are disabled in PG-only production unless explicitly opted in for development.
- IP-only HTTP is acceptable for this sprint but should move to HTTPS before real trading.

## Handoff

- Deployment foundation is live. Next likely step: migrate the first research/strategy module from SQLite-specific access to Postgres repositories.
