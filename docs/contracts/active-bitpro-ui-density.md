# Active Contract: BitPro UI Density Parity (All Subpages)

Status: Active from 2026-07-27.

## Sprint Name

`bitpro-ui-density-all-subpages`

## Goal

Bring every StockPro first-level workspace **and every nested L2/L3 surface**
(WorkspaceTabs, `?tab=` views, list/editor/detail modes, create wizards, detail
nested tabs, and drawers) to BitPro operator UI density, module rhythm and
truthful data-state semantics, while keeping StockPro's A-share APIs,
PostgreSQL evidence and paper-only safety boundary.

## Reference (read-only)

- BitPro repository: `/Users/jie.feng/Dev/Github/Private/BitPro`
- Page contracts: `BitPro/docs/pages/*.md`
- Layout rhythm: `BitPro/frontend/src/pages/*`, `MainLayout.tsx`
- Shared primitives: `@bitpro/ui` from `BitPro/packages/bitpro-ui`
- Visual skill: `~/.codex/skills/financial-operator-ui/SKILL.md`

Do not copy BitPro business-page source into StockPro.

## Subpage Inventory (must all pass)

| Route | Required surfaces |
| --- | --- |
| `/` | All primary dashboard sections |
| `/market` | `structure`, `sectors`, `sentiment`, `events`, `calendar`, `stock` |
| `/pools` | `mine`, `screener`, `factor`, `sector`, `event`, `snapshots` — workflow strip 建规则→生成→封存→回测; mine is the operator workbench with next-action guidance; create tabs explain type purpose; `snapshots` is handoff to backtest |
| `/factors` | `library`, `runs`, `single`, `multi`, `correlation`, `values`, author modal |
| `/strategy` | `my` / `plaza`, list, editor, detail |
| `/backtest` | dashboard, wizard steps 1–3, detail tabs 总览/收益分析/持仓/交易/订单/日志/代码与参数/归因, compare |
| `/paper` | `preferred` / `all`, create, detail modules, trades/events |
| `/watch` | `signals`, `execution`, `pools`, `charts`, `alerts` |
| `/monitor` | `overview`, `strategy`, `data`, `risk`, `notifications` |
| `/review` | `market`, `pools`, `strategy`, `trades`, `logs` |
| `/data` | `overview`, `datasets`, `coverage`, `jobs`, `providers` |
| `/ai-lab` | `autonomous`, `research`, `optimize` |
| `/admin-login` | admin / guest |
| `/data/processing` | `assets`, `jobs`, `quality`, `features`, `legacy` (+ legacy children) |

Pages without a BitPro twin (`/pools`, `/factors`) reuse the Strategy/Data shell
rhythm with A-share content.

## Delivery Order

0. Shared operator shell components.
1. Strategy list / editor / detail (template page).
2. Backtest + Paper (all modes and nested tabs).
3. Watch / Monitor / Review (every `?tab=`).
4. Home / Market / Pools / Factors (every tab/workspace).
5. AI Lab / Data / Data Processing / Admin Login.
6. Cross-route desktop + 390px acceptance of the full inventory.

## In Scope

- Shared shell: page header, segmented controls, filter bars, catalogue cards,
  evidence strips, loading/empty/stale/error/permission panels.
- Reuse `@bitpro/ui` `DataPanel`, `MetricCard`, `StatusBadge`, `LogStream`.
- Align module order and density with BitPro docs/pages for mapped routes.
- Keep honest freshness, missing-value and seed/acceptance isolation rules from
  the superseded research-workshop hardening contract.

## Out Of Scope

- Real broker / `/live-real` parity.
- On-chain, arbitrage, Signal Bot, Orbit posting.
- Copying BitPro business TSX.
- Enabling scheduler, provider sync, historical backfill or remote deploy.
- Fabricated market data.

## Done Means

- Every surface in the inventory uses the shared shell rhythm and passes desktop
  + 390px inspection without page-level horizontal overflow.
- Strategy → Backtest → Paper → Watch → Monitor → Review module order matches
  BitPro behavioural baseline with A-share substitutions only.
- Stale/missing/restricted states are visible; null is never shown as business zero.
- Read-only page loads do not mutate PostgreSQL or call providers.
- `./scripts/check.sh` passes; `docs/progress.md` records each batch and the
  next unfinished subpage.
