from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.v2.endpoints import factorlab as factorlab_endpoint  # noqa: E402
from app.db.local_db import LocalDatabase  # noqa: E402
from app.factorlab.research_models import FactorResearchTaskConfig  # noqa: E402
from app.factorlab.research_repository import FactorResearchRepository  # noqa: E402
from app.services.agent.providers.contracts import (  # noqa: E402
    ProviderCapabilities,
)
from app.services.factorlab_service import (  # noqa: E402
    FactorLabService,
    FactorResearchCapacityError,
)


class ImmediateRunner:
    def __init__(self, repository: FactorResearchRepository):
        self.repository = repository

    def run(self, task_id: str):
        task = self.repository.get_task(task_id)
        if task.status == "queued":
            self.repository.transition(task_id, {"queued"}, "running")
        elif task.status == "paused":
            self.repository.transition(task_id, {"paused"}, "running")
        current = self.repository.get_task(task_id)
        if current.status == "running":
            return self.repository.transition(
                task_id,
                {"running"},
                "completed",
                stop_reason="fixture_completed",
            )
        return current


def setup_client(
    tmp_path: Path,
    monkeypatch,
    *,
    capability_resolver=None,
    runner_factory=None,
    max_concurrent_runners: int = 2,
    max_estimated_input_rows: int = 2_000_000,
):
    database = LocalDatabase(str(tmp_path / "factorlab-api.db"))
    database.init_db()
    service = FactorLabService(
        database,
        factor_root=tmp_path / "factors",
        experiment_root=tmp_path / "experiments",
        runner_factory=runner_factory or (
            lambda config: ImmediateRunner(FactorResearchRepository(database))
        ),
        provider_capability_resolver=capability_resolver,
        max_concurrent_runners=max_concurrent_runners,
        max_estimated_input_rows=max_estimated_input_rows,
    )
    service.bootstrap()
    monkeypatch.setattr(factorlab_endpoint, "factorlab_service", service)
    app = FastAPI()
    app.include_router(factorlab_endpoint.router, prefix="/api/v2/factorlab")
    return TestClient(app), service


def two_factor_ids(service: FactorLabService) -> list[str]:
    summary = service.summary()
    by_definition = {row["definition_id"]: row["instance_id"] for row in summary["instances"]}
    return [by_definition["momentum.roc"], by_definition["momentum.rsi"]]


def manual_payload(service: FactorLabService) -> dict:
    roc_id, rsi_id = two_factor_ids(service)
    return {
        "exchange": "okx",
        "market_type": "swap",
        "symbols": ["BTC/USDT:USDT", "ETH/USDT:USDT"],
        "timeframe": "1h",
        "start_ms": 1_700_000_000_000,
        "end_ms": 1_710_000_000_000,
        "mode": "manual",
        "factor_instance_ids": [roc_id, rsi_id],
        "manual_combinations": [
            {
                "hypothesis": "ROC with RSI",
                "expression": {
                    "type": "weighted_sum",
                    "terms": [
                        {"weight": 0.7, "node": {"type": "factor", "instance_id": roc_id}},
                        {"weight": 0.3, "node": {"type": "factor", "instance_id": rsi_id}},
                    ],
                },
            }
        ],
        "horizon_bars": 3,
        "base_cost_bps": 20,
        "stress_cost_bps": 40,
        "n_splits": 5,
        "max_candidates": 10,
        "max_runtime_sec": 60,
        "max_no_improvement": 10,
        "max_combination_leaves": 4,
        "target_accepted_candidates": 1,
    }


def wait_for_status(client: TestClient, task_id: str, expected: str) -> dict:
    for _ in range(100):
        response = client.get(f"/api/v2/factorlab/research/tasks/{task_id}")
        payload = response.json()["data"]
        if payload["status"] == expected:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not reach {expected}")


