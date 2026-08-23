from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.core.admin_auth import create_auth_dependency
from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile
from app.services.strategy_application_service import StrategyApplicationService


class StrategyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    script_content: str = Field(min_length=1, max_length=200_000)


class StrategyVersionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    description: str | None = Field(default=None, max_length=1000)
    script_content: str = Field(min_length=1, max_length=200_000)


class StrategyValidateRequest(BaseModel):
    script_content: str = Field(min_length=1, max_length=200_000)


class QuickRunRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


def create_strategy_router(context: AppContext) -> APIRouter:
    router = APIRouter()
    service = StrategyApplicationService(context.repositories.strategies)
    require_authenticated = create_auth_dependency(context)

    def require_admin(profile: AuthProfile) -> None:
        if profile.role != "admin":
            raise HTTPException(status_code=403, detail="Admin permission required.")

    @router.get("/strategies")
    async def strategies(_profile: AuthProfile = Depends(require_authenticated)) -> dict[str, object]:
        return {"items": service.list_strategies()}

    @router.post("/strategies")
    async def create_strategy(body: StrategyCreateRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        try:
            return service.create_strategy(body.model_dump(exclude_none=True))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.get("/strategies/{version_id}")
    async def strategy(
        version_id: str,
        include_audit: bool = Query(default=False),
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, Any]:
        item = service.get_strategy(version_id, include_audit=include_audit)
        if item is None:
            raise HTTPException(status_code=404, detail="策略版本不存在")
        return item

    @router.post("/strategies/{parent_id}/versions")
    async def create_version(parent_id: str, body: StrategyVersionRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        try:
            return service.create_version(parent_id, body.model_dump(exclude_none=True))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/strategies/validate")
    async def validate(body: StrategyValidateRequest, _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        return service.validate(body.model_dump())

    @router.post("/strategies/{version_id}/quick-run")
    async def quick_run(version_id: str, body: QuickRunRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        try:
            return service.quick_run(version_id, body.model_dump(exclude_none=True))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return router
