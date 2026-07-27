from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.db import db_instance
from app.services.backtest_workbench_service import BacktestWorkbenchService
from app.services.guest_access_service import GuestAccessError, GuestAccessService


router = APIRouter()
service = BacktestWorkbenchService(db_instance)
guest_access_service = GuestAccessService(db_instance)


class BacktestRunRequest(BaseModel):
    strategy_version_id: str
    dataset_snapshot_id: int
    universe_snapshot_id: int
    symbols: List[str]
    start_date: str
    end_date: str
    initial_cash: float = 1_000_000
    factor_snapshot_id: Optional[int] = None
    pool_snapshot_id: Optional[int] = None
    cost_model_id: Optional[str] = None
    research_protocol_id: Optional[str] = None
    experiment_id: Optional[str] = None
    benchmark_code: str = "000300.SH"
    parameters: Dict[str, Any] = Field(default_factory=dict)
    event_limit: int = 30
    name: str = ""


class LegacyRunBacktestRequest(BaseModel):
    strategy_id: int
    symbols: Optional[List[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_capital: float = 100000.0
    position_pct: float = 0.95
    commission: float = 0.0003
    stamp_duty: float = 0.0005
    slippage: float = 0.0002
    min_commission: float = 5.0


class CompareRequest(BaseModel):
    run_ids: List[str]


class ProtocolRequest(BaseModel):
    name: str
    hypothesis: str
    universe_description: str = ""
    benchmark_code: str = "000300.SH"
    train_start: str
    train_end: str
    validation_start: Optional[str] = None
    validation_end: Optional[str] = None
    out_of_sample_start: str
    out_of_sample_end: str
    embargo_days: int = 0
    capacity_rules: Dict[str, Any] = Field(default_factory=dict)
    promotion_thresholds: Dict[str, Any] = Field(default_factory=dict)
    rejected_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    selection_rationale: Optional[str] = None
    status: str = "sealed"


class ExperimentRequest(BacktestRunRequest):
    hypothesis: str


class MatrixRequest(BaseModel):
    parameter_grid: Dict[str, List[Any]]
    start_date: str
    end_date: str
    initial_cash: float = 1_000_000
    symbols: List[str]
    event_limit: int = 30


class HistoricalReferenceRequest(BaseModel):
    base_snapshot_id: int
    start_date: str
    end_date: str
    symbols: List[str]
    benchmarks: List[str] = Field(default_factory=lambda: ["000300.SH"])


def _http_error(exc: ValueError, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(exc))


@router.get("/cost-models")
async def list_cost_models() -> Dict[str, Any]:
    return {"items": service.list_cost_models()}


@router.get("/configuration")
async def get_configuration() -> Dict[str, Any]:
    return service.configuration()


@router.post("/datasets/historical-references")
async def sync_historical_references(request: HistoricalReferenceRequest) -> Dict[str, Any]:
    try:
        return service.reference_service.sync_historical_backtest_references(
            request.base_snapshot_id,
            request.start_date,
            request.end_date,
            request.symbols,
            request.benchmarks,
        )
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/protocols")
async def create_protocol(request: ProtocolRequest) -> Dict[str, Any]:
    try:
        return service.create_protocol(request.model_dump())
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.get("/protocols")
async def list_protocols() -> Dict[str, Any]:
    return {"items": service.list_protocols()}


@router.post("/quick-runs")
async def quick_run(request: BacktestRunRequest, http_request: Request) -> Dict[str, Any]:
    principal = getattr(http_request.state, "auth_principal", {"role": "admin"})
    try:
        usage_id = guest_access_service.reserve_backtest(
            principal,
            endpoint="/api/backtest/quick-runs",
            start_date=request.start_date,
            end_date=request.end_date,
        )
    except GuestAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    try:
        result = service.run(request.model_dump(), mode="quick")
        guest_access_service.finish_backtest(
            usage_id, success=True, run_id=str(result.get("id") or "")
        )
        return result
    except ValueError as exc:
        guest_access_service.finish_backtest(
            usage_id, success=False, failure_reason=str(exc)
        )
        raise _http_error(exc) from exc
    except Exception as exc:
        guest_access_service.finish_backtest(
            usage_id, success=False, failure_reason=str(exc)
        )
        raise


@router.post("/runs")
async def full_run(request: BacktestRunRequest, http_request: Request) -> Dict[str, Any]:
    principal = getattr(http_request.state, "auth_principal", {"role": "admin"})
    try:
        usage_id = guest_access_service.reserve_backtest(
            principal,
            endpoint="/api/backtest/runs",
            start_date=request.start_date,
            end_date=request.end_date,
        )
    except GuestAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    try:
        result = service.run(request.model_dump(), mode="full")
        guest_access_service.finish_backtest(
            usage_id, success=True, run_id=str(result.get("id") or "")
        )
        return result
    except ValueError as exc:
        guest_access_service.finish_backtest(
            usage_id, success=False, failure_reason=str(exc)
        )
        raise _http_error(exc) from exc
    except Exception as exc:
        guest_access_service.finish_backtest(
            usage_id, success=False, failure_reason=str(exc)
        )
        raise


@router.get("/runs")
async def list_runs(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    items = service.list_runs(limit)
    return {"items": items, "total": len(items)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> Dict[str, Any]:
    try:
        return service.get_run(run_id)
    except ValueError as exc:
        raise _http_error(exc, 404) from exc


@router.get("/runs/{run_id}/metrics")
async def get_metrics(run_id: str) -> Dict[str, Any]:
    try:
        return {"items": service.metrics(run_id)}
    except ValueError as exc:
        raise _http_error(exc, 404) from exc


@router.get("/runs/{run_id}/series")
async def get_series(run_id: str) -> Dict[str, Any]:
    try:
        return service.series(run_id)
    except ValueError as exc:
        raise _http_error(exc, 404) from exc


@router.get("/runs/{run_id}/positions")
async def get_positions(run_id: str, trade_date: Optional[str] = None) -> Dict[str, Any]:
    try:
        return {"items": service.positions(run_id, trade_date)}
    except ValueError as exc:
        raise _http_error(exc, 404) from exc


@router.get("/runs/{run_id}/orders")
async def get_orders(run_id: str) -> Dict[str, Any]:
    try:
        return {"items": service.orders(run_id)}
    except ValueError as exc:
        raise _http_error(exc, 404) from exc


@router.get("/runs/{run_id}/trades")
async def get_trades(run_id: str) -> Dict[str, Any]:
    try:
        return {"items": service.trades(run_id)}
    except ValueError as exc:
        raise _http_error(exc, 404) from exc


@router.get("/runs/{run_id}/logs")
async def get_logs(run_id: str) -> Dict[str, Any]:
    try:
        return {"items": service.logs(run_id)}
    except ValueError as exc:
        raise _http_error(exc, 404) from exc


@router.get("/runs/{run_id}/attribution")
async def get_attribution(run_id: str) -> Dict[str, Any]:
    try:
        return {"items": service.attribution(run_id)}
    except ValueError as exc:
        raise _http_error(exc, 404) from exc


@router.post("/compare")
async def compare(request: CompareRequest) -> Dict[str, Any]:
    try:
        return service.compare(request.run_ids)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/runs/{run_id}/evaluate-promotion")
async def evaluate_promotion(run_id: str) -> Dict[str, Any]:
    try:
        return service.evaluate_promotion(run_id)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/experiments")
async def create_experiment(request: ExperimentRequest) -> Dict[str, Any]:
    try:
        return service.create_experiment(request.model_dump())
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.get("/experiments")
async def list_experiments(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    return {"items": service.list_experiments(limit)}


@router.post("/experiments/{experiment_id}/matrix")
async def run_matrix(experiment_id: str, request: MatrixRequest) -> Dict[str, Any]:
    try:
        payload = request.model_dump(exclude={"parameter_grid"})
        return service.run_matrix(experiment_id, request.parameter_grid, payload)
    except ValueError as exc:
        raise _http_error(exc) from exc


# Compatibility wrappers. They resolve immutable inputs before entering the new runtime.
@router.post("/run")
async def legacy_run(request: LegacyRunBacktestRequest, http_request: Request) -> Dict[str, Any]:
    strategy = db_instance.get_strategy_by_id(request.strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")
    version_result = service.runtime.ensure_legacy_version(request.strategy_id, strategy)
    version = version_result["strategy_version"]
    snapshot = service._row(
        """
        SELECT s.* FROM dataset_snapshots s
        WHERE s.status='sealed' AND EXISTS(
            SELECT 1 FROM dataset_snapshot_items i WHERE i.snapshot_id=s.id AND i.dataset_code='daily_bars'
        ) ORDER BY s.id DESC LIMIT 1
        """
    )
    universe = service._row("SELECT * FROM universe_snapshots WHERE status='sealed' ORDER BY id DESC LIMIT 1")
    if not snapshot or not universe:
        raise HTTPException(status_code=400, detail="缺少已封存数据或 Universe Snapshot")
    bars = service.snapshot_service.load_daily_bars(int(snapshot["id"]), limit=1_000_000)
    available_symbols = sorted({str(item["symbol"]) for item in bars})
    symbols = [service._normalize_symbol(item) for item in request.symbols] if request.symbols else available_symbols[:20]
    start = request.start_date or min(str(item["trade_date"])[:10] for item in bars if str(item["symbol"]) in symbols)
    end = request.end_date or max(str(item["trade_date"])[:10] for item in bars if str(item["symbol"]) in symbols)
    principal = getattr(http_request.state, "auth_principal", {"role": "admin"})
    try:
        usage_id = guest_access_service.reserve_backtest(
            principal,
            endpoint="/api/backtest/run",
            start_date=start,
            end_date=end,
        )
    except GuestAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    try:
        result = service.run({
            "strategy_version_id": str(version["id"]), "dataset_snapshot_id": int(snapshot["id"]),
            "universe_snapshot_id": int(universe["id"]), "symbols": symbols,
            "start_date": start, "end_date": end, "initial_cash": request.initial_capital,
            "parameters": {"position_pct": request.position_pct}, "benchmark_code": "000300.SH",
            "name": strategy["name"],
        }, mode="full")
        guest_access_service.finish_backtest(
            usage_id, success=True, run_id=str(result.get("id") or "")
        )
        return _legacy_shape(result)
    except ValueError as exc:
        guest_access_service.finish_backtest(
            usage_id, success=False, failure_reason=str(exc)
        )
        raise _http_error(exc) from exc
    except Exception as exc:
        guest_access_service.finish_backtest(
            usage_id, success=False, failure_reason=str(exc)
        )
        raise


@router.get("/results")
async def legacy_results(limit: int = Query(20, ge=1, le=200)) -> Dict[str, Any]:
    items = [_legacy_shape(item) for item in service.list_runs(limit) if item.get("status") == "success"]
    return {"items": items, "total": len(items)}


def _legacy_shape(run: Dict[str, Any]) -> Dict[str, Any]:
    metrics = {item["metric_code"]: item["metric_value"] for item in run.get("core_metrics") or []}
    parameters = run.get("parameters") or {}
    return {
        "engine": "stockpro.v1", "status": "completed" if run.get("status") == "success" else run.get("status"),
        "backtest_id": str(run.get("id")), "strategy_id": run.get("strategy_version_id"),
        "strategy_name": run.get("strategy_name") or run.get("name"),
        "symbols": (run.get("universe") or {}).get("symbols") or [], "symbol_names": {},
        "start_date": str(run.get("start_date")), "end_date": str(run.get("end_date")),
        "initial_capital": float(run.get("initial_cash") or 0),
        "final_capital": float(run.get("initial_cash") or 0) * (1 + float(metrics.get("strategy_return") or 0)),
        "total_return": float(metrics.get("strategy_return") or 0) * 100,
        "annual_return": float(metrics.get("annualized_return") or 0) * 100,
        "max_drawdown": float(metrics.get("maximum_drawdown") or 0) * 100,
        "sharpe": metrics.get("sharpe"), "profit_factor": metrics.get("profit_loss_ratio"),
        "win_rate": float(metrics.get("win_rate") or 0) * 100,
        "total_trades": int(metrics.get("completed_trades") or 0),
        "equity_curve": [], "trades": [], "created_at": str(run.get("created_at")),
        "run_id": str(run.get("id")), "run_mode": run.get("run_mode"), "promotion_status": run.get("promotion_status"),
    }
