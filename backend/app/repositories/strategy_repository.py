from __future__ import annotations

from typing import Any

import psycopg2.extras

from app.domain.strategy.models import ImmutableEvidenceError
from app.services.strategy_runtime_service import StrategyRuntimeService, validate_strategy_python


class PostgresStrategyRepository:
    def __init__(self, database) -> None:
        self.database = database
        self.service = StrategyRuntimeService(database)

    def list_strategies(self) -> list[dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT ON (name) *
                    FROM strategy_versions
                    ORDER BY name,version DESC,created_at DESC
                    """
                )
                return [dict(row) for row in cursor.fetchall()]

    def get_strategy_version(self, version_id: str) -> dict[str, Any] | None:
        return self.service.get_version(version_id)

    def create_strategy(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.service.create_strategy(payload)

    def create_version(self, parent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.service.create_version(parent_id, payload)

    def validate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return validate_strategy_python(str(payload.get("script_content") or ""))

    def quick_run(self, version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.service.replay(version_id, {**payload, "mode": "quick"})

    def update_contract_metadata(self, version_id: str, metadata: dict[str, object]) -> None:
        raise ImmutableEvidenceError("historical contract metadata is read-only")
