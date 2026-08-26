"""Read-only A-share PostgreSQL repository behind the original BitPro market API."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import psycopg2

from app.core.config import settings


class MarketRepository:
    SUPPORTED_INTRADAY_TIMEFRAMES = {"1m", "5m", "15m", "30m", "60m"}

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
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
        observed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return int(observed.timestamp() * 1000)

    @staticmethod
    def _iso(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)

    @staticmethod
    def _freshness(observed_at: datetime | None, *, stale_after_seconds: int = 15 * 60) -> Dict:
        if observed_at is None:
            return {
                "basis": "source_updated_at",
                "observed_at": None,
                "age_seconds": None,
                "stale_after_seconds": stale_after_seconds,
                "stale": True,
            }
        observed = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=timezone.utc)
        age = max(0, int((datetime.now(timezone.utc) - observed).total_seconds()))
        return {
            "basis": "source_updated_at",
            "observed_at": observed.isoformat(),
            "age_seconds": age,
            "stale_after_seconds": stale_after_seconds,
            "stale": age > stale_after_seconds,
        }

    @staticmethod
    def _table_exists(cursor, table_name: str) -> bool:
        cursor.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
        return cursor.fetchone()[0] is not None

    @staticmethod
    def _side_levels(raw: Any, limit: int) -> List[List[float]]:
        if raw is None:
            return []
        rows = raw if isinstance(raw, list) else []
        levels: List[List[float]] = []
        for item in rows[: max(1, min(int(limit), 1000))]:
            try:
                if isinstance(item, dict):
                    price = item.get("price")
                    volume = item.get("volume")
                else:
                    price, volume = item[0], item[1]
                levels.append([float(price), float(volume)])
            except (TypeError, ValueError, IndexError, KeyError):
                continue
        return levels

    @staticmethod
    def _status_for_rows(rows: List[Dict], *, empty_reason: str) -> Dict:
        if rows:
            return {"data_status": "ok", "unavailable_reason": None}
        return {"data_status": "empty", "unavailable_reason": empty_reason}

    def list_symbols(self, asset_class: str, limit: int = 5000) -> List[str]:
        return [item["symbol"] for item in self.list_instruments(asset_class, limit)]

    def list_instruments(self, asset_class: str, limit: int = 10000) -> List[Dict]:
        bounded = max(1, min(int(limit), 20000))
        normalized = str(asset_class or "stock").lower()
        query = """
            SELECT symbol,name,exchange,asset_class,industry,board,list_status
            FROM instrument_definitions WHERE market='CN' AND list_status IN ('L','P')
        """
        params: list[object] = []
        if normalized != "all":
            query += " AND asset_class=%s"
            params.append(normalized)
        query += " ORDER BY exchange,symbol LIMIT %s"
        params.append(bounded)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()
        return [
            {
                "symbol": self._canonical_symbol(row[0]),
                "name": str(row[1] or ""),
                "display_name": f"{str(row[1] or '').strip()} {self._canonical_symbol(row[0])}".strip(),
                "exchange": row[2],
                "asset_class": row[3],
                "industry": row[4],
                "board": row[5],
                "list_status": row[6],
            }
            for row in rows
        ]

    def list_tickers(self, symbols: Optional[List[str]] = None) -> List[Dict]:
        requested = [self._storage_symbol(symbol) for symbol in symbols or []]
        canonical_requested = [self._canonical_symbol(symbol) for symbol in symbols or []]
        realtime_rows: List[tuple] = []
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if self._table_exists(cursor, "realtime_quotes"):
                    query = """
                        SELECT exchange,symbol,last_price,change_percent,volume,amount,
                               turnover_rate,volume_ratio,amplitude,trade_date,source,
                               source_updated_at,collected_at
                        FROM realtime_quotes
                    """
                    params: tuple[object, ...] = ()
                    if canonical_requested:
                        query += " WHERE symbol = ANY(%s)"
                        params = (canonical_requested,)
                    query += " ORDER BY exchange,symbol"
                    cursor.execute(query, params)
                    realtime_rows = cursor.fetchall()
        if realtime_rows:
            return [
                {
                    "exchange": row[0],
                    "symbol": self._canonical_symbol(row[1]),
                    "last": float(row[2] or 0),
                    "changePercent": float(row[3] or 0),
                    "change_percent": float(row[3] or 0),
                    "volume": float(row[4] or 0),
                    "quoteVolume": float(row[5] or 0),
                    "turnover_rate": float(row[6] or 0) if row[6] is not None else None,
                    "volume_ratio": float(row[7] or 0) if row[7] is not None else None,
                    "amplitude": float(row[8] or 0) if row[8] is not None else None,
                    "trade_date": str(row[9]) if row[9] else None,
                    "source": row[10],
                    "source_updated_at": self._iso(row[11]),
                    "collected_at": self._iso(row[12]),
                    "freshness": self._freshness(row[11]),
                    "timestamp": self._timestamp_ms(row[11]),
                    "data_status": "stale" if self._freshness(row[11])["stale"] else "ok",
                }
                for row in realtime_rows
            ]

        query = """
            SELECT r.code,COALESCE(NULLIF(d.name,''),r.name),r.price,r.change_percent,
                   r.volume,r.amount,r.updated_at
            FROM all_stocks_realtime r
            LEFT JOIN instrument_definitions d
              ON d.market='CN'
             AND d.symbol=(split_part(r.code,'_',2)||'.'||split_part(r.code,'_',1))
        """
        params: tuple[object, ...] = ()
        if requested:
            query += " WHERE r.code = ANY(%s)"
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
                "name": str(row[1] or ""),
                "display_name": f"{str(row[1] or '').strip()} {self._canonical_symbol(row[0])}".strip(),
                "last": float(row[2] or 0),
                "changePercent": float(row[3] or 0),
                "change_percent": float(row[3] or 0),
                "volume": float(row[4] or 0),
                "quoteVolume": float(row[5] or 0),
                "timestamp": self._timestamp_ms(row[6]),
                "source_updated_at": self._iso(row[6]),
                "collected_at": self._iso(row[6]),
                "freshness": self._freshness(row[6]),
                "data_status": "legacy_cache",
            }
            for row in rows
        ]

    def lookup_names(self, symbols: List[str]) -> Dict[str, str]:
        from app.domain.instruments.repository import AshareInstrumentRepository
        return AshareInstrumentRepository(self.database_url).lookup_names(symbols)

    def get_klines(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> List[Dict]:
        return self.get_klines_with_status(exchange, symbol, timeframe, limit, start, end)["items"]

    def get_klines_with_status(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> Dict:
        if timeframe != "1d":
            normalized_timeframe = str(timeframe or "").strip().lower()
            if normalized_timeframe not in self.SUPPORTED_INTRADAY_TIMEFRAMES:
                return {
                    "exchange": exchange,
                    "symbol": self._canonical_symbol(symbol),
                    "timeframe": normalized_timeframe,
                    "items": [],
                    "data_status": "unsupported",
                    "unavailable_reason": "A-share intraday cache supports only 1m/5m/15m/30m/60m",
                    "supported_timeframes": sorted(self.SUPPORTED_INTRADAY_TIMEFRAMES | {"1d"}),
                }
            return self._get_minute_bars(exchange, symbol, normalized_timeframe, limit, start, end)

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
        items = [
            {
                "timestamp": int(datetime.combine(row[0], datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5] or 0),
                "quote_volume": float(row[6] or 0),
                "trade_date": str(row[0]),
                "source": "daily_bars",
                "data_status": "ok",
            }
            for row in rows
        ]
        status = self._status_for_rows(
            items,
            empty_reason=f"no sealed daily bar cache for {self._canonical_symbol(symbol)}",
        )
        return {
            "exchange": exchange,
            "symbol": self._canonical_symbol(symbol),
            "timeframe": "1d",
            "items": items,
            **status,
        }

    def _get_minute_bars(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int,
        start: Optional[int],
        end: Optional[int],
    ) -> Dict:
        canonical = self._canonical_symbol(symbol)
        bounded = max(1, min(int(limit), 5000))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "minute_bars"):
                    return {
                        "exchange": exchange,
                        "symbol": canonical,
                        "timeframe": timeframe,
                        "items": [],
                        "data_status": "unavailable",
                        "unavailable_reason": "minute_bars cache table is not migrated",
                    }
                query = """
                    SELECT trade_date,bar_time,open,high,low,close,volume,amount,
                           source,source_updated_at,collected_at
                    FROM minute_bars
                    WHERE symbol=%s AND interval=%s
                """
                params: list[object] = [canonical, timeframe]
                if start is not None:
                    query += " AND bar_time >= %s"
                    params.append(datetime.fromtimestamp(start / 1000, tz=timezone.utc))
                if end is not None:
                    query += " AND bar_time <= %s"
                    params.append(datetime.fromtimestamp(end / 1000, tz=timezone.utc))
                query += " ORDER BY bar_time DESC LIMIT %s"
                params.append(bounded)
                cursor.execute(query, tuple(params))
                rows = list(reversed(cursor.fetchall()))
        items = [
            {
                "timestamp": self._timestamp_ms(row[1]),
                "datetime": self._iso(row[1]),
                "trade_date": str(row[0]),
                "open": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "close": float(row[5]),
                "volume": float(row[6] or 0),
                "quote_volume": float(row[7] or 0),
                "amount": float(row[7] or 0),
                "source": row[8],
                "source_updated_at": self._iso(row[9]),
                "collected_at": self._iso(row[10]),
                "freshness": self._freshness(row[9]),
                "data_status": "stale" if self._freshness(row[9])["stale"] else "ok",
            }
            for row in rows
        ]
        status = self._status_for_rows(
            items,
            empty_reason=f"no A-share {timeframe} minute bar cache for {canonical}",
        )
        if items and any(row.get("data_status") == "stale" for row in items[-3:]):
            status = {"data_status": "stale", "unavailable_reason": None}
        return {
            "exchange": exchange,
            "symbol": canonical,
            "timeframe": timeframe,
            "items": items,
            **status,
        }

    def get_orderbook(self, exchange: str, symbol: str, limit: int) -> Dict:
        canonical = self._canonical_symbol(symbol)
        bounded = max(1, min(int(limit), 1000))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "orderbook_snapshots"):
                    return {
                        "exchange": exchange,
                        "symbol": canonical,
                        "bids": [],
                        "asks": [],
                        "data_status": "unavailable",
                        "unavailable_reason": "orderbook_snapshots cache table is not migrated",
                    }
                cursor.execute(
                    """
                    SELECT trade_date,snapshot_at,source,bids,asks,source_updated_at,collected_at
                    FROM orderbook_snapshots
                    WHERE symbol=%s
                    ORDER BY snapshot_at DESC,id DESC
                    LIMIT 1
                    """,
                    (canonical,),
                )
                row = cursor.fetchone()
        if not row:
            return {
                "exchange": exchange,
                "symbol": canonical,
                "bids": [],
                "asks": [],
                "data_status": "empty",
                "unavailable_reason": f"no A-share order-book cache for {canonical}",
            }
        bids = self._side_levels(row[3], bounded)
        asks = self._side_levels(row[4], bounded)
        freshness = self._freshness(row[5])
        return {
            "exchange": exchange,
            "symbol": canonical,
            "bids": bids,
            "asks": asks,
            "trade_date": str(row[0]) if row[0] else None,
            "snapshot_at": self._iso(row[1]),
            "source": row[2],
            "source_updated_at": self._iso(row[5]),
            "collected_at": self._iso(row[6]),
            "freshness": freshness,
            "data_status": "stale" if freshness["stale"] else ("ok" if bids or asks else "empty"),
            "unavailable_reason": None if bids or asks else f"latest order-book cache has no depth for {canonical}",
        }

    def get_trades(self, exchange: str, symbol: str, limit: int) -> List[Dict]:
        return self.get_trades_with_status(exchange, symbol, limit)["items"]

    def get_trades_with_status(self, exchange: str, symbol: str, limit: int) -> Dict:
        canonical = self._canonical_symbol(symbol)
        bounded = max(1, min(int(limit), 500))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "trade_ticks"):
                    return {
                        "exchange": exchange,
                        "symbol": canonical,
                        "items": [],
                        "data_status": "unavailable",
                        "unavailable_reason": "trade_ticks cache table is not migrated",
                    }
                cursor.execute(
                    """
                    SELECT id,trade_date,trade_time,price,volume,amount,side,source,
                           source_updated_at,collected_at
                    FROM trade_ticks
                    WHERE symbol=%s
                    ORDER BY trade_time DESC,id DESC
                    LIMIT %s
                    """,
                    (canonical, bounded),
                )
                rows = cursor.fetchall()
        items = [
            {
                "id": str(row[0]),
                "trade_date": str(row[1]) if row[1] else None,
                "timestamp": self._timestamp_ms(row[2]),
                "datetime": self._iso(row[2]),
                "price": float(row[3]),
                "amount": float(row[4] or 0),
                "volume": float(row[4] or 0),
                "cost": float(row[5] or 0) if row[5] is not None else None,
                "notional": float(row[5] or 0) if row[5] is not None else None,
                "side": row[6] or "unknown",
                "source": row[7],
                "source_updated_at": self._iso(row[8]),
                "collected_at": self._iso(row[9]),
                "freshness": self._freshness(row[8]),
                "data_status": "stale" if self._freshness(row[8])["stale"] else "ok",
            }
            for row in rows
        ]
        status = self._status_for_rows(
            items,
            empty_reason=f"no A-share recent trade cache for {canonical}",
        )
        if items and any(row.get("data_status") == "stale" for row in items[:3]):
            status = {"data_status": "stale", "unavailable_reason": None}
        return {
            "exchange": exchange,
            "symbol": canonical,
            "items": items,
            **status,
        }

    def market_pulse(self) -> Dict:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM instrument_definitions WHERE market='CN' AND asset_class='stock' AND list_status IN ('L','P')")
                instruments = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FILTER(WHERE change_percent>0),COUNT(*) FILTER(WHERE change_percent<0),COALESCE(SUM(amount),0),COALESCE(AVG(change_percent),0),MAX(updated_at) FROM all_stocks_realtime")
                rise, fall, turnover, average_change, updated_at = cursor.fetchone()
                cursor.execute("SELECT COUNT(*),MIN(date),MAX(date) FROM stock_history")
                daily_count, first_date, last_date = cursor.fetchone()
        return {"instrument_count": instruments, "rise_count": rise, "fall_count": fall, "turnover": turnover, "average_change_pct": average_change, "updated_at": updated_at.isoformat() if updated_at else None, "daily_bar_count": daily_count, "first_trade_date": str(first_date or ""), "trade_date": str(last_date or "")}
