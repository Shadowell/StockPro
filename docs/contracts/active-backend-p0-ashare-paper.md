# Backend P0: A-share paper semantics

- Status: in progress
- Issues: #8/#12 in PR #15; this slice is #13 / #9 / #10
- Owner: BE

## Goal

Keep StockPro on the A-share paper path. Crypto exchange, contract brokers,
funding/arbitrage strategies, and OKX utility scripts must not be importable
from the default product tree.

## In Scope

- Move OKX/Binance live exchange modules, contract paper/brokers, and
  funding/arb/`contract_*` strategies out of `backend/app` and `scripts/`.
- Refuse archived crypto strategy keys in the leftover BitPro registry.
- Leave A-share Paper / backtest on sealed snapshots only.

## Out Of Scope

- Live trading or auto-order.
- Frontend crypto page cleanup (issue #11).
- Changing BitPro.

## Done Means

- `backend/app/exchange/okx.py`, contract paper, funding/arb strategies, and
  `scripts/sync_okx_universe.py` / `okx_orbit_publisher.js` are not on the
  product path.
- Paper and `AShareBacktestEngine` do not import those modules.
- `pytest backend/tests/test_crypto_residue_purged.py rebuild/tests/test_safety.py` passes.

## Paper broker slice (#13 / #9 / #10)

- Shared `AShareSpotBroker` used by Paper and `AShareBacktestEngine`.
- Symbol key is `code.market`; T+1 available qty; 100-share lots; cash ledger.
- Paper fill costs are commission + stamp duty + transfer fee from the
  qualifying backtest cost model (default `cn_stock_default`).
- Paper rejects limit-up buy, limit-down sell, halt, and non-open calendar days.

## Out of this slice

- Live trading / auto order.
- Schema migration for `trades.tax` / `trades.transfer_fee` (cash ledger and
  broker events already carry the full fee split).

## Verify

```bash
PYTHONPATH=backend python3 -m pytest backend/tests/test_ashare_paper_broker.py backend/tests/test_final_ashare_contract.py -q
```
