from __future__ import annotations

import sys
import threading
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.domain.backtest.jobs import BacktestJobService, BacktestResultDelivered  # noqa: E402


class MemoryJobRepository:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.transitions: list[tuple[str, str]] = []
        self.lock = threading.Lock()
        self.next_id = 1

    def create(self, payload: dict, *, parent_job_id: str | None = None, attempt: int = 1, owner: dict | None = None) -> dict:
        with self.lock:
            job_id = f"job-{self.next_id}"
            self.next_id += 1
            row = {
                "job_id": job_id,
                "request_payload": payload,
                "result_payload": {},
                "status": "pending",
                "progress": 0,
                "phase": "queued",
                "message": "queued",
                "parent_job_id": parent_job_id,
                "attempt": attempt,
                "owner_role": (owner or {}).get("role", "admin"),
            }
            self.rows[job_id] = row
            return dict(row)

    def create_many(self, payloads: list[dict], *, owner: dict | None = None) -> list[dict]:
        return [self.create(payload, owner=owner) for payload in payloads]

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            row = self.rows.get(job_id)
            return dict(row) if row else None

    def list(self, **_filters):
        with self.lock:
            return [dict(row) for row in self.rows.values()]

    def transition(self, job_id: str, **patch) -> dict:
        with self.lock:
            row = self.rows[job_id]
            row.update(patch)
            if patch.get("result_payload") is not None:
                row["result_payload"] = patch["result_payload"]
            self.transitions.append((job_id, str(row["status"])))
            return dict(row)

    def cancel_requested(self, job_id: str) -> bool:
        return self.rows[job_id]["status"] in {"cancelling", "cancelled"}


class DeliveredThenCleanupTimeoutExecutor:
    def execute(self, payload: dict, *, progress_hook, cancel_check):
        progress_hook(30, "running", "sealed run persisted")
        raise BacktestResultDelivered(
            "worker cleanup timed out after sealed result delivery",
            result={
                "run_id": "11111111-1111-1111-1111-111111111111",
                "result_id": "result-1",
                "summary": {"total_return": 0.12},
            },
        )


def test_delivered_backtest_result_cleanup_timeout_becomes_success_with_evidence() -> None:
    repo = MemoryJobRepository()
    service = BacktestJobService(repo, DeliveredThenCleanupTimeoutExecutor(), auto_start=False)
    job = service.create_job({"strategy_id": 7})

    result = service.run_job(job["job_id"])

    assert result["status"] == "success"
    assert result["phase"] == "completed"
    assert result["backtest_run_id"] == "11111111-1111-1111-1111-111111111111"
    assert result["result"]["result_id"] == "result-1"
    assert result["error_message"] == "worker cleanup timed out after sealed result delivery"


class BlockingExecutor:
    def __init__(self) -> None:
        self.running = 0
        self.max_running = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()

    def execute(self, payload: dict, *, progress_hook, cancel_check):
        with self.lock:
            self.running += 1
            self.max_running = max(self.max_running, self.running)
        self.started.set()
        while not self.release.is_set():
            if cancel_check():
                raise RuntimeError("cancelled")
            time.sleep(0.005)
        with self.lock:
            self.running -= 1
        return {"run_id": f"run-{payload['strategy_id']}", "result_id": f"result-{payload['strategy_id']}", "summary": {}}


def test_backtest_service_does_not_start_same_attempt_twice_and_respects_worker_slots() -> None:
    repo = MemoryJobRepository()
    executor = BlockingExecutor()
    service = BacktestJobService(repo, executor, max_workers=1, auto_start=False)
    first = service.create_job({"strategy_id": 1})
    second = service.create_job({"strategy_id": 2})

    service.start(first["job_id"])
    service.start(first["job_id"])
    service.start(second["job_id"])
    assert executor.started.wait(1)
    time.sleep(0.03)
    assert executor.max_running == 1

    executor.release.set()
    for _ in range(100):
        rows = {row["job_id"]: row["status"] for row in repo.list()}
        if rows[first["job_id"]] == rows[second["job_id"]] == "success":
            break
        time.sleep(0.01)

    assert repo.get(first["job_id"])["status"] == "success"
    assert repo.get(second["job_id"])["status"] == "success"
    assert [item for item in repo.transitions if item[0] == first["job_id"] and item[1] == "running"].count((first["job_id"], "running")) == 1


def test_backtest_public_view_marks_stale_active_job_interrupted_after_restart() -> None:
    repo = MemoryJobRepository()
    service = BacktestJobService(repo, BlockingExecutor(), auto_start=True)
    job = repo.create({"strategy_id": 3})
    repo.transition(job["job_id"], status="running", progress=25, phase="executing", message="running")

    public = service.get(job["job_id"])

    assert public["status"] == "interrupted"
    assert public["resumable"] is True
    assert repo.get(job["job_id"])["status"] == "running"
