from fastapi import APIRouter

from app.api.endpoints import auth, health
from app.core.config import settings


def _legacy_sqlite_routes_enabled() -> bool:
    return settings.DB_MODE != "postgres" or settings.ENABLE_LEGACY_SQLITE_MODULES


def _include_legacy_sqlite_routes(router: APIRouter) -> None:
    from app.api.endpoints import (
        admin,
        ai,
        analysis,
        batch_import,
        charts,
        data_dev,
        data_hub,
        database,
        factors,
        market,
        preset_tasks,
        sectors,
        stock_screener,
        stocks,
        strategy,
    )

    router.include_router(stocks.router, prefix="/stocks", tags=["stocks"])
    router.include_router(sectors.router, prefix="/sectors", tags=["sectors"])
    router.include_router(ai.router, prefix="/ai", tags=["ai"])
    router.include_router(charts.router, prefix="/charts", tags=["charts"])
    router.include_router(market.router, prefix="/market", tags=["market"])
    router.include_router(admin.router, prefix="/admin", tags=["admin"])
    router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
    router.include_router(database.router, prefix="/database", tags=["database"])
    router.include_router(data_dev.router, prefix="/data-dev", tags=["data-dev"])
    router.include_router(batch_import.router, prefix="/batch-import", tags=["batch-import"])
    router.include_router(preset_tasks.router, prefix="/preset-tasks", tags=["preset-tasks"])
    router.include_router(strategy.router, prefix="/strategy", tags=["strategy"])
    router.include_router(factors.router, prefix="/factors", tags=["factors"])
    router.include_router(stock_screener.router, prefix="/screener", tags=["screener"])
    router.include_router(data_hub.router, prefix="/data-hub", tags=["data-hub"])


def create_api_router(include_legacy_sqlite_routes: bool | None = None) -> APIRouter:
    router = APIRouter()
    router.include_router(health.router, prefix="/health", tags=["health"])
    router.include_router(auth.router, prefix="/auth", tags=["auth"])

    if include_legacy_sqlite_routes is None:
        include_legacy_sqlite_routes = _legacy_sqlite_routes_enabled()

    if include_legacy_sqlite_routes:
        _include_legacy_sqlite_routes(router)

    return router


api_router = create_api_router()
