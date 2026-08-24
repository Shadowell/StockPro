# Quarantined BitPro-only leftovers

These files are **not** part of the StockPro A-share Paper MVP shell.

Deleted from the product tree in the #11 pass:

- `pages/ArbitrageCenter.tsx`
- `pages/OnchainResearch.tsx`
- `pages/ArcConsole.tsx`
- `pages/Trading.tsx`
- `pages/WatchMarket.tsx`
- `pages/liveTrading/**`
- `pages/aiLab/OrbitPostPanel.tsx`
- `components/live/LiveAccountSummaryPanels.tsx`
- `components/FundingRateChart.tsx`
- `components/WatchDataCharts.tsx`
- `components/MarketUniversePanel.tsx`

Still on disk but unrouted / not in the MVP shell (leave for a later cleanup):

- `pages/aiLab/AutoAgentPanel.tsx`
- `pages/aiLab/ResearchWorkbench.tsx`
- leftover `/live` and `/arbitrage` client helpers in `src/api/client.ts`

Do not re-register those routes in `App.tsx` or `MainLayout.tsx`.
