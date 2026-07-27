# Sprint 00 Contract: Product Contract And Page Hierarchy

## Status

Completed on 2026-07-15.

## Sprint Name

`product-contract-and-page-hierarchy`

## Goal

Freeze StockPro's product boundary, BitPro-inspired page hierarchy, data-source policy and delivery sequence before runtime changes begin. The output of this sprint is the contract that prevents later sprints from rebuilding parallel pages or incompatible research, backtest and Paper workflows.

## Dependencies

- None. This is the root contract for Sprint 01-07.

## Verified Current State

Verified on 2026-07-15:

- `frontend/src/App.tsx` registers 15 primary protected business routes plus compatibility redirects.
- `frontend/src/components/Navigation.tsx` exposes separate market overview, sentiment, news, AI, factor and calendar entries.
- Existing strategy, backtest and Paper paths are separate execution implementations.
- TuShare-first with AKShare fallback already exists in `backend/app/services/tushare_provider.py`, but fallback provenance is not persisted as an immutable research input.

## In Scope

- Define the product loop: data -> market research -> stock pool -> strategy version -> backtest -> Paper -> review.
- Define L0 application shell, L1 sidebar pages, L2 page workspaces and L3 object details.
- Freeze 12 L1 pages: Home, Market, Stock Pools, Factors, Strategy, Backtest, AI Lab, Paper, Watch, Monitor, Review and Data.
- Keep real trading hidden and out of the registered order-submission routes.
- Define TuShare as primary research source and AKShare as explicit supplement/fallback.
- Split the roadmap into ordered Sprint 01-07 contracts.

## Out of Scope

- Frontend route or navigation implementation.
- Database migrations.
- Provider, strategy, backtest or Paper runtime changes.
- Real broker integration and production trading.

## Deliverables

- `docs/ashare-research-roadmap.md`
- `docs/spec.md`
- Sprint contracts under `docs/contracts/`
- Superseded status on previous parallel active contracts.

## Architecture Decision

```text
L0 application shell
  -> L1 workflow page
       -> L2 page workspace
            -> L3 object detail
```

Research pages are grouped by user task, not by external API. Paper, Watch and Monitor stay separate because they represent execution, human observation and system health.

## Done Means

1. The roadmap defines exactly 12 L1 pages and their routes.
2. Every legacy route has a keep, redirect or remove decision.
3. Real trading is explicitly excluded.
4. TuShare/AKShare source roles and missing-data behavior are explicit.
5. Sprint 01-07 each have an ordered contract and pass/fail exit criteria.
6. `docs/spec.md` and `docs/progress.md` point to the same active sprint.

## Verification

```bash
git diff --check
rg -n "^## Phase|L1 一级侧栏|路由迁移" docs/ashare-research-roadmap.md
./scripts/check.sh
```

## Rollback Plan

Revert the documentation changes as one unit. No runtime, schema or production state is modified by this sprint.

## Risks / Notes

- Navigation names may evolve during implementation, but route purpose and page ownership cannot change without updating `docs/spec.md`, the roadmap and the active sprint contract together.
- The detailed Data page specification appears early in the roadmap because downstream sprints depend on it, even though Data is last in the L1 sidebar.

## Handoff

- Next contract: `active-sprint-01-data-trust-and-snapshots.md`.
- Do not implement navigation consolidation before the data contracts and runtime APIs needed by the pages exist.
