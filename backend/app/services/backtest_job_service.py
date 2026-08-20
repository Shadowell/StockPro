from __future__ import annotations

import threading
import uuid
from typing import Any, Mapping

import psycopg2.extras

from app.services.backtest_workbench_service import BacktestCancelled, BacktestWorkbenchService
from app.services.guest_access_service import GuestAccessService
from app.services.walk_forward_plan_service import WalkForwardExecutionService


TERMINAL_JOB_STATUSES = {"cancelled", "success", "failed", "interrupted"}
RETRYABLE_JOB_STATUSES = {"cancelled", "failed", "interrupted"}


class BacktestJobError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class BacktestJobService:
    def __init__(self, database, *, max_workers: int = 2) -> None:
        self.database = database
        self.workbench = BacktestWorkbenchService(database)
        self.walk_forward = WalkForwardExecutionService(database)
        self.guest_access = GuestAccessService(database)
        self._slots = threading.BoundedSemaphore(max(1, max_workers))
        self._active: dict[str, threading.Thread] = {}
        self._active_lock = threading.Lock()

    def create_job(
        self,
        payload: Mapping[str, Any],
        *,
        mode: str,
        principal: Mapping[str, Any],
        parent_job_id: str | None = None,
        attempt: int = 1,
    ) -> dict[str, Any]:
        if mode not in {"quick", "full"}:
            raise BacktestJobError("run mode 只能为 quick 或 full")
        usage_id = self.guest_access.reserve_backtest(
            principal,
            endpoint="/api/backtest/jobs",
            start_date=str(payload.get("start_date") or ""),
            end_date=str(payload.get("end_date") or ""),
        )
        job_id = str(uuid.uuid4())
        try:
            with self.database.get_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        INSERT INTO backtest_jobs
                            (job_id, request_payload, run_mode, owner_role,
                             owner_session_id, owner_guest_code_id, guest_usage_id,
                             parent_job_id, attempt, message)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING *
                        """,
                        (
                            job_id,
                            psycopg2.extras.Json(dict(payload)),
                            mode,
                            str(principal.get("role") or "admin"),
                            principal.get("session_id"),
                            principal.get("guest_code_id"),
                            usage_id,
                            parent_job_id,
                            attempt,
                            "任务已进入本地队列",
                        ),
                    )
                    row = dict(cursor.fetchone())
                    self._log_cursor(
                        cursor,
                        job_id,
                        "info",
                        "queued",
                        "回测任务已持久化并进入本地队列",
                        {"run_mode": mode, "attempt": attempt},
                    )
                conn.commit()
        except Exception:
            self.guest_access.finish_backtest(
                usage_id, success=False, failure_reason="回测任务创建失败"
            )
            raise
        self.start(job_id)
        return self._serialize(row)

    def create_walk_forward_job(
        self,
        payload: Mapping[str, Any],
        *,
        principal: Mapping[str, Any],
        parent_job_id: str | None = None,
        attempt: int = 1,
    ) -> dict[str, Any]:
        if principal.get("role") == "guest":
            raise BacktestJobError("访客账号不能启动 Walk-forward 参数优化", 403)
        # Fail before the queue write when the snapshot, folds or grid are invalid.
        self.walk_forward.plan_service.preview(payload)
        self.walk_forward._expand_grid(payload.get("parameter_grid") or {})
        job_id = str(uuid.uuid4())
        with self.database.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO backtest_jobs
                        (job_id, request_payload, run_mode, job_type, owner_role,
                         owner_session_id, owner_guest_code_id, parent_job_id,
                         attempt, message)
                    VALUES (%s, %s, 'full', 'walk_forward', %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        job_id,
                        psycopg2.extras.Json(dict(payload)),
                        str(principal.get("role") or "admin"),
                        principal.get("session_id"),
                        principal.get("guest_code_id"),
                        parent_job_id,
                        attempt,
                        "Walk-forward 任务已进入本地队列",
                    ),
                )
                row = dict(cursor.fetchone())
                self._log_cursor(
                    cursor,
                    job_id,
                    "info",
                    "queued",
                    "Walk-forward 任务已持久化并进入本地队列",
                    {"job_type": "walk_forward", "attempt": attempt},
                )
            conn.commit()
        self.start(job_id)
        return self._serialize(row)

    def start(self, job_id: str) -> None:
        with self._active_lock:
            current = self._active.get(job_id)
            if current and current.is_alive():
                return
            thread = threading.Thread(
                target=self._worker,
                args=(job_id,),
                name=f"stockpro-backtest-{job_id[:8]}",
                daemon=True,
            )
            self._active[job_id] = thread
            thread.start()

    def list_jobs(
        self, principal: Mapping[str, Any], *, limit: int = 100
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if principal.get("role") == "guest":
            conditions.append("owner_session_id = %s")
            params.append(principal.get("session_id"))
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(max(1, min(int(limit), 200)))
        return self._rows(
            f"""
            SELECT * FROM backtest_jobs
            {where}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            tuple(params),
        )

    def get_job(
        self, job_id: str, principal: Mapping[str, Any]
    ) -> dict[str, Any]:
        row = self._row("SELECT * FROM backtest_jobs WHERE job_id = %s", (job_id,))
        if not row:
            raise BacktestJobError("回测任务不存在", 404)
        self._ensure_access(row, principal)
        return row

    def logs(
        self,
        job_id: str,
        principal: Mapping[str, Any],
        *,
        after_id: int = 0,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        self.get_job(job_id, principal)
        return self._rows(
            """
            SELECT * FROM backtest_job_logs
            WHERE job_id = %s AND id > %s
            ORDER BY id
            LIMIT %s
            """,
            (job_id, max(0, after_id), max(1, min(limit, 1000))),
        )

    def cancel(
        self, job_id: str, principal: Mapping[str, Any]
    ) -> dict[str, Any]:
        current = self.get_job(job_id, principal)
        if current["status"] in TERMINAL_JOB_STATUSES:
            return current
        with self.database.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE backtest_jobs
                    SET status = 'cancelling',
                        phase = 'cancelling',
                        message = '用户请求停止，正在安全结束',
                        cancel_requested_at = NOW(),
                        updated_at = NOW()
                    WHERE job_id = %s
                      AND status IN ('pending', 'running')
                    RETURNING *
                    """,
                    (job_id,),
                )
                row = cursor.fetchone()
                if row:
                    self._log_cursor(
                        cursor,
                        job_id,
                        "warning",
                        "cancelling",
                        "收到用户停止请求",
                        {},
                    )
            conn.commit()
        return self.get_job(job_id, principal)

    def retry(
        self, job_id: str, principal: Mapping[str, Any]
    ) -> dict[str, Any]:
        current = self.get_job(job_id, principal)
        if current["status"] not in RETRYABLE_JOB_STATUSES:
            raise BacktestJobError(
                f"当前状态不可重试: {current['status']}", 409
            )
        if current.get("job_type") == "walk_forward":
            return self.create_walk_forward_job(
                current["request_payload"],
                principal=principal,
                parent_job_id=job_id,
                attempt=int(current["attempt"] or 1) + 1,
            )
        return self.create_job(
            current["request_payload"],
            mode=str(current["run_mode"]),
            principal=principal,
            parent_job_id=job_id,
            attempt=int(current["attempt"] or 1) + 1,
        )

    def recover_interrupted(self) -> int:
        with self.database.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE backtest_jobs
                    SET status = 'interrupted',
                        phase = 'interrupted',
                        message = '后端进程重启，任务已中断，可创建重试任务',
                        updated_at = NOW(),
                        finished_at = NOW()
                    WHERE status IN ('pending', 'running', 'cancelling')
                    RETURNING job_id, guest_usage_id
                    """
                )
                rows = [dict(row) for row in cursor.fetchall()]
                for row in rows:
                    self._log_cursor(
                        cursor,
                        str(row["job_id"]),
                        "warning",
                        "interrupted",
                        "后端进程重启，任务状态已收敛为 interrupted",
                        {},
                    )
                    if row.get("guest_usage_id"):
                        cursor.execute(
                            """
                            UPDATE guest_backtest_usage
                            SET status = 'failed',
                                failure_reason = '后端进程重启，回测任务中断',
                                finished_at = NOW()
                            WHERE id = %s AND status = 'running'
                            """,
                            (row["guest_usage_id"],),
                        )
                cursor.execute(
                    """
                    UPDATE backtest_runs
                    SET status = 'failed',
                        progress = 100,
                        error_message = COALESCE(NULLIF(error_message, ''), '后端进程重启，回测未完成写入'),
                        finished_at = COALESCE(finished_at, NOW())
                    WHERE status = 'running'
                    """
                )
            conn.commit()
        return len(rows)

    def _worker(self, job_id: str) -> None:
        with self._slots:
            job = self._row("SELECT * FROM backtest_jobs WHERE job_id = %s", (job_id,))
            if not job:
                return
            usage_id = job.get("guest_usage_id")
            try:
                if self._cancel_requested(job_id):
                    raise BacktestCancelled("任务在开始前已取消")
                self._transition(
                    job_id,
                    status="running",
                    progress=2,
                    phase="validating",
                    message="正在校验不可变策略和研究快照",
                    started=True,
                )

                last_progress = 2.0
                last_phase = "validating"

                def progress(progress_value: float, phase: str, message: str) -> None:
                    nonlocal last_progress, last_phase
                    if phase == last_phase and progress_value - last_progress < 2:
                        return
                    self._transition(
                        job_id,
                        status="running",
                        progress=progress_value,
                        phase=phase,
                        message=message,
                    )
                    last_progress = progress_value
                    last_phase = phase

                if job.get("job_type") == "walk_forward":
                    result = self.walk_forward.execute(
                        job["request_payload"],
                        progress_hook=progress,
                        cancel_check=lambda: self._cancel_requested(job_id),
                    )
                    self._transition(
                        job_id,
                        status="success",
                        progress=100,
                        phase="completed",
                        message="Walk-forward OOS 证据已完成",
                        result_payload=result,
                        terminal=True,
                    )
                else:
                    result = self.workbench.run(
                        job["request_payload"],
                        mode=str(job["run_mode"]),
                        progress_hook=progress,
                        cancel_check=lambda: self._cancel_requested(job_id),
                    )
                    run_id = str(result.get("id") or "")
                    self._transition(
                        job_id,
                        status="success",
                        progress=100,
                        phase="completed",
                        message="回测完成，结果证据已封存",
                        backtest_run_id=run_id,
                        terminal=True,
                    )
                    self.guest_access.finish_backtest(
                        usage_id, success=True, run_id=run_id
                    )
            except BacktestCancelled as exc:
                latest = self._row(
                    "SELECT progress FROM backtest_jobs WHERE job_id = %s",
                    (job_id,),
                )
                self._transition(
                    job_id,
                    status="cancelled",
                    progress=float((latest or {}).get("progress") or 0),
                    phase="cancelled",
                    message=str(exc),
                    terminal=True,
                    level="warning",
                )
                self.guest_access.finish_backtest(
                    usage_id, success=False, failure_reason=str(exc)
                )
            except Exception as exc:
                self._transition(
                    job_id,
                    status="failed",
                    progress=100,
                    phase="failed",
                    message="回测执行失败",
                    error_message=str(exc)[:1000],
                    terminal=True,
                    level="error",
                )
                self.guest_access.finish_backtest(
                    usage_id, success=False, failure_reason=str(exc)[:1000]
                )
            finally:
                with self._active_lock:
                    self._active.pop(job_id, None)

    def _transition(
        self,
        job_id: str,
        *,
        status: str,
        progress: float,
        phase: str,
        message: str,
        error_message: str | None = None,
        backtest_run_id: str | None = None,
        result_payload: Mapping[str, Any] | None = None,
        started: bool = False,
        terminal: bool = False,
        level: str = "info",
    ) -> None:
        with self.database.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE backtest_jobs
                    SET status = %s,
                        progress = %s,
                        phase = %s,
                        message = %s,
                        error_message = %s,
                        backtest_run_id = COALESCE(%s, backtest_run_id),
                        result_payload = COALESCE(%s, result_payload),
                        started_at = CASE WHEN %s THEN COALESCE(started_at, NOW()) ELSE started_at END,
                        finished_at = CASE WHEN %s THEN NOW() ELSE finished_at END,
                        updated_at = NOW()
                    WHERE job_id = %s
                    """,
                    (
                        status,
                        max(0, min(float(progress), 100)),
                        phase,
                        message,
                        error_message,
                        backtest_run_id,
                        psycopg2.extras.Json(dict(result_payload)) if result_payload is not None else None,
                        started,
                        terminal,
                        job_id,
                    ),
                )
                self._log_cursor(
                    cursor,
                    job_id,
                    level,
                    phase,
                    message if not error_message else f"{message}: {error_message}",
                    {"progress": progress, "status": status},
                )
            conn.commit()

    def _cancel_requested(self, job_id: str) -> bool:
        row = self._row(
            "SELECT status, cancel_requested_at FROM backtest_jobs WHERE job_id = %s",
            (job_id,),
        )
        return bool(
            row
            and (
                row.get("cancel_requested_at") is not None
                or row.get("status") in {"cancelling", "cancelled"}
            )
        )

    @staticmethod
    def _ensure_access(
        row: Mapping[str, Any], principal: Mapping[str, Any]
    ) -> None:
        if principal.get("role") != "guest":
            return
        if str(row.get("owner_session_id") or "") != str(
            principal.get("session_id") or ""
        ):
            raise BacktestJobError("访客只能查看或管理自己创建的回测任务", 403)

    @staticmethod
    def _log_cursor(
        cursor,
        job_id: str,
        level: str,
        phase: str,
        message: str,
        payload: Mapping[str, Any],
    ) -> None:
        cursor.execute(
            """
            INSERT INTO backtest_job_logs(job_id, level, phase, message, payload)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (job_id, level, phase, message, psycopg2.extras.Json(dict(payload))),
        )

    def _row(self, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        rows = self._rows(query, params)
        return rows[0] if rows else None

    def _rows(
        self, query: str, params: tuple[Any, ...]
    ) -> list[dict[str, Any]]:
        with self.database.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [self._serialize(dict(row)) for row in cursor.fetchall()]

    @staticmethod
    def _serialize(row: dict[str, Any]) -> dict[str, Any]:
        for key, value in list(row.items()):
            if hasattr(value, "isoformat"):
                row[key] = value.isoformat()
        return row
