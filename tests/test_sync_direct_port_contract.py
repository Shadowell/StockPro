from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import sync as sync_endpoint  # noqa: E402
from app.core.errors import register_exception_handlers  # noqa: E402


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(sync_endpoint.router, prefix="/api/v2/sync")
    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False)


def test_sync_frontend_read_routes_are_registered(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Service:
        def status(self, *, include_items: bool = False):
            captured["status_include_items"] = include_items
            return {"is_running": False, "summary": {"total_records": 0}, "details": []}

        def assets(self):
            return {"assets": [], "total_records": 0, "total_pairs": 0, "total_items": 0}

        def data(self, *, exchange=None):
            captured["data_exchange"] = exchange
            return []

        def table_stats(self):
            return {"tables": [], "total_records": 0, "total_pairs": 0, "market_stats": {}}

        def quality(self, *, exchange, symbols, timeframes, max_items):
            captured["quality"] = (exchange, symbols, timeframes, max_items)
            return {
                "checked_at": "2026-08-27T00:00:00Z",
                "summary": {
                    "checked": 2,
                    "ok": 1,
                    "error": 1,
                    "missing": 0,
                    "issue_count": 1,
                    "truncated": False,
                    "max_items": max_items,
                },
                "items": [],
            }

        def jobs(self, *, limit: int = 20, include_items: bool = False):
            captured["jobs"] = (limit, include_items)
            return {"jobs": []}

    monkeypatch.setattr(sync_endpoint, "sync_domain_service", Service())
    client = _client()

    assert client.get("/api/v2/sync/status").status_code == 200
    assert client.get("/api/v2/sync/assets").status_code == 200
    assert client.get("/api/v2/sync/data?exchange=CN").status_code == 200
    assert client.get("/api/v2/sync/table-stats").status_code == 200
    assert client.get("/api/v2/sync/jobs?limit=5&include_items=true").status_code == 200
    quality = client.get(
        "/api/v2/sync/quality?exchange=CN&symbols=600519.SH,000001.SZ&timeframes=1d&max_items=8"
    )

    assert quality.status_code == 200
    assert captured["status_include_items"] is False
    assert captured["data_exchange"] == "CN"
    assert captured["jobs"] == (5, True)
    assert captured["quality"] == ("CN", ["600519.SH", "000001.SZ"], ["1d"], 8)
