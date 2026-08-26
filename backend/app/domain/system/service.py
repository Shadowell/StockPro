"""System domain service."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Dict

from app.exchange import exchange_manager


class SystemDomainService:
    async def health(self) -> Dict:
        return {
            "status": "healthy",
            "service": "BitPro API",
            "timestamp": datetime.now().isoformat(),
        }

    async def exchanges(self) -> Dict[str, str]:
        statuses: Dict[str, str] = {}
        for name in ["okx"]:
            exchange = exchange_manager.get_exchange(name)
            if not exchange:
                statuses[name] = "not_configured"
                continue
            try:
                await asyncio.to_thread(exchange.load_markets)
                statuses[name] = "connected"
            except Exception as exc:
                statuses[name] = f"error: {exc}"
        return statuses


system_domain_service = SystemDomainService()
