"""PostgreSQL persistence for asynchronous A-share backtest jobs."""
from __future__ import annotations

from typing import Any, Callable
import uuid

import psycopg2
import psycopg2.extras

from app.core.config import settings


PATCH_COLUMNS = {
    "status", "progress", "phase", "message", "error_message", "backtest_run_id", "result_payload",
}


class PostgresBacktestJobRepository:
    def __init__(self, database_url: str | None = None, *, connection_factory: Callable[..., object] = psycopg2.connect) -> None:
        self.database_url = database_url or settings.DATABASE_URL
        self.connection_factory = connection_factory

    def _connect(self, *, readonly: bool):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for backtest jobs")
        connection = self.connection_factory(self.database_url)
        connection.set_session(readonly=readonly, autocommit=False)
        return connection

    @staticmethod
    def _log(cursor, job_id: str, level: str, phase: str, message: str, payload: dict | None = None) -> None:
        cursor.execute(
            "INSERT INTO backtest_job_logs(job_id,level,phase,message,payload) VALUES (%s,%s,%s,%s,%s)",
            (job_id, level, phase, message, psycopg2.extras.Json(payload or {})),
        )

    def create(self, payload: dict, *, parent_job_id: str | None = None, attempt: int = 1, owner: dict | None = None) -> dict:
        job_id = str(uuid.uuid4())
        principal = dict(owner or {})
        with self._connect(readonly=False) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO backtest_jobs
                    (job_id,request_payload,run_mode,status,progress,phase,message,owner_role,
                     owner_session_id,owner_guest_code_id,parent_job_id,attempt,job_type,result_payload)
                    VALUES (%s,%s,'full','pending',0,'queued','任务已进入本地队列',%s,%s,%s,%s,%s,'single','{}'::jsonb)
                    RETURNING *
                    """,
                    (
                        job_id,
                        psycopg2.extras.Json(dict(payload)),
                        str(principal.get("role") or "admin"),
                        principal.get("session_id"),
                        principal.get("guest_code_id"),
                        parent_job_id,
                        max(1, int(attempt)),
                    ),
                )
                row = dict(cursor.fetchone())
                self._log(cursor, job_id, "info", "queued", "回测任务已持久化并进入本地队列", {"attempt": row["attempt"]})
        return row

    def get(self, job_id: str) -> dict | None:
        with self._connect(readonly=True) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM backtest_jobs WHERE job_id=%s", (str(job_id),))
                row = cursor.fetchone()
        return dict(row) if row else None

    def list(self, *, strategy_id: int | None = None, status: str | None = None, limit: int = 50, owner_session_id: str | None = None, **_: Any) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if strategy_id is not None:
            clauses.append("request_payload->>'strategy_id'=%s")
            params.append(str(strategy_id))
        statuses = [item.strip() for item in str(status or "").split(",") if item.strip()]
        if statuses:
            clauses.append("status=ANY(%s)")
            params.append(statuses)
        if owner_session_id:
            clauses.append("owner_session_id=%s")
            params.append(owner_session_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 200)))
        with self._connect(readonly=True) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(f"SELECT * FROM backtest_jobs {where} ORDER BY created_at DESC LIMIT %s", params)
                return [dict(row) for row in cursor.fetchall()]

    def transition(self, job_id: str, **patch: Any) -> dict:
        unknown = set(patch) - PATCH_COLUMNS
        if unknown:
            raise ValueError(f"不支持的任务状态字段：{sorted(unknown)[0]}")
        if not patch:
            row = self.get(job_id)
            if not row:
                raise ValueError("回测任务不存在")
            return row
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in patch.items():
            assignments.append(f"{key}=%s")
            values.append(psycopg2.extras.Json(value) if key == "result_payload" else value)
        status = str(patch.get("status") or "")
        if status == "running":
            assignments.append("started_at=COALESCE(started_at,NOW())")
        if status == "cancelling":
            assignments.append("cancel_requested_at=COALESCE(cancel_requested_at,NOW())")
        if status in {"success", "failed", "cancelled", "interrupted"}:
            assignments.append("finished_at=COALESCE(finished_at,NOW())")
        assignments.append("updated_at=NOW()")
        values.append(str(job_id))
        with self._connect(readonly=False) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(f"UPDATE backtest_jobs SET {','.join(assignments)} WHERE job_id=%s RETURNING *", values)
                row = cursor.fetchone()
                if not row:
                    raise ValueError("回测任务不存在")
                result = dict(row)
                phase = str(result.get("phase") or result.get("status") or "update")
                level = "error" if result.get("status") == "failed" else "warning" if result.get("status") in {"cancelling", "cancelled", "interrupted"} else "info"
                self._log(cursor, str(job_id), level, phase, str(result.get("message") or phase), {"progress": float(result.get("progress") or 0)})
        return result

    def cancel_requested(self, job_id: str) -> bool:
        with self._connect(readonly=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT status IN ('cancelling','cancelled') FROM backtest_jobs WHERE job_id=%s", (str(job_id),))
                row = cursor.fetchone()
        return bool(row and row[0])
