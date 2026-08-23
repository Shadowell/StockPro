from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.endpoints.health import create_health_router
from app.api.endpoints.auth import create_auth_router
from app.api.endpoints.market import create_market_router
from app.api.endpoints.pools import create_pools_router
from app.api.endpoints.factors import create_factors_router
from app.api.endpoints.strategy import create_strategy_router
from app.api.endpoints.backtest import create_backtest_router
from app.api.endpoints.paper import create_paper_router
from app.api.endpoints.signals import create_signals_router
from app.api.endpoints.watch import create_watch_router
from app.api.endpoints.monitor import create_monitor_router
from app.api.endpoints.review import create_review_router


def create_api_router(context: Any | None = None) -> APIRouter:
    router = APIRouter()
    router.include_router(create_health_router(context), prefix="/health", tags=["health"])
    if context is not None:
        router.include_router(create_auth_router(context), prefix="/auth", tags=["auth"])
        if hasattr(context.repositories, "market"):
            router.include_router(create_market_router(context), prefix="/market", tags=["market"])
        if hasattr(context.repositories, "pools"):
            router.include_router(create_pools_router(context), tags=["pools"])
        if hasattr(context.repositories, "factors"):
            router.include_router(create_factors_router(context), tags=["factors"])
        if hasattr(context.repositories, "strategies"):
            router.include_router(create_strategy_router(context), tags=["strategies"])
        if hasattr(context.repositories, "backtests"):
            router.include_router(create_backtest_router(context), prefix="/backtest", tags=["backtest"])
        if hasattr(context.repositories, "paper"):
            router.include_router(create_paper_router(context), prefix="/paper", tags=["paper"])
        if hasattr(context.repositories, "operations"):
            router.include_router(create_signals_router(context), prefix="/signals", tags=["signals"])
            router.include_router(create_watch_router(context), prefix="/watch", tags=["watch"])
            router.include_router(create_monitor_router(context), prefix="/monitor", tags=["monitor"])
        if hasattr(context.repositories, "review"):
            router.include_router(create_review_router(context), prefix="/review", tags=["review"])
    return router
