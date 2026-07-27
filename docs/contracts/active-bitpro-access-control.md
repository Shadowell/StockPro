# Sprint Contract: BitPro-parity Access Control

> Status: Completed on 2026-07-27.

## Goal

Provide a usable administrator and invitation-guest boundary for the StockPro
A-share workflow while keeping agent access and real-broker execution explicitly
unavailable.

## In Scope

- Preserve administrator password login and full local write access.
- Add PostgreSQL-backed, hash-only invitation codes with expiry and revocation.
- Allow authenticated guests to read research and runtime evidence.
- Deny guest writes except quota-controlled backtest execution.
- Enforce daily run count, concurrent run count and date-range quotas before a
  guest backtest starts.
- Expose role, permissions, expiry and quota limits through the session API.
- Add administrator invitation management and a guest login mode.
- Show a persistent guest boundary and visibly disable known write actions.

## Out of Scope

- `stockpro-mcp-v1` and external agent credentials.
- Asynchronous backtest workers, cancellation and retry.
- Real-broker accounts, orders or deployment.
- Provider synchronization or historical market-data backfill.

## Contract

1. Invitation plaintext is returned once and only its SHA-256 hash is persisted.
2. Revoked or expired invitations invalidate issued guest tokens immediately.
3. Guest GET/HEAD/OPTIONS requests are allowed under the authenticated boundary.
4. Guest mutations return `403`, except the three supported backtest run routes.
5. Guest backtests reserve PostgreSQL usage before execution and record success or
   failure after execution.
6. Quota rejection returns `429` with a reader-facing reason.
7. The frontend blocks prohibited requests and disables known write controls with
   the same permission explanation.

## Done Means

- Authentication and route-boundary tests pass.
- A real local invitation can log in and read an authenticated page.
- A guest provider/data write is rejected.
- An over-range guest backtest is rejected before the backtest engine runs.
- Revocation invalidates an existing guest token.
- Administrator invitation management and guest mobile UI pass browser checks.
- Both services are restarted, health/storage checks pass and `scripts/check.sh`
  passes.
