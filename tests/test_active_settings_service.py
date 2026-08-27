from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.core.auth_middleware import mcp_token_auth  # noqa: E402
from app.api.v2.endpoints import settings as settings_endpoint  # noqa: E402

try:  # pragma: no cover - keeps the red test as an assertion, not collection failure.
    from app.domain.settings.service import PostgresSettingsService
except ModuleNotFoundError:  # pragma: no cover
    PostgresSettingsService = None  # type: ignore[assignment]


class MemorySettingsRepository:
    def __init__(self) -> None:
        self.settings: dict[str, dict] = {}
        self.tokens: list[dict] = []

    def get_setting(self, key: str) -> dict | None:
        return self.settings.get(key)

    def set_setting(self, key: str, value: dict, *, updated_by: str) -> None:
        self.settings[key] = dict(value)

    def list_mcp_tokens(self) -> list[dict]:
        return [dict(item) for item in reversed(self.tokens) if item.get("revoked_at") is None]

    def create_mcp_token(self, payload: dict) -> dict:
        row = {"id": len(self.tokens) + 1, **payload, "created_at": "2026-08-27T15:00:00+00:00", "last_used_at": None, "revoked_at": None}
        self.tokens.append(row)
        return dict(row)

    def revoke_mcp_token(self, token_id: int) -> dict:
        for item in self.tokens:
            if item["id"] == token_id:
                item["revoked_at"] = "2026-08-27T15:05:00+00:00"
                return {"id": token_id, "revoked_at": item["revoked_at"]}
        return {"id": token_id, "revoked_at": None}


@pytest.fixture
def service(monkeypatch) -> tuple[object, MemorySettingsRepository]:
    assert PostgresSettingsService is not None, "PostgresSettingsService should exist"
    repository = MemorySettingsRepository()
    monkeypatch.setattr(settings, "BITPRO_AUTH_TOKEN_SECRET", "test-settings-secret", raising=False)
    monkeypatch.setattr(settings, "STOCKPRO_MCP_API_TOKEN", "", raising=False)
    monkeypatch.setattr(settings, "BITPRO_MCP_API_TOKEN", "", raising=False)
    return PostgresSettingsService(repository=repository), repository


def test_feishu_webhook_is_encrypted_at_rest_and_only_masked_on_read(service) -> None:
    settings_service, repository = service
    webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/abcdef1234567890"

    saved = settings_service.set_feishu_webhook(webhook, updated_by="admin-session")

    stored = repository.settings["feishu_webhook"]
    assert stored["ciphertext"]
    assert webhook not in str(stored)
    assert saved == {
        "webhook_configured": True,
        "masked_webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/****abcd...7890",
        "source": "database",
    }
    assert settings_service.get_feishu_webhook() == saved
    assert settings_service.resolve_feishu_webhook() == webhook


@pytest.mark.parametrize(
    "url",
    [
        "http://open.feishu.cn/open-apis/bot/v2/hook/token",
        "https://127.0.0.1/open-apis/bot/v2/hook/token",
        "https://open.feishu.cn.evil.example/open-apis/bot/v2/hook/token",
        "https://open.feishu.cn/open-apis/contact/v3/users",
    ],
)
def test_feishu_webhook_rejects_non_allowlisted_targets(service, url: str) -> None:
    settings_service, _ = service

    with pytest.raises(ValueError, match="飞书机器人 Webhook"):
        settings_service.set_feishu_webhook(url, updated_by="admin-session")


