from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.local_db import db_instance as db
from app.services.strategy_lab_service import strategy_lab_service

router = APIRouter()


class SaveStrategyRequest(BaseModel):
    name: str
    script_content: str
    description: Optional[str] = ""
    interval_seconds: int = 60


class AutoDevelopRequest(BaseModel):
    objective: str = "首板突破"
    symbols: Optional[List[str]] = None
    risk_level: str = "balanced"


class BacktestRunRequest(BaseModel):
    strategy_id: int
    symbols: Optional[List[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_capital: float = 100000.0
    position_pct: float = 0.9
    commission: float = 0.0003
    stamp_duty: float = 0.001
    slippage: float = 0.0002
    min_commission: float = 5.0


class PaperRunRequest(BaseModel):
    strategy_id: int
    symbols: Optional[List[str]] = None
    initial_capital: float = 100000.0
    position_pct: float = 0.3
    commission: float = 0.0003
    slippage: float = 0.0002


@router.get("/strategy/list")
async def get_strategies() -> List[Dict[str, Any]]:
    return db.get_strategies()


@router.get("/strategy/{strategy_id}")
async def get_strategy(strategy_id: int) -> Dict[str, Any]:
    strategy = db.get_strategy_by_id(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy


@router.post("/strategy/save")
async def save_strategy(request: SaveStrategyRequest) -> Dict[str, Any]:
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Strategy name is required")
    if not request.script_content.strip():
        raise HTTPException(status_code=400, detail="Script content is required")
    strategy_id = db.save_strategy(
        name=request.name.strip(),
        script_content=request.script_content,
        description=request.description or "",
        interval_seconds=request.interval_seconds,
    )
    return {"success": True, "id": strategy_id, "strategy": db.get_strategy_by_id(strategy_id)}


@router.put("/strategy/{strategy_id}")
async def update_strategy(strategy_id: int, request: SaveStrategyRequest) -> Dict[str, Any]:
    existing = db.get_strategy_by_id(strategy_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategy_id = db.save_strategy(
        name=request.name.strip(),
        script_content=request.script_content,
        description=request.description or "",
        interval_seconds=request.interval_seconds,
    )
    return db.get_strategy_by_id(strategy_id)


@router.post("/strategy/auto-develop")
async def auto_develop_strategy(request: AutoDevelopRequest) -> Dict[str, Any]:
    try:
        return strategy_lab_service.auto_develop_strategy(
            objective=request.objective,
            symbols=request.symbols,
            risk_level=request.risk_level,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/backtest/run")
async def run_backtest(request: BacktestRunRequest) -> Dict[str, Any]:
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


@router.get("/backtest/results")
async def list_backtest_results(limit: int = 20) -> Dict[str, Any]:
    items = strategy_lab_service.list_backtest_results(limit=limit)
    return {"items": items, "total": len(items)}


@router.post("/paper/run")
async def run_paper(request: PaperRunRequest) -> Dict[str, Any]:
    try:
        return strategy_lab_service.run_paper_trading(
            strategy_id=request.strategy_id,
            symbols=request.symbols,
            initial_capital=request.initial_capital,
            position_pct=request.position_pct,
            commission=request.commission,
            slippage=request.slippage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/paper/accounts")
async def list_paper_accounts() -> Dict[str, Any]:
    accounts = strategy_lab_service.list_paper_accounts()
    return {"accounts": accounts, "total": len(accounts)}


@router.get("/paper/{account_id}")
async def get_paper_account(account_id: int) -> Dict[str, Any]:
    try:
        return strategy_lab_service.get_paper_account(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/paper/{account_id}/refresh")
async def refresh_paper_account(account_id: int) -> Dict[str, Any]:
    try:
        return strategy_lab_service.refresh_paper_account(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/paper/{account_id}/stop")
async def stop_paper_account(account_id: int) -> Dict[str, Any]:
    try:
        return strategy_lab_service.stop_paper_account(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
