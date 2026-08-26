"""Read-only A-share Paper implementation for BitPro's original live workspace."""
from fastapi import APIRouter, Query

from app.core.contracts import ok
from app.domain.paper import paper_domain_service


router = APIRouter()


@router.get("/instances")
async def paper_instances():
    return ok({"items": await paper_domain_service.list_instances()})


@router.get("/dashboard")
async def paper_dashboard(instance_id: int | None = Query(None)):
    return ok(await paper_domain_service.dashboard(instance_id))


@router.get("/events")
async def paper_events(instance_id: int, limit: int = Query(50, ge=1, le=500)):
    return ok({"events": await paper_domain_service.events(instance_id, limit)})


@router.get("/equity_curve")
async def paper_equity_curve(instance_id: int):
    return ok(await paper_domain_service.equity_curve(instance_id))


@router.get("/trades")
async def paper_trades(instance_id: int, limit: int = Query(100, ge=1, le=500)):
    return ok(await paper_domain_service.trades(instance_id, limit))
