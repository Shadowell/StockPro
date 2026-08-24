"""StockPro rebuild-safe application entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import create_api_router
from app.core.app_context import AppContext, build_app_context
from app.core.config import settings
from app.core.rebuild_safety import assert_safe_to_start


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger("stockpro.main")


def create_app(context: AppContext | None = None) -> FastAPI:
    assert_safe_to_start(REPOSITORY_ROOT)
    app_context = context or build_app_context()
    application = FastAPI(
        title="StockPro API",
        description="A股量化研究、策略、回测与模拟平台",
        version="0.1.0-rebuild",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(create_api_router(app_context), prefix="/api")

    @application.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "message": "StockPro rebuild safety boundary is active",
            "docs": "/docs",
            "api": "/api",
        }

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        scheduler = None
        if settings.ENABLE_SCHEDULER:
            try:
                from app.services.ashare_scheduler_service import AshareSchedulerService

                scheduler = AshareSchedulerService(app_context)
                await scheduler.start()
            except Exception:
                logger.exception("A-share operations scheduler failed to start; continuing without it")
                scheduler = None
        yield
        if scheduler is not None:
            scheduler.shutdown()

    application.router.lifespan_context = lifespan
    return application


app = create_app()