def test_create_list_detail_and_trials_routes_use_persisted_research_state(tmp_path: Path, monkeypatch) -> None:
    client, service = setup_client(tmp_path, monkeypatch)

    created_response = client.post(
        "/api/v2/factorlab/research/tasks",
        json=manual_payload(service),
    )

    assert created_response.status_code == 200
    created = created_response.json()["data"]
    assert created["task_id"].startswith("frt_")
    assert created["mode"] == "manual"
    assert "provider_snapshot" not in created
    completed = wait_for_status(client, created["task_id"], "completed")
    assert completed["stop_reason"] == "fixture_completed"
    listed = client.get("/api/v2/factorlab/research/tasks").json()["data"]
    assert [row["task_id"] for row in listed] == [created["task_id"]]
    trials = client.get(
        f"/api/v2/factorlab/research/tasks/{created['task_id']}/trials"
    ).json()["data"]
    assert trials == []


def test_pause_and_explicit_resume_use_sqlite_state(tmp_path: Path, monkeypatch) -> None:
    client, service = setup_client(tmp_path, monkeypatch)
    repo = service.research_repository
    task = repo.create_task(FactorResearchTaskConfig.from_dict(manual_payload(service)))
    repo.transition(task.task_id, {"queued"}, "running")

    paused = client.post(
        f"/api/v2/factorlab/research/tasks/{task.task_id}/pause"
    )

    assert paused.status_code == 200
    assert paused.json()["data"]["status"] == "paused"
    assert paused.json()["data"]["stop_reason"] == "operator_paused"

    resumed = client.post(
        f"/api/v2/factorlab/research/tasks/{task.task_id}/resume"
    )
    assert resumed.status_code == 200
    completed = wait_for_status(client, task.task_id, "completed")
    assert completed["stop_reason"] == "fixture_completed"


