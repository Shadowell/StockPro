"""Data sync endpoints for API v2."""
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Query

from app.core.contracts import ok
from app.domain.sync import sync_domain_service
from app.services.data_sync_service import data_sync_service

router = APIRouter()

_quick_sync_tasks: Dict[str, Dict[str, Any]] = {}


def _split_csv(value: Optional[str]) -> Optional[List[str]]:
    if value is None:
        return None
    items = [item.strip() for item in str(value).split(",") if item.strip()]
    return items or None


def _has_running_quick_sync(exclude_key: Optional[str] = None) -> bool:
    return any(
        key != exclude_key and bool(info.get("running"))
        for key, info in _quick_sync_tasks.items()
    )


@router.get("/status")
async def status():
    return ok(sync_domain_service.status())


@router.get("/jobs")
async def jobs(
    limit: int = Query(20, ge=1, le=100, description="返回最近任务数"),
    include_items: bool = Query(True, description="是否包含每个交易对/周期明细"),
):
    return ok(sync_domain_service.jobs(limit=limit, include_items=include_items))


@router.get("/config")
async def config():
    return ok(sync_domain_service.config())


@router.get("/schedule")
async def schedule_config():
    return ok(sync_domain_service.schedule_config())


@router.put("/schedule")
async def update_schedule_config(payload: Dict[str, Any] = Body(default_factory=dict)):
    return ok(sync_domain_service.update_schedule_config(payload))


@router.post("/symbols")
async def add_symbol(payload: Dict[str, Any] = Body(...)):
    try:
        return ok(sync_domain_service.add_symbol(payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/symbols")
async def remove_symbol(payload: Dict[str, Any] = Body(...)):
    try:
        return ok(sync_domain_service.remove_symbol(payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/data")
async def available_data(exchange: Optional[str] = Query(None, description="交易所")):
    return ok(sync_domain_service.available_data(exchange))


@router.get("/assets")
async def assets():
    return ok(sync_domain_service.assets())


@router.post("/start")
async def start(
    background_tasks: BackgroundTasks,
    payload: Dict[str, Any] = Body(default_factory=dict),
):
    if sync_domain_service.is_running():
        raise HTTPException(status_code=409, detail="已有同步任务在运行中")

    try:
        job = sync_domain_service.create_job(payload, history_days=90)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    background_tasks.add_task(sync_domain_service.run_job, job["job_id"])
    return ok(
        {
            "job_id": job["job_id"],
            "message": "同步任务已启动",
            "exchange": job["exchange"],
            "symbols": job["symbols"],
            "timeframes": job["timeframes"],
            "history_days": job["history_days"],
            "start_date": job["start_date"],
            "end_date": job["end_date"],
        }
    )


@router.post("/sync-one")
async def sync_one(payload: Dict[str, Any] = Body(...)):
    if sync_domain_service.is_running():
        raise HTTPException(status_code=409, detail="已有同步任务在运行中")
    return ok(await sync_domain_service.sync_one(payload))


@router.post("/quick-sync")
async def quick_sync(
    background_tasks: BackgroundTasks,
    payload: Dict[str, Any] = Body(...),
):
    exchange = str(payload.get("exchange") or "okx")
    symbol = str(payload.get("symbol") or "BTC/USDT:USDT")
    timeframe = str(payload.get("timeframe") or "1h")
    history_days = 90
    try:
        data_sync_service.validate_sync_scope([symbol], [timeframe])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    key = f"{exchange}:{symbol}:{timeframe}"

    if key in _quick_sync_tasks and _quick_sync_tasks[key].get("running"):
        return ok(
            {
                "task_id": _quick_sync_tasks[key]["task_id"],
                "message": "该数据已在同步中",
                "duplicate": True,
            }
        )
    if data_sync_service.get_sync_status().get("is_running") or _has_running_quick_sync(exclude_key=key):
        raise HTTPException(status_code=409, detail="已有同步任务在运行中，请稍后再试")

    task_id = str(uuid.uuid4())[:8]
    _quick_sync_tasks[key] = {"task_id": task_id, "running": True, "result": None}

    async def _run() -> None:
        try:
            result = await data_sync_service.sync_klines(
                exchange_name=exchange,
                symbol=symbol,
                timeframe=timeframe,
                history_days=history_days,
            )
            _quick_sync_tasks[key] = {
                "task_id": task_id,
                "running": False,
                "result": {
                    "status": result.status.value,
                    "total_fetched": result.total_fetched,
                    "total_inserted": result.total_inserted,
                    "error": result.error,
                },
            }
        except Exception as exc:
            _quick_sync_tasks[key] = {
                "task_id": task_id,
                "running": False,
                "result": {"status": "error", "error": str(exc)},
            }

    background_tasks.add_task(_run)
    return ok({"task_id": task_id, "message": "同步任务已启动", "key": key})


@router.get("/quick-sync/{task_id}")
async def quick_sync_task(task_id: str):
    for key, info in _quick_sync_tasks.items():
        if info.get("task_id") == task_id:
            return ok({"task_id": task_id, "key": key, **info})
    return ok({"task_id": task_id, "running": False, "result": None, "message": "任务不存在"})


@router.post("/daily-update")
async def daily_update(
    background_tasks: BackgroundTasks,
    exchange: str = Query("okx", description="交易所"),
    payload: Dict[str, Any] = Body(default_factory=dict),
):
    if sync_domain_service.is_running():
        raise HTTPException(status_code=409, detail="已有同步任务在运行中")

    try:
        job = sync_domain_service.create_job(payload, exchange=exchange, history_days=90)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    background_tasks.add_task(sync_domain_service.run_job, job["job_id"])
    return ok(
        {
            "job_id": job["job_id"],
            "message": "增量更新已启动",
            "exchange": job["exchange"],
            "symbols": job["symbols"],
            "timeframes": job["timeframes"],
            "history_days": job["history_days"],
            "start_date": job["start_date"],
            "end_date": job["end_date"],
        }
    )


@router.post("/delete-data")
async def delete_data(payload: Dict[str, Any] = Body(...)):
    try:
        return ok(sync_domain_service.delete_data(payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/table-stats")
async def table_stats():
    return ok(sync_domain_service.table_stats())


@router.get("/quality")
async def quality(
    exchange: str = Query("okx", description="交易所"),
    symbols: Optional[str] = Query(None, description="逗号分隔的交易对列表"),
    timeframes: Optional[str] = Query(None, description="逗号分隔的周期列表"),
    max_items: int = Query(200, ge=1, le=500, description="最多检查多少个交易对/周期组合"),
):
    return ok(sync_domain_service.quality(
        exchange=exchange,
        symbols=_split_csv(symbols),
        timeframes=_split_csv(timeframes),
        max_items=max_items,
    ))
