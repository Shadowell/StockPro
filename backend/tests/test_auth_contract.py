from __future__ import annotations

import hashlib
import importlib
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient


BACKEND_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class FakeStorageHealth:
    status: str = "healthy"
    database: str = "postgresql"
    applied_migrations: int = 37
    expected_migrations: int = 37


class FakeAuthRepository:
    def __init__(self, guest_code: str = "guest-code") -> None:
        self.guest_hash = hashlib.sha256(guest_code.encode("utf-8")).hexdigest()
        self.events: list[dict[str, object]] = []
        self.touched: list[int] = []

    def storage_health(self) -> FakeStorageHealth:
        return FakeStorageHealth()

    def get_active_guest_code(self, code_hash: str, now: datetime):
        if code_hash != self.guest_hash:
            return None
        return {
            "id": 7,
            "expires_at": now + timedelta(hours=1),
            "max_backtests_per_day": 3,
            "max_concurrent_backtests": 1,
            "max_backtest_days": 90,
        }

    def touch_guest_code(self, code_id: int, now: datetime) -> None:
        self.touched.append(code_id)

    def get_active_guest_code_by_id(self, code_id: int, now: datetime):
        if code_id != 7:
            return None
        return {
            "id": 7,
            "expires_at": now + timedelta(hours=1),
            "max_backtests_per_day": 3,
            "max_concurrent_backtests": 1,
            "max_backtest_days": 90,
        }

    def record_auth_event(self, **event) -> None:
        self.events.append(event)


def _client(monkeypatch, repository: FakeAuthRepository | None = None) -> tuple[TestClient, FakeAuthRepository]:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://stockpro@127.0.0.1/stockpro_bitpro_rebase_dev",
    )
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        module = importlib.import_module("app.main")
        repo = repository or FakeAuthRepository()
        settings = SimpleNamespace(
            PROJECT_NAME="StockPro",
            BACKEND_CORS_ORIGINS=["http://localhost:4444"],
            AUTH_ENABLED=True,
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            ADMIN_TOKEN_SECRET="test-token-secret-with-sufficient-length",
            AUTH_TOKEN_TTL_SECONDS=3600,
            AUTH_COOKIE_NAME="stockpro_session",
            AUTH_COOKIE_SECURE=False,
        )
        context = SimpleNamespace(
            settings=settings,
            repositories=SimpleNamespace(health=repo, auth=repo),
            clock=lambda: datetime(2026, 8, 23, tzinfo=timezone.utc),
        )
        return TestClient(module.create_app(context)), repo
    finally:
        sys.path.remove(str(BACKEND_ROOT))


def test_current_auth_contract(monkeypatch) -> None:
    client, repository = _client(monkeypatch)

    admin = client.post(
        "/api/auth/admin/login",
        json={"username": "admin", "password": "secret"},
    )

    assert admin.status_code == 200
    set_cookie = admin.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=strict" in set_cookie
    token = admin.json()["access_token"]
    profile = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert profile["role"] == "admin"
    assert profile["authenticated"] is True
    assert TestClient(client.app).get("/api/market/overview").status_code == 401
    assert repository.events[-1]["success"] is True
    assert "secret" not in str(repository.events)
    assert token not in str(repository.events)


def test_guest_code_is_hashed_and_resolves_read_permissions(monkeypatch) -> None:
    client, repository = _client(monkeypatch)

    response = client.post("/api/auth/guest/login", json={"code": "guest-code"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["role"] == "guest"
    assert payload["permissions"] == ["read", "backtest:run"]
    assert payload["guest_code_id"] == 7
    assert repository.touched == [7]
    assert "guest-code" not in str(repository.events)
    profile = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    ).json()
    assert profile["role"] == "guest"
    assert profile["guest_code_id"] == 7


def test_invalid_admin_credentials_are_generic_and_audited(monkeypatch) -> None:
    client, repository = _client(monkeypatch)

    response = client.post(
        "/api/auth/admin/login",
        json={"username": "admin", "password": "wrong"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials."
    assert repository.events[-1]["success"] is False
    assert "wrong" not in str(repository.events)


def test_legacy_auth_paths_do_not_exist(monkeypatch) -> None:
    client, _ = _client(monkeypatch)

    assert client.post("/api/v2/auth/admin/login", json={}).status_code == 404
    assert client.post("/api/v1/auth/admin/login", json={}).status_code == 404


def test_login_attempts_are_rate_limited(monkeypatch) -> None:
    client, repository = _client(monkeypatch)

    for _ in range(10):
        response = client.post(
            "/api/auth/admin/login",
            json={"username": "admin", "password": "wrong"},
        )
        assert response.status_code == 401

    blocked = client.post(
        "/api/auth/admin/login",
        json={"username": "admin", "password": "wrong"},
    )
    assert blocked.status_code == 429
    assert len(repository.events) == 10


def test_frontend_does_not_persist_or_retain_bearer_token() -> None:
    source = (BACKEND_ROOT.parent / "frontend/src/auth/AuthProvider.tsx").read_text(
        encoding="utf-8"
    )

    assert "localStorage" not in source
    assert "sessionStorage" not in source
    normalize_source = source.split("function normalizeSession", 1)[1].split(
        "export function AuthProvider", 1
    )[0]
    assert "...session" not in normalize_source
