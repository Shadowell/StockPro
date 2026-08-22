"""StockPro rebuild-safe application entrypoint.

Wave 0 intentionally exposes only a minimal current API. PostgreSQL services and
A-share domain routers are registered in later waves after their contracts pass.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.rebuild_safety import assert_safe_to_start


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def register_current_api(application: FastAPI) -> None:
    router = APIRouter(prefix="/api")

    @router.get("/health", tags=["System"])
    async def health() -> dict[str, object]:
        return {
            "status": "rebuild_safe",
            "project": settings.PROJECT_NAME,
            "database_backend": settings.DATABASE_BACKEND,
            "services_started": False,
            "writes_performed": False,
        }

    @router.get("/auth/me", tags=["Auth"])
    async def auth_session() -> dict[str, object]:
        return {
            "authEnabled": False,
            "authenticated": True,
            "role": "admin",
            "permissions": ["admin"],
        }

    application.include_router(router)


def create_app() -> FastAPI:
    assert_safe_to_start(REPOSITORY_ROOT)
    application = FastAPI(
        title="StockPro API",
        description="A股量化研究、策略、回测与模拟平台",
        version="0.1.0-rebuild",
        openapi_url="/api/openapi.json",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_current_api(application)

    @application.get("/")
    async def root() -> dict[str, str]:
        return {
            "message": "StockPro rebuild safety boundary is active",
            "docs": "/docs",
            "api": "/api",
        }

    return application


app = create_app()