def test_mcp_token_plaintext_is_returned_once_and_repository_keeps_hash_only(service) -> None:
    settings_service, repository = service

    created = settings_service.create_mcp_token(
        name="Codex production",
        expires_in_days=30,
        rate_limit_per_min=120,
        tool_groups=["read", "research_backtest_paper_mutation", "live_diagnostic"],
        created_by="admin-session",
    )

    token = created["token"]
    stored = repository.tokens[0]
    assert token.startswith("sp_mcp_")
    assert stored["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str(stored)
    assert created["item"]["masked_token"].startswith("sp_mcp_")

    listed = settings_service.list_mcp_tokens()
    assert listed["status"] == {
        "configured": True,
        "env_token_configured": False,
        "active_token_count": 1,
    }
    assert "token" not in listed["items"][0]
    assert token not in str(listed)

    revoked = settings_service.revoke_mcp_token(created["item"]["id"])
    assert revoked["revoked_at"]
    assert settings_service.list_mcp_tokens()["status"]["active_token_count"] == 0


def build_settings_client(settings_service, *, role: str = "admin") -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def inject_auth(request: Request, call_next):
        request.state.auth = {"authenticated": True, "role": role, "session_id": f"{role}-session"}
        return await call_next(request)

    app.include_router(settings_endpoint.router, prefix="/api/v2/settings")
    settings_endpoint.postgres_settings_service = settings_service
    return TestClient(app, raise_server_exceptions=False)


def test_settings_routes_complete_admin_read_create_and_revoke_cycle(service) -> None:
    settings_service, _ = service
    client = build_settings_client(settings_service)

    assert client.get("/api/v2/settings/feishu-webhook").status_code == 200
    assert client.get("/api/v2/settings/mcp-token").status_code == 200
    assert client.get("/api/v2/settings/mcp-agent-tokens").status_code == 200

    created = client.post(
        "/api/v2/settings/mcp-agent-tokens",
        json={"name": "Codex", "expires_in_days": 30, "rate_limit_per_min": 90},
    )
    assert created.status_code == 200
    token = created.json()["token"]
    assert token.startswith("sp_mcp_")

    listed = client.get("/api/v2/settings/mcp-agent-tokens")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["name"] == "Codex"
    assert token not in str(listed.json())

    token_id = created.json()["item"]["id"]
    revoked = client.delete(f"/api/v2/settings/mcp-agent-tokens/{token_id}")
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"]


def test_settings_routes_require_admin_and_reject_unsafe_webhook(service) -> None:
    settings_service, _ = service
    guest = build_settings_client(settings_service, role="guest")

    for path in ("/feishu-webhook", "/mcp-token", "/mcp-agent-tokens"):
        assert guest.get(f"/api/v2/settings{path}").status_code == 403

    admin = build_settings_client(settings_service)
    invalid = admin.post(
        "/api/v2/settings/feishu-webhook",
        json={"webhook_url": "https://127.0.0.1/open-apis/bot/v2/hook/metadata"},
    )
    assert invalid.status_code == 400
    assert "飞书机器人 Webhook" in invalid.json()["detail"]


def test_mcp_auth_prefers_stockpro_header_and_keeps_legacy_fallback(monkeypatch) -> None:
    captured: list[str] = []
    monkeypatch.setattr(
        "app.core.auth_middleware.postgres_mcp_token_verifier.verify_token",
        lambda token: captured.append(token) or ({"authenticated": True} if token else None),
    )
    monkeypatch.setattr(settings, "STOCKPRO_MCP_AUTH_HEADER", "X-StockPro-MCP-Token")
    monkeypatch.setattr(settings, "BITPRO_MCP_AUTH_HEADER", "X-BitPro-MCP-Token")

    primary = StarletteRequest({
        "type": "http",
        "method": "GET",
        "path": "/api/v2/system/health",
        "headers": [(b"x-stockpro-mcp-token", b"primary-secret"), (b"x-bitpro-mcp-token", b"legacy-secret")],
    })
    assert mcp_token_auth(primary) == {"authenticated": True}
    assert captured[-1] == "primary-secret"

    legacy = StarletteRequest({
        "type": "http",
        "method": "GET",
        "path": "/api/v2/system/health",
        "headers": [(b"x-bitpro-mcp-token", b"legacy-secret")],
    })
    assert mcp_token_auth(legacy) == {"authenticated": True}
    assert captured[-1] == "legacy-secret"
