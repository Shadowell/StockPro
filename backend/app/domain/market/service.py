"""Domain service for market data with non-blocking adapters."""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone
import math
import time
from typing import Any, Dict, List, Optional

import numpy as np

from app.domain.market.akshare_intraday import AkshareIntradayProvider
from app.domain.market.akshare_symbols import AkshareSymbolProvider
from app.domain.market.key_levels import LEVEL_TYPES, compute_key_levels, summarize_levels
from app.domain.market.repository import MarketRepository
from app.domain.market.research_metrics import (
    ABNORMALITY_DEFINITION_VERSION,
    MARKET_PHASE_DEFINITION_VERSION,
    SECTOR_RPS_DEFINITION_VERSION,
)
from app.domain.market.overview import unavailable_market_overview
from app.services.indicators import EMA, MACD, RSI


class MarketDomainService:
    """BitPro market contract backed only by A-share PostgreSQL evidence."""

    def __init__(
        self,
        repo: Optional[MarketRepository] = None,
        intraday_provider: Optional[AkshareIntradayProvider] = None,
        symbol_provider: Optional[AkshareSymbolProvider] = None,
    ):
        self.repo = repo or MarketRepository()
        self.intraday_provider = intraday_provider or AkshareIntradayProvider()
        self.symbol_provider = symbol_provider or AkshareSymbolProvider()
        self._home_dashboard_cache: dict[str, tuple[float, Dict[str, Any]]] = {}
        self._home_dashboard_lock = asyncio.Lock()

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

    async def get_klines_payload(
        self,
        exchange_name: str,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> Dict[str, Any]:
        if hasattr(self.repo, "get_klines_with_status"):
            try:
                payload = await asyncio.to_thread(
                    self.repo.get_klines_with_status,
                    exchange_name,
                    symbol,
                    timeframe,
                    limit,
                    start,
                    end,
                )
            except Exception as exc:
                payload = {
                    "exchange": exchange_name,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "items": [],
                    "data_status": "unavailable",
                    "unavailable_reason": f"A-share kline cache unavailable: {type(exc).__name__}",
                }
            if self._should_fetch_intraday(payload, timeframe):
                fallback = await asyncio.to_thread(
                    self.intraday_provider.fetch,
                    exchange_name,
                    symbol,
                    timeframe,
                    limit,
                    start,
                    end,
                )
                if fallback.get("items"):
                    fallback["fallback_from"] = {
                        "data_status": payload.get("data_status"),
                        "unavailable_reason": payload.get("unavailable_reason"),
                    }
                    return fallback
                if payload.get("items"):
                    payload = dict(payload)
                    payload["fallback_error"] = fallback.get("unavailable_reason")
                    payload["fallback_source"] = fallback.get("provider_source")
                    return payload
                return fallback
            return payload
        items = await self.get_klines(exchange_name, symbol, timeframe, limit, start, end)
        return {
            "exchange": exchange_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "items": items,
            "data_status": "ok" if items else "empty",
            "unavailable_reason": None if items else "cache returned no rows",
        }

    async def get_sector_heatmap(self, window: str = "1d") -> Dict[str, Any]:
        """板块热力图聚合（只读）。窗口 1d/5d/20d，等权涨跌，面积 = 标的数。"""
        normalized = str(window or "1d").strip().lower()
        if normalized not in {"1d", "5d", "20d"}:
            normalized = "1d"
        return await asyncio.to_thread(self.repo.get_sector_heatmap, normalized)

    async def get_key_levels(self, exchange_name: str, symbol: str, limit: int = 500) -> Dict[str, Any]:
        """个股关键价位（只读）：基于 1d 日线复用 get_klines_payload 链路实时计算。"""
        bounded_limit = max(20, min(int(limit), 2000))
        payload = await self.get_klines_payload(exchange_name, symbol, "1d", bounded_limit)
        klines = payload.get("items", [])
        levels = compute_key_levels(klines)
        turnover_source = (
            "row_field"
            if any(isinstance(k.get("turnover_rate"), (int, float)) for k in klines)
            else "unavailable"
        )
        return {
            "exchange": exchange_name,
            "symbol": payload.get("symbol") or symbol,
            "close": levels.get("close"),
            "rows_used": levels.get("rows_used", 0),
            "groups": levels.get("groups", {}),
            "summary": summarize_levels(levels.get("groups", {}), levels.get("close")),
            "level_types": LEVEL_TYPES,
            "as_of_trade_date": payload.get("to_date"),
            "rows_available": len(klines),
            "data_status": payload.get("data_status"),
            "unavailable_reason": payload.get("unavailable_reason"),
            "provider_source": payload.get("provider_source") or payload.get("source"),
            "turnover_source": turnover_source,
            "provider_calls": 0,
            "writes_performed": False,
            "paper_mutated": False,
        }

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
        kline_payload = await self.get_klines_payload(exchange_name, symbol, timeframe, limit, start, end)
        klines = kline_payload.get("items", [])
        payload = self.build_technical_indicators(klines, ema_periods or [5, 10, 20, 30])
        payload.update({
            "exchange": exchange_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "kline_data_status": kline_payload.get("data_status"),
            "kline_source": kline_payload.get("provider_source") or kline_payload.get("source"),
        })
        return payload

    @staticmethod
    def _should_fetch_intraday(payload: Dict[str, Any], timeframe: str) -> bool:
        normalized_timeframe = str(timeframe or "").strip().lower()
        if normalized_timeframe not in MarketRepository.SUPPORTED_INTRADAY_TIMEFRAMES:
            return False
        status = str(payload.get("data_status") or "").strip().lower()
        if status in {"empty", "unavailable", "provider_error"}:
            return True
        return status == "stale"

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
        try:
            return await asyncio.to_thread(self.repo.get_orderbook, exchange_name, symbol, limit)
        except Exception as exc:
            return {
                "exchange": exchange_name,
                "symbol": symbol,
                "bids": [],
                "asks": [],
                "data_status": "unavailable",
                "unavailable_reason": f"A-share order-book cache unavailable: {type(exc).__name__}",
            }

    async def get_trades(self, exchange_name: str, symbol: str, limit: int = 50) -> List[Dict]:
        return await asyncio.to_thread(self.repo.get_trades, exchange_name, symbol, limit)

    async def get_trades_payload(self, exchange_name: str, symbol: str, limit: int = 50) -> Dict[str, Any]:
        if hasattr(self.repo, "get_trades_with_status"):
            try:
                return await asyncio.to_thread(self.repo.get_trades_with_status, exchange_name, symbol, limit)
            except Exception as exc:
                return {
                    "exchange": exchange_name,
                    "symbol": symbol,
                    "items": [],
                    "data_status": "unavailable",
                    "unavailable_reason": f"A-share recent trade cache unavailable: {type(exc).__name__}",
                }
        items = await self.get_trades(exchange_name, symbol, limit)
        return {
            "exchange": exchange_name,
            "symbol": symbol,
            "items": items,
            "data_status": "ok" if items else "empty",
            "unavailable_reason": None if items else "cache returned no rows",
        }

    async def get_symbols(self, exchange_name: str, quote: str = "CNY", market_type: str = "stock") -> List[str]:
        asset_class = (market_type or "stock").strip().lower()
        if asset_class not in {"stock", "etf", "index", "all"}:
            asset_class = "stock"
        if hasattr(self.repo, "list_symbols"):
            try:
                symbols = await asyncio.to_thread(self.repo.list_symbols, asset_class, 5000)
            except Exception:
                symbols = []
            if symbols:
                return symbols
        instruments = await self.get_instruments(exchange_name, quote, market_type)
        return [item["symbol"] for item in instruments]

    async def get_instruments(self, exchange_name: str, quote: str = "CNY", market_type: str = "stock") -> List[Dict]:
        asset_class = (market_type or "stock").strip().lower()
        if asset_class not in {"stock", "etf", "index", "all"}:
            asset_class = "stock"
        if not hasattr(self.repo, "list_instruments"):
            return await asyncio.to_thread(self.symbol_provider.fetch_instruments, asset_class) if asset_class in {"stock", "all"} else []
        try:
            instruments = await asyncio.to_thread(self.repo.list_instruments, asset_class, 10000)
        except Exception:
            instruments = []
        if instruments or asset_class not in {"stock", "all"}:
            return instruments
        return await asyncio.to_thread(self.symbol_provider.fetch_instruments, asset_class)

    async def lookup_names(self, symbols: List[str]) -> Dict[str, str]:
        return await asyncio.to_thread(self.repo.lookup_names, symbols)

    async def market_pulse(self) -> Dict:
        return await asyncio.to_thread(self.repo.market_pulse)

    async def get_market_overview(self, trade_date: str | None = None) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(self.repo.get_market_overview, trade_date)
        except Exception as exc:
            return unavailable_market_overview(f"A股首页基础指标读取失败：{type(exc).__name__}")

    async def get_market_phase(self, trade_date: str | None = None) -> Dict:
        try:
            return await asyncio.to_thread(self.repo.get_market_phase, trade_date)
        except Exception as exc:
            return {
                "trade_date": trade_date,
                "phase": "unknown",
                "status": "unavailable",
                "confidence": 0.0,
                "reasons": [],
                "missing_inputs": [f"A-share market phase cache unavailable: {type(exc).__name__}"],
                "definition_version": MARKET_PHASE_DEFINITION_VERSION,
            }

    async def get_market_sentiment(self, trade_date: str | None = None) -> Dict:
        try:
            return await asyncio.to_thread(self.repo.get_market_sentiment, trade_date)
        except Exception as exc:
            return {
                "trade_date": trade_date,
                "status": "unavailable",
                "missing_inputs": [f"A-share market sentiment cache unavailable: {type(exc).__name__}"],
                "definition_version": "ashare-market-sentiment.v1",
            }

    async def list_market_timeline(self, *, limit: int = 60) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(self.repo.list_market_timeline, limit=limit)
        except Exception as exc:
            return {
                "items": [],
                "data_status": "unavailable",
                "unavailable_reason": f"A-share market timeline unavailable: {type(exc).__name__}",
                "limit": limit,
                "writes_performed": False,
                "paper_mutated": False,
            }

    async def get_home_dashboard(self, trade_date: str | None = None) -> Dict[str, Any]:
        """Read one coherent persisted home snapshot with a short single-flight cache."""
        cache_key = str(trade_date or "latest")
        cached = self._home_dashboard_cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] < 5.0:
            return copy.deepcopy(cached[1])
        async with self._home_dashboard_lock:
            cached = self._home_dashboard_cache.get(cache_key)
            now = time.monotonic()
            if cached and now - cached[0] < 5.0:
                return copy.deepcopy(cached[1])
            overview, phase, sentiment, industry, concept, movers, events = await asyncio.gather(
                self.get_market_overview(trade_date),
                self.get_market_phase(trade_date),
                self.get_market_sentiment(trade_date),
                self.list_sector_rps(trade_date=trade_date, classification_system="industry", limit=1000),
                self.list_sector_rps(trade_date=trade_date, classification_system="concept", limit=1000),
                self.list_symbol_abnormalities(trade_date=trade_date, limit=10),
                self.list_market_events(limit=10),
            )
            modules = {
                "overview": overview,
                "phase": phase,
                "sentiment": sentiment,
                "industry_rps": industry,
                "concept_rps": concept,
                "movers": movers,
                "events": events,
            }
            observed_dates: dict[str, str] = {}
            observed_snapshots: dict[str, int] = {}
            for name, payload in modules.items():
                if not isinstance(payload, dict):
                    continue
                module_date = payload.get("trade_date") or (payload.get("evidence") or {}).get("trade_date")
                snapshot_id = payload.get("source_snapshot_id") or (payload.get("evidence") or {}).get("source_snapshot_id")
                items = payload.get("items") or payload.get("events") or []
                if isinstance(items, list) and items:
                    module_date = module_date or items[0].get("trade_date")
                    snapshot_id = snapshot_id or items[0].get("source_snapshot_id")
                if module_date:
                    observed_dates[name] = str(module_date)[:10]
                if snapshot_id is not None:
                    observed_snapshots[name] = int(snapshot_id)
            warnings: list[str] = []
            if len(set(observed_dates.values())) > 1:
                warnings.append("首页模块交易日不一致")
            if len(set(observed_snapshots.values())) > 1:
                warnings.append("首页模块封存快照不一致")
            required_statuses = [
                str((overview.get("evidence") or {}).get("status") or overview.get("status") or "empty"),
                str(phase.get("status") or "empty"),
                str(sentiment.get("status") or "empty"),
                str(industry.get("data_status") or "empty"),
                str(movers.get("data_status") or "empty"),
            ]
            data_status = "ready" if not warnings and all(item in {"ready", "ok"} for item in required_statuses) else "partial"
            evidence = dict(overview.get("evidence") or {})
            if len(set(observed_dates.values())) == 1:
                evidence["trade_date"] = next(iter(observed_dates.values()))
            if len(set(observed_snapshots.values())) == 1:
                evidence["source_snapshot_id"] = next(iter(observed_snapshots.values()))
            available_at = evidence.get("available_at") or evidence.get("last_success_at")
            data_age_seconds: int | None = None
            if available_at:
                try:
                    observed_at = datetime.fromisoformat(str(available_at).replace("Z", "+00:00"))
                    if observed_at.tzinfo is None:
                        observed_at = observed_at.replace(tzinfo=timezone.utc)
                    data_age_seconds = max(0, int((datetime.now(timezone.utc) - observed_at).total_seconds()))
                except ValueError:
                    data_age_seconds = None
            if trade_date:
                evidence["data_mode"] = "历史回看"
            elif data_age_seconds is not None and data_age_seconds > 36 * 60 * 60 and data_status != "error":
                data_status = "stale"
                warnings.append("首页封存数据超过 36 小时")
            evidence.update({
                "status": data_status,
                "data_status": data_status,
                "data_age_seconds": data_age_seconds,
                "consistency_warnings": warnings,
                "observed_trade_dates": observed_dates,
                "observed_snapshot_ids": observed_snapshots,
                "provider_calls": 0,
                "writes_performed": False,
                "paper_mutated": False,
            })
            result = {
                "evidence": evidence,
                **modules,
                "data_status": data_status,
                "provider_calls": 0,
                "writes_performed": False,
                "paper_mutated": False,
            }
            if cache_key not in self._home_dashboard_cache and len(self._home_dashboard_cache) >= 32:
                oldest_key = min(self._home_dashboard_cache, key=lambda key: self._home_dashboard_cache[key][0])
                self._home_dashboard_cache.pop(oldest_key, None)
            self._home_dashboard_cache[cache_key] = (time.monotonic(), result)
            return copy.deepcopy(result)

    async def list_sector_rps(
        self,
        *,
        trade_date: str | None = None,
        classification_system: str = "industry",
        limit: int = 20,
    ) -> Dict:
        try:
            return await asyncio.to_thread(
                self.repo.list_sector_rps,
                trade_date=trade_date,
                classification_system=classification_system,
                limit=limit,
            )
        except Exception as exc:
            return {
                "items": [],
                "data_status": "unavailable",
                "unavailable_reason": f"A-share sector RPS cache unavailable: {type(exc).__name__}",
                "definition_version": SECTOR_RPS_DEFINITION_VERSION,
            }

    async def get_sector_rps_history(
        self,
        sector_code: str,
        *,
        classification_system: str = "industry",
        limit: int = 60,
    ) -> Dict:
        try:
            return await asyncio.to_thread(
                self.repo.get_sector_rps_history,
                sector_code,
                classification_system=classification_system,
                limit=limit,
            )
        except Exception as exc:
            return {
                "items": [],
                "data_status": "unavailable",
                "unavailable_reason": f"A-share sector RPS history cache unavailable: {type(exc).__name__}",
                "definition_version": SECTOR_RPS_DEFINITION_VERSION,
            }

    async def list_sector_members(
        self,
        sector_code: str,
        *,
        classification_system: str = "industry",
        trade_date: str | None = None,
        limit: int = 500,
    ) -> Dict:
        try:
            return await asyncio.to_thread(
                self.repo.list_sector_members,
                sector_code,
                classification_system=classification_system,
                trade_date=trade_date,
                limit=limit,
            )
        except Exception as exc:
            return {
                "items": [],
                "data_status": "unavailable",
                "unavailable_reason": f"A-share sector membership cache unavailable: {type(exc).__name__}",
            }

    async def list_symbol_abnormalities(self, *, trade_date: str | None = None, limit: int = 20) -> Dict:
        try:
            return await asyncio.to_thread(self.repo.list_symbol_abnormalities, trade_date=trade_date, limit=limit)
        except Exception as exc:
            return {
                "items": [],
                "data_status": "unavailable",
                "unavailable_reason": f"A-share abnormality cache unavailable: {type(exc).__name__}",
                "definition_version": ABNORMALITY_DEFINITION_VERSION,
            }

    async def get_symbol_abnormality(self, symbol: str, *, trade_date: str | None = None) -> Dict:
        try:
            return await asyncio.to_thread(self.repo.get_symbol_abnormality, symbol, trade_date=trade_date)
        except Exception as exc:
            return {
                "symbol": symbol,
                "trade_date": trade_date,
                "tags": [],
                "status": "unavailable",
                "missing_inputs": [f"A-share abnormality cache unavailable: {type(exc).__name__}"],
                "definition_version": ABNORMALITY_DEFINITION_VERSION,
            }

    async def list_market_events(
        self,
        *,
        limit: int = 10,
        source: str | None = None,
        severity: str | None = None,
    ) -> Dict[str, Any]:
        try:
            if not hasattr(self.repo, "list_market_events"):
                return {
                    "events": [],
                    "data_status": "unavailable",
                    "unavailable_reason": "A-share market event repository is not available",
                    "orders_created": 0,
                    "paper_mutated": False,
                }
            return await asyncio.to_thread(
                self.repo.list_market_events,
                limit=limit,
                source=source,
                severity=severity,
            )
        except Exception as exc:
            return {
                "events": [],
                "data_status": "unavailable",
                "unavailable_reason": f"A-share market event cache unavailable: {type(exc).__name__}",
                "orders_created": 0,
                "paper_mutated": False,
            }


market_domain_service = MarketDomainService()
