from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app.core.admin_auth import create_auth_dependency
from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile
from app.services.operations_application_service import OperationsApplicationService, public


class RulePayload(BaseModel):
    model_config = ConfigDict(extra="allow")


def create_watch_router(context: AppContext) -> APIRouter:
    router = APIRouter(); repository = context.repositories.operations; service = OperationsApplicationService(repository); require_authenticated = create_auth_dependency(context)
    def admin(profile: AuthProfile) -> None:
        if profile.role != "admin": raise HTTPException(status_code=403, detail="Admin permission required.")
    def translated(error: ValueError, missing: bool = False) -> HTTPException: return HTTPException(status_code=404 if missing else 422, detail=str(error))

    @router.get("/context")
    async def watch_context(scope: Literal["business", "audit"] = Query(default="business"), _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]: return service.watch_context(scope)

    @router.get("/alerts")
    async def alerts(status: str | None = Query(default="active"), limit: int = Query(default=200, ge=1, le=500), _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        items = public(repository.list_alerts(status, limit)); return {"items": items, "total": len(items)}

    @router.post("/alerts/{alert_id}/acknowledge")
    async def acknowledge_alert(alert_id: str, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        admin(profile)
        try: return public(repository.acknowledge_alert(alert_id, profile.username or profile.role))
        except ValueError as error: raise translated(error, True) from error

    @router.get("/rules")
    async def rules(scope: Literal["business", "audit"] = Query(default="business"), _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        items = public(repository.list_rules(scope)); return {"items": items, "total": len(items), "scope": scope}

    @router.post("/rules")
    async def create_rule(body: RulePayload, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        admin(profile)
        try: return public(repository.create_rule(body.model_dump()))
        except ValueError as error: raise translated(error) from error

    @router.post("/rules/{rule_id}/versions")
    async def create_rule_version(rule_id: str, body: RulePayload, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        admin(profile)
        try: return public(repository.create_rule_version(rule_id, body.model_dump()))
        except ValueError as error: raise translated(error) from error

    @router.post("/rules/{rule_id}/preview")
    async def preview(rule_id: str, _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        try: return public(repository.preview_rule(rule_id))
        except ValueError as error: raise translated(error, True) from error

    @router.post("/rules/{rule_id}/evaluate")
    async def evaluate(rule_id: str, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        admin(profile)
        try:
            result = public(repository.evaluate_rule(rule_id)); result["orders_created"] = 0; return result
        except ValueError as error: raise translated(error) from error

    return router
