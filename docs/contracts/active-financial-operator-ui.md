# Sprint Contract: Financial Operator UI Unification

> Status: Completed locally on 2026-07-16.

## Sprint Name

`financial-operator-ui-unification`

## Goal

Unify every StockPro route under the `financial-operator-ui` contract and the reusable `@bitpro/ui` primitives, preserving the existing A-share workflows while adopting BitPro's dark, dense financial operator-workbench language.

## In Scope

- Apply `BitProTheme` once at the application shell and import `@bitpro/ui/styles.css` once.
- Reuse `DataPanel`, `MetricCard`, and `StatusBadge` where their semantics fit; do not copy BitPro business pages.
- Standardize the application shell, grouped navigation, top market strip, page canvas, cards, tables, filters, forms, drawers, tabs, badges, loading, empty, stale, error, and permission states.
- Cover all primary routes: `/`, `/market`, `/pools`, `/factors`, `/strategy`, `/backtest`, `/ai-lab`, `/paper`, `/watch`, `/monitor`, `/review`, `/data`, `/data/processing`, and `/admin-login`.
- Preserve configurable A-share up/down color semantics and tabular numeric typography.
- Keep data source, snapshot date/version, refresh state, and execution state visible where the existing API exposes them.
- Provide usable desktop, tablet, and mobile layouts without introducing a second navigation or page hierarchy.
- Extend E2E assertions for shared shell and route-level visual-contract markers.

## Out of Scope

- Copying BitPro business-page source code or business-specific mock data.
- Backend API, database, strategy, execution, or market-data behavior changes.
- Production deployment.
- Replacing real data with decorative placeholder dashboards.

## Deliverables

- Local `@bitpro/ui` dependency and single global style import.
- Shared StockPro financial-workspace primitives and tokens.
- Unified shell and navigation.
- All routed pages rendered inside the financial operator theme.
- Page-specific density and responsive corrections where the shared contract is insufficient.
- Updated UI specification, progress record, and automated checks.

## Done Means

- Every route listed in scope exposes the shared financial-workspace marker and renders without horizontal page overflow at supported breakpoints.
- Cards, tables, controls, tabs, and statuses follow one coherent dark operator-console hierarchy.
- Market movement, operational status, and execution state use distinct semantic colors.
- Loading, empty, stale, error, and permission states remain legible and stable.
- `npm run check`, `npm run lint`, `npm run build`, relevant Playwright checks, and `./scripts/check.sh` pass, or any external blocker is explicitly recorded.
- Frontend and backend are cleanly restarted and both required ports plus backend health are verified after source changes.

## Verification

```bash
cd frontend
npm run check
npm run lint
npm run build
npm run test:e2e:mock
cd ..
./scripts/check.sh
```

Manual or visual QA checks:

- Verify every scoped route at desktop width.
- Verify shell, navigation, tables, filters, and primary actions at mobile width.
- Confirm the configured red-up/green-down and green-up/red-down schemes propagate through the shared theme.
- Confirm no BitPro business page code or fabricated live market data was introduced.

## Risks / Notes

- The repository contains a large uncommitted A-share roadmap implementation; this sprint must preserve those changes and avoid backend edits.
- Several pages are large and use legacy utility-class combinations, so shared normalization should be paired with targeted corrections instead of broad rewrites.
- The local `@bitpro/ui` package is consumed as a file dependency from the sibling BitPro repository.

## Handoff

- After this sprint, new trading, monitoring, and data-admin pages must start from the shared financial-workspace primitives and the repository `AGENTS.md` frontend-design rule.
