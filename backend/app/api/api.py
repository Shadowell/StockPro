from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.endpoints.health import create_health_router


def create_api_router(context: Any | None = None) -> APIRouter:
    router = APIRouter()
    router.include_router(create_health_router(context), prefix="/health", tags=["health"])
    return router
