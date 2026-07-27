from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from app.db import db_instance
from app.services.paper_runtime_service import PaperRuntimeService


router = APIRouter()
service = PaperRuntimeService(db_instance)


@router.get("/context")
async def watch_context() -> Dict[str, Any]:
    return service.watch_context()


@router.get("/alerts")
async def list_alerts(status: Optional[str] = Query("active"), limit: int = Query(200, ge=1, le=500)) -> Dict[str, Any]:
    items = service.list_alerts(status, limit)
    return {"items": items, "total": len(items)}


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str) -> Dict[str, Any]:
    try:
        return service.acknowledge_alert(alert_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
