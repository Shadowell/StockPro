"""Domain service for market data with non-blocking adapters."""
from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.errors import ExchangeUnavailableError, UpstreamError
from app.domain.market.repository import MarketRepository
from app.exchange import exchange_manager
from app.services.indicators import EMA, MACD, RSI


TICKERS_CACHE_TTL_SEC = 15.0


class MarketDomainService:
    """Market domain service with strict upstream dependency behavior."""

    def __init__(self, repo: Optional[MarketRepository] = None):
        self.repo = repo or MarketRepository()
        self._response_cache: Dict[Tuple[Any, ...], Tuple[float, Any]] = {}

    def _cache_get(self, key: Tuple[Any, ...], ttl_sec: float) -> Any:
        cached = self._response_cache.get(key)
        if not cached:
            return None
        cached_at, value = cached
        if time.monotonic() - cached_at > ttl_sec:
            self._response_cache.pop(key, None)
            return None
        return value

    def _cache_set(self, key: Tuple[Any, ...], value: Any) -> Any:
        if len(self._response_cache) > 512:
            self._response_cache.clear()
        self._response_cache[key] = (time.monotonic(), value)
        return value

    def _get_exchange(self, exchange_name: str):
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ExchangeUnavailableError(f"交易所 {exchange_name} 不可用")
        return exchange

    def _cache_tickers(self, exchange_name: str, tickers: List[Dict]) -> None:
        for ticker in tickers:
            symbol = ticker.get("symbol")
            if symbol:
                self.repo.update_ticker_cache(exchange_name, symbol, ticker)

    async def get_ticker(self, exchange_name: str, symbol: str) -> Dict:
        key = ("ticker", exchange_name, symbol)
        cached = self._cache_get(key, 2.0)
        if cached is not None:
            return cached
        exchange = self._get_exchange(exchange_name)
        try:
            ticker = await asyncio.to_thread(exchange.fetch_ticker, symbol)
            await asyncio.to_thread(self.repo.update_ticker_cache, exchange_name, symbol, ticker)
            return self._cache_set(key, ticker)
        except Exception as exc:
            raise UpstreamError(f"获取行情失败: {exc}") from exc

    async def get_tickers(self, exchange_name: str, symbols: Optional[List[str]] = None) -> List[Dict]:
        key = ("tickers", exchange_name, tuple(symbols or ()))
        cached = self._cache_get(key, TICKERS_CACHE_TTL_SEC)
        if cached is not None:
            return cached
        exchange = self._get_exchange(exchange_name)
        try:
            tickers = await asyncio.to_thread(exchange.fetch_tickers, symbols)
            if isinstance(tickers, dict):
                normalized = list(tickers.values())
            else:
                normalized = tickers or []
            await asyncio.to_thread(self._cache_tickers, exchange_name, normalized)
            return self._cache_set(key, normalized)
        except Exception as exc:
            raise UpstreamError(f"批量获取行情失败: {exc}") from exc

    async def get_klines(
        self,
        exchange_name: str,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> List[Dict]:
        cached = await asyncio.to_thread(
            self.repo.get_klines,
            exchange_name,
            symbol,
            timeframe,
            limit,
            start,
            end,
        )
        bounded_history_read = start is not None or end is not None
        if bounded_history_read and cached and len(cached) >= limit:
            return self._continuous_recent_tail(cached, timeframe, limit)

        exchange = self._get_exchange(exchange_name)
        # 仅在查询“最近N根”（无时间范围）时做实时补齐，避免页面卡在旧时间点。
        should_refresh_latest = start is None and end is None

        # 默认至少补 8 根，避免只拉 1 根导致去重后无变化
        refresh_limit = max(8, min(50, max(1, limit // 5)))

        if should_refresh_latest and cached:
            try:
                latest = await asyncio.to_thread(exchange.fetch_ohlcv, symbol, timeframe, refresh_limit)
                if latest:
                    await asyncio.to_thread(self.repo.insert_klines, exchange_name, symbol, timeframe, latest)
                    merged = self._merge_klines(cached, latest, limit)
                    if self._has_large_time_gap(merged, timeframe):
                        try:
                            full_latest = await asyncio.to_thread(exchange.fetch_ohlcv, symbol, timeframe, limit)
                            if full_latest:
                                await asyncio.to_thread(
                                    self.repo.insert_klines,
                                    exchange_name,
                                    symbol,
                                    timeframe,
                                    full_latest,
                                )
                                return self._continuous_recent_tail(full_latest, timeframe, limit)
                        except Exception:
                            return self._continuous_recent_tail(merged, timeframe, limit)
                    return self._continuous_recent_tail(merged, timeframe, limit)
            except Exception:
                # 实时补齐失败时回退缓存，避免前端直接 502
                if len(cached) >= limit:
                    return self._continuous_recent_tail(cached, timeframe, limit)
                # 缓存不够时继续走下面的全量拉取

        try:
            klines = await asyncio.to_thread(exchange.fetch_ohlcv, symbol, timeframe, limit, start)
            if klines:
                await asyncio.to_thread(self.repo.insert_klines, exchange_name, symbol, timeframe, klines)
                if cached and should_refresh_latest:
                    merged = self._merge_klines(cached, klines, limit)
                    if self._has_large_time_gap(merged, timeframe):
                        return self._continuous_recent_tail(klines, timeframe, limit)
                    return self._continuous_recent_tail(merged, timeframe, limit)
            return self._continuous_recent_tail(klines, timeframe, limit)
        except Exception as exc:
            if cached:
                # 上游失败时，优先返回已缓存数据（页面可继续展示，避免“无数据/离线”）
                return self._continuous_recent_tail(cached, timeframe, limit)
            raise UpstreamError(f"获取K线失败: {exc}") from exc

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
        key = ("orderbook", exchange_name, symbol, int(limit))
        cached = self._cache_get(key, 1.0)
        if cached is not None:
            return cached
        exchange = self._get_exchange(exchange_name)
        valid_limits = [5, 10, 20, 50, 100, 500, 1000]
        adjusted_limit = min(v for v in valid_limits if v >= limit) if limit <= 1000 else 1000
        try:
            orderbook = await asyncio.to_thread(exchange.fetch_order_book, symbol, adjusted_limit)
            return self._cache_set(key, orderbook)
        except Exception as exc:
            raise UpstreamError(f"获取订单簿失败: {exc}") from exc

    async def get_trades(self, exchange_name: str, symbol: str, limit: int = 50) -> List[Dict]:
        exchange = self._get_exchange(exchange_name)
        try:
            return await asyncio.to_thread(exchange.fetch_trades, symbol, limit)
        except Exception as exc:
            raise UpstreamError(f"获取成交失败: {exc}") from exc

    async def get_symbols(self, exchange_name: str, quote: str = "USDT", market_type: str = "spot") -> List[str]:
        normalized_market_type = (market_type or "spot").strip().lower()
        key = ("symbols", exchange_name, quote, normalized_market_type)
        cached = self._cache_get(key, 300.0)
        if cached is not None:
            return cached
        exchange = self._get_exchange(exchange_name)
        try:
            symbols = await asyncio.to_thread(exchange.get_symbols, quote, normalized_market_type)
            return self._cache_set(key, symbols)
        except Exception as exc:
            raise UpstreamError(f"获取交易对失败: {exc}") from exc


market_domain_service = MarketDomainService()
