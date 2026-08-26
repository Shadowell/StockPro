#!/usr/bin/env python3
"""Sync full funding-rate history from Binance USD-M into production SQLite.

Why Binance: its fapi/v1/fundingRate endpoint serves the complete history back
to each contract's listing (BTC: 2019), while the OKX endpoint only returns the
latest ~3 months. Cross-exchange funding is itself a valid market-wide
sentiment feature; rows are stored with exchange='binanceusdm' so OKX-native
rows are never mixed.

Idempotent: re-running skips symbols whose latest stored row is fresh.
Run on the production host.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone

DB = "/opt/bitpro/data/crypto_data.db"
SYMBOLS = [
    "ETH", "BTC", "SOL", "XRP", "DOGE", "HYPE", "TRUMP", "PEPE",
    "BICO", "KAITO", "WLD", "ADA", "SHIB", "BNB", "SUI", "LINK",
    "UNI", "ONDO", "AAVE", "BCH", "BOME", "FIL", "AVAX", "NEAR",
    "GPS", "LTC", "PENGU", "XLM", "ORDI", "PEOPLE", "CRV", "ETC",
    "TRX", "JTO", "OP", "ARB", "ETHFI", "ICP",
]
EXCHANGE_TAG = "binanceusdm"
FRESH_WINDOW_MS = 8 * 3600 * 1000 * 2  # skip if last row < 16h old


def get(url: str, retries: int = 3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except Exception as exc:
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))


def main():
    conn = sqlite3.connect(DB)
    now_ms = int(time.time() * 1000)
    report = {"synced": [], "fresh": [], "missing_on_binance": [], "errors": {}}

    for base in SYMBOLS:
        bsym = f"{base}USDT"
        try:
            # probe existence first (cheap)
            probe = get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={bsym}&limit=1")
            if not probe:
                report["missing_on_binance"].append(bsym)
                continue

            latest = conn.execute(
                "SELECT MAX(timestamp) FROM funding_rate_history WHERE exchange=? AND symbol=?",
                (EXCHANGE_TAG, bsym),
            ).fetchone()[0]
            if latest and now_ms - latest < FRESH_WINDOW_MS:
                report["fresh"].append(bsym)
                continue

            start_ms = 1567296000000 if latest is None else latest + 1  # from 2019-09 or incremental
            inserted = 0
            cursor = start_ms
            while True:
                batch = get(
                    f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={bsym}"
                    f"&startTime={cursor}&limit=1000"
                )
                if not batch:
                    break
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO funding_rate_history
                    (exchange, symbol, timestamp, funding_rate, mark_price)
                    VALUES (?, ?, ?, ?, NULL)
                    """,
                    [(EXCHANGE_TAG, bsym, int(r["fundingTime"]), float(r["fundingRate"])) for r in batch],
                )
                inserted += len(batch)
                last_t = max(int(r["fundingTime"]) for r in batch)
                if len(batch) < 1000 or last_t >= now_ms - FRESH_WINDOW_MS:
                    break
                cursor = last_t + 1
                time.sleep(0.12)  # polite rate limit
            conn.commit()
            newest = conn.execute(
                "SELECT datetime(MAX(timestamp)/1000,'unixepoch') FROM funding_rate_history WHERE exchange=? AND symbol=?",
                (EXCHANGE_TAG, bsym),
            ).fetchone()[0]
            report["synced"].append({"symbol": bsym, "inserted": inserted, "newest": newest})
            print(f"{bsym:<12} +{inserted:>5} rows -> {newest}", flush=True)
        except Exception as exc:
            report["errors"][bsym] = repr(exc)[:120]
            print(f"{bsym:<12} ERROR {exc!r}", flush=True)

    conn.close()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = f"/tmp/funding_sync_report_{stamp}.json"
    with open(path, "w") as fh:
        json.dump(report, fh, indent=2)
    total_rows = sum(s["inserted"] for s in report["synced"])
    print(f"\nDONE synced={len(report['synced'])} fresh={len(report['fresh'])} "
          f"missing={len(report['missing_on_binance'])} errors={len(report['errors'])} "
          f"inserted_total={total_rows}\nreport: {path}")


if __name__ == "__main__":
    main()
