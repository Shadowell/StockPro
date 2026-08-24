"""Operations endpoints: scheduler visibility and manual operator triggers."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.admin_auth import create_auth_dependency
from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile


class DailyReferenceRunRequest(BaseModel):
    trade_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    force: bool = False


class ScheduleUpdateRequest(BaseModel):
    cron: Optional[str] = None
    timezone: Optional[str] = None
    enabled: Optional[bool] = None
    catchup_days: Optional[int] = Field(default=None, ge=1, le=10)
    max_retries: Optional[int] = Field(default=None, ge=1, le=5)


class PaperBulkAdvanceRequest(BaseModel):
    max_dates: int = Field(default=260, ge=1, le=1000)


def _scheduler(context: AppContext):
    from app.services.ashare_scheduler_service import AshareSchedulerService

    active = AshareSchedulerService.active()
    if active is not None:
        return active
    # Not started (ENABLE_SCHEDULER=false): build an ephemeral view so manual
    # triggers and schedule reads still work against PG.
    return AshareSchedulerService(context)


def create_operations_router(context: AppContext) -> APIRouter:
    router = APIRouter()
    require_authenticated = create_auth_dependency(context)

    def require_admin(profile: AuthProfile) -> None:
        if profile.role != "admin":
            raise HTTPException(status_code=403, detail="Admin permission required.")

    @router.get("/scheduler")
    async def scheduler_status(_profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        """Read-only scheduler status; works whether or not ENABLE_SCHEDULER is on."""
        try:
            return _scheduler(context).status()
        except Exception as error:
            raise HTTPException(status_code=503, detail=f"调度器状态不可用：{error}") from error

    @router.put("/scheduler/daily-reference")
    async def update_schedule(
        body: ScheduleUpdateRequest,
        profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, Any]:
        require_admin(profile)
        try:
            return _scheduler(context).update_daily_reference_schedule(body.model_dump(exclude_none=True))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/scheduler/daily-reference/run")
    async def run_daily_reference(
        body: DailyReferenceRunRequest,
        profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, Any]:
        """Manual post-close run for one trade date (idempotent per date)."""
        require_admin(profile)
        import asyncio

        try:
            service = _scheduler(context)
            result = await asyncio.to_thread(
                service.trigger_daily_reference_now, body.trade_date, body.force
            )
            return result
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/paper/advance")
    async def advance_all_paper(
        body: PaperBulkAdvanceRequest,
        profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, Any]:
        """Catch up every running paper instance (idempotent per cycle key)."""
        require_admin(profile)
        import asyncio

        from app.services.paper_runtime_service import PaperRuntimeService

        database = context.repositories.data.database
        try:
            return await asyncio.to_thread(
                PaperRuntimeService(database).advance_instances, None, body.max_dates
            )
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return router
