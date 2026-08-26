from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.auth_middleware import AuthMiddleware  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.contracts import ok  # noqa: E402
from app.db.local_db import LocalDatabase  # noqa: E402
from app.mcp.client import BitProMcpClient  # noqa: E402
from app.mcp.server import create_remote_app, mount_remote_mcp  # noqa: E402

try:  # pragma: no cover - keeps missing service as a normal red assertion.
    from app.services.mcp_token_service import McpAgentTokenService  # noqa: E402
except ModuleNotFoundError:  # pragma: no cover
    McpAgentTokenService = None  # type: ignore[assignment]


class FakeHttpClient:
    def __init__(self, responses: list[httpx.Response]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self.responses:
            raise AssertionError("no fake response queued")
        return self.responses.pop(0)


def test_auth_middleware_accepts_mcp_token_as_admin(monkeypatch) -> None:
    monkeypatch.setattr(settings, "BITPRO_AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BITPRO_MCP_API_TOKEN", "agent-secret", raising=False)
    monkeypatch.setattr(settings, "BITPRO_MCP_AUTH_HEADER", "X-Test-MCP-Token", raising=False)

    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.post("/api/v2/settings/ping")
    async def settings_ping(request: Request):
        return ok(request.state.auth)

    client = TestClient(app, raise_server_exceptions=False)

    assert client.post("/api/v2/settings/ping").status_code == 401
    assert client.post("/api/v2/settings/ping", headers={"X-Test-MCP-Token": "wrong"}).status_code == 401

    response = client.post("/api/v2/settings/ping", headers={"X-Test-MCP-Token": "agent-secret"})

    assert response.status_code == 200
    assert response.json()["data"]["role"] == "admin"
    assert response.json()["data"]["auth_method"] == "mcp_token"


def test_auth_middleware_accepts_generated_mcp_agent_token(monkeypatch, tmp_path: Path) -> None:
    assert McpAgentTokenService is not None, "McpAgentTokenService should exist"
    db = LocalDatabase(str(tmp_path / "mcp_agent_auth.db"))
    db.init_db()
    token_service = McpAgentTokenService(db=db)
    created = token_service.create_token(name="Hermes Agent")

    import app.core.auth_middleware as auth_middleware_module

    monkeypatch.setattr(auth_middleware_module, "mcp_token_service", token_service, raising=False)
    monkeypatch.setattr(settings, "BITPRO_AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BITPRO_MCP_API_TOKEN", "", raising=False)
    monkeypatch.setattr(settings, "BITPRO_MCP_AUTH_HEADER", "X-Test-MCP-Token", raising=False)

    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.post("/api/v2/settings/ping")
    async def settings_ping(request: Request):
        return ok(request.state.auth)

    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/v2/settings/ping", headers={"X-Test-MCP-Token": created["token"]})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["role"] == "admin"
    assert data["auth_method"] == "mcp_token"
    assert data["token_id"] == created["item"]["id"]


def test_client_sends_configured_mcp_token_header(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BITPRO_MCP_API_TOKEN", "agent-secret")
    monkeypatch.setenv("BITPRO_MCP_AUTH_HEADER", "X-Test-MCP-Token")
    fake_http = FakeHttpClient([httpx.Response(200, json={"success": True, "data": {"ok": True}})])
    client = BitProMcpClient(
        base_url="http://bitpro.local/api/v2",
        audit_path=tmp_path / "mcp_audit.jsonl",
        http_client=fake_http,
    )

    assert client.request("GET", "/system/health", tool_name="bitpro_health") == {"ok": True}
    assert fake_http.calls[0]["headers"] == {"X-Test-MCP-Token": "agent-secret"}


def test_remote_mcp_app_requires_agent_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "BITPRO_MCP_API_TOKEN", "agent-secret", raising=False)
    monkeypatch.setattr(settings, "BITPRO_MCP_AUTH_HEADER", "X-Test-MCP-Token", raising=False)
    monkeypatch.setattr(settings, "BITPRO_REMOTE_MCP_REQUIRE_TOKEN", True, raising=False)

    app = create_remote_app()
    client = TestClient(app, raise_server_exceptions=False)

    missing = client.post("/")
    wrong = client.post("/", headers={"X-Test-MCP-Token": "wrong"})
    allowed = client.post("/", headers={"X-Test-MCP-Token": "agent-secret"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert allowed.status_code != 401


def test_mount_remote_mcp_uses_configured_api_v2_path(monkeypatch) -> None:
    monkeypatch.setattr(settings, "BITPRO_REMOTE_MCP_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BITPRO_REMOTE_MCP_PATH", "/api/v2/mcp", raising=False)
    monkeypatch.setattr(settings, "BITPRO_MCP_API_TOKEN", "agent-secret", raising=False)
    monkeypatch.setattr(settings, "BITPRO_REMOTE_MCP_REQUIRE_TOKEN", True, raising=False)

    app = FastAPI()

    assert mount_remote_mcp(app) is True
    assert any(getattr(route, "path", None) == "/api/v2/mcp" for route in app.routes)


def test_mounted_remote_mcp_initializes_session_manager(monkeypatch) -> None:
    monkeypatch.setattr(settings, "BITPRO_REMOTE_MCP_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BITPRO_REMOTE_MCP_PATH", "/api/v2/mcp", raising=False)
    monkeypatch.setattr(settings, "BITPRO_MCP_API_TOKEN", "agent-secret", raising=False)
    monkeypatch.setattr(settings, "BITPRO_MCP_AUTH_HEADER", "X-Test-MCP-Token", raising=False)
    monkeypatch.setattr(settings, "BITPRO_REMOTE_MCP_REQUIRE_TOKEN", True, raising=False)

    app = FastAPI()
    assert mount_remote_mcp(app) is True

    with TestClient(
        app,
        base_url="http://host.docker.internal:8889",
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            "/api/v2/mcp/",
            headers={
                "X-Test-MCP-Token": "agent-secret",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "bitpro-test", "version": "1.0"},
                },
            },
        )

    assert response.status_code == 200
    assert "serverInfo" in response.text


def test_ssh_stdio_launcher_keeps_agent_token_on_server_and_disables_live_writes() -> None:
    launcher = (PROJECT_ROOT / "scripts" / "run_bitpro_mcp_ssh_stdio.sh").read_text(encoding="utf-8")

    assert "/opt/bitpro/.secrets/codex_mcp_token" in launcher
    assert 'export BITPRO_MCP_API_BASE="http://127.0.0.1:8889/api/v2"' in launcher
    assert 'export BITPRO_MCP_AUTH_HEADER="X-BitPro-MCP-Token"' in launcher
    assert 'export BITPRO_MCP_ENABLE_LIVE_TRADING="0"' in launcher
    assert "/opt/bitpro/data/mcp_tool_audit.jsonl" in launcher
    assert 'exec /opt/bitpro/backend/venv/bin/python' in launcher
    assert "cat \"${TOKEN_FILE}\"" in launcher
