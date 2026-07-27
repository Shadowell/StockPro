"""Snapshot-only factor authoring, compute and research APIs."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from app.db import db_instance
from app.services.factor_research_service import FactorResearchService


router = APIRouter()
service = FactorResearchService(db_instance)


class FactorCreateRequest(BaseModel):
    factor_code: str
    factor_name: str
    category: str
    python_code: str
    description: Optional[str] = None
    owner: str = "local"
    dependencies: List[str] = Field(default_factory=lambda: ["daily_bars", "daily_valuation", "universe_history"])
    preprocessing: Dict[str, Any] = Field(default_factory=dict)


class FactorVersionRequest(BaseModel):
    python_code: str
    declared_lookback: Optional[int] = None
    dependencies: List[str] = Field(default_factory=lambda: ["daily_bars", "daily_valuation", "universe_history"])
    preprocessing: Dict[str, Any] = Field(default_factory=dict)
    output_unit: Optional[str] = None


class FactorComputeRequest(BaseModel):
    factor_version_id: int
    trade_date: str
    dataset_snapshot_id: int
    universe_snapshot_id: int


class FactorDailyScheduleRequest(BaseModel):
    trade_date: str
    dataset_snapshot_id: int
    universe_snapshot_id: int


class FactorMaturityRequest(BaseModel):
    evaluation_dataset_snapshot_id: int


class FactorPromotionRequest(BaseModel):
    evaluation_id: int


@router.get("/factors/research/library")
async def factor_research_library() -> Dict[str, Any]:
    return {"items": service.list_library()}


@router.post("/factors")
async def create_factor(request: FactorCreateRequest) -> Dict[str, Any]:
    try:
        return service.create_factor(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/factors/{factor_id}/versions")
async def create_factor_version(factor_id: int, request: FactorVersionRequest) -> Dict[str, Any]:
    try:
        return service.create_version(factor_id, request.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/factor-versions/{version_id}/validate")
async def validate_factor_version(version_id: int) -> Dict[str, Any]:
    try:
        result = service.validate_version(version_id)
        if not result["valid"]:
            raise HTTPException(status_code=422, detail=result)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/factor-compute-runs")
async def create_factor_compute_run(request: FactorComputeRequest) -> Dict[str, Any]:
    try:
        return service.compute_factor(
            request.factor_version_id,
            request.trade_date,
            request.dataset_snapshot_id,
            request.universe_snapshot_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/factor-compute-runs")
async def list_factor_compute_runs(limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    return {"items": service.list_runs(limit)}


@router.post("/factor-schedules/run-daily")
async def run_daily_factor_schedule(request: FactorDailyScheduleRequest) -> Dict[str, Any]:
    try:
        return service.run_daily_schedule(
            request.trade_date,
            request.dataset_snapshot_id,
            request.universe_snapshot_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/factors/{factor_id}/metrics")
async def get_factor_metrics(factor_id: int) -> Dict[str, Any]:
    try:
        return service.factor_metrics(factor_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/factors/{factor_id}/values")
async def get_factor_values(
    factor_id: int,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    return service.factor_values(factor_id, limit=limit, offset=offset)


@router.get("/factor-snapshots/{snapshot_id}")
async def get_factor_snapshot(snapshot_id: int) -> Dict[str, Any]:
    snapshot = service.get_factor_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="因子快照不存在")
    return snapshot


@router.get("/factor-snapshots")
async def list_factor_snapshots(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    return {"items": service.list_factor_snapshots(limit)}


@router.get("/factor-snapshots/{snapshot_id}/values")
async def get_factor_snapshot_values(
    snapshot_id: int,
    factor_code: Optional[str] = Query(None),
    limit: int = Query(5000, ge=1, le=100000),
) -> Dict[str, Any]:
    try:
        return service.factor_snapshot_values(snapshot_id, factor_code=factor_code, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/factor-metrics/mature")
async def mature_factor_metrics(request: FactorMaturityRequest) -> Dict[str, Any]:
    try:
        return service.mature_pending_metrics(request.evaluation_dataset_snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/factor-correlations")
async def list_factor_correlations(
    trade_date: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
) -> Dict[str, Any]:
    return {"items": service.list_correlations(trade_date=trade_date, limit=limit)}


@router.post("/factor-research-protocols")
async def create_factor_research_protocol(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        return service.create_protocol(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/factor-evaluation-runs")
async def create_factor_evaluation_run(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        return service.create_evaluation(payload)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/factors/{factor_id}/promote")
async def promote_factor(factor_id: int, request: FactorPromotionRequest) -> Dict[str, Any]:
    try:
        return service.promote_factor(factor_id, request.evaluation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
