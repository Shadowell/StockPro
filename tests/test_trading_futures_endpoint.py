from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.v2.endpoints import trading  # noqa: E402
from app.core.errors import register_exception_handlers  # noqa: E402


def build_client() -> TestClient:
    app = FastAPI()
    app.include_router(trading.router, prefix="/api/v2/trading")
    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False)


def test_futures_order_open_long_maps_to_trading_service(monkeypatch) -> None:
    calls = []

    async def fake_open_long(exchange, symbol, amount, leverage=1, price=None):
        calls.append((exchange, symbol, amount, leverage, price))
        return {"id": "order-1", "side": "buy"}

    monkeypatch.setattr(trading.trading_service, "futures_open_long", fake_open_long)

    client = build_client()
    response = client.post(
        "/api/v2/trading/futures/order",
        json={
            "exchange": "okx",
            "symbol": "BTC/USDT:USDT",
            "side": "long",
            "action": "open",
            "amount": 0.01,
            "leverage": 3,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["order"]["id"] == "order-1"
    assert calls == [("okx", "BTC/USDT:USDT", 0.01, 3, None)]


def test_futures_order_close_short_maps_to_reduce_only_service(monkeypatch) -> None:
    calls = []

    async def fake_close_short(exchange, symbol, amount, price=None):
        calls.append((exchange, symbol, amount, price))
        return {"id": "order-2", "reduceOnly": True}

    monkeypatch.setattr(trading.trading_service, "futures_close_short", fake_close_short)

    client = build_client()
    response = client.post(
        "/api/v2/trading/futures/order",
        json={
            "exchange": "okx",
            "symbol": "ETH/USDT:USDT",
            "side": "short",
            "action": "close",
            "amount": 0.02,
            "leverage": 5,
            "price": 3000,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["order"]["id"] == "order-2"
    assert calls == [("okx", "ETH/USDT:USDT", 0.02, 3000.0)]


def test_futures_order_rejects_unknown_action_side_pair() -> None:
    client = build_client()
    response = client.post(
        "/api/v2/trading/futures/order",
        json={
            "exchange": "okx",
            "symbol": "ETH/USDT:USDT",
            "side": "sideways",
            "action": "open",
            "amount": 0.02,
            "leverage": 5,
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert "side" in body["error"]["message"]
