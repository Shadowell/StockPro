from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.api.v2.endpoints import auth as auth_endpoint  # noqa: E402
from app.domain.auth.service import ActiveAuthService  # noqa: E402
from app.domain.auth.login_limiter import LoginAttemptLimiter, LoginRateLimitError  # noqa: E402
from app.domain.auth.mcp_tokens import PostgresMcpTokenVerifier  # noqa: E402
from app.main import create_app  # noqa: E402


class FakeAuthRepository:
    def __init__(self):
        self.codes = {}
        self.events = []
        self.revoked_sessions = set()
        self.next_id = 1

    def create_guest_code(self, **payload):
        row = {"id": self.next_id, **payload, "created_at": datetime.now(timezone.utc), "last_used_at": None, "revoked_at": None}
        self.codes[self.next_id] = row
        self.next_id += 1
        return dict(row)

    def active_guest_code(self, *, code_hash=None, code_id=None, now):
        rows = self.codes.values()
        row = next((item for item in rows if (item["code_hash"] == code_hash if code_hash is not None else item["id"] == code_id)), None)
        return dict(row) if row and not row["revoked_at"] and row["expires_at"] > now else None

    def list_guest_codes(self): return [dict(row) for row in self.codes.values() if not row["revoked_at"]]
    def touch_guest_code(self, code_id, now): self.codes[code_id]["last_used_at"] = now
    def revoke_guest_code(self, code_id, now): self.codes[code_id]["revoked_at"] = now; return {"id": code_id, "revoked_at": now}
    def record_event(self, **payload):
        self.events.append(dict(payload))
        if payload["event_type"] == "session_revoked": self.revoked_sessions.add(payload["subject_id"])
    def session_revoked(self, session_id): return session_id in self.revoked_sessions


def test_postgres_auth_contract_issues_and_revokes_signed_admin_session(monkeypatch):
    repository = FakeAuthRepository()
    service = ActiveAuthService(repository)
    password_hash = service.hash_password("correct-password")
    monkeypatch.setattr(settings, "BITPRO_ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "BITPRO_ADMIN_PASSWORD_HASH", password_hash)
    monkeypatch.setattr(settings, "BITPRO_AUTH_TOKEN_SECRET", "x" * 64)
    session = service.login_admin(username="admin", password="correct-password", expected_username="admin", expected_password_hash=password_hash)
    assert service.get_session(session["token"])["role"] == "admin"
    service.revoke_session(session["token"])
    assert service.get_session(session["token"]) is None
    assert any(event["event_type"] == "session_revoked" for event in repository.events)


def test_guest_code_plaintext_is_returned_once_and_revocation_invalidates_token(monkeypatch):
    repository = FakeAuthRepository()
    fixed_now = datetime(2026, 8, 26, tzinfo=timezone.utc)
    service = ActiveAuthService(repository, clock=lambda: fixed_now)
    monkeypatch.setattr(settings, "BITPRO_AUTH_TOKEN_SECRET", "y" * 64)
    created = service.create_guest_code(note="review", expires_in_minutes=60, max_backtests_per_day=2, max_concurrent_backtests=1, max_backtest_days=30)
    assert created["code"].startswith("BP-")
    assert created["code"] not in str(repository.codes[created["id"]])
    assert "code_hash" not in created
    session = service.login_guest(created["code"])
    assert service.get_session(session["token"])["max_backtests_per_day"] == 2
    service.revoke_guest_code(created["id"])
    assert service.get_session(session["token"]) is None


def test_active_auth_runtime_has_no_sqlite_dependency():
    service_source = (BACKEND_ROOT / "app/domain/auth/service.py").read_text()
    repository_source = (BACKEND_ROOT / "app/domain/auth/repository.py").read_text()
    mcp_source = (BACKEND_ROOT / "app/domain/auth/mcp_tokens.py").read_text()
    middleware_source = (BACKEND_ROOT / "app/core/auth_middleware.py").read_text()
    main_source = (BACKEND_ROOT / "app/main.py").read_text()
    assert "sqlite" not in (service_source + repository_source + mcp_source).lower()
    assert "app.services.mcp_token_service" not in middleware_source
    assert "AuthMiddleware" in main_source
    assert 'prefix="/api/v2/auth"' in main_source
    assert '"auth_enabled": False' not in main_source


def test_environment_mcp_token_remains_constant_time_fallback(monkeypatch):
    class NoDatabase:
        def _connect(self, **_): raise AssertionError("env token must not query PostgreSQL")
    monkeypatch.setattr(settings, "BITPRO_MCP_API_TOKEN", "env-mcp-probe")
    verified = PostgresMcpTokenVerifier(NoDatabase()).verify_token("env-mcp-probe")
    assert verified["token_source"] == "env"
    assert verified["scopes"] == ["R", "W", "L", "T"]


def test_login_limiter_blocks_only_after_failed_attempt_budget_is_exhausted():
    limiter = LoginAttemptLimiter(max_failures=2, window_seconds=60)
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)

    limiter.check("203.0.113.10", now=now)
    limiter.record_failure("203.0.113.10", now=now)
    limiter.check("203.0.113.10", now=now)
    limiter.record_failure("203.0.113.10", now=now)

    try:
        limiter.check("203.0.113.10", now=now)
    except LoginRateLimitError as exc:
        assert exc.status_code == 429
    else:
        raise AssertionError("two failures must exhaust the configured budget")


