"""A-share order-flow evidence boundary in the original BitPro page contract."""
from fastapi import APIRouter, Query
from app.core.contracts import ok
from app.domain.orderflow.capital_flow import capital_flow_service
from app.domain.orderflow.realtime_minute import RealtimeMinuteOrderflowService

router=APIRouter()

realtime_minute_service = RealtimeMinuteOrderflowService()


@router.get("/large-trades")
async def large_trades(inst_id: str = Query(""), limit: int = Query(200)):
    _ = limit
    return ok(realtime_minute_service.large_trades(inst_id))


@router.get("/bars")
async def bars(
    inst_id: str = Query(""),
    bar_minutes: int = Query(5),
    hours: int = Query(6),
):
    return ok(realtime_minute_service.bars(inst_id, bar_minutes, hours))


@router.get("/symbols")
async def symbols():
    return ok(realtime_minute_service.symbols())


@router.get("/capital-flow")
async def capital_flow(symbol: str = Query("600519.SH"), days: int = Query(20, ge=5, le=60)):
    return ok(capital_flow_service.summary(symbol, days=days))


@router.get("/stream-status")
async def stream_status():
    status = realtime_minute_service.stream_status()
    return ok(
        {
            "subscribed_count": 0,
            "total_ingested": 0,
            "total_filtered": 0,
            "buffer_size": 0,
            "reconnects": 0,
            "last_msg_at": None,
            "last_flush_at": None,
            "min_notional_usdt": 0,
            "inst_ids": [],
            **status,
        }
    )
