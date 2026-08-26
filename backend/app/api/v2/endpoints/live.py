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


@router.get("/accounts")
async def paper_accounts():
    return ok({"accounts": [{"account_id": "paper", "name": "A股 Paper 现金账本", "exchange": "CN", "exchange_alias": "A股", "is_default": True, "configured": True, "enabled": True, "testnet": True, "display_only": True, "can_trade": False}]})


@router.get("/strategies")
async def paper_strategies():
    return ok({"strategies": await paper_domain_service.list_instances()})


@router.get("/watchlist")
async def paper_watchlist(account_id: str = Query("paper"), limit: int = Query(100)):
    return ok({"account_id": account_id, "exchange": "CN", "items": []})


@router.get("/accounts/{account_id}/positions")
async def account_positions(account_id: str): return ok({"account_id": account_id, "exchange": "CN", "positions": []})


@router.get("/accounts/{account_id}/orders/history")
async def account_orders(account_id: str, limit: int = Query(50)): return ok({"account_id": account_id, "exchange": "CN", "orders": []})
