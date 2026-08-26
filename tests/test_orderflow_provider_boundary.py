from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import orderflow  # noqa: E402


def test_orderflow_stream_status_declares_provider_contract() -> None:
    app = FastAPI()
    app.include_router(orderflow.router, prefix="/api/v2/orderflow")

    response = TestClient(app).get("/api/v2/orderflow/stream-status")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["enabled"] is False
    assert payload["connected"] is False
    assert payload["permission_state"] == "requires_configuration"
    assert payload["provider_source"] == "A-share Level-2/tick vendor"
    assert payload["frequency"] == "realtime_ticks_or_1m_microstructure"
    assert "trade_ticks" in payload["tables"]


def test_orderflow_frontend_collapses_provider_missing_state() -> None:
    page = (ROOT / "frontend/src/pages/OrderFlow.tsx").read_text(encoding="utf-8")
    client = (ROOT / "frontend/src/api/client.ts").read_text(encoding="utf-8")

    assert "permissionState?: string" in client
    assert "providerSource?: string" in client
    assert "const providerMissing = Boolean(" in page
    assert "streamStatus.permissionState === 'requires_configuration'" in page
    assert "A 股 tick Provider 未配置" in page
    assert "{!providerMissing && (" in page
