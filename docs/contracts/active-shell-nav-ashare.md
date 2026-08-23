# Sprint Contract: Align StockPro shell nav with BitPro IA

- Status: in progress
- Issues: #14 (required), #11 (included: package rename + quarantine unused crypto pages)
- Branch: `cursor/align-shell-nav-f0a5`

## Goal

Keep the BitPro shell and route information architecture on StockPro, with
A-share labels and a single workbench state machine. Contract, OKX, live,
arbitrage, onchain, and funding-rate entries must not appear as live product
surfaces. Do not invent a parallel research-desk IA.

## In Scope

- Audit sidebar, routes, and deep links against BitPro IA:
  首页 / 行情 / 股票池 / 因子 / 策略 / 回测 / 模拟 / 盯盘 / 信号 / 监控 / 复盘 / 数据 / AI研发
- Hide reserved futures; mark leftover crypto/live deep links unavailable with a reason
- Reuse `@bitpro/ui` loading / empty / error / permission / unavailable density
- Prefer A-share copy in the shell: 代码.市场, 交易日历, 模拟盘 / 现金账本
- Rename `bitpro-frontend` → `stockpro-frontend`
- Delete or quarantine unrouted Arbitrage / Onchain / Arc / liveTrading pages

## Out of Scope

- New pages beyond the BitPro shell IA
- Backend API or business-rule changes
- Enabling live trading
- Changes to Shadowell/BitPro
- Rewriting every owner page's internals

## Deliverables

- Shared frontend workbench definition and unknown-route resolver
- Shell copy and symbol display aligned to A-share paper MVP
- Package rename and unused crypto page removal
- Spec / progress / E2E updates

## Done Means

- Nav matches BitPro IA; 实盘 / 链上 / ARC / 套利 / 期货 are absent
- `/futures` still redirects home (reserved, not a product page)
- `/live`, `/arbitrage`, `/onchain`, `/arc` show an unavailable reason, not a live workspace
- `frontend/package.json` name is `stockpro-frontend`
- Unrouted crypto pages are gone from the product tree
- Relevant frontend checks pass

## Verification

```bash
npm --prefix frontend run check
npm --prefix frontend run lint
npm --prefix frontend run test:e2e:mock -- tests/e2e/rebuild-shell.spec.ts tests/e2e/rebuild-futures-hidden.spec.ts tests/e2e/rebuild-capabilities.spec.ts
./scripts/check.sh
```

## Risks / Notes

- Rebuild safety forbids registering `live-real` / `onchain` / `arbitrage` / `arc`
  or `path="live"` in `App.tsx` or `MainLayout.tsx`. Hidden deep links are
  resolved by a catch-all outside those files.
- MCP auth header names remain backend contract strings.
