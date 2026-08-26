"""PostgreSQL persistence for asynchronous A-share backtest jobs."""
from __future__ import annotations

from datetime import date
from typing import Any, Callable
import uuid

import psycopg2
import psycopg2.extras

from app.core.config import settings


PATCH_COLUMNS = {
    "status", "progress", "phase", "message", "error_message", "backtest_run_id", "result_payload",
}


class GuestQuotaError(ValueError):
    def __init__(self, message: str, *, status_code: int = 429) -> None:
        super().__init__(message)
        self.status_code = status_code


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

    @staticmethod
    def _reserve_guest_usage(cursor, payload: dict, principal: dict) -> int | None:
        if principal.get("role") != "guest":
            return None
        guest_code_id = int(principal.get("guest_code_id") or 0)
        session_id = str(principal.get("session_id") or "")
        if not guest_code_id or not session_id:
            raise GuestQuotaError("访客会话缺少配额身份", status_code=403)
        cursor.execute(
            """SELECT * FROM guest_access_codes
               WHERE id=%s AND revoked_at IS NULL AND expires_at>NOW() FOR UPDATE""",
            (guest_code_id,),
        )
        code = cursor.fetchone()
        if not code:
            raise GuestQuotaError("邀请码已撤销或已过期", status_code=403)
        try:
            start_date = date.fromisoformat(str(payload.get("start_date") or "")[:10])
            end_date = date.fromisoformat(str(payload.get("end_date") or "")[:10])
        except ValueError as exc:
            raise GuestQuotaError("回测日期格式无效", status_code=400) from exc
        if start_date > end_date:
            raise GuestQuotaError("回测开始日期不能晚于结束日期", status_code=400)
        max_days = int(code["max_backtest_days"] or 365)
        if (end_date - start_date).days > max_days:
            raise GuestQuotaError(f"访客邀请码最长回测区间为 {max_days} 天", status_code=403)
        cursor.execute(
            """SELECT COUNT(*) AS count FROM backtest_jobs
               WHERE owner_role='guest' AND owner_guest_code_id=%s
                 AND status IN ('pending','running','cancelling')""",
            (guest_code_id,),
        )
        if int(cursor.fetchone()["count"] or 0) >= int(code["max_concurrent_backtests"] or 1):
            raise GuestQuotaError(f"访客邀请码并发回测上限为 {int(code['max_concurrent_backtests'] or 1)} 个")
        cursor.execute(
            """SELECT COUNT(*) AS count FROM guest_backtest_usage
               WHERE guest_code_id=%s AND created_at>=date_trunc('day',NOW())
                 AND created_at<date_trunc('day',NOW())+INTERVAL '1 day'""",
            (guest_code_id,),
        )
        daily = int(cursor.fetchone()["count"] or 0)
        max_daily = int(code["max_backtests_per_day"] or 0)
        if max_daily and daily >= max_daily:
            raise GuestQuotaError(f"访客邀请码每日回测上限为 {max_daily} 次")
        cursor.execute(
            """INSERT INTO guest_backtest_usage
               (guest_code_id,session_id,endpoint,start_date,end_date,status)
               VALUES (%s,%s,'/api/v2/backtest/run_job',%s,%s,'running') RETURNING id""",
            (guest_code_id, session_id, start_date, end_date),
        )
        return int(cursor.fetchone()["id"])

    def create(self, payload: dict, *, parent_job_id: str | None = None, attempt: int = 1, owner: dict | None = None) -> dict:
        job_id = str(uuid.uuid4())
        principal = dict(owner or {})
        with self._connect(readonly=False) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                guest_usage_id = self._reserve_guest_usage(cursor, payload, principal)
                cursor.execute(
                    """
                    INSERT INTO backtest_jobs
                    (job_id,request_payload,run_mode,status,progress,phase,message,owner_role,
                     owner_session_id,owner_guest_code_id,guest_usage_id,parent_job_id,attempt,job_type,result_payload)
                    VALUES (%s,%s,'full','pending',0,'queued','任务已进入本地队列',%s,%s,%s,%s,%s,%s,'single','{}'::jsonb)
                    RETURNING *
                    """,
                    (
                        job_id,
                        psycopg2.extras.Json(dict(payload)),
                        str(principal.get("role") or "admin"),
                        principal.get("session_id"),
                        principal.get("guest_code_id"),
                        guest_usage_id,
                        parent_job_id,
                        max(1, int(attempt)),
                    ),
                )
                row = dict(cursor.fetchone())
                self._log(cursor, job_id, "info", "queued", "回测任务已持久化并进入本地队列", {"attempt": row["attempt"]})
        return row

    def create_many(self, payloads: list[dict], *, owner: dict | None = None) -> list[dict]:
        if not payloads:
            return []
        principal = dict(owner or {})
        job_ids = [str(uuid.uuid4()) for _ in payloads]
        values = [
            (
                job_id,
                psycopg2.extras.Json(dict(payload)),
                str(principal.get("role") or "admin"),
                principal.get("session_id"),
                principal.get("guest_code_id"),
            )
            for job_id, payload in zip(job_ids, payloads)
        ]
        with self._connect(readonly=False) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO backtest_jobs
                    (job_id,request_payload,run_mode,status,progress,phase,message,owner_role,
                     owner_session_id,owner_guest_code_id,attempt,job_type,result_payload)
                    VALUES %s
                    """,
                    values,
                    template="(%s,%s,'full','pending',0,'queued','任务已进入本地队列',%s,%s,%s,1,'single','{}'::jsonb)",
                    page_size=50,
                )
                psycopg2.extras.execute_values(
                    cursor,
                    "INSERT INTO backtest_job_logs(job_id,level,phase,message,payload) VALUES %s",
                    [(job_id, "info", "queued", "批量回测任务已持久化并进入本地队列", psycopg2.extras.Json({"attempt": 1})) for job_id in job_ids],
                    page_size=50,
                )
                cursor.execute("SELECT * FROM backtest_jobs WHERE job_id=ANY(%s::uuid[])", (job_ids,))
                rows_by_id = {str(row["job_id"]): dict(row) for row in cursor.fetchall()}
        return [rows_by_id[job_id] for job_id in job_ids]

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
                if result.get("guest_usage_id") and status in {"success", "failed", "cancelled", "interrupted"}:
                    usage_status = "success" if status == "success" else "failed"
                    failure_reason = None if usage_status == "success" else str(result.get("error_message") or result.get("message") or status)[:2000]
                    cursor.execute(
                        """UPDATE guest_backtest_usage
                           SET status=%s,run_id=%s,failure_reason=%s,finished_at=NOW()
                           WHERE id=%s AND status='running'""",
                        (usage_status, str(result.get("backtest_run_id") or "") or None, failure_reason, result["guest_usage_id"]),
                    )
        return result

    def cancel_requested(self, job_id: str) -> bool:
        with self._connect(readonly=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT status IN ('cancelling','cancelled') FROM backtest_jobs WHERE job_id=%s", (str(job_id),))
                row = cursor.fetchone()
        return bool(row and row[0])
