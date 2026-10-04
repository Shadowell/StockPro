"""SSO contract tests: in-process ASGI and mock HTTPS, no services or databases."""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.v2.endpoints import auth as auth_endpoint
from app.core.auth_middleware import AuthMiddleware
from app.core.config import settings
from app.core.errors import register_exception_handlers

ORIGIN = "https://stockpro.notenap.com"
VERIFY_URL = "https://monitor.notenap.com/api/auth/sso/session"
COOKIE = "notenap_session=central-session.test-signature"
IDENTITY = {"authenticated": True, "user": "测试管理员", "role": "admin"}


class LocalSessions:
    def __init__(self):
        self.sessions = {}
        self.revoked = []

    def get_session(self, token):
        return self.sessions.get(token)

    def revoke_session(self, token):
        self.revoked.append(token)
        self.sessions.pop(token, None)


@pytest.fixture
def app_client(monkeypatch):
    monkeypatch.setattr(settings, "BITPRO_AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "BITPRO_AUTH_COOKIE_NAME", "bitpro_session")
    monkeypatch.setattr(settings, "STOCKPRO_MCP_API_TOKEN", "machine-probe-token")
    sessions = LocalSessions()
    monkeypatch.setattr(auth_endpoint, "auth_service", sessions)
    app = FastAPI()
    app.add_middleware(AuthMiddleware, auth_service=sessions)
    register_exception_handlers(app)
    app.include_router(auth_endpoint.router, prefix="/api/auth")
    app.include_router(auth_endpoint.router, prefix="/api/v2/auth")

    @app.api_route("/api/v2/probe", methods=["GET", "POST"])
    async def probe(request: Request):
        return request.state.auth

    return TestClient(app, base_url=ORIGIN), sessions


@pytest.fixture
def central(monkeypatch):
    original = httpx.AsyncClient
    calls = []
    config = {"status": 200, "json": IDENTITY}
    clients = []

    def respond(request):
        calls.append(request)
        if config.get("timeout"):
            raise httpx.ReadTimeout("test timeout", request=request)
        if "content" in config:
            return httpx.Response(config["status"], content=config["content"])
        return httpx.Response(config["status"], json=config["json"], headers=config.get("headers", {}))

    def factory(*args, **kwargs):
        clients.append(dict(kwargs))
        kwargs["transport"] = httpx.MockTransport(respond)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return config, calls, clients


@pytest.mark.parametrize("path", ["/api/auth/me", "/api/v2/auth/me", "/api/v2/probe"])
def test_central_session_authenticates_all_browser_entrypoints(app_client, central, path):
    client, _ = app_client
    response = client.get(path, headers={"Cookie": COOKIE + "; private_cookie=never-forward", "Authorization": "Bearer never-forward", "X-Operator-User": "forged"})
    assert response.status_code == 200
    identity = response.json().get("data", response.json())
    assert identity["authenticated"] is True
    assert identity["role"] == "admin"
    assert identity["user"] == "测试管理员"
    config, calls, clients = central
    assert len(calls) == 1
    assert str(calls[0].url) == VERIFY_URL
    assert calls[0].headers["cookie"] == COOKIE
    assert "authorization" not in calls[0].headers
    assert "x-operator-user" not in calls[0].headers
    assert clients[0]["follow_redirects"] is False
    assert clients[0]["trust_env"] is False
    assert clients[0]["timeout"] <= 5


@pytest.mark.parametrize("cookie", [
    "notenap_session=first; notenap_session=second",
    "notenap_session=",
    'notenap_session="quoted"',
    "notenap_session=bad value",
    "notenap_session=" + "x" * 1025,
    "notenap_session=non+urlsafe",
    "notenap_session=non/urlsafe",
])
def test_ambiguous_or_malformed_cookie_never_contacts_central(app_client, central, cookie):
    client, _ = app_client
    response = client.get("/api/v2/probe", headers={"Cookie": cookie})
    assert response.status_code == 401
    assert not central[1]


def test_duplicate_cookie_headers_are_rejected(app_client, central):
    response = app_client[0].get("/api/v2/probe", headers=[("Cookie", COOKIE), ("Cookie", "notenap_session=second")])
    assert response.status_code == 401
    assert not central[1]


@pytest.mark.parametrize("payload", [None, [], {}, {**IDENTITY, "authenticated": 1}, {**IDENTITY, "role": "guest"}, {**IDENTITY, "user": " "}, {**IDENTITY, "user": 123}])
def test_untrusted_central_identity_fails_closed(app_client, central, payload):
    central[0]["json"] = payload
    response = app_client[0].get("/api/v2/probe", headers={"Cookie": COOKIE})
    assert response.status_code == 503
    assert "central-session" not in response.text


@pytest.mark.parametrize("status", [302, 403, 500, 503])
def test_central_failure_and_redirect_never_authorize(app_client, central, status):
    central[0].update(status=status, headers={"Location": "https://untrusted.invalid/"})
    response = app_client[0].get("/api/v2/probe", headers={"Cookie": COOKIE})
    assert response.status_code == 503
    assert len(central[1]) == 1


def test_timeout_and_invalid_json_are_unavailable(app_client, central):
    central[0]["timeout"] = True
    assert app_client[0].get("/api/auth/me", headers={"Cookie": COOKIE}).status_code == 503
    central[0].pop("timeout")
    central[0]["content"] = b"not json"
    assert app_client[0].get("/api/v2/auth/me", headers={"Cookie": COOKIE}).status_code == 503


def test_expired_session_and_forged_identity_do_not_authorize(app_client, central):
    central[0]["status"] = 401
    client, _ = app_client
    assert client.get("/api/v2/probe", headers={"Cookie": COOKIE}).status_code == 401
    response = client.get("/api/auth/me", headers={"Cookie": COOKIE})
    assert response.json()["data"]["authenticated"] is False
    count = len(central[1])
    assert client.get("/api/v2/probe", headers={"X-Operator-User": "admin", "X-Forwarded-User": "admin"}).status_code == 401
    assert len(central[1]) == count


@pytest.mark.parametrize("role", ["admin", "guest"])
def test_valid_local_session_keeps_role_without_central_call(app_client, central, role):
    client, sessions = app_client
    sessions.sessions["local-test"] = {"authenticated": True, "role": role, "session_id": "local-id"}
    headers = {"Cookie": "bitpro_session=local-test; " + COOKIE}
    for path in ("/api/v2/probe", "/api/auth/me", "/api/v2/auth/me"):
        response = client.get(path, headers=headers)
        identity = response.json().get("data", response.json())
        assert identity["role"] == role
    assert not central[1]
    assert client.post("/api/v2/probe", headers=headers).status_code == (200 if role == "admin" else 403)


@pytest.mark.parametrize("path", ["/api/v2/probe", "/api/auth/me", "/api/v2/auth/me"])
def test_mcp_token_still_wins_over_central_cookie(app_client, central, path):
    response = app_client[0].get(path, headers={"X-StockPro-MCP-Token": "machine-probe-token", "Cookie": COOKIE})
    identity = response.json().get("data", response.json())
    assert response.status_code == 200
    assert identity["authenticated"] is True
    assert identity["role"] == "admin"
    assert not central[1]


@pytest.mark.parametrize("origin,status", [(ORIGIN, 200), (None, 200), ("https://monitor.notenap.com", 403), ("https://evil.invalid", 403), ("null", 403), ("http://stockpro.notenap.com", 403)])
def test_sso_writes_require_same_https_origin_when_present(app_client, central, origin, status):
    headers = {"Cookie": COOKIE}
    if origin is not None:
        headers["Origin"] = origin
    assert app_client[0].post("/api/v2/probe", headers=headers).status_code == status


@pytest.mark.parametrize("path", ["/api/auth/logout", "/api/v2/auth/logout"])
def test_logout_clears_local_and_shared_cookies_without_central_call(app_client, central, path):
    client, sessions = app_client
    response = client.post(path, headers={"Cookie": "bitpro_session=local-test; " + COOKIE, "Origin": ORIGIN})
    assert response.status_code == 200
    cookies = response.headers.get_list("set-cookie")
    assert any(c.startswith('bitpro_session="";') and "Max-Age=0" in c for c in cookies)
    assert any(c.startswith('notenap_session="";') and "Domain=.notenap.com" in c and "Max-Age=0" in c and "Secure" in c for c in cookies)
    assert sessions.revoked == ["local-test"]
    assert not central[1]


def test_cross_origin_logout_cannot_clear_shared_session(app_client, central):
    client, sessions = app_client
    response = client.post("/api/auth/logout", headers={"Cookie": COOKIE, "Origin": "https://evil.notenap.com"})
    assert response.status_code == 403
    assert "set-cookie" not in response.headers
    assert not sessions.revoked
    assert not central[1]


def test_local_only_logout_preserves_local_development_origin(app_client, central):
    client, sessions = app_client
    response = client.post("/api/auth/logout", headers={"Cookie": "bitpro_session=local-test", "Origin": "http://localhost:4444"})
    assert response.status_code == 200
    assert sessions.revoked == ["local-test"]
    assert not central[1]


def test_invalid_local_session_can_fall_back_to_valid_central_session(app_client, central):
    response = app_client[0].get("/api/v2/probe", headers={"Cookie": "bitpro_session=expired; " + COOKIE})
    assert response.status_code == 200
    assert response.json()["auth_method"] == "hypermonitor_sso"
    assert len(central[1]) == 1


def test_duplicate_or_host_spoofed_origin_is_rejected(app_client, central):
    client, _ = app_client
    response = client.post("/api/v2/probe", headers=[("Cookie", COOKIE), ("Origin", ORIGIN), ("Origin", ORIGIN)])
    assert response.status_code == 403
    response = client.post("/api/v2/probe", headers={"Cookie": COOKIE, "Origin": "https://evil.invalid", "Host": "evil.invalid", "X-Forwarded-Host": "evil.invalid"})
    assert response.status_code == 403
    assert not central[1]


def test_mcp_scopes_do_not_turn_into_browser_permissions(app_client, central, monkeypatch):
    import app.core.auth_middleware as middleware

    original = {"authenticated": True, "role": "admin", "auth_method": "mcp_token", "scopes": ["R"], "tool_groups": ["read"], "token_id": 7}
    monkeypatch.setattr(middleware.postgres_mcp_token_verifier, "verify_token", lambda token: original if token == "scoped-token" else None)
    response = app_client[0].post("/api/v2/probe", headers={"Cookie": COOKIE, "X-StockPro-MCP-Token": "scoped-token"})
    assert response.json() == original
    assert not central[1]
