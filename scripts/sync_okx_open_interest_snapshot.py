#!/usr/bin/env python3
"""Snapshot current OKX swap open interest into production SQLite.

OKX offers no free OI *history* endpoint, so the only path to a long OI series
is accumulating our own snapshots. This script pulls ALL live USDT swaps in one
batch call (/public/open-interest?instType=SWAP) and upserts into the existing
open_interest_history table. Safe to run repeatedly (e.g. hourly via cron);
each run adds one snapshot per instrument.

Run on the production host.
"""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.request
from urllib.error import HTTPError

DB = "/opt/bitpro/data/crypto_data.db"


def get(url: str, retries: int = 4):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "BitPro/1.0 (+https://github.com/Shadowell/BitPro)"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except HTTPError as exc:
            last = exc
            if exc.code in (403, 429):  # rate limited: back off hard
                time.sleep(30 * (attempt + 1))
            else:
                raise
    raise last


def okx_inst_to_symbol(inst_id: str) -> str | None:
    # BTC-USDT-SWAP -> BTC/USDT:USDT ; skip non-USDT settles
    parts = inst_id.split("-")
    if len(parts) == 3 and parts[1] == "USDT" and parts[2] == "SWAP":
        return f"{parts[0]}/USDT:{parts[2]}"
    return None


def main():
    data = get("https://www.okx.com/api/v5/public/open-interest?instType=SWAP").get("data") or []
    now_ms = int(time.time() * 1000)
    conn = sqlite3.connect(DB)
    inserted = 0
    for row in data:
        symbol = okx_inst_to_symbol(row.get("instId", ""))
        if not symbol:
            continue
        try:
            oi_ccy = float(row.get("oiCcy") or 0)
            oi_usd = float(row.get("oiUsd") or 0) or float(row.get("oi") or 0)
        except (TypeError, ValueError):
            continue
        if oi_ccy <= 0 and oi_usd <= 0:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO open_interest_history
            (exchange, symbol, timestamp, open_interest, open_interest_value)
            VALUES ('okx', ?, ?, ?, ?)
            """,
            (symbol, now_ms, oi_ccy, oi_usd),
        )
        inserted += 1
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM open_interest_history").fetchone()[0]
    conn.close()
    print(f"[{now_ms}] snapshot instruments={inserted} total_rows={total}")


if __name__ == "__main__":
    main()
