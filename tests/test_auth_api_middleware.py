from __future__ import annotations

from http.cookies import SimpleCookie
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.v2.endpoints import auth as auth_endpoint  # noqa: E402
from app.core.auth_middleware import AuthMiddleware  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.contracts import ok  # noqa: E402
from app.core.errors import register_exception_handlers  # noqa: E402
from app.db.local_db import LocalDatabase  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402


def build_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, AuthService]:
    database = LocalDatabase(str(tmp_path / "auth-api.db"))
    database.init_db()
    service = AuthService(db=database)
    password_hash = service.hash_password("admin-pass")

    monkeypatch.setattr(settings, "BITPRO_AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BITPRO_ADMIN_USERNAME", "admin", raising=False)
    monkeypatch.setattr(settings, "BITPRO_ADMIN_PASSWORD_HASH", password_hash, raising=False)
    monkeypatch.setattr(settings, "BITPRO_AUTH_COOKIE_SECURE", False, raising=False)
    monkeypatch.setattr(auth_endpoint, "auth_service", service)

    app = FastAPI()
    app.add_middleware(AuthMiddleware, auth_service=service)
    app.include_router(auth_endpoint.router, prefix="/api/v2/auth")

    @app.get("/api/v2/market/ping")
    async def market_ping():
        return ok({"pong": True})

    @app.post("/api/v2/settings/ping")
    async def settings_ping():
        return ok({"saved": True})

    @app.get("/api/v2/live/accounts/default/balance")
    async def live_balance_ping():
        return ok({"balance": []})

    @app.post("/api/v2/live/strategies/1/pause")
    async def live_pause_ping():
        return ok({"paused": True})

    @app.post("/api/v2/live/positions/close")
    async def paper_close_ping():
        return ok({"closed": True})

    @app.get("/api/v2/trading/accounts/balance")
    async def trading_balance_ping():
        return ok({"balance": []})

    @app.get("/api/v2/arc/missions")
    async def arc_missions_ping():
        return ok({"missions": []})

    @app.post("/api/v2/trading/futures/order")
    async def trading_futures_order_ping():
        return ok({"ordered": True})

    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service


def test_admin_login_sets_cookie_and_can_call_protected_write(tmp_path: Path, monkeypatch) -> None:
    client, _ = build_client(tmp_path, monkeypatch)

    assert client.post("/api/v2/settings/ping").status_code == 401

    response = client.post(
        "/api/v2/auth/admin/login",
        json={"username": "admin", "password": "admin-pass"},
    )
    assert response.status_code == 200
    assert "httponly" in response.headers["set-cookie"].lower()
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    assert int(cookie[settings.BITPRO_AUTH_COOKIE_NAME]["max-age"]) > 60 * 60 * 24 * 365
    assert response.json()["data"]["role"] == "admin"

    protected = client.post("/api/v2/settings/ping")
    assert protected.status_code == 200
    assert protected.json()["data"]["saved"] is True


def test_guest_code_can_read_all_pages_but_cannot_mutate_live_or_pause_strategy(tmp_path: Path, monkeypatch) -> None:
    client, service = build_client(tmp_path, monkeypatch)
    code = service.create_guest_code(
        note="demo",
        expires_in_minutes=60,
        max_backtests_per_day=10,
        max_concurrent_backtests=1,
        max_backtest_days=365,
        created_by="admin",
    )["code"]

    response = client.post("/api/v2/auth/guest/login", json={"code": code})
    assert response.status_code == 200
    assert response.json()["data"]["role"] == "guest"

    for path in (
        "/api/v2/market/ping",
        "/api/v2/live/accounts/default/balance",
        "/api/v2/trading/accounts/balance",
    ):
        allowed = client.get(path)
        assert allowed.status_code == 200, path

    for method, path in (
        ("get", "/api/v2/settings/ping"),
        ("get", "/api/v2/arc/missions"),
        ("post", "/api/v2/settings/ping"),
        ("post", "/api/v2/live/strategies/1/pause"),
        ("post", "/api/v2/live/positions/close"),
        ("post", "/api/v2/trading/futures/order"),
    ):
        forbidden = getattr(client, method)(path)
        assert forbidden.status_code == 403, path
        assert "访客" in forbidden.json()["error"]["message"]
