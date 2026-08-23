from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import create_app


class FakeFactorRepository:
    def __init__(self) -> None:
        self.executed_writes: list[str] = []

    def list_library(self):
        return [{"id": 1, "factor_code": "momentum_20d", "factor_name": "20日动量", "category": "momentum", "research_status": "exploratory", "validation_status": "valid", "version_no": 1}]

    def factor_metrics(self, factor_identifier: str):
        return {"factor": self.list_library()[0], "metrics": [{"metric_code": "coverage", "metric_value": 0.96, "pending_reason": None}, {"metric_code": "rank_ic", "metric_value": None, "pending_reason": "等待未来收益成熟"}]}

    def factor_values(self, factor_identifier: str, limit: int, offset: int): return {"items": []}
    def list_runs(self, limit: int): return []
    def list_correlations(self, trade_date: str | None, limit: int): return []
    def list_snapshots(self, limit: int): return []
    def get_snapshot(self, snapshot_id: int): return None
    def snapshot_values(self, snapshot_id: int, factor_code: str | None, limit: int): return {"items": []}


def _client(repository: FakeFactorRepository) -> TestClient:
    inert = SimpleNamespace()
    context = SimpleNamespace(
        settings=SimpleNamespace(AUTH_ENABLED=False, ADMIN_USERNAME="admin", BACKEND_CORS_ORIGINS=["http://localhost:4444"]),
        repositories=SimpleNamespace(health=inert, auth=inert, factors=repository),
        clock=lambda: datetime.now(timezone.utc),
    )
    return TestClient(create_app(context))


def test_factor_metrics_keep_pending_values_null() -> None:
    repository = FakeFactorRepository()

    payload = _client(repository).get("/api/factors/momentum_20d/metrics").json()

    pending = next(item for item in payload["items"] if item["metric_code"] == "rank_ic")
    assert pending["metric_value"] is None
    assert pending["pending_reason"] == "等待未来收益成熟"
    assert repository.executed_writes == []


def test_factor_library_uses_current_paths() -> None:
    client = _client(FakeFactorRepository())

    assert client.get("/api/factors").status_code == 200
    assert client.get("/api/factor-runs").status_code == 200
    assert client.get("/api/factor-snapshots").status_code == 200
    assert client.get("/api/v2/factors").status_code == 404
