"""Kairos 外生因子采集。

实时预测仍以 Kairos 模型为唯一预测源；本服务只负责尽量采集可公开获取的
市场状态，并以短缓存提供给模型 exog 输入。
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from typing import Any, Dict, Optional

from app.exchange import exchange_manager

logger = logging.getLogger(__name__)


def _okx_swap_inst_id(symbol: str) -> str:
    s = str(symbol or "").strip().upper()
    if s.endswith("-SWAP"):
        return s
    base = s.split("/", 1)[0] if "/" in s else s.split("-", 1)[0]
    quote_part = s.split("/", 1)[1] if "/" in s else "USDT"
    quote = quote_part.split(":", 1)[0].split("-", 1)[0] or "USDT"
    return f"{base}-{quote}-SWAP"


def _okx_ratio_currency(symbol: str) -> str:
    return _okx_swap_inst_id(symbol).split("-", 1)[0]


def _first_okx_row(response: Any) -> Any:
    if isinstance(response, dict):
        data = response.get("data")
        if isinstance(data, list) and data:
            return data[0]
        return response
    if isinstance(response, list) and response:
        return response[0]
    return None


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        v = float(value)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


class ExogenousFeatureService:
    """采集当前可用的外生因子快照，并缓存短时间避免每根 K 线重复打满接口。"""

    def __init__(self) -> None:
        self._ttl_sec = max(5.0, float(os.getenv("KAIROS_EXOG_CACHE_TTL_SEC", "20")))
        self._timeout_sec = max(1.0, float(os.getenv("KAIROS_EXOG_TIMEOUT_SEC", "3")))
        self._cache: Dict[tuple[str, str], Dict[str, Any]] = {}

    async def get_snapshot(self, exchange: str, symbol: str) -> Dict[str, Any]:
        exchange_name = str(exchange or "okx").lower()
        symbol_name = str(symbol or "").strip()
        key = (exchange_name, symbol_name)
        now = time.time()
        cached = self._cache.get(key)
        if cached and now - float(cached.get("_cached_at", 0)) <= self._ttl_sec:
            return dict(cached)

        ex = exchange_manager.get_exchange(exchange_name)
        if not ex:
            snapshot = self._empty_snapshot(exchange_name, symbol_name, ["交易所不可用"])
            self._cache[key] = snapshot
            return dict(snapshot)

        tasks = {
            "ticker": self._safe_call(self._fetch_ticker(ex, exchange_name, symbol_name)),
            "funding": self._safe_call(self._fetch_funding(ex, exchange_name, symbol_name)),
            "orderbook": self._safe_call(self._fetch_orderbook(ex, exchange_name, symbol_name)),
            "long_short": self._safe_call(self._fetch_long_short(ex, exchange_name, symbol_name)),
            "open_interest": self._safe_call(self._fetch_open_interest(ex, exchange_name, symbol_name)),
        }
        results = await asyncio.gather(*tasks.values())

        features: Dict[str, float] = {}
        errors: list[str] = []
        for name, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                errors.append(f"{name}: {result}")
                continue
            if isinstance(result, dict):
                features.update(result)

        snapshot = {
            "exchange": exchange_name,
            "symbol": symbol_name,
            "available": bool(features),
            "features": features,
            "errors": errors,
            "_cached_at": now,
        }
        self._cache[key] = snapshot

        if features:
            logger.info(
                "Kairos 外生因子获取完成：%s %s，可用=%d项，失败=%d项",
                exchange_name,
                symbol_name,
                len(features),
                len(errors),
            )
        else:
            logger.warning(
                "Kairos 外生因子暂不可用：%s %s，原因=%s",
                exchange_name,
                symbol_name,
                "；".join(errors[:3]) or "未知",
            )
        return dict(snapshot)

    async def _safe_call(self, coro):
        try:
            return await asyncio.wait_for(coro, timeout=self._timeout_sec)
        except Exception as exc:
            return exc

    @staticmethod
    def _empty_snapshot(exchange: str, symbol: str, errors: list[str]) -> Dict[str, Any]:
        return {
            "exchange": exchange,
            "symbol": symbol,
            "available": False,
            "features": {},
            "errors": errors,
            "_cached_at": time.time(),
        }

    async def _fetch_ticker(self, ex, exchange: str, symbol: str) -> Dict[str, float]:
        if exchange == "okx" and hasattr(ex.exchange, "publicGetMarketTicker"):
            row = _first_okx_row(
                await asyncio.to_thread(
                    ex.exchange.publicGetMarketTicker,
                    {"instId": _okx_swap_inst_id(symbol)},
                )
            )
            if not row:
                return {}
            last = _num(row.get("last"))
            open24h = _num(row.get("open24h"))
            change_pct = ((last - open24h) / open24h * 100) if last > 0 and open24h > 0 else 0.0
            base_volume = _num(row.get("volCcy24h"))
            quote_volume = _num(row.get("volCcyQuote24h"))
            if quote_volume <= 0 and base_volume > 0 and last > 0:
                quote_volume = base_volume * last
            return {
                "ticker_last": last,
                "ticker_bid": _num(row.get("bidPx")),
                "ticker_ask": _num(row.get("askPx")),
                "ticker_change_pct": change_pct,
                "ticker_volume_base_24h": base_volume,
                "ticker_volume_quote_24h": quote_volume,
            }

        ticker = await asyncio.to_thread(ex.fetch_ticker, symbol)
        return {
            "ticker_last": _num(ticker.get("last")),
            "ticker_bid": _num(ticker.get("bid")),
            "ticker_ask": _num(ticker.get("ask")),
            "ticker_change_pct": _num(ticker.get("change_percent")),
            "ticker_volume_base_24h": _num(ticker.get("volume")),
            "ticker_volume_quote_24h": _num(ticker.get("quote_volume")),
        }

    async def _fetch_funding(self, ex, exchange: str, symbol: str) -> Dict[str, float]:
        if exchange == "okx" and hasattr(ex.exchange, "publicGetPublicFundingRate"):
            row = _first_okx_row(
                await asyncio.to_thread(
                    ex.exchange.publicGetPublicFundingRate,
                    {"instId": _okx_swap_inst_id(symbol)},
                )
            )
            if not row:
                return {}
            mark = _num(row.get("markPx"))
            index = _num(row.get("indexPx"))
            basis = ((mark - index) / index) if mark > 0 and index > 0 else 0.0
            return {
                "funding_rate": _num(row.get("fundingRate")),
                "predicted_funding_rate": _num(row.get("nextFundingRate")),
                "funding_basis": basis,
            }

        rate = await asyncio.to_thread(ex.fetch_funding_rate, symbol)
        if not rate:
            return {}
        mark = _num(rate.get("mark_price"))
        index = _num(rate.get("index_price"))
        basis = ((mark - index) / index) if mark > 0 and index > 0 else 0.0
        return {
            "funding_rate": _num(rate.get("current_rate")),
            "predicted_funding_rate": _num(rate.get("predicted_rate")),
            "funding_basis": basis,
        }

    async def _fetch_orderbook(self, ex, exchange: str, symbol: str) -> Dict[str, float]:
        if exchange == "okx" and hasattr(ex.exchange, "publicGetMarketBooks"):
            row = _first_okx_row(
                await asyncio.to_thread(
                    ex.exchange.publicGetMarketBooks,
                    {"instId": _okx_swap_inst_id(symbol), "sz": "20"},
                )
            )
            if not row:
                return {}
            bids = row.get("bids") or []
            asks = row.get("asks") or []
        else:
            ob = await asyncio.to_thread(ex.fetch_order_book, symbol, 20)
            bids = ob.get("bids") or []
            asks = ob.get("asks") or []

        best_bid = _num(bids[0][0]) if bids else 0.0
        best_ask = _num(asks[0][0]) if asks else 0.0
        mid = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else 0.0
        spread_bps = ((best_ask - best_bid) / mid * 10_000) if mid > 0 else 0.0
        bid_depth = sum(_num(p) * _num(q) for p, q, *_ in bids[:20])
        ask_depth = sum(_num(p) * _num(q) for p, q, *_ in asks[:20])
        total = bid_depth + ask_depth
        imbalance = (bid_depth - ask_depth) / total if total > 0 else 0.0
        return {
            "orderbook_spread_bps": spread_bps,
            "orderbook_imbalance": imbalance,
            "orderbook_bid_depth": bid_depth,
            "orderbook_ask_depth": ask_depth,
        }

    async def _fetch_long_short(self, ex, exchange: str, symbol: str) -> Dict[str, float]:
        if exchange != "okx" or not hasattr(ex.exchange, "publicGetRubikStatContractsLongShortAccountRatio"):
            return {}
        row = _first_okx_row(
            await asyncio.to_thread(
                ex.exchange.publicGetRubikStatContractsLongShortAccountRatio,
                {"ccy": _okx_ratio_currency(symbol), "period": "5m"},
            )
        )
        if not row:
            return {}
        if isinstance(row, dict):
            ratio = _num(
                row.get("longShortRatio")
                or row.get("long_short_ratio")
                or row.get("ratio")
                or row.get("lsr")
            )
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            ratio = _num(row[1])
        else:
            ratio = 0.0
        if ratio <= 0:
            return {}
        return {
            "long_short_ratio": ratio,
            "long_account_ratio": ratio / (1 + ratio),
            "short_account_ratio": 1 / (1 + ratio),
        }

    async def _fetch_open_interest(self, ex, exchange: str, symbol: str) -> Dict[str, float]:
        if exchange != "okx" or not hasattr(ex.exchange, "publicGetPublicOpenInterest"):
            return {}
        row = _first_okx_row(
            await asyncio.to_thread(
                ex.exchange.publicGetPublicOpenInterest,
                {"instType": "SWAP", "instId": _okx_swap_inst_id(symbol)},
            )
        )
        if not row:
            return {}
        return {
            "open_interest_contracts": _num(row.get("oi")),
            "open_interest_base": _num(row.get("oiCcy")),
            "open_interest_quote": _num(row.get("oiUsd")),
        }


exogenous_feature_service = ExogenousFeatureService()
