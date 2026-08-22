from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter


def _storage_payload(context: Any | None) -> dict[str, object]:
    if context is None:
        return {
            "status": "unconfigured",
            "database": "postgresql",
            "applied_migrations": None,
            "expected_migrations": None,
            "writes_performed": False,
        }
    repository = context.repositories.health
    health = repository.storage_health()
    payload = asdict(health) if is_dataclass(health) else dict(health)
    payload["writes_performed"] = False
    return payload


def create_health_router(context: Any | None = None) -> APIRouter:
    router = APIRouter()

    @router.get("")
    async def health() -> dict[str, object]:
        return {
            "status": "rebuild_safe",
            "project": "StockPro",
            "database_backend": "postgresql",
            "services_started": False,
            "writes_performed": False,
        }

    @router.get("/storage")
    async def storage_health() -> dict[str, object]:
        return _storage_payload(context)

    return router
