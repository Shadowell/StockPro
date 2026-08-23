from __future__ import annotations

from typing import Any

from app.services.paper_runtime_service import PaperRuntimeService


class PostgresOperationsRepository:
    """Read models over the preserved Paper runtime evidence tables."""

    def __init__(self, database: Any) -> None:
        self.runtime = PaperRuntimeService(database)

    def watch_context(self, scope: str) -> dict[str, Any]:
        return self.runtime.watch_context(scope)

    def health(self, scope: str) -> dict[str, Any]:
        return self.runtime.health(scope)

    def list_alerts(self, status: str | None, limit: int) -> list[dict[str, Any]]:
        return self.runtime.list_alerts(status, limit)

    def acknowledge_alert(self, alert_id: str, actor: str) -> dict[str, Any]:
        return self.runtime.acknowledge_alert(alert_id, actor)
