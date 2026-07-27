# Active Contract: BitPro Page Parity

Status: completed locally on 2026-07-27.

## Goal

Rebuild StockPro's twelve first-level workspaces around BitPro's page structure,
module hierarchy, operator interactions, density and state semantics while keeping
StockPro's A-share APIs, PostgreSQL evidence and safety boundaries.

## Reference

- Read-only product and implementation reference:
  `/Users/jie.feng/Dev/Github/Private/BitPro`
- Shared presentation primitives: `@bitpro/ui`
- StockPro remains independently implemented. BitPro business page source is not
  copied into StockPro.

## Page Mapping

| StockPro | BitPro baseline | A-share adaptation |
| --- | --- | --- |
| `/` | Home / market dashboard | A-share breadth, indices and rankings |
| `/market` | Market detail | A-share snapshot, structure and evidence |
| `/pools` | Strategy/instance catalogue | Versioned stock-pool catalogue |
| `/factors` | Strategy research workspace | Factor library and run evidence |
| `/strategy` | Strategy centre | Immutable A-share strategy versions |
| `/backtest` | Backtest instance console | PG snapshot-bound backtests |
| `/ai-lab` | AI R&D | A-share research and strategy candidates |
| `/paper` | Paper instance dashboard | Paper-only A-share execution |
| `/watch` | Watch workspace | A-share session and position observation |
| `/monitor` | Monitor centre | Runtime, risk and scheduler health |
| `/review` | Review centre | Sealed daily review and evidence |
| `/data` | Data manager | PG datasets, sync jobs and provider state |

## Delivery Rules

1. Use BitPro's 64px single-column navigation and page-owned headers.
2. Each page uses the BitPro pattern appropriate to its job: catalogue, instance
   console, focused market inspection, or data-maintenance panel.
3. Default business views never expose acceptance or seed objects as normal
   product content. Test objects remain available only through an explicit scope.
4. Loading, empty, stale, error and permission states are visible and truthful.
5. Missing values remain missing; no null-to-zero or neutral-score substitution.
6. Every evidence-bearing module exposes the available trade date, source,
   snapshot/version and update state.
7. Existing StockPro APIs and PG lineage remain the source of truth. No provider
   sync, Paper cycle or production operation is triggered by this sprint.

## Verification

- Clean restart frontend and backend after source changes.
- `./scripts/check.sh`
- Browser acceptance of all twelve routes at desktop and mobile widths.
- Focused assertions for business/test data isolation on `/pools`, `/strategy`,
  `/backtest`, `/ai-lab`, `/paper`, `/watch` and `/monitor`.

## Out Of Scope

- Copying BitPro business page source.
- Cryptocurrency-only fields and workflows.
- Real broker execution.
- Remote deployment or large-scale data synchronization.
