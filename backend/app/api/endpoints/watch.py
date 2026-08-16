import time
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from app.db import db_instance
from app.services.paper_runtime_service import PaperRuntimeService


router = APIRouter()
service = PaperRuntimeService(db_instance)
_WATCH_CACHE: Dict[str, Any] = {}


def reset_watch_cache() -> None:
    _WATCH_CACHE.clear()


@router.get("/context")
async def watch_context(scope: Literal["business", "audit"] = "business") -> Dict[str, Any]:
    now = time.monotonic()
    cached = _WATCH_CACHE.get(scope)
    if cached and now - float(cached.get("at") or 0) < 60:
        return cached["payload"]
    payload = await run_in_threadpool(service.watch_context, scope)
    _WATCH_CACHE[scope] = {"at": time.monotonic(), "payload": payload}
    return payload


@router.get("/alerts")
async def list_alerts(status: Optional[str] = Query("active"), limit: int = Query(200, ge=1, le=500)) -> Dict[str, Any]:
    items = await run_in_threadpool(service.list_alerts, status, limit)
    return {"items": items, "total": len(items)}


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(service.acknowledge_alert, alert_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
