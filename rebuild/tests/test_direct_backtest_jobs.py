from __future__ import annotations

from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.backtest.jobs import BacktestJobService  # noqa: E402
from app.domain.backtest.job_repository import PostgresBacktestJobRepository  # noqa: E402


class MemoryJobRepository:
    def __init__(self):
        self.rows = {}
        self.next_id = 0
        self.transition_count = 0
        self.cancel_check_count = 0

    def create(self, payload, *, parent_job_id=None, attempt=1, owner=None):
        self.next_id += 1
        job_id = f"job-{self.next_id}"
        row = {"job_id": job_id, "request_payload": dict(payload), "status": "pending", "progress": 0.0, "phase": "queued", "message": "queued", "error_message": None, "backtest_run_id": None, "result_payload": {}, "parent_job_id": parent_job_id, "attempt": attempt, "owner_role": (owner or {}).get("role", "admin")}
        self.rows[job_id] = row
        return dict(row)

    def create_many(self, payloads, *, owner=None):
        return [self.create(payload, owner=owner) for payload in payloads]

    def get(self, job_id): return dict(self.rows[job_id]) if job_id in self.rows else None
    def list(self, **_): return [dict(row) for row in self.rows.values()]
    def transition(self, job_id, **patch): self.transition_count += 1; self.rows[job_id].update(patch); return dict(self.rows[job_id])
    def cancel_requested(self, job_id): self.cancel_check_count += 1; return self.rows[job_id]["status"] in {"cancelling", "cancelled"}


class SuccessfulExecutor:
    def execute(self, payload, *, progress_hook, cancel_check):
        assert payload["strategy_id"] == 224
        assert cancel_check() is False
        progress_hook(15, "resolving", "sealed inputs")
        progress_hook(70, "executing", "A-share engine")
        return {"run_id": "run-uuid", "result_id": 123, "summary": {"status": "completed"}}


class FailedExecutor:
    def execute(self, payload, *, progress_hook, cancel_check):
        raise ValueError("sealed snapshot missing")


class NoisyExecutor:
    def execute(self, payload, *, progress_hook, cancel_check):
        for current in range(1001):
            progress_hook(35 + current * 0.045, "engine", f"day {current}")
        return {"run_id": "run-uuid", "result_id": 123, "summary": {"status": "completed"}}


def test_job_moves_pending_running_success_with_persisted_result():
    repository = MemoryJobRepository()
    service = BacktestJobService(repository, SuccessfulExecutor(), auto_start=False)
    created = service.create_job({"strategy_id": 224}, owner={"role": "admin"})
    assert created["status"] == "pending"
    completed = service.run_job(created["job_id"])
    assert completed["status"] == "success"
    assert completed["progress"] == 100
    assert completed["backtest_run_id"] == "run-uuid"
    assert completed["result_payload"]["result_id"] == 123
    assert completed["resumable"] is False


def test_pending_job_can_cancel_without_running_executor():
    repository = MemoryJobRepository()
    service = BacktestJobService(repository, SuccessfulExecutor(), auto_start=False)
    created = service.create_job({"strategy_id": 224})
    cancelled = service.cancel(created["job_id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["resumable"] is True


def test_failed_or_cancelled_job_resumes_as_new_attempt():
    repository = MemoryJobRepository()
    service = BacktestJobService(repository, FailedExecutor(), auto_start=False)
    first = service.create_job({"strategy_id": 224})
    failed = service.run_job(first["job_id"])
    assert failed["status"] == "failed"
    assert failed["error_message"] == "sealed snapshot missing"
    retried = service.resume(first["job_id"])
    assert retried["job_id"] != first["job_id"]
    assert retried["parent_job_id"] == first["job_id"]
    assert retried["attempt"] == 2
    assert retried["status"] == "pending"


def test_job_repository_is_postgres_only_and_has_no_startup_mutation():
    source = (BACKEND_ROOT / "app/domain/backtest/job_repository.py").read_text()
    assert "sqlite" not in source.lower()
    assert "def create(" in source
    assert "def transition(" in source
    assert "def recover" not in source
    assert PostgresBacktestJobRepository.__name__ == "PostgresBacktestJobRepository"


def test_progress_updates_are_throttled_before_postgres_writes():
    repository = MemoryJobRepository()
    service = BacktestJobService(repository, NoisyExecutor(), auto_start=False)
    created = service.create_job({"strategy_id": 224})
    service.run_job(created["job_id"])
    assert repository.transition_count <= 15
    assert repository.cancel_check_count <= 2


def test_jobs_left_active_by_process_restart_are_read_as_interrupted_and_resumable():
    repository = MemoryJobRepository()
    first_process = BacktestJobService(repository, SuccessfulExecutor(), auto_start=False)
    created = first_process.create_job({"strategy_id": 224})
    repository.transition(created["job_id"], status="running", phase="engine", progress=50)
    restarted_process = BacktestJobService(repository, SuccessfulExecutor(), auto_start=True)
    observed = restarted_process.get(created["job_id"])
    assert observed["status"] == "interrupted"
    assert observed["resumable"] is True
    resumed = restarted_process.resume(created["job_id"])
    assert resumed["parent_job_id"] == created["job_id"]
    assert resumed["attempt"] == 2


def test_batch_jobs_are_persisted_before_workers_start():
    repository = MemoryJobRepository()
    service = BacktestJobService(repository, SuccessfulExecutor(), auto_start=False)
    created = service.create_jobs([{"strategy_id": 224}, {"strategy_id": 225}], owner={"role": "admin"})
    assert [row["status"] for row in created] == ["pending", "pending"]
    assert len(repository.rows) == 2
