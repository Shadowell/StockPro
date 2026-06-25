from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.strategy_lab_service import strategy_lab_service

router = APIRouter()


class RunPaperRequest(BaseModel):
    strategy_id: int
    symbols: Optional[List[str]] = None
    initial_capital: float = 100000.0
    position_pct: float = 0.3


@router.post("/run")
async def run_paper(request: RunPaperRequest) -> Dict[str, Any]:
    try:
        return strategy_lab_service.run_paper_trading(
            strategy_id=request.strategy_id,
            symbols=request.symbols,
            initial_capital=request.initial_capital,
            position_pct=request.position_pct,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/accounts")
async def list_paper_accounts() -> Dict[str, Any]:
    accounts = strategy_lab_service.list_paper_accounts()
    return {"accounts": accounts, "total": len(accounts)}


@router.get("/{account_id}")
async def get_paper_account(account_id: int) -> Dict[str, Any]:
    try:
        return strategy_lab_service.get_paper_account(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{account_id}/refresh")
async def refresh_paper_account(account_id: int) -> Dict[str, Any]:
    try:
        return strategy_lab_service.refresh_paper_account(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{account_id}/stop")
async def stop_paper_account(account_id: int) -> Dict[str, Any]:
    try:
        return strategy_lab_service.stop_paper_account(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
