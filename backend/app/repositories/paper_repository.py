from __future__ import annotations

from typing import Any

import psycopg2.extras

from app.services.paper_runtime_service import PaperRuntimeService


class PostgresPaperRepository:
    """Adapter around the preserved PostgreSQL Paper ledger and runtime."""

    def __init__(self, database: Any) -> None:
        self.database = database
        self.runtime = PaperRuntimeService(database)

    def list_instances(self) -> list[dict[str, Any]]:
        return self.runtime.list_instances()

    def get_instance(self, instance_id: str) -> dict[str, Any]:
        return self.runtime.get_instance(instance_id)

    def create_instance(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.runtime.create_instance(payload)

    def start(self, instance_id: str) -> dict[str, Any]:
        return self.runtime.start(instance_id)

    def pause(self, instance_id: str) -> dict[str, Any]:
        return self.runtime.pause(instance_id)

    def resume(self, instance_id: str) -> dict[str, Any]:
        return self.runtime.resume(instance_id)

    def stop(self, instance_id: str) -> dict[str, Any]:
        return self.runtime.stop(instance_id)

    def advance(self, instance_id: str, max_dates: int) -> dict[str, Any]:
        return self.runtime.advance_instance(instance_id, max_dates=max_dates)

    def events(self, instance_id: str) -> list[dict[str, Any]]:
        return self.runtime.events(instance_id)

    def klines(self, instance_id: str, symbol: str) -> dict[str, Any]:
        return self.runtime.get_instance_klines(instance_id, symbol)

    def continuity_manifest(self) -> dict[str, Any]:
        """Read only aggregate used to prove that UI reads preserve the ledger."""
        query = """
            SELECT
              (SELECT COUNT(*) FROM paper_instances)::integer AS instance_count,
              (SELECT COUNT(*) FROM orders WHERE paper_instance_id IS NOT NULL)::integer AS order_count,
              (SELECT COUNT(*) FROM trades WHERE paper_instance_id IS NOT NULL)::integer AS trade_count,
              (SELECT COUNT(*) FROM positions WHERE portfolio_id IN (SELECT portfolio_id FROM paper_instances))::integer AS position_count,
              (SELECT COUNT(*) FROM paper_equity_snapshots)::integer AS equity_sample_count,
              (SELECT COUNT(*) FROM paper_instance_events)::integer AS event_count
        """
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query)
                return dict(cursor.fetchone() or {})
