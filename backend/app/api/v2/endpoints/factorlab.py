"""FactorLab catalog and controlled machine-learning research endpoints."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.contracts import ok
from app.factorlab.research_repository import FactorResearchStateError
from app.services.agent.providers.contracts import ProviderError
from app.services.factorlab_service import FactorResearchCapacityError, factorlab_service


router = APIRouter()


class FactorResearchTaskCreateRequest(BaseModel):
    exchange: str = "okx"
    market_type: Literal["spot", "swap"]
    symbols: list[str] = Field(min_length=1, max_length=100)
    timeframe: str = Field(min_length=1, max_length=16)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    mode: Literal["manual", "auto", "hybrid"]
    factor_instance_ids: list[str] = Field(min_length=1, max_length=100)
    manual_combinations: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    provider_key: str = ""
    model: str = ""
    reasoning_effort: str = "auto"
    speed_mode: str = "standard"
    horizon_bars: int = Field(default=6, ge=1, le=168)
    base_cost_bps: float = Field(default=20.0, ge=0, le=1000)
    stress_cost_bps: float = Field(default=40.0, ge=0, le=2000)
    min_coverage: float = Field(default=0.95, gt=0, le=1)
    n_splits: int = Field(default=5, ge=2, le=20)
    max_candidates: int = Field(default=200, ge=1, le=1000)
    max_runtime_sec: int = Field(default=7200, ge=30, le=86400)
    max_no_improvement: int = Field(default=50, ge=1, le=1000)
    max_combination_leaves: int = Field(default=8, ge=1, le=8)
    target_accepted_candidates: int = Field(default=1, ge=1, le=100)
    random_seed: int = Field(default=42, ge=0, le=2_147_483_647)


@router.get("/summary")
async def summary():
    return ok(factorlab_service.summary())


@router.post("/research/tasks")
async def create_research_task(request: FactorResearchTaskCreateRequest):
    try:
        return ok(await factorlab_service.create_research_task(request.model_dump()))
    except ProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail="研究 Provider 不可用") from exc
    except FactorResearchCapacityError as exc:
        raise HTTPException(status_code=429, detail="因子研究运行容量已满") from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="因子研究任务参数无效") from exc


@router.get("/research/tasks")
async def list_research_tasks():
    return ok(factorlab_service.list_research_tasks())


@router.get("/research/tasks/{task_id}")
async def get_research_task(task_id: str):
    try:
        return ok(factorlab_service.get_research_task(task_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="因子研究任务不存在") from exc


@router.get("/research/tasks/{task_id}/trials")
async def list_research_trials(task_id: str):
    try:
        return ok(factorlab_service.list_research_trials(task_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="因子研究任务不存在") from exc


@router.delete("/research/tasks/{task_id}")
async def delete_research_task(task_id: str):
    try:
        return ok(factorlab_service.archive_research_task(task_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="因子研究任务不存在") from exc
    except FactorResearchStateError as exc:
        raise HTTPException(status_code=409, detail="运行中的任务必须先暂停") from exc


@router.post("/research/tasks/{task_id}/pause")
async def pause_research_task(task_id: str):
    try:
        return ok(factorlab_service.pause_research_task(task_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="因子研究任务不存在") from exc
    except FactorResearchStateError as exc:
        raise HTTPException(status_code=409, detail="当前任务状态不能暂停") from exc


@router.post("/research/tasks/{task_id}/resume")
async def resume_research_task(task_id: str):
    try:
        return ok(await factorlab_service.resume_research_task(task_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="因子研究任务不存在") from exc
    except FactorResearchStateError as exc:
        raise HTTPException(status_code=409, detail="当前任务状态不能恢复") from exc
