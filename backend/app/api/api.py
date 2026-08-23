from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.endpoints.health import create_health_router
from app.api.endpoints.auth import create_auth_router
from app.api.endpoints.market import create_market_router
from app.api.endpoints.pools import create_pools_router
from app.api.endpoints.factors import create_factors_router


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
    return router
