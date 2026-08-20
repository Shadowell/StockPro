"""Explicit PostgreSQL watchlist entries joined to the existing quote cache."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Sequence

import psycopg2.extras


class MarketWatchlistService:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def symbol_key(value: Any) -> str:
        return "".join(re.findall(r"\d", str(value or "")))[:6]

    @classmethod
    def validate_symbol(cls, value: Any) -> str:
        key = cls.symbol_key(value)
        if len(key) != 6:
            raise ValueError("证券代码必须包含 6 位数字")
        return key

    @staticmethod
    def validate_note(value: Any) -> str:
        note = str(value or "").strip()
        if len(note) > 200:
            raise ValueError("自选备注不能超过 200 字")
        return note

    def list_entries(self, owner: str = "admin") -> Dict[str, Any]:
        items = self._rows(
            """
            SELECT w.id,w.owner,w.symbol,w.note,w.created_at,w.updated_at,
                   q.name,q.price,q.change_percent,q.amount,q.turnover,q.volume_ratio,q.amplitude,
                   q.updated_at AS quote_updated_at
            FROM market_watchlist_entries w
            LEFT JOIN all_stocks_realtime q ON regexp_replace(q.code,'[^0-9]','','g')=w.symbol
            WHERE w.owner=%s
            ORDER BY w.created_at DESC,w.id DESC
            """,
            (owner,),
        )
        source_times = [item.get("quote_updated_at") for item in items if item.get("quote_updated_at")]
        return {
            "items": items,
            "total": len(items),
            "source_label": "PostgreSQL 自选清单 + 行情缓存",
            "source_updated_at": max(source_times) if source_times else None,
            "data_status": "available" if items else "empty",
        }

    def add_entry(self, payload: Mapping[str, Any], owner: str = "admin") -> Dict[str, Any]:
        key = self.validate_symbol(payload.get("symbol"))
        note = self.validate_note(payload.get("note"))
        quote = self._row(
            "SELECT code,name FROM all_stocks_realtime WHERE regexp_replace(code,'[^0-9]','','g')=%s ORDER BY updated_at DESC NULLS LAST LIMIT 1",
            (key,),
        )
        if not quote:
            raise ValueError("证券不在当前 A 股行情缓存中")
        return self._row(
            """
            INSERT INTO market_watchlist_entries(owner,symbol,note)
            VALUES (%s,%s,%s)
            ON CONFLICT(owner,symbol) DO UPDATE SET note=EXCLUDED.note,updated_at=NOW()
            RETURNING *
            """,
            (owner, key, note),
        ) or {}

    def delete_entry(self, entry_id: int, owner: str = "admin") -> Dict[str, Any]:
        row = self._row(
            "DELETE FROM market_watchlist_entries WHERE id=%s AND owner=%s RETURNING id,symbol",
            (entry_id, owner),
        )
        if not row:
            raise ValueError("自选条目不存在")
        return {**row, "deleted": True}

    def _rows(self, query: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, tuple(params))
                return [dict(row) for row in cursor.fetchall()]

    def _row(self, query: str, params: Sequence[Any] = ()) -> Dict[str, Any] | None:
        rows = self._rows(query, params)
        return rows[0] if rows else None
