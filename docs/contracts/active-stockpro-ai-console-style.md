# Sprint Contract: StockPro AI Console Style

> Status: Superseded on 2026-07-15 by the A-share Sprint 00-07 contract set; that roadmap completed locally on 2026-07-16 and has no active successor contract.

## Sprint Name

`stockpro-ai-console-style`

## Goal

Align the local frontend with the production server reference at `http://47.79.36.92:4444/`: a compact StockPro AI dark console with grouped navigation, a persistent market ticker, and dense A-share dashboard cards.

## In Scope

- Replace the desktop shell with the StockPro AI brand block, fixed left sidebar, and grouped operator navigation.
- Move `总览看板` into `研究工坊` and remove the empty `数据中台` group.
- Move `管理后台` out of the top daily-operations group and place it in a lower `系统管理` section.
- Rename the strategy backtest workspace from `复盘中心` to `回测中心`.
- Add a separate `复盘中心` route for current-day market review, including breadth, hot sectors, limit-up ladder, risk notes, and saved replay notes.
- Add the desktop top bar with page title, four A-share indices, market status, language toggle, settings, and logout actions.
- Align global dark theme tokens, borders, radius, hover states, and primary accent color with the server screenshot.
- Make the dashboard first viewport start directly with `市场指数`, `短线指标`, and `热门板块` style cards.
- Keep `热门板块` populated when PG cache is empty by using the existing external market fallback, and show TOP5 when no board is above 5%.
- Align the admin login page with the same StockPro AI console language.
- Add E2E coverage for the shell, navigation groups, ticker order, and dashboard first-screen structure.
- Record a local Playwright screenshot for visual QA.

## Out of Scope

- Production deployment.
- Replacing every page's business-specific content layout.
- Real broker execution changes.
- Backend data-contract changes.

## Done Means

- The default local desktop view visually matches the production server style direction.
- Navigation labels match the console grouping: `研究工坊`, `策略工厂`, `执行风控`, with `总览看板` under `研究工坊` and `管理后台` under the lower `系统管理` section.
- `回测中心` and `复盘中心` are distinct navigation entries: backtesting stays under `/backtest`, daily market review lives under `/review`.
- The top ticker and dashboard index cards keep the order `上证指数`, `深证成指`, `创业板指`, `科创50`.
- `热门板块` should not show an empty state when hot-concept rows are available below the 5% threshold.
- Visual QA screenshot and automated checks pass.

## Verification

```bash
npm run check
npm run lint
npm run test:e2e:mock
./scripts/check.sh
```

Manual or QA checks:

- Open `http://127.0.0.1:4444/` after login and compare the first viewport to the production reference screenshot.
- Confirm the dashboard no longer shows the old `量化交易中枢` module chain above market cards.
