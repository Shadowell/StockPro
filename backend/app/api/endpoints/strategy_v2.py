from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import get_database

router = APIRouter()


class CreateStrategyVersionRequest(BaseModel):
    name: str
    script_content: str
    legacy_strategy_id: Optional[int] = None
    description: str = ""
    parameter_schema: Optional[Dict[str, Any]] = None
    data_dependencies: Optional[List[str]] = None
    output_contract: Optional[Dict[str, Any]] = None
    status: str = "draft"


class UpdateStrategyVersionStatusRequest(BaseModel):
    status: str


class CreateSignalRequest(BaseModel):
    strategy_version_id: Optional[str] = None
    legacy_strategy_id: Optional[int] = None
    symbol: str
    name: Optional[str] = None
    signal_type: str = "candidate"
    status: str = "new"
    price: Optional[float] = None
    strength: Optional[float] = None
    reason: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


class UpdateSignalStatusRequest(BaseModel):
    status: str


class CreateBacktestRunRequest(BaseModel):
    strategy_version_id: Optional[str] = None
    name: str = ""
    universe: Optional[Dict[str, Any]] = None
    parameters: Optional[Dict[str, Any]] = None
    start_date: str
    end_date: str


class UpdateBacktestRunRequest(BaseModel):
    status: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


@router.get("/versions")
async def list_strategy_versions(
    name: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    db = get_database()
    versions = db.list_strategy_versions(name=name, status=status)
    return {"versions": versions, "total": len(versions)}


@router.post("/versions")
async def create_strategy_version(request: CreateStrategyVersionRequest) -> Dict[str, Any]:
    db = get_database()
    try:
        version = db.create_strategy_version(
            name=request.name,
            script_content=request.script_content,
            legacy_strategy_id=request.legacy_strategy_id,
            description=request.description,
            parameter_schema=request.parameter_schema,
            data_dependencies=request.data_dependencies,
            output_contract=request.output_contract,
            status=request.status,
        )
        return {"version": version}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/versions/{version_id}")
async def get_strategy_version(version_id: str) -> Dict[str, Any]:
    db = get_database()
    version = db.get_strategy_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Strategy version not found")
    return {"version": version}


@router.patch("/versions/{version_id}/status")
async def update_strategy_version_status(
    version_id: str,
    request: UpdateStrategyVersionStatusRequest,
) -> Dict[str, Any]:
    db = get_database()
    version = db.update_strategy_version_status(version_id, status=request.status)
    if not version:
        raise HTTPException(status_code=404, detail="Strategy version not found")
    return {"version": version}


@router.get("/versions/{version_id}/parameters")
async def get_strategy_parameters(version_id: str) -> Dict[str, Any]:
    db = get_database()
    params = db.get_strategy_parameters(version_id)
    return {"parameters": params}


@router.get("/signals")
async def list_strategy_signals(
    strategy_version_id: Optional[str] = None,
    legacy_strategy_id: Optional[int] = None,
    status: Optional[str] = None,
    signal_type: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    db = get_database()
    signals = db.list_strategy_signals(
        strategy_version_id=strategy_version_id,
        legacy_strategy_id=legacy_strategy_id,
        status=status,
        signal_type=signal_type,
        limit=limit,
    )
    return {"signals": signals, "total": len(signals)}


@router.post("/signals")
async def create_strategy_signal(request: CreateSignalRequest) -> Dict[str, Any]:
    db = get_database()
    try:
        signal = db.insert_strategy_signal(
            strategy_version_id=request.strategy_version_id,
            legacy_strategy_id=request.legacy_strategy_id,
            symbol=request.symbol,
            name=request.name,
            signal_type=request.signal_type,
            status=request.status,
            price=request.price,
            strength=request.strength,
            reason=request.reason,
            payload=request.payload,
        )
        return {"signal": signal}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/signals/{signal_id}/status")
async def update_signal_status(
    signal_id: str,
    request: UpdateSignalStatusRequest,
) -> Dict[str, Any]:
    db = get_database()
    signal = db.update_signal_status(signal_id, status=request.status)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    return {"signal": signal}


@router.get("/backtest-runs")
async def list_backtest_runs(
    strategy_version_id: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    db = get_database()
    runs = db.list_backtest_runs(
        strategy_version_id=strategy_version_id,
        limit=limit,
    )
    return {"runs": runs, "total": len(runs)}


@router.post("/backtest-runs")
async def create_backtest_run(request: CreateBacktestRunRequest) -> Dict[str, Any]:
    db = get_database()
    try:
        run = db.create_backtest_run(
            strategy_version_id=request.strategy_version_id,
            name=request.name,
            universe=request.universe,
            parameters=request.parameters,
            start_date=request.start_date,
            end_date=request.end_date,
        )
        return {"run": run}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/backtest-runs/{run_id}")
async def get_backtest_run(run_id: str) -> Dict[str, Any]:
    db = get_database()
    run = db.get_backtest_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return {"run": run}


@router.patch("/backtest-runs/{run_id}")
async def update_backtest_run(
    run_id: str,
    request: UpdateBacktestRunRequest,
) -> Dict[str, Any]:
    db = get_database()
    run = db.update_backtest_run(
        run_id=run_id,
        status=request.status,
        metrics=request.metrics,
        error_message=request.error_message,
    )
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return {"run": run}


@router.get("/backtest-runs/{run_id}/trades")
async def list_backtest_trades(run_id: str) -> Dict[str, Any]:
    db = get_database()
    trades = db.list_backtest_trades(run_id)
    return {"trades": trades, "total": len(trades)}
