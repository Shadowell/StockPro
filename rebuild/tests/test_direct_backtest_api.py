from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient
from fastapi import HTTPException
import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.main import create_app  # noqa: E402
from app.api.v2.endpoints import backtest as endpoint  # noqa: E402


class FakeJobs:
    def __init__(self): self.created = []
    def create_job(self, payload, *, owner):
        self.created.append((dict(payload), dict(owner)))
        return {"job_id": f"job-{len(self.created)}", "status": "pending"}
    def create_jobs(self, payloads, *, owner):
        return [self.create_job(payload, owner=owner) for payload in payloads]
    def get(self, job_id): return {"job_id": job_id, "status": "running", "result": None}
    def list(self, **filters): return [{"job_id": "job-1", "status": "running", "result": None}]
    def cancel(self, job_id): return {"job_id": job_id, "status": "cancelling", "result": None}
    def resume(self, job_id, *, owner): return {"job_id": "job-2", "parent_job_id": job_id, "attempt": 2, "status": "pending"}


class FakePaperRepository:
    def list_instances(self):
        return [
            {"id": 1, "status": "running", "strategy_id": 224, "strategy_name": "A 股动量", "validation_status": "valid"},
            {"id": 2, "status": "running", "strategy_id": 224, "strategy_name": "A 股动量副本", "validation_status": "valid"},
            {"id": 3, "status": "paused", "strategy_id": 225, "strategy_name": "暂停策略", "validation_status": "valid"},
        ]


class FakeInputGateway:
    def list_configurations(self, limit=100):
        return [{"dataset_snapshot_id": 10, "pool_snapshot_id": 20, "start_date": "2025-08-04", "end_date": "2025-12-31"}]


VALID = {
    "strategy_id": 224,
    "exchange": "SSE",
    "timeframe_mode": "single",
    "timeframe": "1d",
    "start_date": "2023-01-03",
    "end_date": "2025-01-02",
    "initial_capital": 1_000_000,
    "maker_fee_bps": 3,
    "taker_fee_bps": 8,
    "slippage_bps": 10,
}


def test_bitpro_async_backtest_routes_keep_original_frontend_contract(monkeypatch):
    monkeypatch.setattr(endpoint, "backtest_job_service", FakeJobs())
    client = TestClient(create_app())
    created = client.post("/api/v2/backtest/run_job", json=VALID)
    current = client.get("/api/v2/backtest/job/job-1")
    jobs = client.get("/api/v2/backtest/jobs")
    cancelled = client.post("/api/v2/backtest/job/job-1/cancel")
    resumed = client.post("/api/v2/backtest/job/job-1/resume")
    assert created.status_code == 202 and created.json()["data"]["job_id"] == "job-1"
    assert current.json()["data"]["status"] == "running"
    assert jobs.json()["data"][0]["job_id"] == "job-1"
    assert cancelled.json()["data"]["status"] == "cancelling"
    assert resumed.status_code == 202 and resumed.json()["data"]["attempt"] == 2


def test_backtest_api_rejects_non_daily_or_crypto_requests(monkeypatch):
    monkeypatch.setattr(endpoint, "backtest_job_service", FakeJobs())
    client = TestClient(create_app())
    wrong_timeframe = client.post("/api/v2/backtest/run_job", json={**VALID, "timeframe": "1h"})
    wrong_exchange = client.post("/api/v2/backtest/run_job", json={**VALID, "exchange": "okx"})
    assert wrong_timeframe.status_code == 422
    assert wrong_exchange.status_code == 422


def test_batch_backtest_uses_running_paper_strategies_and_sealed_configuration(monkeypatch):
    jobs = FakeJobs()
    monkeypatch.setattr(endpoint, "backtest_job_service", jobs)
    monkeypatch.setattr(endpoint, "paper_repository", FakePaperRepository())
    monkeypatch.setattr(endpoint, "backtest_input_gateway", FakeInputGateway())
    client = TestClient(create_app())
    response = client.post("/api/v2/backtest/run_running_strategies", json={
        "start_date": "2025-08-04", "end_date": "2025-12-31", "initial_capital": 1_000_000,
        "dataset_snapshot_id": 10, "pool_snapshot_id": 20,
    })
    assert response.status_code == 202
    payload = response.json()["data"]
    assert payload["count"] == 1 and payload["skipped_count"] == 1
    assert payload["jobs"][0]["strategy_id"] == 224
    assert jobs.created[0][0]["exchange"] == "CN"
    assert jobs.created[0][0]["dataset_snapshot_id"] == 10
    assert jobs.created[0][0]["pool_snapshot_id"] == 20


def test_batch_backtest_rejects_invalid_or_unsealed_date_ranges(monkeypatch):
    monkeypatch.setattr(endpoint, "backtest_job_service", FakeJobs())
    monkeypatch.setattr(endpoint, "paper_repository", FakePaperRepository())
    monkeypatch.setattr(endpoint, "backtest_input_gateway", FakeInputGateway())
    client = TestClient(create_app())
    invalid = client.post("/api/v2/backtest/run_running_strategies", json={"start_date": "not-a-date"})
    uncovered = client.post("/api/v2/backtest/run_running_strategies", json={"start_date": "2024-01-01", "end_date": "2024-12-31"})
    assert invalid.status_code == 400
    assert uncovered.status_code == 400


def test_batch_backtest_is_admin_only_when_auth_is_enabled(monkeypatch):
    monkeypatch.setattr(endpoint.settings, "BITPRO_AUTH_ENABLED", True)
    request = SimpleNamespace(state=SimpleNamespace(auth={"role": "guest", "auth_method": "session"}))
    with pytest.raises(HTTPException, match="批量回测仅允许管理员执行") as exc:
        endpoint._batch_owner(request)
    assert exc.value.status_code == 403