def test_delete_archives_paused_task_and_active_task_returns_conflict(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, service = setup_client(tmp_path, monkeypatch)
    repo = service.research_repository
    paused = repo.create_task(FactorResearchTaskConfig.from_dict(manual_payload(service)))
    repo.transition(paused.task_id, {"queued"}, "paused", stop_reason="operator_paused")
    active = repo.create_task(FactorResearchTaskConfig.from_dict(manual_payload(service)))

    deleted = client.delete(f"/api/v2/factorlab/research/tasks/{paused.task_id}")
    conflict = client.delete(f"/api/v2/factorlab/research/tasks/{active.task_id}")

    assert deleted.status_code == 200
    assert deleted.json()["data"]["archived_at"] is not None
    listed = client.get("/api/v2/factorlab/research/tasks").json()["data"]
    assert [task["task_id"] for task in listed] == [active.task_id]
    assert conflict.status_code == 409
    assert repo.get_task(active.task_id).archived_at is None


def test_bootstrap_pauses_stale_running_tasks_without_automatic_resume(tmp_path: Path) -> None:
    database = LocalDatabase(str(tmp_path / "factorlab-restart.db"))
    database.init_db()
    service = FactorLabService(database, factor_root=tmp_path / "factors")
    service.bootstrap()
    task = service.research_repository.create_task(
        FactorResearchTaskConfig.from_dict(manual_payload(service))
    )
    service.research_repository.transition(task.task_id, {"queued"}, "running")

    restored_service = FactorLabService(database, factor_root=tmp_path / "factors")
    restored_service.bootstrap()
    restored = restored_service.research_repository.get_task(task.task_id)

    assert restored.status == "paused"
    assert restored.stop_reason == "service_restarted"
    assert restored_service.active_runner_count == 0


def test_auto_task_pins_sanitized_runtime_provider_capabilities(tmp_path: Path, monkeypatch) -> None:
    async def capability_resolver(provider_key: str):
        return ProviderCapabilities(
            provider_key=provider_key,
            display_name="Codex",
            transport_type="codex_cli",
            credential_mode="managed_login",
            credential_source="managed_login",
            models=["gpt-5.6-sol"],
            reasoning_efforts=["high"],
            speed_modes=["standard"],
            supports_structured_output=True,
            configured=True,
            healthy=True,
            command_available=True,
            login_verified=True,
            config_revision="sha256:provider-config",
        )

    client, service = setup_client(
        tmp_path,
        monkeypatch,
        capability_resolver=capability_resolver,
    )
    payload = manual_payload(service)
    payload.update(
        {
            "mode": "auto",
            "manual_combinations": [],
            "provider_key": "codex",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "speed_mode": "standard",
        }
    )

    response = client.post("/api/v2/factorlab/research/tasks", json=payload)

    assert response.status_code == 200
    task_id = response.json()["data"]["task_id"]
    stored = service.research_repository.get_task(task_id)
    assert stored.config.provider_snapshot["provider_key"] == "codex"
    assert stored.config.provider_snapshot["capability_snapshot_hash"].startswith("sha256:")
    assert "token" not in str(stored.config.provider_snapshot).lower()
    assert "provider_snapshot" not in response.json()["data"]


def test_unknown_factor_and_invalid_state_return_controlled_errors(tmp_path: Path, monkeypatch) -> None:
    client, service = setup_client(tmp_path, monkeypatch)
    payload = manual_payload(service)
    payload["factor_instance_ids"] = ["unknown.factor"]

    invalid = client.post("/api/v2/factorlab/research/tasks", json=payload)
    assert invalid.status_code == 400
    assert "unknown.factor" not in invalid.text

    task = service.research_repository.create_task(
        FactorResearchTaskConfig.from_dict(manual_payload(service))
    )
    service.research_repository.transition(task.task_id, {"queued"}, "cancelled")
    resume = client.post(f"/api/v2/factorlab/research/tasks/{task.task_id}/resume")
    assert resume.status_code == 409


def test_unexpected_background_runner_exception_is_consumed_and_persisted(tmp_path: Path, monkeypatch) -> None:
    runner_holder = {}

    class CrashingRunner:
        def run(self, task_id: str):
            repo = runner_holder["repository"]
            repo.transition(task_id, {"queued"}, "running")
            raise RuntimeError("private runner detail")

    client, service = setup_client(
        tmp_path,
        monkeypatch,
        runner_factory=lambda config: CrashingRunner(),
    )
    runner_holder["repository"] = service.research_repository

    response = client.post(
        "/api/v2/factorlab/research/tasks",
        json=manual_payload(service),
    )
    assert response.status_code == 200
    failed = wait_for_status(client, response.json()["data"]["task_id"], "failed")

    assert failed["stop_reason"] == "runner_crashed"
    assert "private runner detail" not in str(failed)


def test_research_runner_capacity_is_bounded_and_returns_429(tmp_path: Path, monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()
    holder = {}

    class BlockingRunner:
        def run(self, task_id: str):
            repo = holder["repository"]
            repo.transition(task_id, {"queued"}, "running")
            started.set()
            release.wait(timeout=5)
            current = repo.get_task(task_id)
            if current.status == "running":
                repo.transition(task_id, {"running"}, "completed", stop_reason="fixture_completed")

    _client, service = setup_client(
        tmp_path,
        monkeypatch,
        runner_factory=lambda config: BlockingRunner(),
        max_concurrent_runners=1,
    )
    holder["repository"] = service.research_repository
    async def scenario():
        first = await service.create_research_task(manual_payload(service))
        assert await asyncio.to_thread(started.wait, 2)
        with pytest.raises(FactorResearchCapacityError):
            await service.create_research_task(manual_payload(service))
        release.set()
        for _ in range(100):
            if service.active_runner_count == 0:
                break
            await asyncio.sleep(0.01)
        return first

    first = asyncio.run(scenario())
    assert first["task_id"].startswith("frt_")
    statuses = [task.status for task in service.research_repository.list_tasks()]
    assert "failed" in statuses

    class CapacityService:
        async def create_research_task(self, payload):
            raise FactorResearchCapacityError("full")

    monkeypatch.setattr(factorlab_endpoint, "factorlab_service", CapacityService())
    app = FastAPI()
    app.include_router(factorlab_endpoint.router, prefix="/api/v2/factorlab")
    response = TestClient(app).post(
        "/api/v2/factorlab/research/tasks",
        json=manual_payload(service),
    )
    assert response.status_code == 429
    assert "容量" in response.text


def test_research_input_row_budget_is_rejected_before_task_creation(tmp_path: Path, monkeypatch) -> None:
    client, service = setup_client(
        tmp_path,
        monkeypatch,
        max_estimated_input_rows=100,
    )
    payload = manual_payload(service)

    response = client.post("/api/v2/factorlab/research/tasks", json=payload)

    assert response.status_code == 400
    assert service.research_repository.list_tasks() == []
