"""ARC console proxy: tokens read/start, humans decide, guests stay out."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.v2.endpoints import arc as arc_endpoint  # noqa: E402
from app.core.auth_middleware import AuthMiddleware  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.errors import register_exception_handlers  # noqa: E402
from app.db.local_db import LocalDatabase  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402
from app.services.hypertrade_client import sign_operator_assertion  # noqa: E402

KNOWN_VECTOR = "v1:1700000000:b3A=:2cd92be04b0e2128c5910cbd8aee254ae2b3a9be44ebef60226ded9479ce8e96"


def test_assertion_signing_matches_the_known_vector() -> None:
    assert (
        sign_operator_assertion(
            mission_id="arc_a",
            decision="approve",
            operator_id="op",
            idempotency_key="k1",
            issued_at=1_700_000_000,
            secret="test-secret",
        )
        == KNOWN_VECTOR
    )


def _app(tmp_path: Path, monkeypatch, *, auth_enabled: bool = True) -> tuple[TestClient, AuthService]:
    database = LocalDatabase(str(tmp_path / "arc-console.db"))
    database.init_db()
    service = AuthService(db=database)
    password_hash = service.hash_password("admin-pass")
    monkeypatch.setattr(settings, "BITPRO_AUTH_ENABLED", auth_enabled, raising=False)
    monkeypatch.setattr(settings, "BITPRO_ADMIN_USERNAME", "admin", raising=False)
    monkeypatch.setattr(settings, "BITPRO_ADMIN_PASSWORD_HASH", password_hash, raising=False)
    monkeypatch.setattr(settings, "BITPRO_AUTH_COOKIE_SECURE", False, raising=False)
    monkeypatch.setattr(settings, "HYPERTRADE_BASE_URL", "https://hypertrade.internal", raising=False)
    monkeypatch.setattr(settings, "HYPERTRADE_SERVICE_TOKEN", "ht_svc_test", raising=False)
    monkeypatch.setattr(settings, "HYPERTRADE_APPROVAL_SIGNING_SECRET", "test-secret", raising=False)

    app = FastAPI()
    app.add_middleware(AuthMiddleware, auth_service=service)
    app.include_router(arc_endpoint.router, prefix="/api/v2/arc")
    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service


def test_unconfigured_base_url_is_a_disabled_state_not_a_500(tmp_path: Path, monkeypatch) -> None:
    client, _ = _app(tmp_path, monkeypatch, auth_enabled=False)
    monkeypatch.setattr(settings, "HYPERTRADE_BASE_URL", "", raising=False)
    monkeypatch.setattr(settings, "HYPERTRADE_API_BASE", None, raising=False)
    monkeypatch.setattr(settings, "HYPERTRADE_SERVICE_TOKEN", "", raising=False)
    response = client.get("/api/v2/arc/config")
    assert response.status_code == 200
    assert response.json()["data"]["configured"] is False
    created = client.post(
        "/api/v2/arc/missions",
        json={"objective": "probe", "symbol": "BTC-USDT-SWAP"},
    )
    assert created.status_code == 503
    assert created.json()["error"]["code"] == "HYPERTRADE_UNAVAILABLE"


def test_guest_session_cannot_decide(tmp_path: Path, monkeypatch) -> None:
    client, service = _app(tmp_path, monkeypatch)
    code = service.create_guest_code(
        note="arc",
        expires_in_minutes=60,
        max_backtests_per_day=1,
        max_concurrent_backtests=1,
        max_backtest_days=30,
        created_by="admin",
    )["code"]
    guest = service.login_guest(code, ip_address="127.0.0.1", user_agent="pytest")
    client.cookies.set(settings.BITPRO_AUTH_COOKIE_NAME, guest["token"])
    response = client.post(
        "/api/v2/arc/missions/arc_x/decide",
        json={"decision": "approve", "reason": "no"},
    )
    assert response.status_code == 403


def test_decide_forwards_the_session_operator_not_a_body_field(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_decide(self, mission_id: str, **kwargs: Any) -> dict[str, Any]:
        captured["mission_id"] = mission_id
        captured.update(kwargs)
        return {"status": "needs_operator", "decision": "rejected"}

    monkeypatch.setattr(arc_endpoint.HyperTradeClient, "decide", fake_decide)
    client, service = _app(tmp_path, monkeypatch)
    admin = service.login_admin(
        username="admin",
        password="admin-pass",
        expected_username="admin",
        expected_password_hash=settings.BITPRO_ADMIN_PASSWORD_HASH,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    client.cookies.set(settings.BITPRO_AUTH_COOKIE_NAME, admin["token"])
    response = client.post(
        "/api/v2/arc/missions/arc_x/decide",
        json={"decision": "reject", "reason": "not yet"},
    )
    assert response.status_code == 200, response.text
    assert captured["operator_id"] == "admin"
    assert captured["decision"] == "reject"
    assert "forged" not in captured.values()


def test_guest_session_cannot_read_pipeline_progress(tmp_path: Path, monkeypatch) -> None:
    client, service = _app(tmp_path, monkeypatch)
    code = service.create_guest_code(
        note="arc",
        expires_in_minutes=60,
        max_backtests_per_day=1,
        max_concurrent_backtests=1,
        max_backtest_days=30,
        created_by="admin",
    )["code"]
    guest = service.login_guest(code, ip_address="127.0.0.1", user_agent="pytest")
    client.cookies.set(settings.BITPRO_AUTH_COOKIE_NAME, guest["token"])
    assert client.get("/api/v2/arc/missions/arc_x/progress").status_code == 403


def test_progress_is_proxied_without_reshaping_the_pipeline(
    tmp_path: Path, monkeypatch
) -> None:
    """The console renders HyperTrade's projection, so BitPro must not rebuild it."""
    upstream = {
        "mission_id": "arc_x",
        "state": "paper_observing",
        "current_stage": "paper",
        "percent": 62.5,
        "blocked": False,
        "stages": [{"key": "paper", "label": "模拟盘观察", "status": "active"}],
        "activity": [{"event_id": "evt_1", "type": "paper_observed", "detail": {}}],
    }

    async def fake_progress(self, mission_id: str) -> dict[str, Any]:
        assert mission_id == "arc_x"
        return upstream

    monkeypatch.setattr(arc_endpoint.HyperTradeClient, "get_progress", fake_progress)
    client, service = _app(tmp_path, monkeypatch)
    admin = service.login_admin(
        username="admin",
        password="admin-pass",
        expected_username="admin",
        expected_password_hash=settings.BITPRO_ADMIN_PASSWORD_HASH,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    client.cookies.set(settings.BITPRO_AUTH_COOKIE_NAME, admin["token"])
    response = client.get("/api/v2/arc/missions/arc_x/progress")
    assert response.status_code == 200, response.text
    assert response.json()["data"] == upstream


def test_decide_rejects_a_caller_supplied_operator_id_in_the_body(
    tmp_path: Path, monkeypatch
) -> None:
    client, service = _app(tmp_path, monkeypatch)
    admin = service.login_admin(
        username="admin",
        password="admin-pass",
        expected_username="admin",
        expected_password_hash=settings.BITPRO_ADMIN_PASSWORD_HASH,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    client.cookies.set(settings.BITPRO_AUTH_COOKIE_NAME, admin["token"])
    response = client.post(
        "/api/v2/arc/missions/arc_x/decide",
        json={"decision": "reject", "reason": "x", "operator_id": "forged"},
    )
    assert response.status_code == 422
