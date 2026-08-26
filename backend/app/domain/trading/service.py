"""Trading domain service with strict upstream dependency policy."""
from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from app.core.errors import ExchangeUnavailableError, UpstreamError
from app.exchange import exchange_manager


class TradingDomainService:
    def _get_exchange(self, exchange_name: str):
        exchange = exchange_manager.get_exchange(exchange_name)
        if not exchange:
            raise ExchangeUnavailableError(f"交易所 {exchange_name} 不可用")
        return exchange

    async def get_balance(self, exchange_name: str) -> List[Dict]:
        exchange = self._get_exchange(exchange_name)
        try:
            return await asyncio.to_thread(exchange.fetch_balance)
        except Exception as exc:
            raise UpstreamError(f"获取余额失败: {exc}") from exc

    async def get_positions(self, exchange_name: str, symbol: Optional[str] = None) -> List[Dict]:
        exchange = self._get_exchange(exchange_name)
        try:
            symbols = [symbol] if symbol else None
            return await asyncio.to_thread(exchange.fetch_positions, symbols)
        except Exception as exc:
            raise UpstreamError(f"获取持仓失败: {exc}") from exc

    async def get_open_orders(self, exchange_name: str, symbol: Optional[str] = None) -> List[Dict]:
        exchange = self._get_exchange(exchange_name)
        try:
            return await asyncio.to_thread(exchange.fetch_open_orders, symbol)
        except Exception as exc:
            raise UpstreamError(f"获取挂单失败: {exc}") from exc


trading_domain_service = TradingDomainService()
