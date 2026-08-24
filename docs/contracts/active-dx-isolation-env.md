# DX: Isolation DB and A-share demo path

- Status: implemented, pending PR review
- Issues: #18 / #19
- Owner: DX

## Goal

Unblock Eva/Leo golden-path checks without a hand-built
`stockpro_bitpro_rebase_dev`, and stop `scripts/run_demo.py` from pointing at
the purged crypto SQLite path.

## In Scope

- One-command provision for `stockpro_bitpro_rebase_dev` (docker-compose or SQL).
- `scripts/check.sh` names that setup path when the isolation URL is missing.
- Retarget `scripts/run_demo.py` to the A-share paper broker / isolation Paper
  list path.

## Out of Scope

- BitPro repository changes.
- New product pages or routes.
- Live trading, production writes, or copying `stockpro_dev` / production data.

## Done Means

- `./scripts/setup_isolation_db.sh` creates the isolation database and prints
  the `DATABASE_URL` Eva should export.
- `./scripts/check.sh` with an empty or non-isolated URL exits with that setup
  command.
- `python3 scripts/run_demo.py` runs an A-share CNY cash-ledger demo and has no
  Kairos / BTC / OKX / SQLite crypto path.

## Verify

```bash
./scripts/setup_isolation_db.sh --print-url
PYTHONPATH=backend python3 -m pytest \
  backend/tests/test_isolation_db_setup.py \
  backend/tests/test_run_demo_ashare.py \
  backend/tests/test_crypto_residue_purged.py -q
PYTHONPATH=backend python3 scripts/run_demo.py
```
