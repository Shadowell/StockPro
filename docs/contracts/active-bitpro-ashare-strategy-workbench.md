# Sprint Contract: BitPro-parity A-share Workflow Foundation

> Status: Completed on 2026-07-27.

## Goal

Establish one truthful, versioned StockPro workflow contract for the BitPro-style
strategy lifecycle:

`Strategy -> Backtest -> Paper -> Watch -> Monitor -> Review`.

StockPro preserves BitPro's behavioral order and evidence semantics while replacing
crypto assumptions with the A-share domain contract.

## In Scope

- Add an authenticated, read-only workflow capability endpoint.
- Publish the workflow contract version, supported stages, incomplete stages,
  authentication modes, feature gates and A-share guardrails.
- Add one shared lifecycle rail across Strategy, Backtest, AI Lab, Paper, Watch,
  Monitor and Review.
- Mark incomplete capability as partial or unavailable instead of hiding it.
- Present the execution scope as Paper-only and make real-broker unavailability
  explicit.
- Preserve PostgreSQL-only page reads and avoid provider calls or database writes.
- Add backend contract tests and mocked browser coverage.

## Out of Scope

- Guest invitation codes and quota enforcement.
- `stockpro-mcp-v1`.
- Asynchronous backtest workers and job persistence.
- Real-broker account binding, orders or deployment.
- Database migrations, provider synchronization and historical backfill.

## Contract

1. Clients call `GET /api/workflow/capabilities` before interpreting lifecycle
   availability.
2. The response distinguishes code capability from runtime data availability.
3. `execution_scope=paper_only`; real broker is `not_implemented` and disabled.
4. The canonical stage order is Strategy, Backtest, Paper, Watch, Monitor, Review.
5. A stage may be `available`, `partial`, `disabled` or `not_implemented`.
6. The UI shows a stable loading, ready or error state for the workflow contract.
7. Failure to load the contract never silently implies that all stages are usable.

## Done Means

- The endpoint is protected by the existing authenticated API boundary.
- The endpoint returns the canonical stage order and honest feature gates.
- Every downstream strategy page shows the same lifecycle rail.
- No first-level navigation label implies that real trading is connected.
- Frontend build/lint, backend tests and focused Playwright checks pass.
- Both services are cleanly restarted and local authenticated browser checks pass
  at desktop and narrow width.
- `docs/progress.md` records verification and the next Sprint.
