"""Funding domain service with strict upstream dependency behavior."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from app.core.errors import ExchangeUnavailableError, UpstreamError
from app.db.local_db import db_instance as db
from app.exchange import exchange_manager


class FundingDomainService:
    """Funding domain service with non-blocking adapter calls."""

    def _get_exchange(self, exchange_name: str):
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ExchangeUnavailableError(f"交易所 {exchange_name} 不可用")
        return exchange

    @staticmethod
    def _cache_rates(exchange_name: str, rates: List[Dict[str, Any]]) -> None:
        for rate in rates:
            symbol = rate.get("symbol")
            if symbol:
                db.update_funding_realtime(exchange_name, symbol, rate)

    async def get_funding_rates(
        self,
        exchange_name: str,
        symbols: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        exchange = self._get_exchange(exchange_name)
        try:
            rates = await asyncio.to_thread(exchange.fetch_funding_rates, symbols)
            await asyncio.to_thread(self._cache_rates, exchange_name, rates)
            return rates
        except Exception as exc:
            raise UpstreamError(f"获取资金费率失败: {exc}") from exc

    async def get_funding_rate(self, exchange_name: str, symbol: str) -> Optional[Dict[str, Any]]:
        exchange = self._get_exchange(exchange_name)
        try:
            rate = await asyncio.to_thread(exchange.fetch_funding_rate, symbol)
            if rate:
                await asyncio.to_thread(db.update_funding_realtime, exchange_name, symbol, rate)
            return rate
        except Exception as exc:
            raise UpstreamError(f"获取资金费率失败: {exc}") from exc

    @staticmethod
    def _cache_history(exchange_name: str, symbol: str, history: List[Dict[str, Any]]) -> None:
        for item in history:
            db.insert_funding_rate(
                exchange_name,
                symbol,
                item.get("timestamp"),
                item.get("rate"),
                item.get("mark_price"),
            )

    async def get_funding_history(
        self,
        exchange_name: str,
        symbol: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        exchange = self._get_exchange(exchange_name)
        try:
            cached = await asyncio.to_thread(db.get_funding_history, exchange_name, symbol, limit)
            if len(cached) >= limit:
                return cached[:limit]

            history = await asyncio.to_thread(exchange.fetch_funding_history, symbol, limit)
            await asyncio.to_thread(self._cache_history, exchange_name, symbol, history)
            return history
        except Exception as exc:
            raise UpstreamError(f"获取资金费率历史失败: {exc}") from exc

    async def get_opportunities(
        self,
        exchange_name: str,
        min_rate: float = 0.0001,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        exchange = self._get_exchange(exchange_name)
        try:
            rates = await asyncio.to_thread(exchange.fetch_funding_rates)
            opportunities: List[Dict[str, Any]] = []
            for rate in rates:
                current_rate = rate.get("current_rate", 0) or 0
                if abs(current_rate) < min_rate:
                    continue
                annualized = abs(current_rate) * 3 * 365 * 100
                opportunities.append(
                    {
                        "symbol": rate.get("symbol"),
                        "exchange": exchange_name,
                        "rate": current_rate,
                        "annualized": round(annualized, 2),
                        "next_funding_time": rate.get("next_funding_time", 0),
                    }
                )
            opportunities.sort(key=lambda x: abs(x["rate"]), reverse=True)
            return opportunities[:limit]
        except Exception as exc:
            raise UpstreamError(f"获取资金费率机会失败: {exc}") from exc

    async def get_summary(self) -> Dict[str, Any]:
        summary: Dict[str, Any] = {"exchanges": {}, "top_opportunities": []}
        all_opportunities: List[Dict[str, Any]] = []

        for exchange_name in ["okx"]:
            try:
                exchange = self._get_exchange(exchange_name)
                rates = await asyncio.to_thread(exchange.fetch_funding_rates)

                positive_count = sum(1 for r in rates if (r.get("current_rate") or 0) > 0)
                negative_count = sum(1 for r in rates if (r.get("current_rate") or 0) < 0)
                avg_rate = sum(r.get("current_rate") or 0 for r in rates) / len(rates) if rates else 0

                summary["exchanges"][exchange_name] = {
                    "total": len(rates),
                    "positive_count": positive_count,
                    "negative_count": negative_count,
                    "avg_rate": round(avg_rate * 100, 4),
                }

                for rate in rates:
                    current_rate = rate.get("current_rate", 0) or 0
                    if abs(current_rate) < 0.0001:
                        continue
                    annualized = abs(current_rate) * 3 * 365 * 100
                    all_opportunities.append(
                        {
                            "symbol": rate.get("symbol"),
                            "exchange": exchange_name,
                            "rate": current_rate,
                            "annualized": round(annualized, 2),
                        }
                    )
            except ExchangeUnavailableError as exc:
                summary["exchanges"][exchange_name] = {"error": str(exc)}
            except Exception as exc:
                summary["exchanges"][exchange_name] = {"error": str(exc)}

        all_opportunities.sort(key=lambda x: abs(x["rate"]), reverse=True)
        summary["top_opportunities"] = all_opportunities[:10]
        return summary


funding_domain_service = FundingDomainService()
