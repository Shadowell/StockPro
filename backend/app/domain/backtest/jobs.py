"""Persistent asynchronous lifecycle for BitPro-compatible backtest jobs."""
from __future__ import annotations

import threading
import time
from typing import Any, Protocol


TERMINAL_STATUSES = {"success", "failed", "cancelled", "interrupted"}
RESUMABLE_STATUSES = {"failed", "cancelled", "interrupted"}


class BacktestCancelled(RuntimeError):
    pass


class JobRepository(Protocol):
    def create(self, payload: dict, *, parent_job_id: str | None = None, attempt: int = 1, owner: dict | None = None) -> dict: ...
    def get(self, job_id: str) -> dict | None: ...
    def list(self, **filters: Any) -> list[dict]: ...
    def transition(self, job_id: str, **patch: Any) -> dict: ...
    def cancel_requested(self, job_id: str) -> bool: ...


class BacktestExecutor(Protocol):
    def execute(self, payload: dict, *, progress_hook, cancel_check) -> dict: ...


class BacktestJobService:
    def __init__(self, repository: JobRepository, executor: BacktestExecutor, *, max_workers: int = 2, auto_start: bool = True) -> None:
        self.repository = repository
        self.executor = executor
        self.auto_start = auto_start
        self._slots = threading.BoundedSemaphore(max(1, int(max_workers)))
        self._active: dict[str, threading.Thread] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def _is_active(self, job_id: str) -> bool:
        with self._lock:
            thread = self._active.get(str(job_id))
            return bool(thread and thread.is_alive())

    def _public(self, row: dict) -> dict:
        payload = dict(row)
        raw_status = str(payload.get("status") or "")
        if self.auto_start and raw_status in {"pending", "running", "cancelling"} and not self._is_active(str(payload.get("job_id") or "")):
            payload["status"] = "interrupted"
            payload["phase"] = "interrupted"
            payload["message"] = "后端进程已重启，原任务可恢复为新尝试"
        request = dict(payload.get("request_payload") or {})
        payload["strategy_id"] = request.get("strategy_id")
        payload["current_bar"] = int(payload.get("current_bar") or 0)
        payload["total_bars"] = int(payload.get("total_bars") or 0)
        payload["percent"] = float(payload.get("progress") or 0)
        payload["request"] = request
        payload["result"] = dict(payload.get("result_payload") or {}) or None
        payload["resumable"] = str(payload.get("status")) in RESUMABLE_STATUSES
        return payload

    def create_job(self, payload: dict, *, owner: dict | None = None, parent_job_id: str | None = None, attempt: int = 1) -> dict:
        row = self.repository.create(payload, parent_job_id=parent_job_id, attempt=attempt, owner=owner or {"role": "admin"})
        with self._lock:
            self._cancel_events[str(row["job_id"])] = threading.Event()
        if self.auto_start:
            self.start(str(row["job_id"]))
        return self._public(row)

    def start(self, job_id: str) -> None:
        with self._lock:
            current = self._active.get(job_id)
            if current and current.is_alive():
                return
            thread = threading.Thread(target=self.run_job, args=(job_id,), name=f"stockpro-backtest-{job_id[:8]}", daemon=True)
            self._active[job_id] = thread
            thread.start()

    def run_job(self, job_id: str) -> dict:
        with self._slots:
            current = self.repository.get(job_id)
            if not current:
                raise ValueError("回测任务不存在")
            if current["status"] == "cancelled":
                return self._public(current)
            with self._lock:
                cancel_event = self._cancel_events.setdefault(job_id, threading.Event())
            if self.repository.cancel_requested(job_id):
                cancel_event.set()
            self.repository.transition(job_id, status="running", progress=2.0, phase="validating", message="正在校验 sealed A 股证据", error_message=None)

            def cancelled() -> bool:
                return cancel_event.is_set()

            last_progress = 2.0
            last_phase = "validating"
            last_write_at = time.monotonic()

            def progress(value: float, phase: str, message: str) -> None:
                nonlocal last_progress, last_phase, last_write_at
                if cancelled():
                    raise BacktestCancelled("用户已停止回测")
                normalized = max(2.0, min(float(value), 99.0))
                now = time.monotonic()
                if phase == last_phase and normalized - last_progress < 5.0 and now - last_write_at < 5.0:
                    return
                self.repository.transition(job_id, status="running", progress=normalized, phase=phase, message=message)
                last_progress, last_phase, last_write_at = normalized, phase, now

            try:
                if cancelled():
                    raise BacktestCancelled("任务在执行前已取消")
                result = self.executor.execute(dict(current["request_payload"]), progress_hook=progress, cancel_check=cancelled)
                row = self.repository.transition(
                    job_id,
                    status="success",
                    progress=100.0,
                    phase="completed",
                    message="回测完成并已封存结果",
                    error_message=None,
                    backtest_run_id=result.get("run_id"),
                    result_payload={"result_id": result.get("result_id"), **dict(result.get("summary") or {})},
                )
            except BacktestCancelled as exc:
                row = self.repository.transition(job_id, status="cancelled", phase="cancelled", message=str(exc), error_message=None)
            except Exception as exc:
                row = self.repository.transition(job_id, status="failed", progress=100.0, phase="failed", message="回测失败", error_message=str(exc)[:2000])
            finally:
                with self._lock:
                    self._active.pop(job_id, None)
                    self._cancel_events.pop(job_id, None)
            return self._public(row)

    def get(self, job_id: str) -> dict:
        row = self.repository.get(job_id)
        if not row:
            raise ValueError("回测任务不存在")
        return self._public(row)

    def list(self, **filters: Any) -> list[dict]:
        return [self._public(row) for row in self.repository.list(**filters)]

    def cancel(self, job_id: str) -> dict:
        row = self.repository.get(job_id)
        if not row:
            raise ValueError("回测任务不存在")
        status = str(row["status"])
        if status in TERMINAL_STATUSES:
            return self._public(row)
        if self.auto_start and status in {"pending", "running", "cancelling"} and not self._is_active(job_id):
            return self._public(self.repository.transition(job_id, status="cancelled", progress=100.0, phase="cancelled", message="后端重启后的遗留任务已取消"))
        with self._lock:
            self._cancel_events.setdefault(job_id, threading.Event()).set()
        if status == "pending":
            result = self._public(self.repository.transition(job_id, status="cancelled", progress=100.0, phase="cancelled", message="任务已在执行前取消"))
            with self._lock:
                self._cancel_events.pop(job_id, None)
            return result
        return self._public(self.repository.transition(job_id, status="cancelling", phase="cancelling", message="用户请求停止，正在安全结束"))

    def resume(self, job_id: str, *, owner: dict | None = None) -> dict:
        row = self.repository.get(job_id)
        if not row:
            raise ValueError("回测任务不存在")
        row_status = str(row["status"])
        stale_active = self.auto_start and row_status in {"pending", "running", "cancelling"} and not self._is_active(job_id)
        if stale_active:
            row = self.repository.transition(job_id, status="interrupted", progress=100.0, phase="interrupted", message="后端进程重启，任务已中断")
            row_status = "interrupted"
        if row_status not in RESUMABLE_STATUSES:
            raise ValueError(f"当前状态不可恢复：{row['status']}")
        return self.create_job(
            dict(row["request_payload"]),
            owner=owner or {"role": row.get("owner_role") or "admin"},
            parent_job_id=str(row["job_id"]),
            attempt=int(row.get("attempt") or 1) + 1,
        )
