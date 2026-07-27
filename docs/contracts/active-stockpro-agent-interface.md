# Sprint Contract: StockPro Agent Tool Interface

> Status: Completed on 2026-07-27.

## Goal

Provide a stable, authenticated `stockpro-mcp-v1` interface so a local Agent can
discover capabilities and operate the existing A-share research lifecycle without
guessing internal routes or bypassing StockPro's evidence boundaries.

## In Scope

- PostgreSQL-backed Agent tokens with SHA-256 hash-only storage and one-time
  plaintext return.
- `R` read and `W` research/backtest/Paper mutation scopes.
- Agent request audit records and mandatory idempotency keys for writes.
- A local stdio MCP entrypoint using the authenticated StockPro HTTP API.
- Stable tools for health, market evidence, strategies, backtest jobs/results,
  Paper instances, Watch, Monitor, Review and Data state.
- Backtest job create/cancel/retry mutations through the same quota and ownership
  boundary as the application.

## Out of Scope

- Remote/public MCP transport.
- Provider synchronization or historical backfill.
- AI-generated strategy code mutation.
- Real broker diagnostics, orders, transfers or live promotion.

## Contract

1. Contract version is `stockpro-mcp-v1`; additions within v1 are additive.
2. Agent tokens use `X-StockPro-MCP-Token`, are stored hash-only and plaintext is
   returned only by the create response.
3. Read tools require scope `R`; mutation tools require scope `W`.
4. Every Agent mutation requires a non-empty `Idempotency-Key`.
5. Duplicate idempotency keys for the same token/tool are rejected before the
   underlying mutation executes.
6. Tool calls use persisted PostgreSQL evidence only unless the tool is explicitly
   categorized as synchronization; this Sprint exposes no synchronization tool.
7. Missing, stale or unavailable data is returned as-is and is never replaced by
   zero, neutral or synthetic values.
8. No real-broker tool exists in v1 and capability discovery reports
   `real_broker_available=false`.

## Done Means

- Migration, token/auth, permission, idempotency and tool mapping tests pass.
- A generated token can call capabilities and health through stdio MCP.
- Read tools return the same payloads as authenticated application endpoints.
- A W-scoped call can create and poll an asynchronous backtest job.
- Revocation immediately invalidates the token.
- Both services restart and `./scripts/check.sh` passes.
