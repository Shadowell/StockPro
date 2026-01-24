from fastapi import APIRouter
from app.api.endpoints import stocks, sectors, ai, charts, market, admin, analysis, database, data_dev, batch_import, preset_tasks, health, strategy

api_router = APIRouter()

api_router.include_router(stocks.router, prefix="/stocks", tags=["stocks"])
api_router.include_router(sectors.router, prefix="/sectors", tags=["sectors"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(charts.router, prefix="/charts", tags=["charts"])
api_router.include_router(market.router, prefix="/market", tags=["market"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
api_router.include_router(database.router, prefix="/database", tags=["database"])
api_router.include_router(data_dev.router, prefix="/data-dev", tags=["data-dev"])
api_router.include_router(batch_import.router, prefix="/batch-import", tags=["batch-import"])
api_router.include_router(preset_tasks.router, prefix="/preset-tasks", tags=["preset-tasks"])
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(strategy.router, prefix="/strategy", tags=["strategy"])
