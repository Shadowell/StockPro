from __future__ import annotations

import sys
import sqlite3
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.local_db import LocalDatabase  # noqa: E402
from app.factorlab.research_models import (  # noqa: E402
    DatasetSnapshot,
    FactorResearchTaskConfig,
    FactorTrial,
)
from app.factorlab.research_repository import (  # noqa: E402
    DuplicateFactorTrialError,
    FactorResearchRepository,
    FactorResearchStateError,
)


def valid_config() -> FactorResearchTaskConfig:
    return FactorResearchTaskConfig(
        exchange="okx",
        market_type="swap",
        symbols=("BTC/USDT:USDT", "ETH/USDT:USDT"),
        timeframe="1h",
        start_ms=1_700_000_000_000,
        end_ms=1_710_000_000_000,
        mode="auto",
        factor_instance_ids=("trend.adx@1:abc", "momentum.rsi@1:def"),
        provider_key="codex",
        model="gpt-5.6-sol",
        reasoning_effort="high",
        speed_mode="standard",
        provider_snapshot={"schema_version": "provider-capability-v2", "provider_key": "codex"},
        horizon_bars=6,
        base_cost_bps=20.0,
        stress_cost_bps=40.0,
        n_splits=5,
        max_candidates=20,
        max_runtime_sec=600,
        max_no_improvement=10,
        max_combination_leaves=4,
        random_seed=17,
    )


def repository(tmp_path: Path) -> FactorResearchRepository:
    database = LocalDatabase(str(tmp_path / "factor-research.db"))
    database.init_db()
    return FactorResearchRepository(database)


def test_research_tables_are_additive_to_existing_database(tmp_path: Path) -> None:
    repo = repository(tmp_path)

    names = {
        row["name"]
        for row in repo.database.get_connection().execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }

    assert {
        "strategies",
        "factor_definitions",
        "factor_research_tasks",
        "factor_dataset_snapshots",
        "factor_trials",
        "factor_research_events",
    } <= names


def test_existing_research_task_table_adds_archived_at_column(tmp_path: Path) -> None:
    database_path = tmp_path / "factor-research-migration.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE factor_research_tasks (
            task_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            config_json TEXT NOT NULL,
            provider_snapshot_json TEXT NOT NULL DEFAULT '{}',
            dataset_snapshot_id TEXT,
            trial_cursor INTEGER NOT NULL DEFAULT 0,
            best_trial_id TEXT,
            stop_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()

    database = LocalDatabase(str(database_path))
    database.init_db()
    columns = {
        row["name"]
        for row in database.get_connection().execute(
            "PRAGMA table_info(factor_research_tasks)"
        )
    }

    assert "archived_at" in columns


