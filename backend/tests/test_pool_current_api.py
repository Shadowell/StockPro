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


class FakePoolRepository:
    def __init__(self) -> None:
        self.generation_id = "11111111-1111-1111-1111-111111111111"
        self.pool_id = "22222222-2222-2222-2222-222222222222"

    def list_pools(self):
        return [{"id": self.pool_id, "name": "质量股票池", "pool_type": "screener", "status": "active", "snapshot_count": 0, "current_member_count": 0}]

    def get_pool(self, pool_id: str):
        return {"id": pool_id, "name": "质量股票池", "pool_type": "screener", "status": "active", "rule_version": 1, "config": {}}

    def create_pool(self, payload):
        return {**self.get_pool(self.pool_id), "rule": {"rule_version": 1, "content_hash": "rule-hash"}}

    def generate(self, pool_id: str, payload):
        return {"id": self.generation_id, "pool_id": pool_id, "status": "success", "members": [], "member_count": 0}

    def members(self, pool_id: str, generation_id: str | None = None):
        return []

    def seal_snapshot(self, pool_id: str, generation_id: str | None = None):
        assert generation_id == self.generation_id
        return {"id": 9, "pool_id": pool_id, "generation_id": generation_id, "status": "sealed", "manifest_hash": "snapshot-hash", "member_count": 0}

    def list_snapshots(self, pool_id: str | None = None):
        return []

    def get_snapshot(self, snapshot_id: int):
        return {"id": snapshot_id, "status": "sealed", "manifest_hash": "snapshot-hash", "members": []}


def _client() -> TestClient:
    pools = FakePoolRepository()
    inert = SimpleNamespace()
    context = SimpleNamespace(
        settings=SimpleNamespace(AUTH_ENABLED=False, ADMIN_USERNAME="admin", BACKEND_CORS_ORIGINS=["http://localhost:4444"]),
        repositories=SimpleNamespace(health=inert, auth=inert, market=inert, pools=pools),
        clock=lambda: datetime.now(timezone.utc),
    )
    return TestClient(create_app(context))


def test_pool_snapshot_never_copies_unsealed_members() -> None:
    client = _client()
    created = client.post("/api/pools", json={"name": "质量股票池", "pool_type": "screener", "config": {}}).json()
    generated = client.post(f"/api/pools/{created['id']}/generate", json={"trade_date": "2026-08-21"}).json()
    sealed = client.post(f"/api/pools/{created['id']}/snapshots", json={"generation_id": generated["id"]}).json()

    assert generated["status"] == "success"
    assert sealed["status"] == "sealed"
    assert sealed["manifest_hash"]


def test_pool_reads_use_current_paths() -> None:
    client = _client()

    assert client.get("/api/pools").status_code == 200
    assert client.get("/api/pool-snapshots").status_code == 200
    assert client.get("/api/v2/pools").status_code == 404
