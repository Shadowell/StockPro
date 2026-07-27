from fastapi import APIRouter, Depends

from app.api.endpoints import (
    acceptance,
    admin,
    ai,
    analysis,
    auth,
    backtest,
    batch_import,
    charts,
    data,
    data_dev,
    data_hub,
    database,
    factors,
    factor_research,
    health,
    market,
    monitor_runtime,
    paper,
    pools,
    preset_tasks,
    review,
    sectors,
    stocks,
    strategy,
    strategy_runtime,
    watch,
    workflow,
)
from app.core.admin_auth import require_authenticated


def create_api_router() -> APIRouter:
    router = APIRouter()
    router.include_router(health.router, prefix="/health", tags=["health"])
    router.include_router(auth.router, prefix="/auth", tags=["auth"])

    protected = APIRouter(dependencies=[Depends(require_authenticated)])
    protected.include_router(admin.router, prefix="/admin", tags=["admin"])
    protected.include_router(acceptance.router, prefix="/acceptance", tags=["local-acceptance"])
    protected.include_router(market.router, prefix="/market", tags=["market"])
    protected.include_router(stocks.router, prefix="/stocks", tags=["stocks"])
    protected.include_router(sectors.router, prefix="/sectors", tags=["sectors"])
    protected.include_router(ai.router, prefix="/ai", tags=["ai"])
    protected.include_router(charts.router, prefix="/charts", tags=["charts"])
    protected.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
    protected.include_router(data.router, prefix="/data", tags=["data"])
    protected.include_router(data_hub.router, prefix="/data-hub", tags=["data-hub"])
    protected.include_router(data_dev.router, prefix="/data-dev", tags=["data-dev"])
    protected.include_router(database.router, prefix="/database", tags=["database"])
    protected.include_router(batch_import.router, prefix="/batch-import", tags=["batch-import"])
    protected.include_router(preset_tasks.router, prefix="/preset-tasks", tags=["preset-tasks"])
    protected.include_router(strategy_runtime.router, prefix="/strategy", tags=["strategy-runtime-v1"])
    protected.include_router(strategy.router, prefix="/strategy", tags=["strategy"])
    protected.include_router(backtest.router, prefix="/backtest", tags=["backtest"])
    protected.include_router(paper.router, prefix="/paper", tags=["paper"])
    protected.include_router(watch.router, prefix="/watch", tags=["watch"])
    protected.include_router(workflow.router, prefix="/workflow", tags=["workflow"])
    protected.include_router(monitor_runtime.router, prefix="/monitor", tags=["monitor"])
    protected.include_router(review.router, prefix="/review", tags=["review"])
    protected.include_router(factors.router, prefix="/factors", tags=["factors"])
    protected.include_router(factor_research.router, tags=["factor-research"])
    protected.include_router(pools.router, tags=["stock-pools"])

    router.include_router(protected)
    return router


api_router = create_api_router()
