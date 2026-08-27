"""A-share Paper status adapter for BitPro monitoring consumers."""
from fastapi import APIRouter, Query

from app.core.contracts import ok
from app.domain.market import market_domain_service
from app.domain.paper import paper_domain_service


router = APIRouter()


async def _statuses():
    items = await paper_domain_service.list_instances()
    return [{"strategy_id": item["id"], "name": item["name"], "status": item["status"], "symbols": item.get("symbols", []), "pnl": item.get("total_pnl", 0), "return_pct": item.get("return_pct", 0), "win_rate": 0, "profit_factor": 0, "sharpe_ratio": 0, "max_drawdown": item.get("max_drawdown", 0), "total_trades": item.get("total_trades", 0)} for item in items]


@router.get("/active_strategies")
async def active_strategies():
    return ok(await _statuses())


@router.get("/running-strategies")
async def running_strategies():
    return ok(await _statuses())


@router.get("/alerts")
async def alerts(): return ok([])


@router.get("/events")
async def events(
    limit: int = Query(10, ge=1, le=100),
    source: str | None = Query(None, pattern="^(strategy|signal|price|abnormal|sector)$"),
    severity: str | None = Query(None, pattern="^(info|warning|critical)$"),
):
    """Return persisted alert-only events; this read path never evaluates or writes."""
    return ok(await market_domain_service.list_market_events(limit=limit, source=source, severity=severity))


@router.get("/long-short-ratio")
async def breadth_ratio(): return ok({"symbol": "CN-A", "ratio": None, "unavailable_reason": "A-share breadth is shown on the home page"})


@router.get("/open-interest")
async def gross_exposure(): return ok({"symbol": "CN-A", "open_interest": None, "unavailable_reason": "A-share Paper exposure is shown per instance"})
