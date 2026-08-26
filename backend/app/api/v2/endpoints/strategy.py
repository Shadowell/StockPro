"""A-share implementation of the original BitPro strategy catalogue contract."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.core.contracts import ok
from app.domain.strategy import strategy_domain_service


router = APIRouter()
StrategyTypeQuery = Literal["all", "momentum", "mean_reversion", "multi_factor", "event", "other"]


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
async def get_strategy(strategy_id: str):
    item = await strategy_domain_service.get(strategy_id)
    if item is None:
        raise HTTPException(status_code=404, detail="A-share strategy version not found")
    return ok(item)
