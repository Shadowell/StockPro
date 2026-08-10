"""Authoritative local A-share trading-date resolution.

Trading workflows may only use dates published by the normalized TuShare
``trade_calendar`` dataset.  Weekends are deterministically closed; uncovered
weekdays remain unknown and are blocked instead of being guessed open.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional, Sequence

import psycopg2.extras


class TradingDateService:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def normalize(value: Any) -> str:
        text = str(value or "").strip()[:10]
        try:
            return date.fromisoformat(text).isoformat()
        except (TypeError, ValueError) as exc:
            raise ValueError("交易日期必须为 YYYY-MM-DD") from exc

    def status(self, value: Any) -> str:
        target = self.normalize(value)
        row = self._row(
            """
            SELECT CASE
                     WHEN lower(COALESCE(r.payload->>'is_open', 'false'))
                          IN ('1','true','t','y','yes','open') THEN TRUE
                     ELSE FALSE
                   END AS is_open
            FROM dataset_partition_records r
            JOIN dataset_partitions p ON p.id = r.partition_id
            JOIN dataset_definitions d ON d.id = p.dataset_id
            WHERE d.code = 'trade_calendar'
              AND p.status = 'published'
              AND r.payload->>'trade_date' = %s
            ORDER BY p.created_at DESC, r.record_ordinal DESC
            LIMIT 1
            """,
            (target,),
        )
        if row is not None:
            return "open" if bool(row.get("is_open")) else "closed"
        if date.fromisoformat(target).weekday() >= 5:
            return "closed"
        return "unknown"

    def latest_open_date(self, on_or_before: Any = None) -> Optional[str]:
        boundary = self.normalize(on_or_before or date.today().isoformat())
        row = self._row(
            """
            WITH ranked AS (
                SELECT r.payload->>'trade_date' AS trade_date,
                       CASE
                         WHEN lower(COALESCE(r.payload->>'is_open', 'false'))
                              IN ('1','true','t','y','yes','open') THEN TRUE
                         ELSE FALSE
                       END AS is_open,
                       ROW_NUMBER() OVER (
                           PARTITION BY r.payload->>'trade_date'
                           ORDER BY p.created_at DESC, r.record_ordinal DESC
                       ) AS rank
                FROM dataset_partition_records r
                JOIN dataset_partitions p ON p.id = r.partition_id
                JOIN dataset_definitions d ON d.id = p.dataset_id
                WHERE d.code = 'trade_calendar'
                  AND p.status = 'published'
                  AND r.payload ? 'trade_date'
                  AND (r.payload->>'trade_date')::date <= %s::date
            )
            SELECT trade_date
            FROM ranked
            WHERE rank = 1 AND is_open = TRUE
            ORDER BY trade_date DESC
            LIMIT 1
            """,
            (boundary,),
        )
        return str(row["trade_date"])[:10] if row and row.get("trade_date") else None

    def resolve_market_data_date(self, value: Any = None, *, on_or_before: Any = None) -> str:
        if value is None or not str(value).strip():
            latest = self.latest_open_date(on_or_before)
            if not latest:
                raise ValueError("本地交易日历没有可用的最近开放日")
            return latest
        target = self.normalize(value)
        state = self.status(target)
        if state == "closed":
            raise ValueError(f"{target} 为非交易日，不允许创建行情或因子分区；维护任务请使用维护任务类型")
        if state == "unknown":
            raise ValueError(f"交易日历未覆盖 {target}，为避免伪造行情分区已阻断任务")
        return target

    def _row(self, query: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()
                return dict(row) if row else None
