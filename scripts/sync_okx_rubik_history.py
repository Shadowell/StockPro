#!/usr/bin/env python3
"""Sync OKX-native sentiment/flow history into production SQLite.

Sources (all public OKX endpoints, verified reachable from the host):
- rubik/stat/taker-volume            : daily taker sell/buy volume, ~180d depth -> metric='taker_volume'
- rubik/stat/contracts/long-short-account-ratio : ~180d ratio      -> metric='long_short_ratio'
- rubik/stat/margin/loan-ratio       : margin borrowing sentiment        -> metric='margin_loan_ratio'

Storage: table okx_rubik_stats (metric, ccy, timestamp, value, value2) with
UNIQUE(metric, ccy, timestamp); idempotent re-runs only fill gaps.
Note on depth limits measured on 2026-08-24: taker-volume & long-short ~180 days,
funding rate ~3 months (already collected elsewhere), no free OI *history* —
OI is accumulated forward by sync_okx_open_interest_snapshot.py.
"""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.request

DB = "/opt/bitpro/data/crypto_data.db"
CCYS = [
    "ETH", "BTC", "SOL", "XRP", "DOGE", "HYPE", "TRUMP", "PEPE",
    "BICO", "KAITO", "WLD", "ADA", "SHIB", "BNB", "SUI", "LINK",
    "UNI", "ONDO", "AAVE", "BCH", "BOME", "FIL", "AVAX", "NEAR",
    "GPS", "LTC", "PENGU", "XLM", "ORDI", "PEOPLE", "CRV", "ETC",
    "TRX", "JTO", "OP", "ARB", "ETHFI", "ICP",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS okx_rubik_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric TEXT NOT NULL,
    ccy TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    value REAL NOT NULL,
    value2 REAL,
    UNIQUE(metric, ccy, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_okx_rubik_metric_ccy_ts
    ON okx_rubik_stats(metric, ccy, timestamp);
"""


def get(url: str, retries: int = 3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "BitPro/1.0 (+https://github.com/Shadowell/BitPro)"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except Exception as exc:
            last = exc
            time.sleep(5.0 * (attempt + 1))
    raise last


def ensure_table(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_rows(conn, metric, ccy, rows, two_values=False):
    payload = []
    for row in rows:
        ts = int(row[0])
        v = float(row[1])
        v2 = float(row[2]) if two_values and len(row) > 2 else None
        payload.append((metric, ccy, ts, v, v2))
    conn.executemany(
        "INSERT OR IGNORE INTO okx_rubik_stats (metric, ccy, timestamp, value, value2) VALUES (?,?,?,?,?)",
        payload,
    )
    return len(payload)


def main():
    conn = sqlite3.connect(DB)
    ensure_table(conn)
    stats = {"taker_volume": 0, "long_short_ratio": 0, "margin_loan_ratio": 0}
    errors = {}

    for ccy in CCYS:
        # 1) taker flow: [ts, sellVol, buyVol]
        try:
            r = get(f"https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy={ccy}&instType=CONTRACTS&period=1D")
            rows = r.get("data") or []
            if rows:
                stats["taker_volume"] += upsert_rows(conn, "taker_volume", ccy, rows, two_values=True)
        except Exception as exc:
            errors[f"taker:{ccy}"] = repr(exc)[:80]
        time.sleep(1.2)

        # 2) long/short account ratio: [ts, ratio]
        try:
            r = get(f"https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy={ccy}&period=1D")
            rows = r.get("data") or []
            if rows:
                stats["long_short_ratio"] += upsert_rows(conn, "long_short_ratio", ccy, rows)
        except Exception as exc:
            errors[f"lsr:{ccy}"] = repr(exc)[:80]
        time.sleep(1.2)

    # 3) margin loan ratio is per-ccy too but shallower pool; best-effort
    for ccy in ("BTC", "ETH", "SOL"):
        try:
            r = get(f"https://www.okx.com/api/v5/rubik/stat/margin/loan-ratio?ccy={ccy}")
            rows = r.get("data") or []
            if rows:
                stats["margin_loan_ratio"] += upsert_rows(conn, "margin_loan_ratio", ccy, rows)
        except Exception as exc:
            errors[f"margin:{ccy}"] = repr(exc)[:80]
        time.sleep(0.12)

    conn.commit()
    counts = conn.execute(
        "SELECT metric, COUNT(*), MIN(datetime(timestamp/1000,'unixepoch')), MAX(datetime(timestamp/1000,'unixepoch')) "
        "FROM okx_rubik_stats GROUP BY metric"
    ).fetchall()
    conn.close()
    for m, n, t0, t1 in counts:
        print(f"{m:<20} rows={n:>7} {t0} ~ {t1}")
    print(f"inserted this run: {stats} errors: {len(errors)}")
    if errors:
        print(json.dumps(errors, indent=1)[:500])


if __name__ == "__main__":
    main()
