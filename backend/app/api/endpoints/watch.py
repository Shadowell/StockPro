import time
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from app.db import db_instance
from app.services.paper_runtime_service import PaperRuntimeService
from app.services.watch_rule_service import WatchRuleService


router = APIRouter()
service = PaperRuntimeService(db_instance)
rule_service = WatchRuleService(db_instance)
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


@router.get("/rules")
async def list_watch_rules() -> Dict[str, Any]:
    items = await run_in_threadpool(rule_service.list_watch_rules)
    return {"items": items, "total": len(items)}


@router.post("/rules")
async def create_watch_rule(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(rule_service.create_watch_rule, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/rules/{rule_id}/versions")
async def create_watch_rule_version(rule_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(rule_service.create_watch_rule_version, rule_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/rules/{rule_id}/preview")
async def preview_watch_rule(rule_id: str) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(rule_service.preview_watch_rule, rule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/rules/{rule_id}/evaluate")
async def evaluate_watch_rule(rule_id: str) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(rule_service.evaluate_watch_rule, rule_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
