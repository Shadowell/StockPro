from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import live  # noqa: E402
from app.core.errors import register_exception_handlers  # noqa: E402


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(live.router, prefix="/api/v2/live")
    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False)


def test_watch_market_returns_empty_state_when_no_paper_account(monkeypatch) -> None:
    class Service:
        async def watch_market(self, account_id, symbol, timeframe, limit):
            raise ValueError("没有可用 A 股 Paper 账户")

    monkeypatch.setattr(live, "paper_domain_service", Service())

    response = _client().get("/api/v2/live/watchlist/market?symbol=600519.SH&timeframe=1d")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["data_status"] == "unavailable"
    assert payload["klines"] == []
    assert payload["positions"] == []
    assert payload["message"] == "没有可用 A 股 Paper 账户"


def test_watch_markers_returns_empty_state_when_no_paper_account(monkeypatch) -> None:
    class Service:
        async def trade_markers(self, account_id, symbol, limit):
            raise ValueError("没有可用 A 股 Paper 账户")

    monkeypatch.setattr(live, "paper_domain_service", Service())

    response = _client().get("/api/v2/live/watchlist/markers?symbol=600519.SH")

    assert response.status_code == 200
    assert response.json()["data"]["markers"] == []


def test_watch_derivatives_data_is_registered_for_a_share_not_applicable_state() -> None:
    response = _client().get("/api/v2/live/watchlist/derivatives-data?symbol=600519.SH")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["exchange"] == "CN"
    assert payload["open_interest"]["points"] is None
    assert payload["funding_rate"]["status"] == "not_applicable"
