"""Security-aware settings service for the active PostgreSQL runtime."""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.domain.settings.repository import PostgresSettingsRepository


FEISHU_SETTING_KEY = "feishu_webhook"
FEISHU_HOSTS = {"open.feishu.cn", "open.larksuite.com"}
FEISHU_PATH_RE = re.compile(r"^/open-apis/bot/v2/hook/[A-Za-z0-9_-]{8,}$")
TOOL_GROUP_SCOPES = {
    "read": "R",
    "research_backtest_paper_mutation": "W",
    "live_diagnostic": "L",
    "live_mutation": "T",
}
DEFAULT_TOOL_GROUPS = ["read", "research_backtest_paper_mutation", "live_diagnostic"]


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


class PostgresSettingsService:
    def __init__(self, repository: PostgresSettingsRepository | None = None) -> None:
        self.repository = repository or PostgresSettingsRepository()

    @staticmethod
    def _cipher() -> Fernet:
        secret = str(settings.BITPRO_AUTH_TOKEN_SECRET or "").strip()
        if not secret:
            raise RuntimeError("BITPRO_AUTH_TOKEN_SECRET is required to encrypt settings")
        digest = hashlib.sha256(f"stockpro-settings-v1:{secret}".encode()).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    @staticmethod
    def _validate_feishu_webhook(raw: str) -> str:
        value = str(raw or "").strip()
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in FEISHU_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or not FEISHU_PATH_RE.fullmatch(parsed.path)
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("请填写有效的飞书机器人 Webhook URL")
        return value

    @staticmethod
    def _mask_webhook(value: str) -> str | None:
        if not value:
            return None
        prefix, token = value.rsplit("/", 1)
        masked = "****" if len(token) <= 8 else f"****{token[:4]}...{token[-4:]}"
        return f"{prefix}/{masked}"

    def resolve_feishu_webhook(self) -> str:
        env_value = str(settings.FEISHU_WEBHOOK_URL or "").strip()
        if env_value:
            return env_value
        stored = self.repository.get_setting(FEISHU_SETTING_KEY) or {}
        ciphertext = str(stored.get("ciphertext") or "").strip()
        if not ciphertext:
            return ""
        try:
            return self._cipher().decrypt(ciphertext.encode()).decode()
        except (InvalidToken, ValueError):
            return ""

    def get_feishu_webhook(self) -> dict[str, Any]:
        value = self.resolve_feishu_webhook()
        source = "env" if str(settings.FEISHU_WEBHOOK_URL or "").strip() else "database" if value else "none"
        return {
            "webhook_configured": bool(value),
            "masked_webhook_url": self._mask_webhook(value),
            "source": source,
        }

    def set_feishu_webhook(self, webhook_url: str, *, updated_by: str) -> dict[str, Any]:
        value = self._validate_feishu_webhook(webhook_url)
        ciphertext = self._cipher().encrypt(value.encode()).decode()
        self.repository.set_setting(
            FEISHU_SETTING_KEY,
            {"version": 1, "ciphertext": ciphertext},
            updated_by=updated_by,
        )
        return {
            "webhook_configured": True,
            "masked_webhook_url": self._mask_webhook(value),
            "source": "database",
        }

    @staticmethod
    def _normalize_tool_groups(tool_groups: list[str] | None) -> list[str]:
        groups = [str(item).strip() for item in (tool_groups or DEFAULT_TOOL_GROUPS) if str(item).strip()]
        invalid = [item for item in groups if item not in TOOL_GROUP_SCOPES]
        if invalid:
            raise ValueError(f"不支持的 MCP tool group: {', '.join(invalid)}")
        return list(dict.fromkeys(groups or DEFAULT_TOOL_GROUPS))

    @staticmethod
    def _serialize_token(row: dict) -> dict[str, Any]:
        prefix = str(row.get("token_prefix") or "")
        return {
            "id": int(row["id"]),
            "name": str(row.get("name") or "MCP Agent"),
            "token_prefix": prefix,
            "masked_token": f"{prefix}****",
            "scopes": [str(item) for item in row.get("scopes") or []],
            "tool_groups": [str(item) for item in row.get("tool_groups") or []],
            "rate_limit_per_min": int(row.get("rate_limit_per_min") or 120),
            "expires_at": _iso(row.get("expires_at")),
            "created_at": _iso(row.get("created_at")),
            "created_by": row.get("created_by"),
            "last_used_at": _iso(row.get("last_used_at")),
            "revoked_at": _iso(row.get("revoked_at")),
        }

    @staticmethod
    def _env_token_configured() -> bool:
        return bool(
            str(getattr(settings, "STOCKPRO_MCP_API_TOKEN", "") or "").strip()
            or str(settings.BITPRO_MCP_API_TOKEN or "").strip()
        )

    def list_mcp_tokens(self) -> dict[str, Any]:
        items = [self._serialize_token(row) for row in self.repository.list_mcp_tokens()]
        env_configured = self._env_token_configured()
        return {
            "items": items,
            "policy": {
                "plaintext_returned_once": True,
                "static_token_env": "STOCKPRO_MCP_API_TOKEN",
                "auth_header_default": "X-StockPro-MCP-Token",
                "legacy_token_env": "BITPRO_MCP_API_TOKEN",
                "legacy_auth_header": "X-BitPro-MCP-Token",
                "storage": "postgresql_sha256_hash_only",
            },
            "status": {
                "configured": env_configured or bool(items),
                "env_token_configured": env_configured,
                "active_token_count": len(items),
            },
        }

    def create_mcp_token(
        self,
        *,
        name: str,
        expires_in_days: int,
        rate_limit_per_min: int,
        tool_groups: list[str] | None,
        created_by: str,
    ) -> dict[str, Any]:
        groups = self._normalize_tool_groups(tool_groups)
        token = f"sp_mcp_{secrets.token_urlsafe(32)}"
        payload = {
            "name": str(name or "").strip() or "MCP Agent",
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "token_prefix": token[:18],
            "scopes": [TOOL_GROUP_SCOPES[group] for group in groups],
            "tool_groups": groups,
            "rate_limit_per_min": max(1, min(10_000, int(rate_limit_per_min or 120))),
            "expires_at": datetime.now(timezone.utc) + timedelta(days=max(1, min(3650, int(expires_in_days or 90)))),
            "created_by": str(created_by or "admin"),
        }
        row = self.repository.create_mcp_token(payload)
        return {"token": token, "item": self._serialize_token(row)}

    def revoke_mcp_token(self, token_id: int) -> dict[str, Any]:
        result = self.repository.revoke_mcp_token(int(token_id))
        return {"id": int(result["id"]), "revoked_at": _iso(result.get("revoked_at"))}

    def get_mcp_token_status(self) -> dict[str, Any]:
        listed = self.list_mcp_tokens()
        return {
            "configured": listed["status"]["configured"],
            "source": "env" if listed["status"]["env_token_configured"] else "generated" if listed["items"] else "none",
            "masked_token": listed["items"][0]["masked_token"] if listed["items"] else None,
            "created_at": listed["items"][0]["created_at"] if listed["items"] else None,
            "updated_at": listed["items"][0]["last_used_at"] if listed["items"] else None,
            "note": listed["items"][0]["name"] if listed["items"] else None,
            "auth_header": "X-StockPro-MCP-Token",
            "token_env": "STOCKPRO_MCP_API_TOKEN",
            "legacy_auth_header": "X-BitPro-MCP-Token",
            "legacy_token_env": "BITPRO_MCP_API_TOKEN",
            "remote_enabled": bool(settings.BITPRO_REMOTE_MCP_ENABLED),
            "remote_path": str(settings.BITPRO_REMOTE_MCP_PATH or "/api/v2/mcp"),
            "require_token": bool(settings.BITPRO_REMOTE_MCP_REQUIRE_TOKEN),
        }


postgres_settings_service = PostgresSettingsService()
