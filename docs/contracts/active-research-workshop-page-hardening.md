# Sprint Contract: Research Workshop Page Hardening

> Status: Active from 2026-07-27.

## Sprint Name

`research-workshop-page-hardening`

## Goal

Review and improve every primary workspace, fixing data-state bugs and keeping routed pages focused on truthful, decision-oriented A-share workflows rather than implementation notes, development prompts, or agent-authored explanations.

For Strategy Development and its downstream workflow, BitPro's strategy module is the required behavioral baseline. Preserve the BitPro strategy catalogue -> validate/create/version -> backtest -> Paper -> monitor/review flow and replace only the asset-domain rules with the StockPro A-share contract.

## In Scope

- Audit every primary route: Dashboard, Market Research, Stock Pools, Factor Research, Strategy, Backtest, AI Lab, Paper, Watch, Monitor, Review, Data Center, Data Processing, and Admin Login.
- Start with Factor Research, using the user-provided screenshot as the visual baseline.
- Verify Strategy, Backtest, Paper, Monitor and Review as one connected BitPro-parity workflow rather than unrelated pages, including action order, state transitions, immutable version lineage, task progress, filters and evidence drill-down.
- Apply A-share substitutions at the domain boundary: exchange-qualified stock symbols, trading calendar/sessions, long-only default, T+1, 100-share lots, price limits, suspension/ST rules, corporate actions, A-share costs and liquidity/capacity checks.
- Verify each page against the real local backend as well as loading, partial-error, empty, desktop, and narrow-screen states.
- Preserve snapshot provenance and distinguish research dates, knowledge cutoffs, publication state, and metric maturity.
- Reuse the existing financial operator theme and `@bitpro/ui` primitives where they fit.
- Add or update focused automated coverage for each completed page.

## Out of Scope

- Real broker execution or production deployment.
- Fabricated market or research data.
- Cross-cutting backend rewrites unrelated to a page defect.
- Provider synchronization unless a verified page defect cannot be fixed at the presentation or API-contract boundary.

## Current Slice

Data-integrity remediation, delivered in this order:

1. Remove misleading presentation: stale market state cannot appear available, missing values remain unavailable, simulated Stock-terminal values are removed, Pool evidence uses only its bound snapshot, and persisted schedule configuration is distinct from a running scheduler.
2. Separate read paths from synchronization: authenticated page GETs remain PostgreSQL-only and write-free; provider calls and publication stay behind explicit jobs or administrator actions.
3. Complete research evidence presentation: acceptance fixtures are labelled, factor maturity remains pending until evaluated, and Strategy/Backtest/Paper/Review preserve their immutable snapshot and version lineage.
4. Standardize all primary pages on source, business date, response time, freshness, snapshot/version, loading, empty, stale, error, restricted and not-configured states.
5. Add API-contract, read-only, database-integrity and browser regression coverage.

Large provider synchronization, historical backfill, schedule enablement, database migration execution and immutable evidence regeneration still require a separate explicit approval before they run. Code and fixture-backed tests for those paths remain in scope.

## Done Means

- The current page uses real API values and does not imply unavailable metrics are zero.
- A failed optional endpoint does not hide usable core data.
- Snapshot IDs are accompanied by their business meaning and research date.
- Desktop and narrow-screen browser checks pass after clean frontend/backend restarts.
- `npm run check`, focused Playwright checks, and the relevant repository checks pass.
- `docs/progress.md` records completed page evidence and the next page.
- A strategy can be followed without a workflow fork from catalogue and immutable version creation through backtest evidence, Paper eligibility/execution, monitoring and review, with every crypto-specific field replaced or explicitly marked unsupported under the A-share contract.
- No primary page labels a stale cache as real-time, substitutes a business zero for missing evidence, or presents an unbound snapshot as lineage.
- Loading a primary page performs no provider request and no PostgreSQL mutation.
