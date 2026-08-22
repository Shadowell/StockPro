"""Paper trading (simulation) API — v2 paths used by the LiveTrading page."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from app.core.contracts import ok
from app.core.errors import NotFoundError

router = APIRouter()

# 暂无独立「模拟实例」持久化：返回空列表即可消除前端 404；后续可接入 DB / 引擎会话
_paper_instances: List[Dict[str, Any]] = []


@router.get("/instances")
async def list_instances():
    return ok({"instances": list(_paper_instances)})


@router.get("/instances/{instance_id}")
async def get_instance(instance_id: str):
    for inst in _paper_instances:
        if str(inst.get("id")) == instance_id:
            return ok(inst)
    raise NotFoundError("Instance not found")


@router.delete("/instances/{instance_id}")
async def delete_instance(instance_id: str):
    global _paper_instances
    before = len(_paper_instances)
    _paper_instances = [i for i in _paper_instances if str(i.get("id")) != instance_id]
    if len(_paper_instances) == before:
        raise NotFoundError("Instance not found")
    return ok({"deleted": True})


@router.delete("/instances")
async def clear_instances():
    global _paper_instances
    _paper_instances = []
    return ok({"cleared": True})


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
