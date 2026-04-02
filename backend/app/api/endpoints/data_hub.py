from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.data_hub_service import data_hub_service

router = APIRouter()


class CreateDataHubJobRequest(BaseModel):
    action: str = Field(..., description="任务动作，如 import_daily_data / run_data_dev_task")
    scope: Optional[str] = Field(None, description="任务作用域（通常为 dataset_id）")
    params: Dict[str, Any] = Field(default_factory=dict, description="任务参数")


class RunQualityRequest(BaseModel):
    datasets: Optional[List[str]] = Field(
        None,
        description="需要执行质量检查的数据集列表，默认: stock_history, stock_fundamentals, daily_concept_sectors",
    )


@router.get("/datasets")
async def list_datasets() -> Dict[str, Any]:
    return {"status": "success", "data": data_hub_service.list_datasets()}


@router.get("/datasets/{dataset_id}/freshness")
async def get_dataset_freshness(dataset_id: str) -> Dict[str, Any]:
    try:
        return {"status": "success", "data": data_hub_service.get_dataset_freshness(dataset_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/jobs")
async def create_job(request: CreateDataHubJobRequest) -> Dict[str, Any]:
    try:
        job = data_hub_service.create_job(
            action=request.action,
            scope=request.scope,
            params=request.params,
        )
        return {"status": "success", "data": job}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/jobs")
async def list_jobs(
    action: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    scope: Optional[str] = Query(None),
    parent_job_key: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> Dict[str, Any]:
    jobs = data_hub_service.list_jobs(
        action=action,
        status=status,
        scope=scope,
        parent_job_key=parent_job_key,
        limit=limit,
    )
    return {"status": "success", "data": jobs, "count": len(jobs)}


@router.get("/jobs/{job_key}")
async def get_job(job_key: str) -> Dict[str, Any]:
    job = data_hub_service.get_job(job_key)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "success", "data": job}


@router.get("/jobs/{job_key}/logs")
async def get_job_logs(job_key: str, limit: int = Query(200, ge=1, le=500)) -> Dict[str, Any]:
    job = data_hub_service.get_job(job_key)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    logs = job.get("logs") or []
    return {"status": "success", "data": logs[-limit:]}


@router.post("/jobs/{job_key}/rerun")
async def rerun_job(job_key: str) -> Dict[str, Any]:
    try:
        job = data_hub_service.rerun_job(job_key)
        return {"status": "success", "data": job}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/jobs/{job_key}/cancel")
async def cancel_job(job_key: str) -> Dict[str, Any]:
    try:
        job = data_hub_service.cancel_job(job_key)
        return {"status": "success", "data": job}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/quality/run")
async def run_quality(request: RunQualityRequest) -> Dict[str, Any]:
    report = data_hub_service.run_quality_checks(request.datasets)
    return {"status": "success", "data": report}


@router.get("/quality/report")
async def get_latest_quality_report() -> Dict[str, Any]:
    report = data_hub_service.get_latest_quality_report()
    if report is None:
        return {"status": "success", "data": None}
    return {"status": "success", "data": report}


@router.get("/features/screener")
async def get_screener_features(
    days: int = Query(15, ge=5, le=30),
    max_range_pct: float = Query(2.0, ge=0.5, le=5.0),
    main_board_only: bool = Query(True),
    min_price: float = Query(5.0, ge=0),
    max_price: float = Query(100.0, ge=1),
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    result = data_hub_service.get_screener_features(
        {
            "days": days,
            "max_range_pct": max_range_pct,
            "main_board_only": main_board_only,
            "min_price": min_price,
            "max_price": max_price,
            "limit": limit,
        }
    )
    return result


@router.get("/features/factors")
async def get_factor_features(
    factor_code: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    ascending: bool = Query(False),
    category: Optional[str] = Query(None),
) -> Dict[str, Any]:
    result = data_hub_service.get_factor_features(
        factor_code=factor_code,
        date=date,
        limit=limit,
        ascending=ascending,
        category=category,
    )
    return result
