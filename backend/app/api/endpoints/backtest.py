from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app.core.admin_auth import create_auth_dependency
from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile
from app.services.backtest_application_service import BacktestApplicationService


class BacktestPayload(BaseModel):
    model_config = ConfigDict(extra="allow")


class BacktestRunRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    mode: Literal["quick", "full"] = "quick"


def _principal(profile: AuthProfile) -> dict[str, Any]:
    return asdict(profile)


def create_backtest_router(context: AppContext) -> APIRouter:
    router = APIRouter()
    repository = context.repositories.backtests
    service = BacktestApplicationService(repository)
    require_authenticated = create_auth_dependency(context)

    def require_admin(profile: AuthProfile) -> None:
        if profile.role != "admin":
            raise HTTPException(status_code=403, detail="Admin permission required.")

    def translate(error: Exception) -> HTTPException:
        return HTTPException(status_code=int(getattr(error, "status_code", 422)), detail=str(error))

    @router.get("/configuration")
    async def configuration(_profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        return service.configuration()

    @router.get("/runs")
    async def runs(limit: int = Query(default=50, ge=1, le=200), _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, object]:
        return {"items": service.list_runs(limit)}

    @router.get("/runs/{run_id}")
    async def run(run_id: str, _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        try: return service.get_run(run_id)
        except ValueError as error: raise HTTPException(status_code=404, detail=str(error)) from error

    @router.get("/runs/{run_id}/metrics")
    async def metrics(run_id: str, _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, object]: return {"items": repository.metrics(run_id)}

    @router.get("/runs/{run_id}/series")
    async def series(run_id: str, _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]: return repository.series(run_id)

    @router.get("/runs/{run_id}/orders")
    async def orders(run_id: str, _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, object]: return {"items": repository.orders(run_id)}

    @router.get("/runs/{run_id}/trades")
    async def trades(run_id: str, _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, object]: return {"items": repository.trades(run_id)}

    @router.get("/runs/{run_id}/positions")
    async def positions(run_id: str, trade_date: str | None = None, _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, object]: return {"items": repository.positions(run_id, trade_date)}

    @router.get("/runs/{run_id}/logs")
    async def logs(run_id: str, _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, object]: return {"items": repository.logs(run_id)}

    @router.get("/compare")
    async def compare(run_ids: list[str] = Query(default=[]), _profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]: return repository.compare(run_ids)

    @router.post("/run")
    async def execute(body: BacktestRunRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        payload = body.model_dump(exclude={"mode"}, exclude_none=True)
        try: return service.run(payload, mode=body.mode)
        except Exception as error: raise translate(error) from error

    @router.post("/matrix")
    async def matrix(body: BacktestPayload, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        try: return service.run_matrix(body.model_dump())
        except Exception as error: raise translate(error) from error

    @router.post("/walk-forward")
    async def walk_forward(body: BacktestPayload, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        require_admin(profile)
        try: return service.run_walk_forward(body.model_dump())
        except Exception as error: raise translate(error) from error

    @router.get("/jobs")
    async def jobs(limit: int = Query(default=100, ge=1, le=200), profile: AuthProfile = Depends(require_authenticated)) -> dict[str, object]: return {"items": repository.list_jobs(_principal(profile), limit)}

    @router.post("/jobs")
    async def create_job(body: BacktestRunRequest, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        try: return repository.create_job(body.model_dump(exclude={"mode"}, exclude_none=True), body.mode, _principal(profile))
        except Exception as error: raise translate(error) from error

    @router.get("/jobs/{job_id}")
    async def job(job_id: str, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        try: return repository.get_job(job_id, _principal(profile))
        except Exception as error: raise translate(error) from error

    @router.get("/jobs/{job_id}/logs")
    async def job_logs(job_id: str, after_id: int = 0, limit: int = Query(default=500, ge=1, le=1000), profile: AuthProfile = Depends(require_authenticated)) -> dict[str, object]: return {"items": repository.job_logs(job_id, _principal(profile), after_id, limit)}

    @router.post("/jobs/{job_id}/cancel")
    async def cancel(job_id: str, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        try: return repository.cancel_job(job_id, _principal(profile))
        except Exception as error: raise translate(error) from error

    @router.post("/jobs/{job_id}/retry")
    async def retry(job_id: str, profile: AuthProfile = Depends(require_authenticated)) -> dict[str, Any]:
        try: return repository.retry_job(job_id, _principal(profile))
        except Exception as error: raise translate(error) from error

    return router
