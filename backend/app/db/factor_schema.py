"""FactorLab SQLite control-plane schema."""

from __future__ import annotations

import sqlite3


def create_factor_tables(cursor: sqlite3.Cursor) -> None:
    """Create additive FactorLab catalog and research control-plane tables."""
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
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_research_tasks (
            task_id TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK(status IN (
                'queued', 'running', 'paused', 'completed', 'failed', 'cancelled'
            )),
            config_json TEXT NOT NULL,
            provider_snapshot_json TEXT NOT NULL DEFAULT '{}',
            dataset_snapshot_id TEXT,
            trial_cursor INTEGER NOT NULL DEFAULT 0 CHECK(trial_cursor >= 0),
            best_trial_id TEXT,
            stop_reason TEXT,
            archived_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    task_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(factor_research_tasks)").fetchall()
    }
    if "archived_at" not in task_columns:
        cursor.execute("ALTER TABLE factor_research_tasks ADD COLUMN archived_at TEXT")
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_factor_research_tasks_status
        ON factor_research_tasks(status, updated_at, task_id)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_factor_research_tasks_archived
        ON factor_research_tasks(archived_at, created_at, task_id)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_dataset_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            manifest_json TEXT NOT NULL,
            artifact_path TEXT NOT NULL,
            row_count INTEGER NOT NULL CHECK(row_count >= 0),
            feature_count INTEGER NOT NULL CHECK(feature_count > 0),
            created_at TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES factor_research_tasks(task_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_factor_dataset_snapshots_task
        ON factor_dataset_snapshots(task_id, created_at, snapshot_id)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_trials (
            trial_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            semantic_hash TEXT NOT NULL,
            model_type TEXT NOT NULL,
            feature_ids_json TEXT NOT NULL,
            parameters_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL CHECK(status IN ('completed', 'rejected', 'failed')),
            metrics_json TEXT NOT NULL DEFAULT '{}',
            hard_gate_failures_json TEXT NOT NULL DEFAULT '[]',
            artifact_manifest_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES factor_research_tasks(task_id),
            UNIQUE(task_id, ordinal),
            UNIQUE(task_id, semantic_hash, model_type)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_factor_trials_task_status
        ON factor_trials(task_id, status, ordinal)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_research_events (
            event_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES factor_research_tasks(task_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_factor_research_events_task
        ON factor_research_events(task_id, created_at, event_id)
        """
    )
