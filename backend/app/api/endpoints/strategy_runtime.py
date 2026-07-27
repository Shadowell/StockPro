"""Stable StockPro Strategy API v1 authoring and replay endpoints."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import db_instance
from app.services.strategy_runtime_service import StrategyRuntimeService


router = APIRouter()
service = StrategyRuntimeService(db_instance)


class StrategyCreateRequest(BaseModel):
    name: str
    script_content: str
    description: str = ""
    parameter_schema: Dict[str, Any] = Field(default_factory=dict)
    data_dependencies: List[str] = Field(default_factory=lambda: ["daily_bars"])
    dependency_manifest: Dict[str, Any] = Field(default_factory=dict)
    runtime_limits: Dict[str, Any] = Field(default_factory=dict)


class StrategyVersionCreateRequest(BaseModel):
    script_content: str
    description: Optional[str] = None
    parameter_schema: Dict[str, Any] = Field(default_factory=dict)
    data_dependencies: List[str] = Field(default_factory=lambda: ["daily_bars"])
    dependency_manifest: Dict[str, Any] = Field(default_factory=dict)
    runtime_limits: Dict[str, Any] = Field(default_factory=dict)


class StrategyReplayRequest(BaseModel):
    dataset_snapshot_id: int
    factor_snapshot_id: Optional[int] = None
    mode: str = "quick"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    symbols: List[str] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    event_limit: int = 30


@router.post("")
async def create_strategy_v1(request: StrategyCreateRequest) -> Dict[str, Any]:
    try:
        return service.create_strategy(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{strategy_id}/versions")
async def create_strategy_version(strategy_id: str, request: StrategyVersionCreateRequest) -> Dict[str, Any]:
    try:
        parent_id = strategy_id
        if strategy_id.isdigit():
            latest = service.latest_for_legacy(int(strategy_id))
            if not latest:
                raise ValueError("旧策略尚无版本，请先保存为 Strategy API v1")
            parent_id = str(latest["id"])
        return service.create_version(parent_id, request.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{strategy_id}/versions/latest")
async def get_latest_strategy_version(strategy_id: int) -> Dict[str, Any]:
    version = service.latest_for_legacy(strategy_id)
    if not version:
        if not db_instance.get_strategy_by_id(strategy_id):
            raise HTTPException(status_code=404, detail="策略不存在")
        raise HTTPException(
            status_code=404,
            detail="策略尚未保存为版本；只读请求不会自动创建版本。",
        )
    return version


@router.post("/versions/{version_id}/validate")
async def validate_strategy_version(version_id: str) -> Dict[str, Any]:
    try:
        report = service.validate_version(version_id)
        if not report["valid"]:
            raise HTTPException(status_code=422, detail=report)
        return report
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/versions/{version_id}")
async def get_strategy_version(version_id: str) -> Dict[str, Any]:
    version = service.get_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="策略版本不存在")
    return version


@router.post("/versions/{version_id}/quick-run")
async def quick_run_strategy_version(version_id: str, request: StrategyReplayRequest) -> Dict[str, Any]:
    try:
        return service.replay(version_id, {**request.model_dump(), "mode": "quick"})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/versions/{version_id}/replay")
async def replay_strategy_version(version_id: str, request: StrategyReplayRequest) -> Dict[str, Any]:
    try:
        return service.replay(version_id, request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/replays/{run_id}/intents")
async def get_strategy_replay_intents(run_id: str) -> Dict[str, Any]:
    return {"items": service.list_intents(run_id)}
