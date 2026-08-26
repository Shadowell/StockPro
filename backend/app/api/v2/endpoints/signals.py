"""Read-only A-share adapter for BitPro's signal-centre contracts."""
from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Query

from app.core.contracts import ok
from app.domain.strategy.repository import StrategyRepository


router = APIRouter()
repository = StrategyRepository()


@router.get("/signal-channels")
async def list_signal_channels():
    # Crypto webhook destinations are intentionally not carried into StockPro.
    return ok({"channels": []})


@router.get("/signal-strategies")
async def list_signal_strategies():
    rows = await asyncio.to_thread(repository.list_strategies)
    strategies = []
    for row in rows:
        raw_id = row.get("legacy_strategy_id")
        if raw_id is None:
            raw_id = UUID(str(row["id"])).int & 2147483647
        strategies.append(
            {
                "strategy_id": int(raw_id),
                "strategy_name": str(row.get("name") or ""),
                "signal_enabled": False,
                "manual_approval_required": True,
                "status": "read_only",
                "exchange": "CN",
                "symbols": [],
                "market_type": "stock",
                "total_pnl": None,
                "return_pct": None,
                "updated_at": row.get("updated_at"),
            }
        )
    return ok({"strategies": strategies})


@router.get("/signals")
async def list_signals(
    status: str | None = Query(None),
    strategy_id: int | None = Query(None),
    channel_id: int | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    del status, strategy_id, channel_id, limit
    return ok({"signals": []})
