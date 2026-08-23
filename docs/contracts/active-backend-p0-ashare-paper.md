# Backend P0: A-share paper semantics

- Status: in progress
- Issues: #8, #12 (this slice), then #13 / #9 / #10
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

## Next

Issue #13: A-share spot paper broker (cash ledger, T+1, lot 100, calendar).
Issues #9 / #10: align paper fees and limit-up/down/halt with backtest.
