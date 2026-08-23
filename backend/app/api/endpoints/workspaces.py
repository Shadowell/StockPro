from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.admin_auth import create_auth_dependency
from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile


def create_workspace_router(context: AppContext) -> APIRouter:
    router = APIRouter()
    require_authenticated = create_auth_dependency(context)

    @router.get("/market/overview")
    async def market_overview(
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, object]:
        return {
            "status": "adapting",
            "market": "ashare",
            "data": None,
            "writes_performed": False,
        }

    return router
