# Sprint Contract: Cloud B/S Postgres Deployment Foundation

> Status: Active production foundation. On 2026-08-01 the frontend UI package was moved inside the StockPro repository so self-hosted Actions builds no longer depend on a sibling checkout.

## Sprint Name

`cloud-bs-pg-deploy-foundation`

## Goal

Move StockPro's active direction to a cloud-hosted B/S strategy workstation deployed to `root@47.79.36.92` with React, FastAPI, Nginx, systemd, and Postgres foundations.

## In Scope

- Update product spec and deployment documentation for Web-first React + FastAPI + Postgres.
- Add Postgres migration runner and initial strategy-workbench schema.
- Add production environment shape for `DATABASE_URL`.
- Upgrade BitPro-style deployment scripts and GitHub Actions to run migrations before service start.
- Keep runtime routes and background services on Postgres repositories.
- Keep Electron as optional shell only.

## Out of Scope

- SaaS-grade multi-tenant permissions beyond admin login.
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
- Production config requires `DATABASE_URL` and documents Postgres-only runtime expectations.

## Verification

```bash
./scripts/check.sh
```

Manual or QA checks:

- Review deployment docs for no committed secrets.
- Production server has PostgreSQL installed, `stockpro_prod` created, and `/opt/stockpro/backend/.env` configured with server-local secrets.
- Verify `curl http://47.79.36.92:4444/api/health/health` and `/api/health/storage` after deployment.

## Risks / Notes

- Runtime pages should call Postgres-backed API routes only.
- IP-only HTTP is acceptable for this sprint but should move to HTTPS before real trading.

## Handoff

- Deployment foundation is live. Next likely step: keep research and strategy modules on the shared Postgres repositories as new features land.
