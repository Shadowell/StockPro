"""FactorLab SQLite control-plane schema."""

from __future__ import annotations

import sqlite3


def create_factor_tables(cursor: sqlite3.Cursor) -> None:
    """Create the additive FactorLab phase-one tables and indexes."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_definitions (
            definition_id TEXT NOT NULL,
            definition_version INTEGER NOT NULL CHECK(definition_version > 0),
            display_name TEXT NOT NULL,
            family TEXT NOT NULL,
            role TEXT NOT NULL,
            description TEXT NOT NULL,
            kernel_name TEXT NOT NULL,
            expression_json TEXT NOT NULL,
            inputs_json TEXT NOT NULL,
            parameter_schema_json TEXT NOT NULL,
            lookback_bars INTEGER NOT NULL CHECK(lookback_bars > 0),
            availability TEXT NOT NULL,
            orientation TEXT NOT NULL,
            missing_policy TEXT NOT NULL,
            valid_min REAL,
            valid_max REAL,
            implementation_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            PRIMARY KEY(definition_id, definition_version)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_factor_definitions_catalog
        ON factor_definitions(family, role, status, definition_id)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_instances (
            instance_id TEXT PRIMARY KEY,
            definition_id TEXT NOT NULL,
            definition_version INTEGER NOT NULL,
            parameters_json TEXT NOT NULL,
            parameter_hash TEXT NOT NULL,
            required_bars INTEGER NOT NULL CHECK(required_bars > 0),
            created_at TEXT NOT NULL,
            FOREIGN KEY(definition_id, definition_version)
                REFERENCES factor_definitions(definition_id, definition_version),
            UNIQUE(definition_id, definition_version, parameter_hash)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_factor_instances_definition
        ON factor_instances(definition_id, definition_version, created_at)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_latest (
            exchange TEXT NOT NULL,
            market_type TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            instance_id TEXT NOT NULL,
            event_time INTEGER NOT NULL,
            available_at INTEGER NOT NULL,
            computed_at INTEGER NOT NULL,
            value REAL,
            value_status TEXT NOT NULL,
            dataset_revision TEXT NOT NULL,
            PRIMARY KEY(exchange, market_type, symbol, timeframe, instance_id),
            FOREIGN KEY(instance_id) REFERENCES factor_instances(instance_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_factor_latest_event_time
        ON factor_latest(instance_id, timeframe, event_time)
        """
    )
