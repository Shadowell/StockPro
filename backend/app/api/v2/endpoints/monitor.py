"""A-share Paper status adapter for BitPro monitoring consumers."""
from fastapi import APIRouter

from app.core.contracts import ok
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
