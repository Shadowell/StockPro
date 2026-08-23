from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.core.admin_auth import create_auth_dependency
from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile


class PoolCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    pool_type: Literal["screener", "factor", "sector", "event", "manual"]
    description: str = Field(default="", max_length=500)
    data_purpose: Literal["user", "acceptance", "seed"] = "user"
    rule_type: str | None = Field(default=None, max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)


class PoolGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    trade_date: str
    dataset_snapshot_id: int | None = None
    universe_snapshot_id: int | None = None
    factor_snapshot_id: int | None = None
    market_evidence_snapshot_id: int | None = None


class PoolSealRequest(BaseModel):
    generation_id: str


def create_pools_router(context: AppContext) -> APIRouter:
    router = APIRouter()
    repository = context.repositories.pools
    require_authenticated = create_auth_dependency(context)

    def require_admin(profile: AuthProfile) -> None:
        if profile.role != "admin":
            raise HTTPException(status_code=403, detail="Admin permission required.")

    @router.get("/pools")
    async def list_pools(
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, object]:
        return {"items": repository.list_pools()}

    @router.post("/pools")
    async def create_pool(
        body: PoolCreateRequest,
        profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, Any]:
        require_admin(profile)
        payload = body.model_dump(exclude_none=True)
        if payload.get("rule_type") is None:
            payload.pop("rule_type", None)
        try:
            return repository.create_pool(payload)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.get("/pools/{pool_id}")
    async def get_pool(
        pool_id: str,
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, Any]:
        try:
            return repository.get_pool(pool_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.post("/pools/{pool_id}/generate")
    async def generate(
        pool_id: str,
        body: PoolGenerateRequest,
        profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, Any]:
        require_admin(profile)
        try:
            return repository.generate(pool_id, body.model_dump(exclude_none=True))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.get("/pools/{pool_id}/members")
    async def members(
        pool_id: str,
        generation_id: str | None = None,
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, object]:
        try:
            return {"items": repository.members(pool_id, generation_id)}
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.get("/pools/{pool_id}/snapshots")
    async def pool_snapshots(
        pool_id: str,
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, object]:
        return {"items": repository.list_snapshots(pool_id)}

    @router.post("/pools/{pool_id}/snapshots")
    async def seal_snapshot(
        pool_id: str,
        body: PoolSealRequest,
        profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, Any]:
        require_admin(profile)
        try:
            return repository.seal_snapshot(pool_id, body.generation_id)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.get("/pool-snapshots")
    async def snapshots(
        pool_id: str | None = Query(default=None),
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, object]:
        return {"items": repository.list_snapshots(pool_id)}

    @router.get("/pool-snapshots/{snapshot_id}")
    async def snapshot(
        snapshot_id: int,
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, Any]:
        try:
            return repository.get_snapshot(snapshot_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return router