def test_login_limiter_success_and_window_expiry_restore_attempts():
    limiter = LoginAttemptLimiter(max_failures=1, window_seconds=60)
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)

    limiter.record_failure("203.0.113.20", now=now)
    limiter.clear("203.0.113.20")
    limiter.check("203.0.113.20", now=now)

    limiter.record_failure("203.0.113.20", now=now)
    limiter.check("203.0.113.20", now=now + timedelta(seconds=61))


def test_admin_login_endpoint_returns_429_after_source_exhausts_failure_budget(monkeypatch):
    class RejectingAuthService:
        calls = 0

        @staticmethod
        def validate_admin_config(**_):
            return None

        def login_admin(self, **_):
            self.calls += 1
            raise auth_endpoint.ActiveAuthError("管理员账号或密码错误", status_code=401)

    service = RejectingAuthService()
    monkeypatch.setattr(settings, "BITPRO_AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "BITPRO_ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "BITPRO_ADMIN_PASSWORD_HASH", "configured")
    monkeypatch.setattr(auth_endpoint, "auth_service", service)
    monkeypatch.setattr(auth_endpoint, "login_limiter", LoginAttemptLimiter(max_failures=2, window_seconds=60))
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v2/auth/admin/login",
            "headers": [],
            "client": ("203.0.113.30", 443),
            "scheme": "https",
            "server": ("stockpro.notenap.com", 443),
        }
    )
    payload = auth_endpoint.AdminLoginRequest(username="admin", password="wrong")

    for _ in range(2):
        with pytest.raises(auth_endpoint.AuthRequestError) as caught:
            asyncio.run(auth_endpoint.admin_login(payload, request, Response()))
        assert caught.value.status_code == 401

    with pytest.raises(auth_endpoint.AuthRequestError) as caught:
        asyncio.run(auth_endpoint.admin_login(payload, request, Response()))
    assert caught.value.status_code == 429
    assert service.calls == 2


def test_admin_login_sets_strict_secure_http_only_session_cookie(monkeypatch):
    class SuccessfulAuthService:
        @staticmethod
        def validate_admin_config(**_):
            return None

        @staticmethod
        def login_admin(**_):
            return {
                "token": "signed-session-token",
                "session_id": "session-id",
                "role": "admin",
                "authenticated": True,
                "expires_at": "2026-08-27T00:00:00+00:00",
                "max_age": 3600,
            }

    monkeypatch.setattr(settings, "BITPRO_AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "BITPRO_AUTH_COOKIE_SECURE", True)
    monkeypatch.setattr(settings, "BITPRO_ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "BITPRO_ADMIN_PASSWORD_HASH", "configured")
    monkeypatch.setattr(auth_endpoint, "auth_service", SuccessfulAuthService())
    monkeypatch.setattr(auth_endpoint, "login_limiter", LoginAttemptLimiter())
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v2/auth/admin/login",
            "headers": [],
            "client": ("203.0.113.40", 443),
            "scheme": "https",
            "server": ("stockpro.notenap.com", 443),
        }
    )
    response = Response()

    asyncio.run(
        auth_endpoint.admin_login(
            auth_endpoint.AdminLoginRequest(username="admin", password="correct"),
            request,
            response,
        )
    )

    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=strict" in cookie


def test_login_source_uses_nginx_real_ip_instead_of_spoofable_forwarded_chain():
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v2/auth/admin/login",
            "headers": [
                (b"x-real-ip", b"198.51.100.50"),
                (b"x-forwarded-for", b"203.0.113.250, 198.51.100.50"),
            ],
            "client": ("127.0.0.1", 52341),
            "scheme": "https",
            "server": ("stockpro.notenap.com", 443),
        }
    )

    assert auth_endpoint._client_ip(request) == "198.51.100.50"


def test_application_returns_typed_auth_error_instead_of_internal_error(monkeypatch):
    class RejectingAuthService:
        @staticmethod
        def validate_admin_config(**_):
            return None

        @staticmethod
        def login_admin(**_):
            raise auth_endpoint.ActiveAuthError("管理员账号或密码错误", status_code=401)

    monkeypatch.setattr(settings, "BITPRO_AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "BITPRO_ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "BITPRO_ADMIN_PASSWORD_HASH", "configured")
    monkeypatch.setattr(auth_endpoint, "auth_service", RejectingAuthService())
    monkeypatch.setattr(auth_endpoint, "login_limiter", LoginAttemptLimiter())

    response = TestClient(create_app(), raise_server_exceptions=False).post(
        "/api/v2/auth/admin/login",
        json={"username": "admin", "password": "wrong"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_ERROR"
