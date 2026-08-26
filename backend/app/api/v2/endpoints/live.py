"""Read-only A-share Paper implementation for BitPro's original live workspace."""
import asyncio

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.contracts import ok
from app.domain.paper import paper_domain_service
from app.domain.paper.cycle import PaperCycleService
from app.domain.paper.cycle_repository import PostgresPaperCycleRepository
from app.domain.backtest.strategy_process import StrategyProcessRunner
from app.services.ashare_execution import explicit_instrument_key


router = APIRouter()
paper_cycle_service = PaperCycleService(PostgresPaperCycleRepository(), StrategyProcessRunner())


class PaperCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    qualifying_backtest_run_id: str
    initial_cash: float = Field(default=1_000_000, gt=0, le=1_000_000_000)
    start: bool = True


class PaperInstanceAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_id: int


class PaperStopAction(PaperInstanceAction):
    clear_metrics: bool = False


class PaperAdvanceAction(PaperInstanceAction):
    max_dates: int = Field(default=1, ge=1, le=260)


def _require_write(request: Request) -> None:
    auth = getattr(request.state, "auth", None) or {"role": "admin"}
    if settings.BITPRO_AUTH_ENABLED and auth.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    if auth.get("auth_method") == "mcp_token" and "W" not in set(auth.get("scopes") or []):
        raise HTTPException(status_code=403, detail="MCP Token 缺少 Paper 写入权限")


def _translate(exc: ValueError) -> HTTPException:
    code = 404 if "不存在" in str(exc) else 422
    return HTTPException(status_code=code, detail=str(exc))


def _missing_paper_account(exc: ValueError) -> bool:
    return str(exc) == "没有可用 A 股 Paper 账户"


def _empty_watch_market(account_id: str, symbol: str, timeframe: str, message: str) -> dict[str, object]:
    normalized = explicit_instrument_key(symbol) or symbol
    return {
        "account_id": account_id,
        "exchange": "CN",
        "symbol": normalized,
        "timeframe": timeframe,
        "ticker": {
            "symbol": normalized,
            "last": 0,
            "open": 0,
            "high": 0,
            "low": 0,
            "volume": 0,
            "change_percent": 0,
        },
        "klines": [],
        "orderbook": {"bids": [], "asks": []},
        "recent_trades": [],
        "positions": [],
        "data_status": "unavailable",
        "message": message,
    }


def _empty_derivatives(account_id: str, symbol: str, timeframe: str) -> dict[str, object]:
    normalized = explicit_instrument_key(symbol) or symbol
    empty = {
        "points": None,
        "status": "not_applicable",
        "message": "A 股 Paper 盯盘不使用合约衍生品指标",
    }
    return {
        "account_id": account_id,
        "exchange": "CN",
        "symbol": normalized,
        "timeframe": timeframe,
        "open_interest": dict(empty),
        "funding_rate": dict(empty),
        "long_short_ratio": dict(empty),
        "taker_volume": dict(empty),
        "basis": dict(empty),
    }


@router.get("/instances")
async def paper_instances():
    return ok({"items": await paper_domain_service.list_instances()})


@router.get("/candidates")
async def paper_candidates():
    return ok(await paper_domain_service.list_candidates())


@router.post("/instances", status_code=status.HTTP_201_CREATED)
async def create_paper_instance(body: PaperCreateRequest, request: Request):
    _require_write(request)
    try:
        payload = body.model_dump(exclude={"start"})
        return ok(await paper_domain_service.create(payload, start=body.start))
    except ValueError as exc:
        raise _translate(exc) from exc


@router.post("/start")
async def start_paper_instance(body: PaperInstanceAction, request: Request):
    _require_write(request)
    try:
        row = await paper_domain_service.start(body.instance_id)
        return ok(row)
    except ValueError as exc:
        raise _translate(exc) from exc


@router.post("/pause")
async def pause_paper_instance(body: PaperInstanceAction, request: Request):
    _require_write(request)
    try:
        return ok(await paper_domain_service.pause(body.instance_id))
    except ValueError as exc:
        raise _translate(exc) from exc


