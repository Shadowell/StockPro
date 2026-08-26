"""Paper trading (simulation) API — v2 paths used by the LiveTrading page."""
from typing import Optional

from fastapi import APIRouter, Query

from app.core.contracts import ok

router = APIRouter()


@router.get("/signals")
async def list_signals(
    instance_id: Optional[str] = None,
    strategy: Optional[str] = None,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
):
    _ = (instance_id, strategy, symbol, timeframe, limit)
    return ok({"signals": []})
