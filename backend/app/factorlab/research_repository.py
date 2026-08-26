"""SQLite repository for immutable FactorLab research evidence."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from app.db.local_db import LocalDatabase
from app.factorlab.research_models import (
    DatasetSnapshot,
    FactorResearchTask,
    FactorResearchTaskConfig,
    FactorTrial,
    utc_now_iso,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class FactorResearchStateError(ValueError):
    """Raised when a task lifecycle transition is not permitted."""


class DuplicateFactorTrialError(ValueError):
    """Raised instead of overwriting an existing trial."""


class FactorResearchRepository:
    _ALLOWED_TRANSITIONS = {
        "queued": {"running", "paused", "cancelled", "failed"},
        "running": {"paused", "completed", "failed", "cancelled"},
        "paused": {"running", "cancelled"},
        "completed": set(),
        "failed": set(),
        "cancelled": set(),
    }

    def __init__(self, database: LocalDatabase):
        self.database = database

    def create_task(self, config: FactorResearchTaskConfig) -> FactorResearchTask:
        task_id = f"frt_{uuid.uuid4().hex[:16]}"
        now = utc_now_iso()
        self.database.get_connection().execute(
            """
            INSERT INTO factor_research_tasks (
                task_id, status, config_json, provider_snapshot_json,
                dataset_snapshot_id, trial_cursor, best_trial_id, stop_reason,
                created_at, updated_at
            ) VALUES (?, 'queued', ?, ?, NULL, 0, NULL, NULL, ?, ?)
            """,
            (task_id, _json(config.to_dict()), _json(dict(config.provider_snapshot)), now, now),
        )
        self.database.get_connection().commit()
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> FactorResearchTask:
        row = self.database.get_connection().execute(
            "SELECT * FROM factor_research_tasks WHERE task_id = ?",
            (str(task_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown factor research task: {task_id}")
        return self._task_from_row(row)

    def list_tasks(self, *, limit: int = 100) -> list[FactorResearchTask]:
        rows = self.database.get_connection().execute(
            """
            SELECT * FROM factor_research_tasks
            WHERE archived_at IS NULL
            ORDER BY created_at DESC, task_id DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def archive_task(self, task_id: str) -> FactorResearchTask:
        current = self.get_task(task_id)
        if current.archived_at is not None:
            return current
        if current.status in {"queued", "running"}:
            raise FactorResearchStateError("active factor research task must be paused first")
        now = utc_now_iso()
        connection = self.database.get_connection()
        try:
            cursor = connection.execute(
                """
                UPDATE factor_research_tasks
                SET archived_at = ?, updated_at = ?
                WHERE task_id = ? AND status = ? AND archived_at IS NULL
                """,
                (now, now, task_id, current.status),
            )
            if int(cursor.rowcount or 0) != 1:
                raise FactorResearchStateError("factor research task changed concurrently")
            connection.execute(
                """
                INSERT INTO factor_research_events (
                    event_id, task_id, event_type, detail_json, created_at
                ) VALUES (?, ?, 'task_archived', ?, ?)
                """,
                (
                    f"fre_{uuid.uuid4().hex[:20]}",
                    task_id,
                    _json({"status": current.status}),
                    now,
                ),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        return self.get_task(task_id)

    def pause_running_tasks(self, *, stop_reason: str) -> int:
        paused = 0
        for task in self.list_tasks(limit=500):
            if task.status != "running":
                continue
            self.transition(
                task.task_id,
                {"running"},
                "paused",
                stop_reason=stop_reason,
            )
            paused += 1
        return paused

    def transition(
        self,
        task_id: str,
        expected_statuses: Iterable[str],
        next_status: str,
        *,
        stop_reason: str | None = None,
    ) -> FactorResearchTask:
        current = self.get_task(task_id)
        if current.archived_at is not None:
            raise FactorResearchStateError("archived factor research task cannot transition")
        expected = {str(status) for status in expected_statuses}
        if current.status not in expected or next_status not in self._ALLOWED_TRANSITIONS[current.status]:
            raise FactorResearchStateError(
                f"invalid factor research transition: {current.status} -> {next_status}"
            )
        now = utc_now_iso()
        normalized_reason = str(stop_reason).strip() if stop_reason is not None else None
        connection = self.database.get_connection()
        try:
            cursor = connection.execute(
                """
                UPDATE factor_research_tasks
                SET status = ?, stop_reason = ?, updated_at = ?
                WHERE task_id = ? AND status = ?
                """,
                (next_status, normalized_reason, now, task_id, current.status),
            )
            if int(cursor.rowcount or 0) != 1:
                raise FactorResearchStateError("factor research task changed concurrently")
            connection.execute(
                """
                INSERT INTO factor_research_events (
                    event_id, task_id, event_type, detail_json, created_at
                ) VALUES (?, ?, 'status_changed', ?, ?)
                """,
                (
                    f"fre_{uuid.uuid4().hex[:20]}",
                    task_id,
                    _json(
                        {
                            "from": current.status,
                            "to": next_status,
                            "stop_reason": normalized_reason,
                        }
                    ),
                    now,
                ),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        return self.get_task(task_id)

    def update_progress(
        self,
        task_id: str,
        *,
        dataset_snapshot_id: str | None = None,
        trial_cursor: int | None = None,
        best_trial_id: str | None = None,
    ) -> FactorResearchTask:
        current = self.get_task(task_id)
        next_cursor = current.trial_cursor if trial_cursor is None else int(trial_cursor)
        if next_cursor < current.trial_cursor:
            raise FactorResearchStateError("trial cursor cannot move backwards")
        self.database.get_connection().execute(
            """
            UPDATE factor_research_tasks
            SET dataset_snapshot_id = ?, trial_cursor = ?, best_trial_id = ?, updated_at = ?
            WHERE task_id = ?
            """,
            (
                dataset_snapshot_id if dataset_snapshot_id is not None else current.dataset_snapshot_id,
                next_cursor,
                best_trial_id if best_trial_id is not None else current.best_trial_id,
                utc_now_iso(),
                task_id,
            ),
        )
        self.database.get_connection().commit()
        return self.get_task(task_id)

    def append_trial(self, trial: FactorTrial) -> None:
        self.get_task(trial.task_id)
        try:
            self.database.get_connection().execute(
                """
                INSERT INTO factor_trials (
                    trial_id, task_id, ordinal, semantic_hash, model_type,
                    feature_ids_json, parameters_json, status, metrics_json,
                    hard_gate_failures_json, artifact_manifest_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trial.trial_id,
                    trial.task_id,
                    int(trial.ordinal),
                    trial.semantic_hash,
                    trial.model_type,
                    _json(list(trial.feature_ids)),
                    _json(dict(trial.parameters)),
                    trial.status,
                    _json(dict(trial.metrics)),
                    _json(list(trial.hard_gate_failures)),
                    _json(dict(trial.artifact_manifest)),
                    trial.created_at,
                ),
            )
            self.database.get_connection().commit()
        except sqlite3.IntegrityError as exc:
            self.database.get_connection().rollback()
            raise DuplicateFactorTrialError("factor trials are immutable and unique") from exc

    def list_trials(self, task_id: str) -> list[FactorTrial]:
        rows = self.database.get_connection().execute(
            """
            SELECT * FROM factor_trials
            WHERE task_id = ?
            ORDER BY ordinal, model_type, trial_id
            """,
            (task_id,),
        ).fetchall()
        return [self._trial_from_row(row) for row in rows]

    def save_dataset_snapshot(self, snapshot: DatasetSnapshot) -> None:
        self.get_task(snapshot.task_id)
        try:
            self.database.get_connection().execute(
                """
                INSERT INTO factor_dataset_snapshots (
                    snapshot_id, task_id, manifest_json, artifact_path,
                    row_count, feature_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.task_id,
                    _json(dict(snapshot.manifest)),
                    snapshot.artifact_path,
                    int(snapshot.row_count),
                    int(snapshot.feature_count),
                    snapshot.created_at,
                ),
            )
            self.database.get_connection().commit()
        except sqlite3.IntegrityError as exc:
            self.database.get_connection().rollback()
            existing = self.get_dataset_snapshot(snapshot.snapshot_id)
            if existing != snapshot:
                raise ValueError("dataset snapshots are immutable") from exc

    def get_dataset_snapshot(self, snapshot_id: str) -> DatasetSnapshot:
        row = self.database.get_connection().execute(
            "SELECT * FROM factor_dataset_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown factor dataset snapshot: {snapshot_id}")
        values = dict(row)
        return DatasetSnapshot(
            snapshot_id=values["snapshot_id"],
            task_id=values["task_id"],
            manifest=json.loads(values["manifest_json"]),
            artifact_path=values["artifact_path"],
            row_count=int(values["row_count"]),
            feature_count=int(values["feature_count"]),
            created_at=values["created_at"],
        )

    def append_event(self, task_id: str, event_type: str, detail: Mapping[str, Any]) -> None:
        self.database.get_connection().execute(
            """
            INSERT INTO factor_research_events (
                event_id, task_id, event_type, detail_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                f"fre_{uuid.uuid4().hex[:20]}",
                task_id,
                str(event_type),
                _json(dict(detail)),
                utc_now_iso(),
            ),
        )
        self.database.get_connection().commit()

    @staticmethod
    def _task_from_row(row: Any) -> FactorResearchTask:
        values = dict(row)
        config_payload = json.loads(values["config_json"])
        provider_snapshot = json.loads(values["provider_snapshot_json"])
        if dict(config_payload.get("provider_snapshot") or {}) != provider_snapshot:
            raise ValueError("factor research Provider snapshot mismatch")
        return FactorResearchTask(
            task_id=values["task_id"],
            status=values["status"],
            config=FactorResearchTaskConfig.from_dict(config_payload),
            dataset_snapshot_id=values["dataset_snapshot_id"],
            trial_cursor=int(values["trial_cursor"]),
            best_trial_id=values["best_trial_id"],
            stop_reason=values["stop_reason"],
            archived_at=values.get("archived_at"),
            created_at=values["created_at"],
            updated_at=values["updated_at"],
        )

    @staticmethod
    def _trial_from_row(row: Any) -> FactorTrial:
        values = dict(row)
        return FactorTrial(
            trial_id=values["trial_id"],
            task_id=values["task_id"],
            ordinal=int(values["ordinal"]),
            semantic_hash=values["semantic_hash"],
            model_type=values["model_type"],
            feature_ids=tuple(json.loads(values["feature_ids_json"])),
            parameters=json.loads(values["parameters_json"]),
            status=values["status"],
            metrics=json.loads(values["metrics_json"]),
            hard_gate_failures=tuple(json.loads(values["hard_gate_failures_json"])),
            artifact_manifest=json.loads(values["artifact_manifest_json"]),
            created_at=values["created_at"],
        )
