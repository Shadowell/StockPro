import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.db import db_instance
from app.services.paper_runtime_service import PaperRuntimeService
from app.services.strategy_lab_service import strategy_lab_service

router = APIRouter()
runtime_service = PaperRuntimeService(db_instance)
_PAPER_LIST_CACHE: Dict[str, Any] = {}
_PAPER_LIST_TTL_SECONDS = 20.0


def reset_paper_list_cache() -> None:
    _PAPER_LIST_CACHE.clear()


class RunPaperRequest(BaseModel):
    strategy_id: int
    symbols: Optional[List[str]] = None
    initial_capital: float = 100000.0
    position_pct: float = 0.3


class PaperInstanceRequest(BaseModel):
    name: str = ""
    strategy_version_id: str
    dataset_snapshot_id: int
    factor_snapshot_id: int
    universe_snapshot_id: int
    pool_snapshot_id: int
    research_protocol_id: str
    qualifying_backtest_run_id: str
    initial_cash: float = 1_000_000
    parameters: Dict[str, Any] = Field(default_factory=dict)
    capacity_limits: Dict[str, Any] = Field(default_factory=dict)
    feed_config: Dict[str, Any] = Field(default_factory=dict)
    data_purpose: Literal["user", "acceptance", "seed"] = "user"


class PaperCycleRequest(BaseModel):
    trade_date: str
    data_available_at: Optional[str] = None
    observed_at: Optional[str] = None
    cycle_key: Optional[str] = None


def _runtime_error(exc: ValueError, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(exc))


@router.get("/instances")
async def list_instances() -> Dict[str, Any]:
    cached = _PAPER_LIST_CACHE.get("payload")
    if cached and time.monotonic() - float(_PAPER_LIST_CACHE.get("at") or 0) < _PAPER_LIST_TTL_SECONDS:
        return cached
    items = await run_in_threadpool(runtime_service.list_instances)
    payload = {"items": items, "total": len(items)}
    _PAPER_LIST_CACHE["at"] = time.monotonic()
    _PAPER_LIST_CACHE["payload"] = payload
    return payload


@router.post("/instances")
async def create_instance(request: PaperInstanceRequest) -> Dict[str, Any]:
    try:
        created = await run_in_threadpool(runtime_service.create_instance, request.model_dump())
    except ValueError as exc:
        raise _runtime_error(exc) from exc
    reset_paper_list_cache()
    return created


@router.get("/instances/{instance_id}")
async def get_instance(instance_id: str) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(runtime_service.get_instance, instance_id)
    except ValueError as exc:
        raise _runtime_error(exc, 404) from exc


@router.post("/instances/{instance_id}/start")
async def start_instance(instance_id: str) -> Dict[str, Any]:
    try:
        started = await run_in_threadpool(runtime_service.start, instance_id)
    except ValueError as exc:
        raise _runtime_error(exc) from exc
    reset_paper_list_cache()
    return started


@router.post("/instances/{instance_id}/pause")
async def pause_instance(instance_id: str) -> Dict[str, Any]:
    try:
        paused = await run_in_threadpool(runtime_service.pause, instance_id)
    except ValueError as exc:
        raise _runtime_error(exc) from exc
    reset_paper_list_cache()
    return paused


@router.post("/instances/{instance_id}/resume")
async def resume_instance(instance_id: str) -> Dict[str, Any]:
    try:
        resumed = await run_in_threadpool(runtime_service.resume, instance_id)
    except ValueError as exc:
        raise _runtime_error(exc) from exc
    reset_paper_list_cache()
    return resumed


@router.post("/instances/{instance_id}/stop")
async def stop_instance(instance_id: str) -> Dict[str, Any]:
    try:
        stopped = await run_in_threadpool(runtime_service.stop, instance_id)
    except ValueError as exc:
        raise _runtime_error(exc) from exc
    reset_paper_list_cache()
    return stopped


@router.post("/instances/{instance_id}/cycles")
async def process_cycle(instance_id: str, request: PaperCycleRequest) -> Dict[str, Any]:
    try:
        cycle = await run_in_threadpool(
            runtime_service.process_cycle,
            instance_id,
            request.model_dump(exclude_none=True),
        )
    except ValueError as exc:
        raise _runtime_error(exc) from exc
    reset_paper_list_cache()
    return cycle


class PaperAdvanceRequest(BaseModel):
    instance_ids: Optional[List[str]] = None
    max_dates: int = Field(default=260, ge=1, le=1000)


@router.post("/instances/advance")
async def advance_instances(request: PaperAdvanceRequest) -> Dict[str, Any]:
    """批量推进运行中 Paper 实例的待处理交易日周期（幂等，可重复调用）。"""
    result = await run_in_threadpool(
        runtime_service.advance_instances,
        instance_ids=request.instance_ids,
        max_dates=request.max_dates,
    )
    reset_paper_list_cache()
    return result


@router.get("/instances/{instance_id}/events")
async def list_instance_events(instance_id: str) -> Dict[str, Any]:
    try:
        items = await run_in_threadpool(runtime_service.events, instance_id)
        return {"items": items, "total": len(items)}
    except ValueError as exc:
        raise _runtime_error(exc, 404) from exc


@router.get("/instances/{instance_id}/klines/{symbol}")
async def get_instance_klines(instance_id: str, symbol: str) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(runtime_service.get_instance_klines, instance_id, symbol)
    except ValueError as exc:
        raise _runtime_error(exc, 404) from exc


@router.post("/run")
async def run_paper(request: RunPaperRequest) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(
            strategy_lab_service.run_paper_trading,
            strategy_id=request.strategy_id,
            symbols=request.symbols,
            initial_capital=request.initial_capital,
            position_pct=request.position_pct,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/accounts")
async def list_paper_accounts() -> Dict[str, Any]:
    accounts = await run_in_threadpool(strategy_lab_service.list_paper_accounts)
    return {"accounts": accounts, "total": len(accounts)}


@router.get("/{account_id}")
async def get_paper_account(account_id: int) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(strategy_lab_service.get_paper_account, account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{account_id}/refresh")
async def refresh_paper_account(account_id: int) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(strategy_lab_service.refresh_paper_account, account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{account_id}/stop")
async def stop_paper_account(account_id: int) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(strategy_lab_service.stop_paper_account, account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
