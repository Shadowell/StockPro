from __future__ import annotations

from pathlib import Path
import sys

from fastapi.testclient import TestClient


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.main import create_app  # noqa: E402
from app.api.v2.endpoints import backtest as endpoint  # noqa: E402


class FakeJobs:
    def create_job(self, payload, *, owner): return {"job_id": "job-1", "status": "pending"}
    def get(self, job_id): return {"job_id": job_id, "status": "running", "result": None}
    def list(self, **filters): return [{"job_id": "job-1", "status": "running", "result": None}]
    def cancel(self, job_id): return {"job_id": job_id, "status": "cancelling", "result": None}
    def resume(self, job_id, *, owner): return {"job_id": "job-2", "parent_job_id": job_id, "attempt": 2, "status": "pending"}


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
