"""StockPro direct-port safety entrypoint.

The complete BitPro application source remains in this repository as the porting
base. Until each domain is converted to A-share/PostgreSQL semantics, this module
is the only runnable backend entrypoint and deliberately imports none of the
BitPro SQLite, exchange, execution, scheduler, or private-account modules.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v2.endpoints.market import router as market_router
from app.api.v2.endpoints.strategy import router as strategy_router
from app.api.v2.endpoints.backtest import router as backtest_router
from app.api.v2.endpoints.live import router as paper_router
from app.api.v2.endpoints.monitor import router as monitor_router
from app.api.v2.endpoints.system import router as system_router
from app.api.v2.endpoints.native_sentiment import router as native_sentiment_router


@asynccontextmanager
async def safe_lifespan(_: FastAPI):
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="StockPro API",
        description="BitPro direct port with A-share conversion in progress",
        version="0.1.0-direct-port",
        openapi_url="/api/openapi.json",
        lifespan=safe_lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        return {
            "status": "rebuild_safe",
            "project": "StockPro",
            "database_backend": "postgresql",
            "services_started": False,
            "writes_performed": False,
        }

    @app.get("/api/health/storage")
    async def storage_health() -> dict[str, object]:
        return {
            "status": "conversion_pending",
            "database": "postgresql",
            "connected": False,
            "writes_performed": False,
        }

    @app.get("/api/auth/me")
    @app.get("/api/v2/auth/me")
    async def auth_me() -> dict[str, object]:
        return {
            "auth_enabled": False,
            "authenticated": True,
            "role": "admin",
            "permissions": ["admin"],
        }

    app.include_router(market_router, prefix="/api/v2/market", tags=["A-share Market"])
    app.include_router(strategy_router, prefix="/api/v2/strategies", tags=["A-share Strategies"])
    app.include_router(backtest_router, prefix="/api/v2/backtest", tags=["A-share Backtests"])
    app.include_router(paper_router, prefix="/api/v2/live", tags=["A-share Paper"])
    app.include_router(monitor_router, prefix="/api/v2/monitor", tags=["A-share Monitor"])
    app.include_router(system_router, prefix="/api/v2/system", tags=["StockPro System"])
    app.include_router(native_sentiment_router, prefix="/api/v2/market", tags=["A-share Breadth"])

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=4445, reload=True)
