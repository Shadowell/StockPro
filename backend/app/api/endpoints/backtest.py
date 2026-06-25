from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.strategy_lab_service import strategy_lab_service

router = APIRouter()


class RunBacktestRequest(BaseModel):
    strategy_id: int
    symbols: Optional[List[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_capital: float = 100000.0
    position_pct: float = 0.95
    commission: float = 0.0003
    stamp_duty: float = 0.001
    slippage: float = 0.0002
    min_commission: float = 5.0


@router.post("/run")
async def run_backtest(request: RunBacktestRequest) -> Dict[str, Any]:
    try:
        return strategy_lab_service.run_backtest(
            strategy_id=request.strategy_id,
            symbols=request.symbols,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            position_pct=request.position_pct,
            commission=request.commission,
            stamp_duty=request.stamp_duty,
            slippage=request.slippage,
            min_commission=request.min_commission,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/results")
async def list_backtest_results(limit: int = Query(20, ge=1, le=200)) -> Dict[str, Any]:
    items = strategy_lab_service.list_backtest_results(limit=limit)
    return {"items": items, "total": len(items)}
