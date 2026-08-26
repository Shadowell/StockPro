"""Read-only A-share PostgreSQL repository behind the original BitPro market API."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

import psycopg2

from app.core.config import settings


class MarketRepository:
    def __init__(
        self,
        database_url: str | None = None,
        *,
        connection_factory: Callable[..., object] = psycopg2.connect,
    ) -> None:
        self.database_url = database_url or settings.DATABASE_URL
        self.connection_factory = connection_factory

    def _connect(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for the A-share market port")
        connection = self.connection_factory(self.database_url)
        connection.set_session(readonly=True, autocommit=False)
        return connection

    @staticmethod
    def _canonical_symbol(raw: str) -> str:
        value = str(raw or "").strip().upper()
        if "." in value:
            return value
        if "_" in value:
            exchange, digits = value.split("_", 1)
            return f"{digits}.{exchange}"
        exchange = "SH" if value.startswith(("5", "6", "9")) else ("BJ" if value.startswith(("4", "8")) else "SZ")
        return f"{value}.{exchange}"

    @classmethod
    def _storage_symbol(cls, raw: str) -> str:
        canonical = cls._canonical_symbol(raw)
        digits, exchange = canonical.rsplit(".", 1)
        return f"{exchange}_{digits}"

    @staticmethod
    def _timestamp_ms(value: datetime | None) -> int | None:
        if value is None:
            return None
        observed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return int(observed.timestamp() * 1000)

    def list_symbols(self, asset_class: str, limit: int = 5000) -> List[str]:
        bounded = max(1, min(int(limit), 10000))
        normalized = str(asset_class or "stock").lower()
        query = "SELECT symbol FROM instrument_definitions"
        params: list[object] = []
        if normalized != "all":
            query += " WHERE asset_class=%s"
            params.append(normalized)
        query += " ORDER BY exchange,symbol LIMIT %s"
        params.append(bounded)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, tuple(params))
                return [self._canonical_symbol(row[0]) for row in cursor.fetchall()]

    def list_tickers(self, symbols: Optional[List[str]] = None) -> List[Dict]:
        requested = [self._storage_symbol(symbol) for symbol in symbols or []]
        query = """
            SELECT code,price,change_percent,volume,amount,updated_at
            FROM all_stocks_realtime
        """
        params: tuple[object, ...] = ()
        if requested:
            query += " WHERE code = ANY(%s)"
            params = (requested,)
        query += " ORDER BY code"
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
        return [
            {
                "exchange": self._canonical_symbol(row[0]).rsplit(".", 1)[1],
                "symbol": self._canonical_symbol(row[0]),
                "last": float(row[1] or 0),
                "changePercent": float(row[2] or 0),
                "change_percent": float(row[2] or 0),
                "volume": float(row[3] or 0),
                "quoteVolume": float(row[4] or 0),
                "timestamp": self._timestamp_ms(row[5]),
            }
            for row in rows
        ]

    def get_klines(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> List[Dict]:
        if timeframe != "1d":
            return []
        query = """
            SELECT date,open,high,low,close,volume,turnover
            FROM stock_history WHERE symbol=%s
        """
        params: list[object] = [self._storage_symbol(symbol)]
        if start is not None:
            query += " AND date >= %s"
            params.append(datetime.fromtimestamp(start / 1000, tz=timezone.utc).date())
        if end is not None:
            query += " AND date <= %s"
            params.append(datetime.fromtimestamp(end / 1000, tz=timezone.utc).date())
        query += " ORDER BY date DESC LIMIT %s"
        params.append(max(1, min(int(limit), 2000)))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, tuple(params))
                rows = list(reversed(cursor.fetchall()))
        return [
            {
                "timestamp": int(datetime.combine(row[0], datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5] or 0),
                "quote_volume": float(row[6] or 0),
            }
            for row in rows
        ]

    def get_orderbook(self, exchange: str, symbol: str, limit: int) -> Dict:
        return {
            "exchange": exchange,
            "symbol": self._canonical_symbol(symbol),
            "bids": [],
            "asks": [],
            "data_status": "empty",
            "unavailable_reason": "PostgreSQL currently has no A-share order-book cache",
        }

    def get_trades(self, exchange: str, symbol: str, limit: int) -> List[Dict]:
        return []

    def market_pulse(self) -> Dict:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*),COUNT(*) FILTER(WHERE change_percent>0),COUNT(*) FILTER(WHERE change_percent<0),COALESCE(SUM(amount),0),COALESCE(AVG(change_percent),0),MAX(updated_at) FROM all_stocks_realtime")
                instruments, rise, fall, turnover, average_change, updated_at = cursor.fetchone()
                cursor.execute("SELECT COUNT(*),MIN(date),MAX(date) FROM stock_history")
                daily_count, first_date, last_date = cursor.fetchone()
        return {"instrument_count": instruments, "rise_count": rise, "fall_count": fall, "turnover": turnover, "average_change_pct": average_change, "updated_at": updated_at.isoformat() if updated_at else None, "daily_bar_count": daily_count, "first_trade_date": str(first_date or ""), "trade_date": str(last_date or "")}
