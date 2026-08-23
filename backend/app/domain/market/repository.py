"""Market data repository wrappers."""
from __future__ import annotations

from typing import Dict, List, Optional

from app.db.local_db import db_instance as db
from app.services.kline_file_store import kline_store


class MarketRepository:
    """Repository abstraction for market-related persistence."""

    def update_ticker_cache(self, exchange: str, symbol: str, ticker: Dict) -> None:
        db.update_ticker_cache(exchange, symbol, ticker)

    def get_klines(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> List[Dict]:
        rows = kline_store.read_klines(
            exchange,
            symbol,
            timeframe,
            start_ms=start,
            end_ms=end,
            limit=limit,
        )
        if rows:
            return rows
        return db.get_klines(exchange, symbol, timeframe, limit, start, end)

    def insert_klines(self, exchange: str, symbol: str, timeframe: str, klines: List[Dict]) -> int:
        return kline_store.append_klines(exchange, symbol, timeframe, klines)
