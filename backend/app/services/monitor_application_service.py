from __future__ import annotations

from typing import Any

from app.repositories.protocols import OperationsRepository
from app.services.operations_application_service import public


class MonitorApplicationService:
    def __init__(self, repository: OperationsRepository) -> None:
        self.repository = repository

    def summary(self, scope: str = "business") -> dict[str, Any]:
        raw = public(self.repository.health(scope))
        strategy_health = []
        for item in raw.get("strategy_health", []):
            strategy_health.append({**item, "lifecycle_status": str(item.get("status") or "unknown")})
        return {
            **raw,
            "overall_status": raw.get("status") or "unavailable",
            "strategy_health": strategy_health,
            "response_generated_at": raw.get("response_generated_at"),
        }
