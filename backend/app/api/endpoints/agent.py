"""AI 策略研发任务端点（BitPro 式多智能体闭环的 A 股入口）。"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.core.admin_auth import require_admin
from app.db import db_instance
from app.services.agent.llm_client import llm_available, resolve_model_name
from app.services.agent.orchestrator import AgentOrchestrator

router = APIRouter()
service = AgentOrchestrator(db_instance)


class AgentTaskCreateRequest(BaseModel):
    name: str
    user_prompt: str = ""
    goal: Dict[str, Any] = Field(default_factory=dict)
    research_config: Dict[str, Any] = Field(default_factory=dict)
    max_iterations: int = 6
    llm_model: Optional[str] = None


class AgentTaskPromoteRequest(BaseModel):
    iteration: int


def _task_summary(task) -> Dict[str, Any]:
    best = task.best_record
    return {
        "id": task.task_id,
        "name": task.name,
        "status": task.status,
        "stage": task.stage,
        "stage_label": task.stage_label,
        "goal": task.goal.to_dict(),
        "user_prompt": task.user_prompt,
        "iteration_count": len(task.iterations),
        "max_iterations": task.max_iterations,
        "best_iteration": task.best_iteration,
        "best_score": best.score if best else None,
        "best_metrics": (best.backtest_metrics if best else None),
        "llm_model": task.llm_model,
        "promoted_strategy_version_id": task.promoted_strategy_version_id,
        "error_message": task.error_message or None,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


@router.get("/config")
async def get_agent_config() -> Dict[str, Any]:
    def build() -> Dict[str, Any]:
        defaults = service.default_research_config()
        return {
            "llm_available": llm_available(),
            "default_model": resolve_model_name(None),
            "defaults": defaults,
        }
    return await run_in_threadpool(build)


@router.get("/tasks")
async def list_agent_tasks(limit: int = 50) -> Dict[str, Any]:
    tasks = await run_in_threadpool(service.list_tasks, limit)
    return {"tasks": [_task_summary(task) for task in tasks]}


@router.post("/tasks")
async def create_agent_task(request: AgentTaskCreateRequest, username: str = Depends(require_admin)) -> Dict[str, Any]:
    def create() -> Dict[str, Any]:
        try:
            task = service.create_task(request.model_dump())
            started = service.start_task(task.task_id)
            return {"task": _task_summary(started)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await run_in_threadpool(create)


@router.get("/tasks/{task_id}")
async def get_agent_task(task_id: str) -> Dict[str, Any]:
    def build() -> Dict[str, Any]:
        task = service.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        summary = _task_summary(task)
        summary["research_config"] = task.research_config
        summary["strategy_spec"] = task.strategy_spec.to_dict() if task.strategy_spec else None
        return summary
    return await run_in_threadpool(build)


@router.get("/tasks/{task_id}/iterations")
async def list_agent_iterations(task_id: str) -> Dict[str, Any]:
    return {"iterations": await run_in_threadpool(service.list_iterations, task_id)}


@router.post("/tasks/{task_id}/start")
async def start_agent_task(task_id: str, username: str = Depends(require_admin)) -> Dict[str, Any]:
    def start() -> Dict[str, Any]:
        try:
            return {"task": _task_summary(service.start_task(task_id))}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await run_in_threadpool(start)


@router.post("/tasks/{task_id}/stop")
async def stop_agent_task(task_id: str, username: str = Depends(require_admin)) -> Dict[str, Any]:
    def stop() -> Dict[str, Any]:
        if not service.stop_task(task_id):
            raise HTTPException(status_code=400, detail="任务不存在或不在可停止状态")
        task = service.get_task(task_id)
        return {"task": _task_summary(task) if task else None}
    return await run_in_threadpool(stop)


@router.delete("/tasks/{task_id}")
async def delete_agent_task(task_id: str, username: str = Depends(require_admin)) -> Dict[str, Any]:
    def delete() -> Dict[str, Any]:
        try:
            deleted = service.delete_task(task_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {"deleted": True}
    return await run_in_threadpool(delete)


@router.post("/tasks/{task_id}/promote")
async def promote_agent_iteration(task_id: str, request: AgentTaskPromoteRequest, username: str = Depends(require_admin)) -> Dict[str, Any]:
    def promote() -> Dict[str, Any]:
        try:
            return service.promote(task_id, request.iteration)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await run_in_threadpool(promote)
