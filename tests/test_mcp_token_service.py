from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.v2.endpoints import auth as auth_endpoint  # noqa: E402
from app.api.v2.endpoints import settings as settings_endpoint  # noqa: E402
from app.core.auth_middleware import AuthMiddleware  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.contracts import ok  # noqa: E402
from app.db.local_db import LocalDatabase  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402
from app.services.mcp_token_service import mcp_token_service  # noqa: E402


def build_settings_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, LocalDatabase]:
    database = LocalDatabase(str(tmp_path / "mcp-token.db"))
    database.init_db()
    auth_service = AuthService(db=database)

    monkeypatch.setattr(settings_endpoint, "db", database)
    monkeypatch.setattr(auth_endpoint, "auth_service", auth_service)
    monkeypatch.setattr(mcp_token_service, "db", database)
    monkeypatch.setattr(settings, "BITPRO_AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BITPRO_ADMIN_USERNAME", "admin", raising=False)
    monkeypatch.setattr(settings, "BITPRO_ADMIN_PASSWORD_HASH", auth_service.hash_password("admin-pass"), raising=False)
    monkeypatch.setattr(settings, "BITPRO_AUTH_COOKIE_SECURE", False, raising=False)
    monkeypatch.setattr(settings, "BITPRO_MCP_API_TOKEN", "", raising=False)
    monkeypatch.setattr(settings, "BITPRO_MCP_AUTH_HEADER", "X-Test-MCP-Token", raising=False)
    monkeypatch.setattr(settings, "BITPRO_REMOTE_MCP_REQUIRE_TOKEN", True, raising=False)

    app = FastAPI()
    app.add_middleware(AuthMiddleware, auth_service=auth_service)
    app.include_router(auth_endpoint.router, prefix="/api/v2/auth")
    app.include_router(settings_endpoint.router, prefix="/api/v2/settings")

    @app.get("/api/v2/market/symbols")
    async def market_symbols(request: Request):
        return ok({"auth": request.state.auth, "symbols": ["BTC/USDT:USDT"]})

    client = TestClient(app, raise_server_exceptions=False)
    assert client.post("/api/v2/auth/admin/login", json={"username": "admin", "password": "admin-pass"}).status_code == 200
    return client, database


def test_mcp_token_generate_returns_plaintext_once_and_persists_only_hash(tmp_path: Path, monkeypatch) -> None:
    client, database = build_settings_client(tmp_path, monkeypatch)

    generated = client.post("/api/v2/settings/mcp-token/generate", json={"note": "codex agent"})

    assert generated.status_code == 200
    payload = generated.json()
    token = payload["token"]
    assert token.startswith("bp_mcp_")
    assert len(token) >= 48
    assert payload["configured"] is True
    assert payload["source"] == "generated"
    assert payload["auth_header"] == "X-Test-MCP-Token"
    assert payload["masked_token"].startswith("bp_mcp_")
    assert payload["masked_token"] != token
    assert "token_hash" not in json.dumps(payload)

    row = database.get_app_setting("mcp_api_token")
    assert row
    stored = json.loads(row)
    assert stored["token_hash"]
    assert token not in row
    assert stored["note"] == "codex agent"

    status = client.get("/api/v2/settings/mcp-token")
    assert status.status_code == 200
    status_text = json.dumps(status.json())
    assert "token" not in status.json()
    assert token not in status_text
    assert status.json()["configured"] is True
    assert status.json()["source"] == "generated"


def test_generated_mcp_token_authenticates_api_requests_after_runtime_env_is_empty(tmp_path: Path, monkeypatch) -> None:
    client, _ = build_settings_client(tmp_path, monkeypatch)
    token = client.post("/api/v2/settings/mcp-token/generate", json={"note": "agent"}).json()["token"]

    monkeypatch.setattr(settings, "BITPRO_MCP_API_TOKEN", "", raising=False)
    client.cookies.clear()

    assert client.get("/api/v2/market/symbols").status_code == 401
    wrong = client.get("/api/v2/market/symbols", headers={"X-Test-MCP-Token": "wrong"})
    assert wrong.status_code == 401

    response = client.get("/api/v2/market/symbols", headers={"X-Test-MCP-Token": token})

    assert response.status_code == 200
    assert response.json()["data"]["symbols"] == ["BTC/USDT:USDT"]
    assert response.json()["data"]["auth"]["role"] == "admin"
    assert response.json()["data"]["auth"]["auth_method"] == "mcp_token"
