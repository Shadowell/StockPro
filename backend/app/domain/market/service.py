"""Domain service for market data with non-blocking adapters."""
from __future__ import annotations

import asyncio
import math
from typing import Any, Dict, List, Optional

import numpy as np

from app.domain.market.repository import MarketRepository
from app.services.indicators import EMA, MACD, RSI


class MarketDomainService:
    """BitPro market contract backed only by A-share PostgreSQL evidence."""

    def __init__(self, repo: Optional[MarketRepository] = None):
        self.repo = repo or MarketRepository()

    async def get_ticker(self, exchange_name: str, symbol: str) -> Dict:
        items = await asyncio.to_thread(self.repo.list_tickers, [symbol])
        if not items:
            raise LookupError(f"A-share instrument not found: {symbol}")
        return items[0]

    async def get_tickers(self, exchange_name: str, symbols: Optional[List[str]] = None) -> List[Dict]:
        return await asyncio.to_thread(self.repo.list_tickers, symbols)

    async def get_klines(
        self,
        exchange_name: str,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> List[Dict]:
        return await asyncio.to_thread(
            self.repo.get_klines,
            exchange_name,
            symbol,
            timeframe,
            limit,
            start,
            end,
        )

    async def get_technical_indicators(
        self,
        exchange_name: str,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
        start: Optional[int] = None,
        end: Optional[int] = None,
        ema_periods: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        klines = await self.get_klines(exchange_name, symbol, timeframe, limit, start, end)
        payload = self.build_technical_indicators(klines, ema_periods or [5, 10, 20, 30])
        payload.update({
            "exchange": exchange_name,
            "symbol": symbol,
            "timeframe": timeframe,
        })
        return payload

    @staticmethod
    def build_technical_indicators(
        klines: List[Dict],
        ema_periods: List[int],
    ) -> Dict[str, Any]:
        normalized = [MarketDomainService._normalize_kline_row(k) for k in klines]
        normalized = [k for k in normalized if k is not None]
        timestamps = [int(k["timestamp"]) for k in normalized]
        closes = np.array([float(k["close"]) for k in normalized], dtype=float)

        series: Dict[str, List[Optional[float]]] = {}
        periods = sorted({int(p) for p in ema_periods if int(p) > 0})
        for period in periods:
            values = EMA(closes, period) if len(closes) else np.array([], dtype=float)
            series[f"EMA{period}"] = MarketDomainService._series_from_array(values)

        rsi_values = RSI(closes, 14) if len(closes) else np.array([], dtype=float)
        series["RSI14"] = MarketDomainService._series_from_array(rsi_values)

        if len(closes):
            macd_line, signal_line, histogram = MACD(closes)
        else:
            macd_line = signal_line = histogram = np.array([], dtype=float)
        series["MACD"] = MarketDomainService._series_from_array(macd_line)
        series["MACD_signal"] = MarketDomainService._series_from_array(signal_line)
        series["MACD_hist"] = MarketDomainService._series_from_array(histogram)

        return {
            "source": "backend_derived_from_ohlcv",
            "data_source": "market_klines",
            "timestamps": timestamps,
            "series": series,
        }

    @staticmethod
    def _series_from_array(values: np.ndarray) -> List[Optional[float]]:
        result: List[Optional[float]] = []
        for value in values:
            try:
                number = float(value)
            except (TypeError, ValueError):
                result.append(None)
                continue
            if not math.isfinite(number):
                result.append(None)
            else:
                result.append(round(number, 8))
        return result

    @staticmethod
    def _normalize_kline_row(row: Any) -> Optional[Dict[str, float]]:
        try:
            if isinstance(row, dict):
                return {
                    "timestamp": int(row["timestamp"]),
                    "close": float(row["close"]),
                }
            if isinstance(row, (list, tuple)) and len(row) >= 5:
                return {
                    "timestamp": int(row[0]),
                    "close": float(row[4]),
                }
        except (KeyError, TypeError, ValueError):
            return None
        return None

    @staticmethod
    def _merge_klines(base: List[Dict], incoming: List[Dict], limit: int) -> List[Dict]:
        """按 timestamp 合并去重并返回最后 limit 根（时间升序）。"""
        by_ts: Dict[int, Dict] = {}
        for k in base:
            ts = int(k.get("timestamp", 0))
            if ts:
                by_ts[ts] = k
        for k in incoming:
            ts = int(k[0]) if isinstance(k, list) else int(k.get("timestamp", 0))
            if not ts:
                continue
            if isinstance(k, list):
                by_ts[ts] = {
                    "timestamp": int(k[0]),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                }
            else:
                by_ts[ts] = k

        merged = [by_ts[t] for t in sorted(by_ts.keys())]
        if limit > 0:
            merged = merged[-limit:]
        return merged

    @staticmethod
    def _timeframe_ms(timeframe: str) -> Optional[int]:
        unit = str(timeframe or "").strip().lower()
        try:
            if unit.endswith("m"):
                return int(unit[:-1]) * 60_000
            if unit.endswith("h"):
                return int(unit[:-1]) * 3_600_000
            if unit.endswith("d"):
                return int(unit[:-1]) * 86_400_000
        except ValueError:
            return None
        return None

    @staticmethod
    def _row_timestamp(row: Any) -> Optional[int]:
        try:
            if isinstance(row, dict):
                return int(row.get("timestamp", 0))
            if isinstance(row, (list, tuple)) and row:
                return int(row[0])
        except (TypeError, ValueError):
            return None
        return None

    @classmethod
    def _has_large_time_gap(cls, rows: List[Any], timeframe: str) -> bool:
        step = cls._timeframe_ms(timeframe)
        if not step or len(rows) < 2:
            return False
        timestamps = [ts for ts in (cls._row_timestamp(row) for row in rows) if ts]
        timestamps.sort()
        return any(curr - prev > step * 3 for prev, curr in zip(timestamps, timestamps[1:]))

    @classmethod
    def _continuous_recent_tail(cls, rows: List[Any], timeframe: str, limit: int) -> List[Any]:
        step = cls._timeframe_ms(timeframe)
        valid_rows = [(cls._row_timestamp(row), row) for row in rows]
        sorted_rows = [(ts, row) for ts, row in valid_rows if ts]
        sorted_rows.sort(key=lambda item: item[0])
        if step and len(sorted_rows) >= 2:
            tail_start = 0
            for idx in range(len(sorted_rows) - 1, 0, -1):
                if sorted_rows[idx][0] - sorted_rows[idx - 1][0] > step * 3:
                    tail_start = idx
                    break
            sorted_rows = sorted_rows[tail_start:]
        tail = [row for _, row in sorted_rows]
        if limit > 0:
            return tail[-limit:]
        return tail

    async def get_orderbook(self, exchange_name: str, symbol: str, limit: int = 20) -> Dict:
        return await asyncio.to_thread(self.repo.get_orderbook, exchange_name, symbol, limit)

    async def get_trades(self, exchange_name: str, symbol: str, limit: int = 50) -> List[Dict]:
        return await asyncio.to_thread(self.repo.get_trades, exchange_name, symbol, limit)

    async def get_symbols(self, exchange_name: str, quote: str = "USDT", market_type: str = "spot") -> List[str]:
        asset_class = (market_type or "stock").strip().lower()
        if asset_class not in {"stock", "etf", "index", "all"}:
            asset_class = "stock"
        return await asyncio.to_thread(self.repo.list_symbols, asset_class, 5000)

    async def market_pulse(self) -> Dict:
        return await asyncio.to_thread(self.repo.market_pulse)


market_domain_service = MarketDomainService()