def test_task_config_round_trip_preserves_provider_and_budget_snapshot(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    config = valid_config()

    created = repo.create_task(config)
    restored = repo.get_task(created.task_id)

    assert restored.status == "queued"
    assert restored.config == config
    assert restored.config.provider_snapshot == {
        "schema_version": "provider-capability-v2",
        "provider_key": "codex",
    }
    assert restored.trial_cursor == 0
    assert restored.dataset_snapshot_id is None
    assert restored.best_trial_id is None


def test_research_ledger_preserves_failed_trials_and_rejects_invalid_transition(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    task = repo.create_task(valid_config())
    rejected = FactorTrial(
        trial_id=f"{task.task_id}:0000:ridge",
        task_id=task.task_id,
        ordinal=0,
        semantic_hash="sha256:combination-a",
        model_type="ridge",
        feature_ids=("trend.adx@1:abc",),
        parameters={"alpha": 1.0},
        status="rejected",
        metrics={},
        hard_gate_failures=("insufficient_samples",),
        artifact_manifest={},
    )

    repo.append_trial(rejected)
    repo.transition(task.task_id, {"queued"}, "running")
    repo.transition(task.task_id, {"running"}, "paused", stop_reason="operator_paused")

    restored = repo.list_trials(task.task_id)
    assert restored == [rejected]
    assert repo.get_task(task.task_id).stop_reason == "operator_paused"
    with pytest.raises(FactorResearchStateError):
        repo.transition(task.task_id, {"completed"}, "running")


def test_status_transition_and_audit_event_are_one_sqlite_transaction(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    task = repo.create_task(valid_config())
    repo.database.get_connection().execute(
        """
        CREATE TRIGGER reject_factor_research_event
        BEFORE INSERT ON factor_research_events
        BEGIN
            SELECT RAISE(ABORT, 'event write failed');
        END
        """
    )
    repo.database.get_connection().commit()

    with pytest.raises(sqlite3.IntegrityError, match="event write failed"):
        repo.transition(task.task_id, {"queued"}, "running")

    assert repo.get_task(task.task_id).status == "queued"


def test_archive_and_audit_event_are_one_sqlite_transaction(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    task = repo.create_task(valid_config())
    repo.transition(task.task_id, {"queued"}, "paused")
    repo.database.get_connection().execute(
        """
        CREATE TRIGGER reject_factor_research_archive_event
        BEFORE INSERT ON factor_research_events
        WHEN NEW.event_type = 'task_archived'
        BEGIN
            SELECT RAISE(ABORT, 'archive event write failed');
        END
        """
    )
    repo.database.get_connection().commit()

    with pytest.raises(sqlite3.IntegrityError, match="archive event write failed"):
        repo.archive_task(task.task_id)

    assert repo.get_task(task.task_id).archived_at is None
    assert [item.task_id for item in repo.list_tasks()] == [task.task_id]


def test_trial_ordinal_and_semantic_model_identity_cannot_be_overwritten(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    task = repo.create_task(valid_config())
    trial = FactorTrial(
        trial_id=f"{task.task_id}:0000:equal_weight",
        task_id=task.task_id,
        ordinal=0,
        semantic_hash="sha256:combination-a",
        model_type="equal_weight",
        feature_ids=("trend.adx@1:abc",),
        parameters={},
        status="completed",
        metrics={"score": 61.5},
        hard_gate_failures=("profit_factor_below_threshold",),
        artifact_manifest={"model": "baseline"},
    )

    repo.append_trial(trial)
    with pytest.raises(DuplicateFactorTrialError):
        repo.append_trial(trial)

    assert repo.list_trials(task.task_id) == [trial]


def test_dataset_snapshot_and_progress_are_saved_without_rewriting_trials(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    task = repo.create_task(valid_config())
    snapshot = DatasetSnapshot(
        snapshot_id="fds_sha256_fixture",
        task_id=task.task_id,
        manifest={"symbols": ["BTC/USDT:USDT", "ETH/USDT:USDT"], "horizon_bars": 6},
        artifact_path="data/factors/experiments/fds_sha256_fixture/dataset.parquet",
        row_count=1200,
        feature_count=2,
    )

    repo.save_dataset_snapshot(snapshot)
    repo.update_progress(
        task.task_id,
        dataset_snapshot_id=snapshot.snapshot_id,
        trial_cursor=7,
        best_trial_id="trial-best",
    )

    restored = repo.get_task(task.task_id)
    assert repo.get_dataset_snapshot(snapshot.snapshot_id) == snapshot
    assert restored.dataset_snapshot_id == snapshot.snapshot_id
    assert restored.trial_cursor == 7
    assert restored.best_trial_id == "trial-best"


def test_archiving_completed_task_hides_it_without_deleting_evidence(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    task = repo.create_task(valid_config())
    snapshot = DatasetSnapshot(
        snapshot_id="fds_archive_fixture",
        task_id=task.task_id,
        manifest={"symbols": ["BTC/USDT:USDT"]},
        artifact_path="data/factors/experiments/fds_archive_fixture/dataset.parquet",
        row_count=100,
        feature_count=2,
    )
    trial = FactorTrial(
        trial_id=f"{task.task_id}:0000:ridge",
        task_id=task.task_id,
        ordinal=0,
        semantic_hash="sha256:archive-combination",
        model_type="ridge",
        feature_ids=("trend.adx@1:abc",),
        parameters={"alpha": 1.0},
        status="completed",
        metrics={"score": 72.0},
        hard_gate_failures=(),
        artifact_manifest={"model": "ridge.json"},
    )
    repo.save_dataset_snapshot(snapshot)
    repo.append_trial(trial)
    repo.transition(task.task_id, {"queued"}, "running")
    repo.transition(task.task_id, {"running"}, "completed")

    archived = repo.archive_task(task.task_id)

    assert archived.archived_at is not None
    assert repo.list_tasks() == []
    assert repo.get_task(task.task_id) == archived
    assert repo.get_dataset_snapshot(snapshot.snapshot_id) == snapshot
    assert repo.list_trials(task.task_id) == [trial]
    event = repo.database.get_connection().execute(
        """
        SELECT event_type FROM factor_research_events
        WHERE task_id = ? ORDER BY created_at DESC LIMIT 1
        """,
        (task.task_id,),
    ).fetchone()
    assert event["event_type"] == "task_archived"


@pytest.mark.parametrize("status", ["queued", "running"])
def test_active_research_task_must_be_paused_before_archiving(
    tmp_path: Path,
    status: str,
) -> None:
    repo = repository(tmp_path)
    task = repo.create_task(valid_config())
    if status == "running":
        repo.transition(task.task_id, {"queued"}, "running")

    with pytest.raises(FactorResearchStateError, match="active"):
        repo.archive_task(task.task_id)

    assert repo.get_task(task.task_id).archived_at is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbols", ()),
        ("horizon_bars", 0),
        ("base_cost_bps", -1.0),
        ("n_splits", 1),
        ("max_candidates", 0),
    ],
)
def test_task_config_rejects_invalid_research_boundaries(field: str, value) -> None:
    payload = valid_config().to_dict()
    payload[field] = value

    with pytest.raises(ValueError):
        FactorResearchTaskConfig.from_dict(payload)


@pytest.mark.parametrize(
    "provider_snapshot",
    [
        {"provider_key": "cursor"},
        {"provider_key": "codex", "api_key": "must-not-persist"},
        {"provider_key": "codex", "nested": {"token": "must-not-persist"}},
        {"provider_key": "codex", "command": "/usr/local/bin/codex"},
    ],
)
def test_task_config_rejects_mismatched_or_sensitive_provider_snapshot(provider_snapshot) -> None:
    payload = valid_config().to_dict()
    payload["provider_snapshot"] = provider_snapshot

    with pytest.raises(ValueError):
        FactorResearchTaskConfig.from_dict(payload)
