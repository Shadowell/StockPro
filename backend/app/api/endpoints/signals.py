from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.admin_auth import create_auth_dependency
from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile
from app.services.signal_application_service import SignalApplicationService


def create_signals_router(context: AppContext) -> APIRouter:
    router = APIRouter(); service = SignalApplicationService(context.repositories.operations); require_authenticated = create_auth_dependency(context)

    @router.get("")
    async def signals(scope: Literal["business", "audit"] = Query(default="business"), _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]: return service.list(scope)

    @router.get("/{signal_id}")
    async def signal(signal_id: str, _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        try: return service.detail(signal_id)
        except ValueError as error: raise HTTPException(status_code=404, detail=str(error)) from error

    @router.post("/{signal_id}/acknowledge")
    async def acknowledge(signal_id: str, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        if profile.role != "admin": raise HTTPException(status_code=403, detail="Admin permission required.")
        try: return service.acknowledge(signal_id, profile.username or profile.role)
        except ValueError as error: raise HTTPException(status_code=404, detail=str(error)) from error

    return router
