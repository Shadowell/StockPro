"""Read-only PostgreSQL gateway for sealed backtest inputs."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

import psycopg2
import psycopg2.extras

from app.core.config import settings
from app.services.ashare_execution import explicit_instrument_key, storage_symbol


COVERAGE_DATASETS = {"daily_bars", "trade_calendar", "benchmark_bars", "price_limits"}
SYMBOL_DATASETS = {"daily_bars", "price_limits", "suspensions", "corporate_actions"}


class PostgresBacktestInputGateway:
    def __init__(self, database_url: str | None = None, *, connection_factory: Callable[..., object] = psycopg2.connect) -> None:
        self.database_url = database_url or settings.DATABASE_URL
        self.connection_factory = connection_factory

    def _connect(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for sealed backtest inputs")
        connection = self.connection_factory(self.database_url)
        connection.set_session(readonly=True, autocommit=False)
        return connection

    def get_strategy(self, strategy_id: int | str) -> dict | None:
        raw = str(strategy_id)
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM strategy_versions
                    WHERE status <> 'archived' AND (id::text=%s OR legacy_strategy_id::text=%s)
                    ORDER BY version DESC,created_at DESC LIMIT 1
                    """,
                    (raw, raw),
                )
                row = cursor.fetchone()
        return dict(row) if row else None

    def resolve_snapshot(self, *, start_date: str, end_date: str, snapshot_id: int | None, required_datasets: set[str]) -> dict:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT s.id,s.name,s.status,s.knowledge_cutoff_at,s.manifest_hash,s.created_at,
                           i.dataset_code,p.start_date,p.end_date,p.row_count
                    FROM dataset_snapshots s
                    JOIN dataset_snapshot_items i ON i.snapshot_id=s.id
                    JOIN dataset_partitions p ON p.id=i.partition_id
                    WHERE s.status='sealed' AND (%s IS NULL OR s.id=%s)
                    ORDER BY s.id DESC,i.dataset_code,p.start_date
                    """,
                    (snapshot_id, snapshot_id),
                )
                rows = [dict(row) for row in cursor.fetchall()]
        grouped: dict[int, dict[str, Any]] = {}
        for row in rows:
            snapshot = grouped.setdefault(
                int(row["id"]),
                {
                    "id": int(row["id"]),
                    "name": row["name"],
                    "status": row["status"],
                    "knowledge_cutoff_at": row["knowledge_cutoff_at"],
                    "manifest_hash": row["manifest_hash"],
                    "created_at": row["created_at"],
                    "coverage": defaultdict(list),
                },
            )
            snapshot["coverage"][str(row["dataset_code"])].append(row)
        for snapshot in grouped.values():
            coverage = snapshot["coverage"]
            if not required_datasets.issubset(coverage):
                continue
            valid = True
            for code in COVERAGE_DATASETS:
                items = coverage.get(code) or []
                starts = [str(item["start_date"]) for item in items if item.get("start_date")]
                ends = [str(item["end_date"]) for item in items if item.get("end_date")]
                if not starts or not ends or min(starts) > start_date or max(ends) < end_date:
                    valid = False
                    break
            if valid:
                snapshot["datasets"] = sorted(coverage)
                del snapshot["coverage"]
                return snapshot
        target = f" #{snapshot_id}" if snapshot_id is not None else ""
        raise ValueError(f"没有覆盖 {start_date} 至 {end_date} 的 sealed 数据快照{target}")

    def resolve_pool(self, *, snapshot_id: int, pool_snapshot_id: int | None) -> dict:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT s.id,s.dataset_snapshot_id,s.trade_date,s.knowledge_cutoff_at,s.manifest_hash,
                           s.member_count,s.status,p.name
                    FROM stock_pool_snapshots s JOIN stock_pools p ON p.id=s.pool_id
                    WHERE s.status='sealed' AND s.dataset_snapshot_id=%s
                      AND (%s IS NULL OR s.id=%s)
                    ORDER BY s.id DESC LIMIT 1
                    """,
                    (snapshot_id, pool_snapshot_id, pool_snapshot_id),
                )
                row = cursor.fetchone()
                if not row:
                    raise ValueError("sealed 数据快照没有可用股票池")
                pool = dict(row)
                cursor.execute(
                    "SELECT symbol FROM stock_pool_snapshot_members WHERE snapshot_id=%s ORDER BY ordinal",
                    (int(pool["id"]),),
                )
                pool["symbols"] = [str(item["symbol"]) for item in cursor.fetchall()]
        return pool

    def load_dataset(self, snapshot_id: int, dataset_code: str, *, symbols: list[str], start_date: str, end_date: str) -> list[dict]:
        query = """
            SELECT r.payload
            FROM dataset_snapshot_items i
            JOIN dataset_partition_records r ON r.partition_id=i.partition_id
            WHERE i.snapshot_id=%s AND i.dataset_code=%s
              AND COALESCE(r.payload->>'trade_date',r.payload->>'ex_date','') BETWEEN %s AND %s
        """
        params: list[Any] = [int(snapshot_id), str(dataset_code), start_date, end_date]
        if dataset_code in SYMBOL_DATASETS and symbols:
            aliases = sorted({alias for symbol in symbols for alias in (symbol, storage_symbol(symbol))})
            query += " AND COALESCE(r.payload->>'symbol',r.payload->>'ts_code','')=ANY(%s)"
            params.append(aliases)
        elif dataset_code == "benchmark_bars":
            query += " AND COALESCE(r.payload->>'symbol',r.payload->>'ts_code','')=ANY(%s)"
            params.append(["000300.SH", "SH_000300"])
        query += " ORDER BY COALESCE(r.payload->>'trade_date',r.payload->>'ex_date',''),r.record_ordinal LIMIT 1000000"
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [dict(row["payload"]) for row in cursor.fetchall()]
