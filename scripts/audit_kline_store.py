#!/usr/bin/env python3
"""Audit and repair BitPro file-store K-line quality issues.

The script is production-oriented: scan first, then optionally backup/delete
flagged partitions, resync them from OKX, and mark overlapping backtest results
as data-quality invalidated.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.kline_file_store import (  # noqa: E402
    KlineFileStore,
    KlineStoreConfig,
    find_kline_quality_issues,
)


TIMEFRAME_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}

OKX_BAR_BY_TIMEFRAME = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1H",
    "2h": "2H",
    "4h": "4H",
    "6h": "6H",
    "12h": "12H",
    "1d": "1D",
}


def sanitize_symbol(symbol: str) -> str:
    return str(symbol).replace("/", "-").replace(":", "_")


def unsanitize_symbol(name: str) -> str:
    if "_" in name:
        base, settle = name.split("_", 1)
        return f"{base.replace('-', '/')}:{settle}"
    return name.replace("-", "/")


def date_start_ms(value: str) -> int:
    return int(datetime.strptime(value, "%Y-%m-%d").timestamp() * 1000)


def date_end_ms(value: str) -> int:
    return int(datetime.strptime(f"{value} 23:59:59", "%Y-%m-%d %H:%M:%S").timestamp() * 1000)


def okx_inst_id(symbol: str) -> str:
    value = str(symbol).strip()
    if ":" in value:
        base_quote, _settle = value.split(":", 1)
        return f"{base_quote.replace('/', '-')}-SWAP"
    return value.replace("/", "-")


def _fetch_okx_history_rows(
    *,
    symbol: str,
    timeframe: str,
    start_ms: int,
    end_ms: int,
    max_per_request: int,
    delay_sec: float,
) -> list[dict]:
    bar = OKX_BAR_BY_TIMEFRAME.get(str(timeframe).lower(), str(timeframe))
    inst_id = okx_inst_id(symbol)
    interval_ms = TIMEFRAME_MS.get(str(timeframe).lower(), 3_600_000)
    current_end = int(end_ms) + interval_ms
    rows_by_ts: dict[int, dict] = {}
    limit = max(1, min(int(max_per_request), 100))
    while current_end > start_ms:
        response = requests.get(
            "https://www.okx.com/api/v5/market/history-candles",
            params={"instId": inst_id, "bar": bar, "after": str(current_end), "limit": str(limit)},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or []
        if not data:
            break
        for item in data:
            ts = int(item[0])
            if start_ms <= ts <= end_ms:
                rows_by_ts[ts] = {
                    "timestamp": ts,
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5] or 0),
                }
        oldest = min(int(item[0]) for item in data)
        if oldest >= current_end:
            break
        current_end = oldest
        if delay_sec > 0:
            time.sleep(delay_sec)
    return [rows_by_ts[ts] for ts in sorted(rows_by_ts)]


def _iter_symbol_dirs(exchange_dir: Path, symbols: Iterable[str] | None) -> list[tuple[str, Path]]:
    if symbols:
        return [(symbol, exchange_dir / sanitize_symbol(symbol)) for symbol in symbols]
    if not exchange_dir.exists():
        return []
    return [
        (unsanitize_symbol(path.name), path)
        for path in sorted(exchange_dir.iterdir())
        if path.is_dir() and not path.name.startswith("_")
    ]


def _iter_timeframe_dirs(symbol_dir: Path, timeframes: Iterable[str] | None) -> list[tuple[str, Path]]:
    if timeframes:
        return [(timeframe, symbol_dir / timeframe) for timeframe in timeframes]
    if not symbol_dir.exists():
        return []
    return [
        (path.name, path)
        for path in sorted(symbol_dir.iterdir())
        if path.is_dir() and not path.name.startswith("_")
    ]


def audit_store(
    *,
    root_dir: str | Path,
    exchange: str = "okx",
    symbols: Iterable[str] | None = None,
    timeframes: Iterable[str] | None = None,
) -> list[dict]:
    root = Path(root_dir)
    store = KlineFileStore(KlineStoreConfig(root_dir=root, fmt="parquet"))
    findings: list[dict] = []
    for symbol, symbol_dir in _iter_symbol_dirs(root / exchange, symbols):
        if not symbol_dir.exists():
            continue
        for timeframe, timeframe_dir in _iter_timeframe_dirs(symbol_dir, timeframes):
            if not timeframe_dir.exists():
                continue
            df = store.read_dataframe(exchange, symbol, timeframe)
            if df.empty:
                continue
            issues = find_kline_quality_issues(df, exchange=exchange, symbol=symbol, timeframe=timeframe)
            if not issues:
                continue
            first_issue_ts = min(int(issue.get("first_timestamp") or 0) for issue in issues)
            last_issue_ts = max(
                int(issue.get("last_timestamp") or issue.get("first_timestamp") or 0)
                for issue in issues
            )
            finding = {
                "exchange": exchange,
                "symbol": symbol,
                "timeframe": timeframe,
                "row_count": int(len(df)),
                "first_timestamp": int(df["timestamp"].min()),
                "last_timestamp": int(df["timestamp"].max()),
                "first_issue_timestamp": first_issue_ts,
                "last_issue_timestamp": last_issue_ts,
                "issues": issues,
                "path": str(timeframe_dir),
            }
            findings.append(finding)
    return findings


def ensure_backtest_quality_columns(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(backtest_results)").fetchall()}
    additions = {
        "data_quality_status": "ALTER TABLE backtest_results ADD COLUMN data_quality_status TEXT",
        "data_quality_message": "ALTER TABLE backtest_results ADD COLUMN data_quality_message TEXT",
        "data_quality_checked_at": "ALTER TABLE backtest_results ADD COLUMN data_quality_checked_at TEXT",
    }
    for column, statement in additions.items():
        if column not in cols:
            conn.execute(statement)


def _json_loads(value):
    if not value:
        return None
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def _row_symbols(row: sqlite3.Row) -> set[str]:
    symbols: set[str] = set()
    raw_symbols = _json_loads(row["symbols"] if "symbols" in row.keys() else None)
    if isinstance(raw_symbols, list):
        symbols.update(str(item) for item in raw_symbols if item)
    elif isinstance(raw_symbols, str):
        symbols.add(raw_symbols)

    cfg = _json_loads(row["config"] if "config" in row.keys() else None)
    if isinstance(cfg, dict):
        for key in ("trade_symbols", "symbols", "feed_symbols"):
            value = cfg.get(key)
            if isinstance(value, list):
                symbols.update(str(item) for item in value if item)
            elif isinstance(value, str):
                symbols.add(value)
        if cfg.get("target_symbol"):
            symbols.add(str(cfg["target_symbol"]))
    return symbols


def _row_timeframe(row: sqlite3.Row) -> str | None:
    if row["timeframe"]:
        return str(row["timeframe"]).lower()
    cfg = _json_loads(row["config"] if "config" in row.keys() else None)
    if isinstance(cfg, dict) and cfg.get("timeframe"):
        return str(cfg["timeframe"]).lower()
    return None


def _row_overlaps_finding(row: sqlite3.Row, finding: dict) -> bool:
    if _row_timeframe(row) != str(finding["timeframe"]).lower():
        return False
    if finding["symbol"] not in _row_symbols(row):
        return False
    try:
        row_start = date_start_ms(row["start_date"])
        row_end = date_end_ms(row["end_date"])
    except Exception:
        return True
    issue_start = int(finding.get("first_issue_timestamp") or finding.get("first_timestamp") or 0)
    issue_end = int(finding.get("last_issue_timestamp") or issue_start)
    return row_start <= issue_end and row_end >= issue_start


def mark_backtest_results_invalidated(db_path: str | Path, findings: list[dict]) -> int:
    if not findings:
        return 0
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_backtest_quality_columns(conn)
    backtest_cols = {row[1] for row in conn.execute("PRAGMA table_info(backtest_results)").fetchall()}
    select_fields = ["br.id", "br.strategy_id", "br.start_date", "br.end_date"]
    if "timeframe" in backtest_cols:
        select_fields.append("br.timeframe")
    else:
        select_fields.append("NULL AS timeframe")
    select_fields.extend(["s.config", "s.symbols"])
    where_sql = "WHERE COALESCE(br.status, 'completed') = 'completed'" if "status" in backtest_cols else ""
    rows = conn.execute(
        f"""
        SELECT {", ".join(select_fields)}
        FROM backtest_results br
        LEFT JOIN strategies s ON s.id = br.strategy_id
        {where_sql}
        """
    ).fetchall()
    checked_at = datetime.now().isoformat(timespec="seconds")
    marked_ids: set[int] = set()
    for row in rows:
        messages = []
        for finding in findings:
            if not _row_overlaps_finding(row, finding):
                continue
            issue_messages = [
                str(issue.get("message") or issue.get("type"))
                for issue in finding.get("issues", [])[:2]
            ]
            messages.append(
                f"{finding['symbol']} {finding['timeframe']} 缓存审计发现污染；"
                + "；".join(issue_messages)
            )
        if not messages:
            continue
        conn.execute(
            """
            UPDATE backtest_results
            SET data_quality_status = 'invalidated',
                data_quality_message = ?,
                data_quality_checked_at = ?
            WHERE id = ?
            """,
            ("；".join(messages[:3]) + "。该历史回测结果不可继续信任，请清理重同步后重跑。", checked_at, row["id"]),
        )
        marked_ids.add(int(row["id"]))
    conn.commit()
    conn.close()
    return len(marked_ids)


def backup_flagged_files(root_dir: str | Path, findings: list[dict], backup_dir: str | Path) -> int:
    root = Path(root_dir)
    backup_root = Path(backup_dir)
    copied = 0
    for finding in findings:
        source_dir = root / finding["exchange"] / sanitize_symbol(finding["symbol"]) / finding["timeframe"]
        if not source_dir.exists():
            continue
        target_dir = backup_root / finding["exchange"] / sanitize_symbol(finding["symbol"]) / finding["timeframe"]
        target_dir.mkdir(parents=True, exist_ok=True)
        for file_path in sorted([*source_dir.glob("*.parquet"), *source_dir.glob("*.csv")]):
            shutil.copy2(file_path, target_dir / file_path.name)
            copied += 1
    return copied


def delete_flagged_files(root_dir: str | Path, findings: list[dict]) -> int:
    root = Path(root_dir)
    deleted = 0
    for finding in findings:
        source_dir = root / finding["exchange"] / sanitize_symbol(finding["symbol"]) / finding["timeframe"]
        if not source_dir.exists():
            continue
        for file_path in sorted([*source_dir.glob("*.parquet"), *source_dir.glob("*.csv")]):
            file_path.unlink(missing_ok=True)
            deleted += 1
    return deleted


def resync_from_okx(
    *,
    root_dir: str | Path,
    findings: list[dict],
    start_date: str,
    end_date: str | None,
    max_per_request: int = 300,
    delay_sec: float = 0.2,
) -> int:
    store = KlineFileStore(KlineStoreConfig(root_dir=Path(root_dir), fmt="parquet"))
    total = 0
    end_ms = date_end_ms(end_date) if end_date else int(time.time() * 1000)
    for finding in findings:
        if finding.get("exchange") != "okx":
            raise ValueError(f"Only okx resync is supported, got {finding.get('exchange')}")
        symbol = finding["symbol"]
        timeframe = finding["timeframe"]
        rows = _fetch_okx_history_rows(
            symbol=symbol,
            timeframe=timeframe,
            start_ms=date_start_ms(start_date),
            end_ms=end_ms,
            max_per_request=max_per_request,
            delay_sec=delay_sec,
        )
        if not rows:
            continue
        store.append_klines(finding["exchange"], symbol, timeframe, rows)
        total += len(rows)
    return total


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit BitPro K-line file-store data quality.")
    parser.add_argument("--root-dir", default=str(PROJECT_ROOT / "data" / "klines"))
    parser.add_argument("--exchange", default="okx")
    parser.add_argument("--symbol", action="append", dest="symbols")
    parser.add_argument("--timeframe", action="append", dest="timeframes")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--mark-backtests", action="store_true")
    parser.add_argument("--backup-dir", default=None)
    parser.add_argument("--delete-flagged", action="store_true")
    parser.add_argument("--resync", action="store_true")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    findings = audit_store(
        root_dir=args.root_dir,
        exchange=args.exchange,
        symbols=args.symbols,
        timeframes=args.timeframes,
    )
    summary = {"findings": findings, "marked_backtests": 0, "backed_up_files": 0, "deleted_files": 0, "resynced_rows": 0}
    if args.mark_backtests:
        if not args.db_path:
            raise SystemExit("--mark-backtests requires --db-path")
        summary["marked_backtests"] = mark_backtest_results_invalidated(args.db_path, findings)
    if args.backup_dir:
        summary["backed_up_files"] = backup_flagged_files(args.root_dir, findings, args.backup_dir)
    if args.delete_flagged:
        if not args.backup_dir:
            raise SystemExit("--delete-flagged requires --backup-dir")
        summary["deleted_files"] = delete_flagged_files(args.root_dir, findings)
    if args.resync:
        if not args.start_date:
            raise SystemExit("--resync requires --start-date")
        summary["resynced_rows"] = resync_from_okx(
            root_dir=args.root_dir,
            findings=findings,
            start_date=args.start_date,
            end_date=args.end_date,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if findings and not (args.mark_backtests or args.delete_flagged or args.resync) else 0


if __name__ == "__main__":
    raise SystemExit(main())
