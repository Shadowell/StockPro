from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://stockpro:stockpro@127.0.0.1:55432/stockpro_bitpro_rebase_dev",
)

from app.api.v2.endpoints import arc
from app.core.config import settings
from app.core.errors import register_exception_handlers


def _client() -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def admin_session(request: Request, call_next):
        request.state.auth = {"role": "admin", "session_id": "test-admin"}
        return await call_next(request)

    app.include_router(arc.router, prefix="/api/v2/arc")
    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False)


def test_unconfigured_arc_is_an_explicit_zero_write_a_share_boundary(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HYPERTRADE_BASE_URL", "", raising=False)
    monkeypatch.setattr(settings, "HYPERTRADE_API_BASE", None, raising=False)
    monkeypatch.setattr(settings, "HYPERTRADE_SERVICE_TOKEN", "", raising=False)
    monkeypatch.setattr(settings, "HYPERTRADE_APPROVAL_SIGNING_SECRET", "", raising=False)
    client = _client()

    config = client.get("/api/v2/arc/config")
    assert config.status_code == 200
    payload = config.json()["data"]
    assert payload["configured"] is False
    assert payload["write_enabled"] is False
    assert payload["paper_mutation"] is False
    assert payload["supported_timeframes"] == ["1D"]
    assert "T+1" in payload["market_rules"]

    missions = client.get("/api/v2/arc/missions").json()["data"]
    assert missions["missions"] == []
    assert missions["data_status"] == "unavailable"

    rejected = client.post(
        "/api/v2/arc/missions",
        json={"objective": "A 股日线趋势", "symbol": "600519.SH", "timeframe": "1D"},
    )
    assert rejected.status_code == 503
    assert rejected.json()["error"]["code"] == "HYPERTRADE_UNAVAILABLE"


def test_arc_rejects_digital_asset_symbols_before_any_upstream_call(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HYPERTRADE_BASE_URL", "https://hypertrade.internal", raising=False)
    monkeypatch.setattr(settings, "HYPERTRADE_SERVICE_TOKEN", "test-token", raising=False)
    response = _client().post(
        "/api/v2/arc/missions",
        json={"objective": "invalid", "symbol": "ETH-USDT-SWAP", "timeframe": "1H"},
    )
    assert response.status_code == 422
