"""Strategy endpoints for API v2."""
from typing import Literal

from fastapi import APIRouter, Query

from app.core.contracts import ok
from app.core.errors import BadRequestError, NotFoundError
from app.domain.strategy import strategy_domain_service
from app.models.schemas import StrategyCreate, StrategyUpdate
from app.services.strategy_service import strategy_service

router = APIRouter()

StrategyTypeQuery = Literal["all", "cta", "martingale", "ai", "market_making"]


@router.get("/risk/status")
async def risk_status():
    return ok(await strategy_service.get_risk_status())


@router.post("/risk/reset-circuit-breaker")
async def reset_circuit_breaker():
    return ok(await strategy_service.reset_circuit_breaker())


@router.get("")
async def list_strategies(
    page: int = Query(1, ge=1),
    per_page: int = Query(18, ge=1, le=60),
    search: str = Query(""),
    status: str = Query("all"),
    asset_class: str = Query("all"),
    strategy_type: StrategyTypeQuery = Query("all"),
    timeframe: str = Query("all"),
    capital: str = Query("all"),
):
    return ok(
        await strategy_domain_service.list_page(
            page=page,
            per_page=per_page,
            search=search,
            status=status,
            asset_class=asset_class,
            strategy_type=strategy_type,
            timeframe=timeframe,
            capital=capital,
        )
    )


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: int):
    item = await strategy_domain_service.get(strategy_id)
    if not item:
        raise NotFoundError("Strategy not found")
    return ok(item)


@router.post("")
async def create_strategy(payload: StrategyCreate):
    try:
        return ok(await strategy_domain_service.create(payload))
    except ValueError as e:
        raise BadRequestError(str(e)) from e


@router.put("/{strategy_id}")
async def update_strategy(strategy_id: int, payload: StrategyUpdate):
    try:
        item = await strategy_domain_service.update(strategy_id, payload)
    except ValueError as e:
        raise BadRequestError(str(e)) from e
    if not item:
        raise NotFoundError("Strategy not found")
    return ok(item)


@router.delete("/{strategy_id}")
async def delete_strategy(strategy_id: int):
    try:
        success = await strategy_domain_service.delete(strategy_id)
    except ValueError as e:
        raise BadRequestError(str(e)) from e
    if not success:
        raise NotFoundError("Strategy not found")
    return ok({"deleted": True})


@router.post("/{strategy_id}/start")
async def start_strategy(strategy_id: int):
    success = await strategy_domain_service.start(strategy_id)
    if not success:
        raise BadRequestError("Failed to start strategy")
    return ok({"started": True})


@router.post("/{strategy_id}/stop")
async def stop_strategy(strategy_id: int):
    success = await strategy_domain_service.stop(strategy_id)
    if not success:
        raise BadRequestError("Failed to stop strategy")
    return ok({"stopped": True})


@router.get("/{strategy_id}/status")
async def strategy_status(strategy_id: int):
    status = await strategy_domain_service.status(strategy_id)
    if not status:
        raise NotFoundError("Strategy not found")
    return ok(status)


@router.get("/{strategy_id}/trades")
async def strategy_trades(strategy_id: int, limit: int = Query(50, ge=1, le=500)):
    return ok(await strategy_domain_service.trades(strategy_id, limit))
