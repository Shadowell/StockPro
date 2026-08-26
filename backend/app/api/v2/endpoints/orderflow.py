"""A-share order-flow evidence boundary in the original BitPro page contract."""
from fastapi import APIRouter, Query
from app.core.contracts import ok

router=APIRouter()

ORDERFLOW_PROVIDER_STATUS = {
    "data_status": "unavailable",
    "provider_source": "A-share Level-2/tick vendor",
    "permission_state": "requires_configuration",
    "frequency": "realtime_ticks_or_1m_microstructure",
    "tables": ["trade_ticks", "orderflow_large_trades", "orderflow_bars"],
    "setup_path": "/settings",
    "last_error": "A-share tick Provider not configured",
}


@router.get("/large-trades")
async def large_trades(inst_id: str = Query(""), limit: int = Query(200)):
    _ = limit
    return ok(
        {
            "items": [],
            "count": 0,
            "symbol": inst_id,
            "unavailable_reason": "A-share tick Provider not configured",
            **ORDERFLOW_PROVIDER_STATUS,
        }
    )


@router.get("/bars")
async def bars(inst_id: str = Query(""), bar_minutes: int = Query(5)):
    return ok(
        {
            "items": [],
            "bar_minutes": bar_minutes,
            "count": 0,
            "symbol": inst_id,
            "unavailable_reason": "A-share tick Provider not configured",
            **ORDERFLOW_PROVIDER_STATUS,
        }
    )


@router.get("/symbols")
async def symbols():
    return ok({"items": [], "count": 0, **ORDERFLOW_PROVIDER_STATUS})


@router.get("/stream-status")
async def stream_status():
    return ok(
        {
            "enabled": False,
            "connected": False,
            "subscribed_count": 0,
            "total_ingested": 0,
            "total_filtered": 0,
            "buffer_size": 0,
            "reconnects": 0,
            "last_msg_at": None,
            "last_flush_at": None,
            "min_notional_usdt": 0,
            "inst_ids": [],
            **ORDERFLOW_PROVIDER_STATUS,
        }
    )
