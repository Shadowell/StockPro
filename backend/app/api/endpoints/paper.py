from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.core.admin_auth import create_auth_dependency
from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile
from app.services.paper_application_service import PaperApplicationService


class PaperCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = Field(min_length=1, max_length=160)


class PaperAdvanceRequest(BaseModel):
    max_dates: int = Field(default=1, ge=1, le=260)


def create_paper_router(context: AppContext) -> APIRouter:
    router = APIRouter()
    repository = context.repositories.paper
    service = PaperApplicationService(repository)
    require_authenticated = create_auth_dependency(context)

    def require_admin(profile: AuthProfile) -> None:
        if profile.role != "admin":
            raise HTTPException(status_code=403, detail="Admin permission required.")

    def translate(error: Exception) -> HTTPException:
        message = str(error)
        status = 404 if "不存在" in message else 422
        return HTTPException(status_code=status, detail=message)

    @router.get("/instances")
    async def instances(
        scope: Literal["business", "audit"] = Query(default="audit"),
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, Any]:
        return service.list_instances(scope)

    @router.get("/instances/{instance_id}")
    async def instance(instance_id: str, _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        try:
            return service.get_instance(instance_id)
        except ValueError as error:
            raise translate(error) from error

    @router.post("/instances")
    async def create(body: PaperCreateRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        try:
            return service.create_instance(body.model_dump(exclude_none=True))
        except ValueError as error:
            raise translate(error) from error

    def run_transition(instance_id: str, action: str, profile: AuthProfile) -> dict[str, Any]:
        require_admin(profile)
        try:
            return service.transition(instance_id, action)
        except ValueError as error:
            raise translate(error) from error

    @router.post("/instances/{instance_id}/advance")
    async def advance(instance_id: str, body: PaperAdvanceRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        try:
            return service.advance(instance_id, body.max_dates)
        except ValueError as error:
            raise translate(error) from error

    @router.post("/instances/{instance_id}/start")
    async def start(instance_id: str, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        return run_transition(instance_id, "start", profile)

    @router.post("/instances/{instance_id}/pause")
    async def pause(instance_id: str, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        return run_transition(instance_id, "pause", profile)

    @router.post("/instances/{instance_id}/resume")
    async def resume(instance_id: str, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        return run_transition(instance_id, "resume", profile)

    @router.post("/instances/{instance_id}/stop")
    async def stop(instance_id: str, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        return run_transition(instance_id, "stop", profile)

    @router.get("/instances/{instance_id}/events")
    async def events(instance_id: str, _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        try:
            return {"items": _public_events(repository.events(instance_id))}
        except ValueError as error:
            raise translate(error) from error

    @router.get("/instances/{instance_id}/klines/{symbol}")
    async def klines(instance_id: str, symbol: str, _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        try:
            return repository.klines(instance_id, symbol)
        except ValueError as error:
            raise translate(error) from error

    return router


def _public_events(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in item.items() if key not in {"api_version", "strategy_api_version", "migration_status"}}
        for item in items
    ]
