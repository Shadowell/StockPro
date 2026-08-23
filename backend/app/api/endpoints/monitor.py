from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from app.core.admin_auth import create_auth_dependency
from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile
from app.services.monitor_application_service import MonitorApplicationService


def create_monitor_router(context: AppContext) -> APIRouter:
    router = APIRouter(); service = MonitorApplicationService(context.repositories.operations); require_authenticated = create_auth_dependency(context)
    def view(scope: str) -> dict[str, Any]: return service.summary(scope)

    @router.get("/summary")
    async def summary(scope: Literal["business", "audit"] = Query(default="business"), _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]: return view(scope)
    @router.get("/strategies")
    async def strategies(scope: Literal["business", "audit"] = Query(default="business"), _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        result = view(scope); return {"items": result.get("strategy_health", []), "total": len(result.get("strategy_health", [])), "scope": scope}
    @router.get("/data")
    async def data(scope: Literal["business", "audit"] = Query(default="business"), _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]: return view(scope).get("data", {})
    @router.get("/risk")
    async def risk(scope: Literal["business", "audit"] = Query(default="business"), _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        result = view(scope); return {"items": result.get("active_alerts", []), "counts": result.get("risk_alerts", []), "scope": scope}
    @router.get("/notifications")
    async def notifications(scope: Literal["business", "audit"] = Query(default="business"), _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]: return {"items": view(scope).get("notifications", []), "scope": scope}
    return router
