"""A-share read path for the original BitPro backtest workbench."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.contracts import ok
from app.domain.backtest import backtest_domain_service
from app.domain.backtest.execution import BacktestExecutionPipeline
from app.domain.backtest.input_repository import PostgresBacktestInputGateway
from app.domain.backtest.inputs import BacktestInputResolver
from app.domain.backtest.job_repository import PostgresBacktestJobRepository
from app.domain.backtest.jobs import BacktestJobService
from app.domain.backtest.result_repository import PostgresBacktestResultRepository
from app.domain.backtest.strategy_process import StrategyProcessRunner


router = APIRouter()
backtest_pipeline = BacktestExecutionPipeline(
    BacktestInputResolver(PostgresBacktestInputGateway()),
    StrategyProcessRunner(),
    PostgresBacktestResultRepository(),
)
backtest_job_service = BacktestJobService(PostgresBacktestJobRepository(), backtest_pipeline)
backtest_input_gateway = backtest_pipeline.resolver.gateway


class BacktestRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy_id: int
    exchange: Literal["SSE", "SZSE", "CN"] = "SSE"
    timeframe_mode: Literal["strategy", "single", "matrix"] = "single"
    timeframe: Literal["1d"] = "1d"
    timeframes: list[Literal["1d"]] | None = None
    start_date: str
    end_date: str
    initial_capital: float = Field(gt=0, le=1_000_000_000)
    maker_fee_bps: float = Field(default=3, ge=0, le=100)
    taker_fee_bps: float = Field(default=8, ge=0, le=100)
    slippage_bps: float = Field(default=10, ge=0, le=100)
    symbols: list[str] | None = None
    dataset_snapshot_id: int | None = None
    pool_snapshot_id: int | None = None


def _owner(request: Request, *, write: bool = False) -> dict:
    auth = getattr(request.state, "auth", None) or {"role": "admin"}
    if settings.BITPRO_AUTH_ENABLED and auth.get("role") not in {"admin", "guest"}:
        raise HTTPException(status_code=403, detail="需要登录后访问回测")
    if write and auth.get("auth_method") == "mcp_token" and "W" not in set(auth.get("scopes") or []):
        raise HTTPException(status_code=403, detail="MCP Token 缺少回测写入权限")
    return dict(auth)


async def _with_result(job: dict, include_result: bool = True) -> dict:
    payload = dict(job)
    result_id = (payload.get("result_payload") or {}).get("result_id")
    if include_result and payload.get("status") == "success" and result_id:
        payload["result"] = await backtest_domain_service.get_result(int(result_id))
    return payload


@router.get("/results")
async def get_backtest_results(
    q: str = Query(""),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort_by: Literal["created", "return", "drawdown", "win_rate"] = Query("created"),
    sort_dir: Literal["asc", "desc"] = Query("desc"),
    include_matrix_summary: bool = Query(False),
):
    del include_matrix_summary
    return ok(await backtest_domain_service.list_results(limit=limit, offset=offset, query=q, sort_by=sort_by, sort_dir=sort_dir))


@router.get("/result/{backtest_id}")
async def get_backtest_result(backtest_id: int):
    result = await backtest_domain_service.get_result(backtest_id)
    if result is None:
        raise HTTPException(status_code=404, detail="A-share backtest run not found")
    return ok(result)


@router.post("/run_job", status_code=status.HTTP_202_ACCEPTED)
async def run_backtest_job(body: BacktestRunRequest, request: Request):
    created = backtest_job_service.create_job(body.model_dump(exclude_none=True), owner=_owner(request, write=True))
    return ok({"job_id": str(created["job_id"])})


@router.get("/job/{job_id}")
async def get_backtest_job(job_id: str, request: Request):
    _owner(request)
    try:
        return ok(await _with_result(backtest_job_service.get(job_id)))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/job/{job_id}/cancel")
async def cancel_backtest_job(job_id: str, request: Request):
    _owner(request, write=True)
    try:
        return ok(await _with_result(backtest_job_service.cancel(job_id)))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/job/{job_id}/resume", status_code=status.HTTP_202_ACCEPTED)
async def resume_backtest_job(job_id: str, request: Request):
    owner = _owner(request, write=True)
    try:
        return ok(backtest_job_service.resume(job_id, owner=owner))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/jobs")
async def get_backtest_jobs(
    request: Request,
    strategy_id: int | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    include_result: bool = Query(False),
):
    owner = _owner(request)
    owner_session_id = owner.get("session_id") if owner.get("role") == "guest" else None
    jobs = backtest_job_service.list(strategy_id=strategy_id, status=status_filter, limit=limit, owner_session_id=owner_session_id)
    return ok([await _with_result(job, include_result=include_result) for job in jobs])


@router.get("/strategies")
async def get_available_strategies():
    return ok([])


@router.get("/configuration")
async def get_backtest_configuration(request: Request):
    _owner(request)
    return ok({"items": backtest_input_gateway.list_configurations()})