@router.post("/resume")
async def resume_paper_instance(body: PaperInstanceAction, request: Request):
    _require_write(request)
    try:
        return ok(await paper_domain_service.resume(body.instance_id))
    except ValueError as exc:
        raise _translate(exc) from exc


@router.post("/stop")
async def stop_paper_instance(body: PaperStopAction, request: Request):
    _require_write(request)
    if body.clear_metrics:
        raise HTTPException(status_code=422, detail="禁止清空模拟盘历史、指标、成交、持仓或权益曲线")
    try:
        return ok(await paper_domain_service.stop(body.instance_id))
    except ValueError as exc:
        raise _translate(exc) from exc


@router.post("/advance")
async def advance_paper_instance(body: PaperAdvanceAction, request: Request):
    _require_write(request)
    try:
        return ok(await asyncio.to_thread(paper_cycle_service.advance, body.instance_id, max_dates=body.max_dates))
    except ValueError as exc:
        raise _translate(exc) from exc


@router.get("/dashboard")
async def paper_dashboard(instance_id: int | None = Query(None)):
    return ok(await paper_domain_service.dashboard(instance_id))


@router.get("/events")
async def paper_events(instance_id: int, limit: int = Query(50, ge=1, le=500)):
    return ok({"events": await paper_domain_service.events(instance_id, limit)})


@router.get("/equity_curve")
async def paper_equity_curve(instance_id: int):
    return ok(await paper_domain_service.equity_curve(instance_id))


@router.get("/trades")
async def paper_trades(instance_id: int, limit: int = Query(100, ge=1, le=500)):
    return ok(await paper_domain_service.trades(instance_id, limit))


@router.get("/accounts")
async def paper_accounts():
    return ok({"accounts": await paper_domain_service.accounts()})


@router.get("/strategies")
async def paper_strategies():
    return ok({"strategies": await paper_domain_service.list_instances()})


@router.get("/watchlist")
async def paper_watchlist(account_id: str = Query("paper"), limit: int = Query(100)):
    return ok({"account_id": account_id, "exchange": "CN", "items": await paper_domain_service.watchlist(account_id, limit)})


@router.get("/watchlist/market")
async def paper_watch_market(
    symbol: str,
    account_id: str = Query("paper"),
    timeframe: str = Query("1d"),
    limit: int = Query(180, ge=1, le=800),
):
    try:
        return ok(await paper_domain_service.watch_market(account_id, symbol, timeframe, limit))
    except ValueError as exc:
        if _missing_paper_account(exc):
            return ok(_empty_watch_market(account_id, symbol, timeframe, str(exc)))
        raise _translate(exc) from exc


@router.get("/watchlist/markers")
async def paper_watch_markers(
    symbol: str,
    account_id: str = Query("paper"),
    limit: int = Query(400, ge=1, le=1000),
):
    try:
        markers = await paper_domain_service.trade_markers(account_id, symbol, limit)
    except ValueError as exc:
        if not _missing_paper_account(exc):
            raise _translate(exc) from exc
        markers = []
    return ok({"account_id": account_id, "exchange": "CN", "symbol": explicit_instrument_key(symbol) or symbol, "markers": markers})


@router.get("/watchlist/derivatives-data")
async def paper_watch_derivatives_data(
    symbol: str,
    account_id: str = Query("paper"),
    timeframe: str = Query("1d"),
    limit: int = Query(120, ge=1, le=500),
):
    _ = limit
    return ok(_empty_derivatives(account_id, symbol, timeframe))


@router.get("/accounts/{account_id}/positions")
async def account_positions(account_id: str): return ok({"account_id": account_id, "exchange": "CN", "positions": await paper_domain_service.account_positions(account_id)})


@router.get("/accounts/{account_id}/orders/history")
async def account_orders(account_id: str, limit: int = Query(50)): return ok({"account_id": account_id, "exchange": "CN", "orders": await paper_domain_service.account_orders(account_id, limit)})
