from __future__ import annotations

from typing import Any

from app.services.stock_pool_service import StockPoolService


class PostgresPoolRepository:
    def __init__(self, database) -> None:
        self.service = StockPoolService(database)

    def list_pools(self) -> list[dict[str, Any]]:
        return self.service.list_pools()

    def get_pool(self, pool_id: str) -> dict[str, Any]:
        return self.service.get_pool(pool_id)

    def create_pool(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.service.create_pool(payload)

    def generate(self, pool_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.service.generate(pool_id, payload)

    def members(self, pool_id: str, generation_id: str | None = None) -> list[dict[str, Any]]:
        return self.service.members(pool_id, generation_id)

    def seal_snapshot(self, pool_id: str, generation_id: str | None = None) -> dict[str, Any]:
        return self.service.seal_snapshot(pool_id, generation_id)

    def list_snapshots(self, pool_id: str | None = None) -> list[dict[str, Any]]:
        return self.service.list_snapshots(pool_id)

    def get_snapshot(self, snapshot_id: int) -> dict[str, Any]:
        return self.service.get_snapshot(snapshot_id)
