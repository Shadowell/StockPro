from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.core.admin_auth import create_auth_dependency
from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile


class FactorCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    factor_code: str = Field(min_length=1, max_length=120)
    factor_name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=80)


class FactorVersionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    python_code: str = Field(min_length=1, max_length=50_000)


class FactorComputeRequest(BaseModel):
    trade_date: str
    dataset_snapshot_id: int
    universe_snapshot_id: int


def create_factors_router(context: AppContext) -> APIRouter:
    router = APIRouter()
    repository = context.repositories.factors
    require_authenticated = create_auth_dependency(context)

    def require_admin(profile: AuthProfile) -> None:
        if profile.role != "admin":
            raise HTTPException(status_code=403, detail="Admin permission required.")

    @router.get("/factors")
    async def factors(_profile: AuthProfile = Depends(require_authenticated)) -> dict[str, object]:
        return {"items": repository.list_library()}

    @router.post("/factors")
    async def create_factor(body: FactorCreateRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        try:
            return repository.create_factor(body.model_dump())
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/factors/{definition_id}/versions")
    async def create_version(definition_id: int, body: FactorVersionRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        try:
            return repository.create_version(definition_id, body.model_dump())
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/factor-versions/{version_id}/validate")
    async def validate(version_id: int, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        return repository.validate_version(version_id)

    @router.post("/factor-versions/{version_id}/compute")
    async def compute(version_id: int, body: FactorComputeRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        try:
            return repository.compute_factor(version_id, body.trade_date, body.dataset_snapshot_id, body.universe_snapshot_id)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.get("/factors/{factor_identifier}/metrics")
    async def metrics(factor_identifier: str, _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, object]:
        try:
            payload = repository.factor_metrics(factor_identifier)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"factor": payload["factor"], "items": payload["metrics"]}

    @router.get("/factors/{factor_identifier}/values")
    async def values(
        factor_identifier: str,
        limit: int = Query(default=500, ge=1, le=5000),
        offset: int = Query(default=0, ge=0),
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, Any]:
        try:
            return repository.factor_values(factor_identifier, limit, offset)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.get("/factor-runs")
    async def runs(limit: int = Query(default=100, ge=1, le=500), _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, object]:
        return {"items": repository.list_runs(limit)}

    @router.get("/factor-correlations")
    async def correlations(
        trade_date: str | None = None,
        limit: int = Query(default=500, ge=1, le=5000),
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, object]:
        return {"items": repository.list_correlations(trade_date, limit)}

    @router.get("/factor-snapshots")
    async def snapshots(limit: int = Query(default=50, ge=1, le=200), _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, object]:
        return {"items": repository.list_snapshots(limit)}

    @router.get("/factor-snapshots/{snapshot_id}")
    async def snapshot(snapshot_id: int, _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        item = repository.get_snapshot(snapshot_id)
        if item is None:
            raise HTTPException(status_code=404, detail="因子快照不存在")
        return item

    @router.get("/factor-snapshots/{snapshot_id}/values")
    async def snapshot_values(
        snapshot_id: int,
        factor_code: str | None = None,
        limit: int = Query(default=5000, ge=1, le=100_000),
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, Any]:
        try:
            return repository.snapshot_values(snapshot_id, factor_code, limit)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return router
