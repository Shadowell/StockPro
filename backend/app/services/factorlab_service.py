"""Read-only operator summary and startup bootstrap for FactorLab."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from app.db.local_db import LocalDatabase, db_instance
from app.factorlab.builtins import builtin_factor_definitions
from app.factorlab.registry import FactorRegistry


class FactorLabService:
    def __init__(
        self,
        database: Optional[LocalDatabase] = None,
        *,
        factor_root: Optional[Path | str] = None,
    ):
        self.database = database or db_instance
        project_root = Path(__file__).resolve().parents[3]
        self.factor_root = Path(factor_root) if factor_root is not None else project_root / "data" / "factors"
        self.registry = FactorRegistry(self.database)

    def bootstrap(self) -> None:
        """Register immutable built-ins and one deterministic default instance each."""
        self.registry.register_builtins()
        for definition in builtin_factor_definitions():
            defaults = {
                name: schema["default"]
                for name, schema in definition.parameter_schema.items()
                if "default" in schema
            }
            self.registry.create_instance(
                definition.definition_id,
                definition.definition_version,
                defaults,
            )

    def summary(self) -> dict[str, Any]:
        definitions = [asdict(definition) for definition in self.registry.list_definitions()]
        connection = self.database.get_connection()
        instance_rows = connection.execute(
            """
            SELECT instance_id, definition_id, definition_version, parameters_json,
                   parameter_hash, required_bars, created_at
            FROM factor_instances
            ORDER BY definition_id, definition_version, instance_id
            """
        ).fetchall()
        latest_rows = connection.execute(
            """
            SELECT exchange, market_type, symbol, timeframe, instance_id,
                   event_time, available_at, computed_at, value, value_status,
                   dataset_revision
            FROM factor_latest
            ORDER BY event_time DESC, instance_id, symbol
            LIMIT 100
            """
        ).fetchall()

        instances = []
        for row in instance_rows:
            item = dict(row)
            parameters = json.loads(item["parameters_json"])
            definition = self.registry.get_definition(
                item["definition_id"],
                int(item["definition_version"]),
            )
            defaults = {
                name: schema.get("default")
                for name, schema in definition.parameter_schema.items()
            }
            item["parameters"] = parameters
            item["is_default"] = parameters == defaults
            instances.append(item)

        latest_values = [dict(row) for row in latest_rows]
        partition_count = sum(1 for _ in self.factor_root.glob("values/**/part-*.parquet"))
        return {
            "status": "ready" if definitions else "empty",
            "phase": "phase1_catalog",
            "statistics": {
                "definition_count": len(definitions),
                "instance_count": len(instances),
                "latest_value_count": self._table_count("factor_latest"),
                "materialized_partition_count": partition_count,
            },
            "definitions": definitions,
            "instances": instances,
            "latest_values": latest_values,
            "data_plane": {
                "format": "parquet",
                "layout": "exchange/market_type/timeframe/factor_instance/date",
                "manifest": "manifest.json",
            },
            "capabilities": {
                "api_mode": "read_only",
                "materialization_store_ready": True,
                "research_metrics_available": False,
                "strategy_runtime_connected": False,
                "paper_live_connected": False,
            },
        }

    def _table_count(self, table: str) -> int:
        allowed = {"factor_latest"}
        if table not in allowed:
            raise ValueError(f"unsupported FactorLab table: {table}")
        row = self.database.get_connection().execute(
            f"SELECT COUNT(*) AS count FROM {table}"
        ).fetchone()
        return int(row["count"])


factorlab_service = FactorLabService()
