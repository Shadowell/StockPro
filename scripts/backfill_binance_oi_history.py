#!/usr/bin/env python3
"""Backfill OI history from Binance Vision daily metrics archives.

Source: https://data.binance.vision/data/futures/um/daily/metrics/<SYM>/
Files contain 5-minute rows: sum_open_interest, sum_open_interest_value,
toptrader/retail long-short ratios, taker buy/sell vol ratio.

We downsample to HOURLY (last 5m row of each hour) and store OI rows into
open_interest_history with exchange='binanceusdm' (isolated from OKX
forward-accumulated rows). Idempotent: existing (symbol, timestamp) rows are
skipped via INSERT OR IGNORE.

Run on the production host. ~39 symbols x ~1690 days of small zip files;
use --symbols/--start to control scope. Parallel downloads with polite delay.
"""
from __future__ import annotations

import argparse
import io
import sqlite3
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

import urllib.request

DB = "/opt/bitpro/data/crypto_data.db"
BASE = "https://data.binance.vision/data/futures/um/daily/metrics/{sym}/{sym}-metrics-{day}.zip"

SYMBOLS = [
    "BTC", "ETH", "SOL", "XRP", "DOGE", "HYPE", "TRUMP", "PEPE",
    "BICO", "KAITO", "WLD", "ADA", "SHIB", "BNB", "SUI", "LINK",
    "UNI", "ONDO", "AAVE", "BCH", "BOME", "FIL", "AVAX", "NEAR",
    "GPS", "LTC", "PENGU", "XLM", "ORDI", "PEOPLE", "CRV", "ETC",
    "TRX", "JTO", "OP", "ARB", "ETHFI", "ICP",
]


def fetch_day(sym_usdt: str, day: str, retries: int = 2):
    url = BASE.format(sym=sym_usdt, day=day)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "BitPro/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                blob = r.read()
            zf = zipfile.ZipFile(io.BytesIO(blob))
            name = zf.namelist()[0]
            return zf.read(name).decode().strip().split("\n")
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(1.0)


def parse_hourly_oi(lines, sym_usdt: str, day: str):
    """Keep the last 5-minute row of each UTC hour; return hourly rows."""
    out = []
    last_by_hour = {}
    header = lines[0].split(",")
    idx = {c: i for i, c in enumerate(header)}
    for line in lines[1:]:
        parts = line.split(",")
        try:
            ts_str = parts[idx["create_time"]]
            # '2024-06-15 00:05:00' is UTC in binance vision metrics
            dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            hour_key = dt.strftime("%Y-%m-%dT%H")
            last_by_hour[hour_key] = parts
        except (ValueError, KeyError):
            continue
    for hour_key, parts in sorted(last_by_hour.items()):
        try:
            ts_str = parts[0]
            dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            ts_ms = int(dt.timestamp() * 1000)
            oi_ccy = float(parts[2])   # sum_open_interest (base ccy)
            oi_usd = float(parts[3])   # sum_open_interest_value (USDT)
            out.append((sym_usdt, ts_ms, oi_ccy, oi_usd))
        except (ValueError, IndexError):
            continue
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--commit-every", type=int, default=40, help="commit per N days processed per symbol")
    args = parser.parse_args()

    conn = sqlite3.connect(DB)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS open_interest_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exchange TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            open_interest REAL NOT NULL,
            open_interest_value REAL,
            UNIQUE(exchange, symbol, timestamp)
        )
        """
    )
    conn.commit()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    days = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]

    # pre-compute which (symbol, day) already has rows to skip re-downloading
    def has_data(bsym: str, day: str) -> bool:
        ts = int(datetime.fromisoformat(day + "T12:00:00+00:00").timestamp() * 1000)
        row = conn.execute(
            "SELECT 1 FROM open_interest_history WHERE exchange='binanceusdm' AND symbol=? "
            "AND timestamp BETWEEN ? AND ? LIMIT 1",
            (bsym, ts - 86_400_000, ts + 86_400_000),
        ).fetchone()
        return row is not None

    tasks = []
    for base in symbols:
        bsym = f"{base}USDT"
        missing = [d for d in days if not has_data(bsym, d)]
        print(f"{bsym}: {len(missing)}/{len(days)} days to fetch", flush=True)
        for d in missing:
            tasks.append((bsym, d))

    print(f"total day-files to fetch: {len(tasks)}", flush=True)
    inserted_total = 0
    done = 0
    t0 = time.time()

    def work(task):
        bsym, d = task
        lines = fetch_day(bsym, d)
        if not lines or len(lines) < 2:
            return task, []
        return task, parse_hourly_oi(lines, bsym, d)

    pending_buffer = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(work, t): t for t in tasks}
        for fut in as_completed(futures):
            task, rows = fut.result()
            done += 1
            pending_buffer.extend(rows)
            if len(pending_buffer) >= 5000:
                conn.executemany(
                    "INSERT OR IGNORE INTO open_interest_history (exchange, symbol, timestamp, open_interest, open_interest_value) "
                    "VALUES ('binanceusdm', ?, ?, ?, ?)",
                    pending_buffer,
                )
                conn.commit()
                inserted_total += len(pending_buffer)
                pending_buffer = []
            if done % 500 == 0:
                rate = done / max(time.time() - t0, 1)
                eta_min = (len(tasks) - done) / max(rate, 0.01) / 60
                print(f"progress {done}/{len(tasks)} ({rate:.1f}/s, ETA {eta_min:.0f}m) inserted~{inserted_total}", flush=True)

    if pending_buffer:
        conn.executemany(
            "INSERT OR IGNORE INTO open_interest_history (exchange, symbol, timestamp, open_interest, open_interest_value) "
            "VALUES ('binanceusdm', ?, ?, ?, ?)",
            pending_buffer,
        )
        conn.commit()
        inserted_total += len(pending_buffer)

    total = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT symbol), datetime(MIN(timestamp/1000,'unixepoch')), datetime(MAX(timestamp/1000,'unixepoch')) "
        "FROM open_interest_history WHERE exchange='binanceusdm'"
    ).fetchone()
    conn.close()
    print(f"\nDONE inserted={inserted_total} binanceusdm OI rows={total[0]} symbols={total[1]} {total[2]} ~ {total[3]}", flush=True)


if __name__ == "__main__":
    main()
