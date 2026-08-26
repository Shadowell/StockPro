from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.local_db import LocalDatabase  # noqa: E402

try:  # pragma: no cover - keeps the red test as an assertion, not collection failure.
    from app.services.mcp_token_service import McpAgentTokenService
except ModuleNotFoundError:  # pragma: no cover
    McpAgentTokenService = None  # type: ignore[assignment]


def _service(tmp_path: Path):
    assert McpAgentTokenService is not None, "McpAgentTokenService should exist"
    db = LocalDatabase(str(tmp_path / "mcp_tokens.db"))
    db.init_db()
    return McpAgentTokenService(db=db)


def test_mcp_agent_token_plaintext_is_returned_once_and_hash_only_is_stored(tmp_path: Path) -> None:
    service = _service(tmp_path)

    created = service.create_token(
        name="Hermes production agent",
        expires_in_days=30,
        rate_limit_per_min=42,
        tool_groups=["read", "research_backtest_paper_mutation", "live_diagnostic"],
    )

    token = created["token"]
    item = created["item"]
    assert token.startswith("bp_mcp_")
    assert item["token_prefix"] in token
    assert item["masked_token"].startswith(item["token_prefix"])
    assert item["rate_limit_per_min"] == 42
    assert item["tool_groups"] == ["read", "research_backtest_paper_mutation", "live_diagnostic"]

    row = service.db.get_connection().execute(
        "SELECT token_hash, token_prefix, name, rate_limit_per_min, tool_groups FROM mcp_agent_tokens WHERE id = ?",
        (item["id"],),
    ).fetchone()
    assert row["name"] == "Hermes production agent"
    assert row["token_hash"] != token
    assert token not in str(dict(row))
    assert "read" in row["tool_groups"]

    verified = service.verify_token(token)
    assert verified is not None
    assert verified["authenticated"] is True
    assert verified["role"] == "admin"
    assert verified["auth_method"] == "mcp_token"
    assert verified["token_id"] == item["id"]
    assert verified["tool_groups"] == item["tool_groups"]

    listed = service.list_tokens()
    assert listed["items"][0]["id"] == item["id"]
    assert "token" not in listed["items"][0]

    service.revoke_token(item["id"])
    assert service.verify_token(token) is None


def test_mcp_agent_token_status_includes_env_and_db_tokens(monkeypatch, tmp_path: Path) -> None:
    service = _service(tmp_path)
    monkeypatch.setattr("app.services.mcp_token_service.settings.BITPRO_MCP_API_TOKEN", "env-secret", raising=False)

    assert service.has_configured_token() is True
    env_auth = service.verify_token("env-secret")
    assert env_auth is not None
    assert env_auth["auth_method"] == "mcp_token"
    assert env_auth["token_source"] == "env"

    service.create_token(name="Codex", expires_in_days=7)
    status = service.get_status()
    assert status["configured"] is True
    assert status["env_token_configured"] is True
    assert status["active_token_count"] == 1


def test_settings_api_can_generate_list_and_revoke_mcp_agent_tokens(monkeypatch, tmp_path: Path) -> None:
    service = _service(tmp_path)
    import app.api.v2.endpoints.settings as settings_endpoint  # noqa: E402

    monkeypatch.setattr(settings_endpoint, "mcp_token_service", service, raising=False)
    app = FastAPI()
    app.include_router(settings_endpoint.router, prefix="/api/v2/settings")
    client = TestClient(app, raise_server_exceptions=False)

    created = client.post(
        "/api/v2/settings/mcp-agent-tokens",
        json={"name": "Hermes", "expires_in_days": 14, "rate_limit_per_min": 99},
    )

    assert created.status_code == 200
    payload = created.json()
    assert payload["token"].startswith("bp_mcp_")
    assert payload["item"]["name"] == "Hermes"
    assert payload["item"]["rate_limit_per_min"] == 99

    listed = client.get("/api/v2/settings/mcp-agent-tokens")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["name"] == "Hermes"
    assert "token" not in listed.json()["items"][0]
    assert listed.json()["policy"]["plaintext_returned_once"] is True

    revoked = client.delete(f"/api/v2/settings/mcp-agent-tokens/{payload['item']['id']}")
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"]
