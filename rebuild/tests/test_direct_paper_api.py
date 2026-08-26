from __future__ import annotations

from pathlib import Path
import sys

from fastapi.testclient import TestClient


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.main import create_app  # noqa: E402
from app.api.v2.endpoints import live as endpoint  # noqa: E402


class FakePaperService:
    async def list_candidates(self): return [{"strategy_id": 186, "qualifying_backtest_run_id": "run-1"}]
    async def create(self, payload, *, start=True): return {"id": 23, "status": "running" if start else "draft", "name": payload["name"]}
    async def pause(self, instance_id): return {"id": int(instance_id), "status": "paused"}
    async def resume(self, instance_id): return {"id": int(instance_id), "status": "running"}
    async def stop(self, instance_id): return {"id": int(instance_id), "status": "stopped"}


def test_paper_lifecycle_routes_preserve_bitpro_live_contract(monkeypatch):
    monkeypatch.setattr(endpoint, "paper_domain_service", FakePaperService())
    client = TestClient(create_app())
    candidates = client.get("/api/v2/live/candidates")
    created = client.post("/api/v2/live/instances", json={"name": "A 股模拟", "qualifying_backtest_run_id": "run-1", "initial_cash": 1_000_000, "start": True})
    paused = client.post("/api/v2/live/pause", json={"instance_id": 23})
    resumed = client.post("/api/v2/live/resume", json={"instance_id": 23})
    stopped = client.post("/api/v2/live/stop", json={"instance_id": 23, "clear_metrics": False})
    assert candidates.json()["data"][0]["strategy_id"] == 186
    assert created.status_code == 201 and created.json()["data"]["status"] == "running"
    assert paused.json()["data"]["status"] == "paused"
    assert resumed.json()["data"]["status"] == "running"
    assert stopped.json()["data"]["status"] == "stopped"


def test_stop_rejects_any_request_to_clear_paper_history(monkeypatch):
    monkeypatch.setattr(endpoint, "paper_domain_service", FakePaperService())
    response = TestClient(create_app()).post("/api/v2/live/stop", json={"instance_id": 23, "clear_metrics": True})
    assert response.status_code == 422
    assert "禁止清空" in response.json()["detail"]
