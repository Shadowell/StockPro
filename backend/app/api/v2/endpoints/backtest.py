"""A-share read path for the original BitPro backtest workbench."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.core.contracts import ok
from app.domain.backtest import backtest_domain_service


router = APIRouter()


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


@router.get("/jobs")
async def get_backtest_jobs():
    return ok([])


@router.get("/strategies")
async def get_available_strategies():
    return ok([])
