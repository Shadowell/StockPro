from __future__ import annotations

from typing import Any

from app.services.factor_research_service import FactorResearchService


class PostgresFactorRepository:
    def __init__(self, database) -> None:
        self.service = FactorResearchService(database)

    def list_library(self) -> list[dict[str, Any]]:
        return self.service.list_library()

    def create_factor(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.service.create_factor(payload)

    def create_version(self, definition_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.service.create_version(definition_id, payload)

    def validate_version(self, version_id: int) -> dict[str, Any]:
        return self.service.validate_version(version_id)

    def compute_factor(
        self,
        version_id: int,
        trade_date: str,
        dataset_snapshot_id: int,
        universe_snapshot_id: int,
    ) -> dict[str, Any]:
        return self.service.compute_factor(
            version_id,
            trade_date,
            dataset_snapshot_id,
            universe_snapshot_id,
        )

    def _definition_id(self, identifier: str) -> int:
        needle = str(identifier).strip()
        for item in self.service.list_library():
            if str(item.get("id")) == needle or str(item.get("factor_code")) == needle:
                return int(item["id"])
        raise ValueError("因子不存在")

    def factor_metrics(self, factor_identifier: str) -> dict[str, Any]:
        return self.service.factor_metrics(self._definition_id(factor_identifier))

    def factor_values(self, factor_identifier: str, limit: int, offset: int) -> dict[str, Any]:
        return self.service.factor_values(self._definition_id(factor_identifier), limit, offset)

    def list_runs(self, limit: int) -> list[dict[str, Any]]:
        return self.service.list_runs(limit)

    def list_correlations(self, trade_date: str | None, limit: int) -> list[dict[str, Any]]:
        return self.service.list_correlations(trade_date, limit)

    def list_snapshots(self, limit: int) -> list[dict[str, Any]]:
        return self.service.list_factor_snapshots(limit)

    def get_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        return self.service.get_factor_snapshot(snapshot_id)

    def snapshot_values(self, snapshot_id: int, factor_code: str | None, limit: int) -> dict[str, Any]:
        return self.service.factor_snapshot_values(snapshot_id, factor_code, limit)
