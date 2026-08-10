"""Versioned stock-pool generation, evidence, snapshot, and backtest handoff APIs."""
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.db import db_instance
from app.services.stock_pool_service import StockPoolService


router = APIRouter()
service = StockPoolService(db_instance)


class PoolCreateRequest(BaseModel):
    name: str
    pool_type: str
    description: str = ""
    rule_type: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    data_purpose: Literal["user", "acceptance", "seed"] = "user"


class PoolGenerateRequest(BaseModel):
    dataset_snapshot_id: int
    universe_snapshot_id: int
    trade_date: str
    factor_snapshot_id: Optional[int] = None
    market_evidence_snapshot_id: Optional[int] = None


class PoolSnapshotRequest(BaseModel):
    generation_id: Optional[str] = None


class PoolBacktestDraftRequest(BaseModel):
    strategy_version_id: str
    start_date: str
    end_date: str
    initial_cash: float = 1_000_000
    cost_model_id: Optional[str] = None
    research_protocol_id: Optional[str] = None
    benchmark_code: str = "000300.SH"
    parameters: Dict[str, Any] = Field(default_factory=dict)
    name: str = ""
    hypothesis: str = ""


def _error(exc: ValueError, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(exc))


@router.get("/pools")
async def list_pools() -> Dict[str, Any]:
    items = await run_in_threadpool(service.list_pools)
    return {"items": items, "total": len(items)}


@router.post("/pools")
async def create_pool(request: PoolCreateRequest) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(
            service.create_pool,
            request.model_dump(exclude_none=True),
        )
    except ValueError as exc:
        raise _error(exc) from exc


@router.get("/pools/{pool_id}")
async def get_pool(pool_id: str) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(service.get_pool, pool_id)
    except ValueError as exc:
        raise _error(exc, 404) from exc


@router.post("/pools/{pool_id}/generate")
async def generate_pool(pool_id: str, request: PoolGenerateRequest) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(
            service.generate,
            pool_id,
            request.model_dump(exclude_none=True),
        )
    except ValueError as exc:
        raise _error(exc) from exc


@router.get("/pools/{pool_id}/members")
async def list_members(pool_id: str, generation_id: Optional[str] = Query(None)) -> Dict[str, Any]:
    try:
        items = await run_in_threadpool(service.members, pool_id, generation_id)
        return {"items": items, "total": len(items)}
    except ValueError as exc:
        raise _error(exc, 404) from exc


@router.post("/pools/{pool_id}/snapshots")
async def seal_snapshot(pool_id: str, request: PoolSnapshotRequest) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(
            service.seal_snapshot,
            pool_id,
            request.generation_id,
        )
    except ValueError as exc:
        raise _error(exc) from exc


@router.get("/pool-snapshots")
async def list_snapshots(pool_id: Optional[str] = Query(None)) -> Dict[str, Any]:
    items = await run_in_threadpool(service.list_snapshots, pool_id)
    return {"items": items, "total": len(items)}


@router.get("/pool-snapshots/{snapshot_id}")
async def get_snapshot(snapshot_id: int) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(service.get_snapshot, snapshot_id)
    except ValueError as exc:
        raise _error(exc, 404) from exc


@router.post("/pool-snapshots/{snapshot_id}/backtest-draft")
@router.post("/pool-snapshots/{snapshot_id}/backtests")
async def create_backtest_draft(snapshot_id: int, request: PoolBacktestDraftRequest) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(
            service.create_backtest_draft,
            snapshot_id,
            request.model_dump(exclude_none=True),
        )
    except ValueError as exc:
        raise _error(exc) from exc
