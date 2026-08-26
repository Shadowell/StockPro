"""A-share order-flow evidence boundary in the original BitPro page contract."""
from fastapi import APIRouter, Query
from app.core.contracts import ok

router=APIRouter()

@router.get("/large-trades")
async def large_trades(inst_id: str = Query(""), limit: int = Query(200)): return ok({"items": [], "count": 0, "symbol": inst_id, "unavailable_reason": "PostgreSQL has no tick-level A-share trade cache"})
@router.get("/bars")
async def bars(inst_id: str = Query(""), bar_minutes: int = Query(5)): return ok({"items": [], "bar_minutes": bar_minutes, "count": 0, "symbol": inst_id})
@router.get("/symbols")
async def symbols(): return ok({"items": [], "count": 0})
@router.get("/stream-status")
async def stream_status(): return ok({"enabled": False, "connected": False, "subscribed_count": 0, "total_ingested": 0, "total_filtered": 0, "buffer_size": 0, "reconnects": 0, "last_msg_at": None, "last_flush_at": None, "last_error": "A-share tick Provider not configured", "min_notional_usdt": 0, "inst_ids": []})
