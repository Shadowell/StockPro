"""Persistent MCP Agent token management."""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import settings
from app.db.local_db import LocalDatabase, db_instance
from app.mcp.schemas import MCP_AGENT_AUTH_POLICY, MCP_SCOPE_CLASSES


DEFAULT_TOOL_GROUPS = ["read", "research_backtest_paper_mutation", "live_diagnostic"]
MCP_TOKEN_SETTING_KEY = "mcp_api_token"
TOOL_GROUP_TO_SCOPE = {
    "read": "R",
    "research_backtest_paper_mutation": "W",
    "live_diagnostic": "L",
    "live_mutation": "T",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _loads_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return [part.strip() for part in text.split(",") if part.strip()]
    if isinstance(loaded, list):
        return [str(item) for item in loaded]
    return []


class McpAgentTokenService:
    def __init__(self, db: LocalDatabase | None = None) -> None:
        self.db = db or db_instance
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = self.db.get_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mcp_agent_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                token_prefix TEXT NOT NULL,
                scopes TEXT NOT NULL DEFAULT '[]',
                tool_groups TEXT NOT NULL DEFAULT '[]',
                rate_limit_per_min INTEGER DEFAULT 120,
                expires_at TEXT,
                revoked_at TEXT,
                created_by TEXT DEFAULT 'admin',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_used_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mcp_agent_tokens_hash
            ON mcp_agent_tokens(token_hash)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mcp_agent_tokens_active
            ON mcp_agent_tokens(revoked_at, expires_at, created_at)
            """
        )
        conn.commit()

    def create_token(
        self,
        *,
        name: str,
        expires_in_days: int = 90,
        rate_limit_per_min: int = 120,
        tool_groups: list[str] | None = None,
        created_by: str = "admin",
    ) -> dict[str, Any]:
        name = str(name or "").strip() or "MCP Agent"
        normalized_groups = self._normalize_tool_groups(tool_groups)
        scopes = [TOOL_GROUP_TO_SCOPE[group] for group in normalized_groups]
        token = f"bp_mcp_{secrets.token_urlsafe(32)}"
        token_prefix = token[:18]
        expires_at = _now() + timedelta(days=max(1, int(expires_in_days or 90)))
        rate_limit = max(1, min(10_000, int(rate_limit_per_min or 120)))

        conn = self.db.get_connection()
        cursor = conn.execute(
            """
            INSERT INTO mcp_agent_tokens
            (name, token_hash, token_prefix, scopes, tool_groups, rate_limit_per_min, expires_at, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                _hash_secret(token),
                token_prefix,
                json.dumps(scopes, ensure_ascii=False),
                json.dumps(normalized_groups, ensure_ascii=False),
                rate_limit,
                _iso(expires_at),
                str(created_by or "admin"),
                _iso(_now()),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM mcp_agent_tokens WHERE id = ?", (int(cursor.lastrowid),)).fetchone()
        return {"token": token, "item": self._row_to_item(row)}

    def list_tokens(self) -> dict[str, Any]:
        rows = self.db.get_connection().execute(
            """
            SELECT * FROM mcp_agent_tokens
            WHERE revoked_at IS NULL
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
        return {
            "items": [self._row_to_item(row) for row in rows],
            "policy": self.get_policy(),
            "status": self.get_status(),
        }

    def revoke_token(self, token_id: int) -> dict[str, Any]:
        revoked_at = _iso(_now())
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE mcp_agent_tokens SET revoked_at = ? WHERE id = ?",
            (revoked_at, int(token_id)),
        )
        conn.commit()
        return {"id": int(token_id), "revoked_at": revoked_at}

    def verify_token(self, token: str | None) -> dict[str, Any] | None:
        token = str(token or "").strip()
        if not token:
            return None

        env_token = str(getattr(settings, "BITPRO_MCP_API_TOKEN", "") or "").strip()
        if env_token and secrets.compare_digest(token, env_token):
            return {
                "authenticated": True,
                "role": "admin",
                "auth_enabled": bool(settings.BITPRO_AUTH_ENABLED),
                "auth_method": "mcp_token",
                "token_source": "env",
                "tool_groups": ["read", "research_backtest_paper_mutation", "live_diagnostic", "live_mutation"],
                "scopes": ["R", "W", "L", "T"],
            }

        token_hash = _hash_secret(token)
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM mcp_agent_tokens WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        if not row or row["revoked_at"]:
            legacy_auth = self._verify_legacy_record(token)
            if legacy_auth:
                return legacy_auth
            return None
        expires_at = str(row["expires_at"] or "")
        if expires_at and expires_at <= _iso(_now()):
            return None
        conn.execute("UPDATE mcp_agent_tokens SET last_used_at = ? WHERE id = ?", (_iso(_now()), int(row["id"])))
        conn.commit()
        item = self._row_to_item(row)
        return {
            "authenticated": True,
            "role": "admin",
            "auth_enabled": bool(settings.BITPRO_AUTH_ENABLED),
            "auth_method": "mcp_token",
            "token_source": "db",
            "token_id": item["id"],
            "token_name": item["name"],
            "token_prefix": item["token_prefix"],
            "scopes": item["scopes"],
            "tool_groups": item["tool_groups"],
            "rate_limit_per_min": item["rate_limit_per_min"],
        }

    def has_configured_token(self) -> bool:
        return bool(self.get_status()["configured"])

    def get_status(self) -> dict[str, Any]:
        env_configured = bool(str(getattr(settings, "BITPRO_MCP_API_TOKEN", "") or "").strip())
        now = _iso(_now())
        try:
            row = self.db.get_connection().execute(
                """
                SELECT COUNT(*) AS count
                FROM mcp_agent_tokens
                WHERE revoked_at IS NULL
                  AND (expires_at IS NULL OR expires_at > ?)
                """,
                (now,),
            ).fetchone()
            active_count = int(row["count"] or 0)
        except Exception:
            active_count = 0
        return {
            "configured": env_configured or active_count > 0 or bool(self._load_legacy_record()),
            "env_token_configured": env_configured,
            "active_token_count": active_count,
        }

    def get_policy(self) -> dict[str, Any]:
        return {
            **MCP_AGENT_AUTH_POLICY,
            "scope_classes": {key: dict(value) for key, value in MCP_SCOPE_CLASSES.items()},
        }

    def legacy_status(self) -> dict[str, Any]:
        status = self.get_status()
        record = self._load_legacy_record()
        latest = self.db.get_connection().execute(
            """
            SELECT * FROM mcp_agent_tokens
            WHERE revoked_at IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        env_token = str(getattr(settings, "BITPRO_MCP_API_TOKEN", "") or "").strip()
        source = "none"
        masked_token: str | None = None
        created_at: str | None = None
        updated_at: str | None = None
        note: str | None = None

        if env_token and record and secrets.compare_digest(_hash_secret(env_token), str(record.get("token_hash") or "")):
            source = str(record.get("source") or "generated")
            masked_token = str(record.get("masked_token") or "") or self._mask_env_token(env_token)
            created_at = record.get("created_at")
            updated_at = record.get("updated_at")
            note = record.get("note")
        elif env_token:
            source = "env"
            masked_token = self._mask_env_token(env_token)
        elif record:
            source = str(record.get("source") or "generated")
            masked_token = str(record.get("masked_token") or "") or None
            created_at = record.get("created_at")
            updated_at = record.get("updated_at")
            note = record.get("note")
        elif latest:
            item = self._row_to_item(latest)
            source = "generated"
            masked_token = item["masked_token"]
            created_at = item["created_at"]
            updated_at = item["last_used_at"] or item["created_at"]
            note = item["name"]

        return {
            "configured": bool(status["configured"]),
            "source": source,
            "masked_token": masked_token,
            "created_at": created_at,
            "updated_at": updated_at,
            "note": note,
            "auth_header": str(getattr(settings, "BITPRO_MCP_AUTH_HEADER", "X-BitPro-MCP-Token") or "").strip(),
            "token_env": "BITPRO_MCP_API_TOKEN",
            "remote_enabled": bool(getattr(settings, "BITPRO_REMOTE_MCP_ENABLED", False)),
            "remote_path": str(getattr(settings, "BITPRO_REMOTE_MCP_PATH", "/api/v2/mcp") or "").strip(),
            "require_token": bool(getattr(settings, "BITPRO_REMOTE_MCP_REQUIRE_TOKEN", True)),
        }

    def generate_legacy_token(self, *, note: str = "") -> dict[str, Any]:
        note_text = str(note or "").strip()
        created = self.create_token(name=note_text or "MCP Agent")
        created_at = str(created["item"]["created_at"] or _iso(_now()))
        record = {
            "version": 1,
            "source": "generated",
            "token_hash": _hash_secret(created["token"]),
            "masked_token": self._mask_env_token(created["token"]),
            "note": note_text,
            "created_at": created_at,
            "updated_at": created_at,
        }
        self.db.set_app_setting(MCP_TOKEN_SETTING_KEY, json.dumps(record, ensure_ascii=False, sort_keys=True))
        settings.BITPRO_MCP_API_TOKEN = created["token"]
        return {
            **self.legacy_status(),
            "configured": True,
            "source": "generated",
            "masked_token": record["masked_token"],
            "created_at": created_at,
            "updated_at": created_at,
            "note": note_text,
            "token": created["token"],
        }

    def _normalize_tool_groups(self, tool_groups: list[str] | None) -> list[str]:
        allowed = set(TOOL_GROUP_TO_SCOPE)
        groups = [str(group).strip() for group in (tool_groups or DEFAULT_TOOL_GROUPS) if str(group).strip()]
        invalid = [group for group in groups if group not in allowed]
        if invalid:
            raise ValueError(f"不支持的 MCP tool group: {', '.join(invalid)}")
        if not groups:
            groups = list(DEFAULT_TOOL_GROUPS)
        return list(dict.fromkeys(groups))

    def _row_to_item(self, row: Any) -> dict[str, Any]:
        row_dict = dict(row)
        scopes = _loads_list(row_dict.get("scopes"))
        tool_groups = _loads_list(row_dict.get("tool_groups"))
        token_prefix = str(row_dict.get("token_prefix") or "")
        return {
            "id": int(row_dict["id"]),
            "name": row_dict.get("name") or "MCP Agent",
            "token_prefix": token_prefix,
            "masked_token": f"{token_prefix}****",
            "scopes": scopes,
            "tool_groups": tool_groups,
            "rate_limit_per_min": int(row_dict.get("rate_limit_per_min") or 120),
            "expires_at": row_dict.get("expires_at"),
            "created_at": row_dict.get("created_at"),
            "created_by": row_dict.get("created_by"),
            "last_used_at": row_dict.get("last_used_at"),
            "revoked_at": row_dict.get("revoked_at"),
        }

    @staticmethod
    def _mask_env_token(token: str) -> str | None:
        value = str(token or "").strip()
        if not value:
            return None
        if len(value) <= 16:
            return f"{value[:4]}...{value[-4:]}"
        return f"{value[:10]}...{value[-6:]}"

    def _load_legacy_record(self) -> dict[str, Any] | None:
        raw = str(self.db.get_app_setting(MCP_TOKEN_SETTING_KEY, "") or "").strip()
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict) or not str(data.get("token_hash") or "").strip():
            return None
        return data

    def _verify_legacy_record(self, token: str) -> dict[str, Any] | None:
        record = self._load_legacy_record()
        expected_hash = str((record or {}).get("token_hash") or "").strip()
        if not expected_hash or not secrets.compare_digest(_hash_secret(token), expected_hash):
            return None
        return {
            "authenticated": True,
            "role": "admin",
            "auth_enabled": bool(settings.BITPRO_AUTH_ENABLED),
            "auth_method": "mcp_token",
            "token_source": str(record.get("source") or "generated"),
            "tool_groups": ["read", "research_backtest_paper_mutation", "live_diagnostic"],
            "scopes": ["R", "W", "L"],
        }


mcp_token_service = McpAgentTokenService()


def get_mcp_token_status() -> dict[str, Any]:
    return mcp_token_service.legacy_status()


def generate_mcp_api_token(*, note: str = "") -> dict[str, Any]:
    return mcp_token_service.generate_legacy_token(note=note)


def verify_mcp_api_token(provided_token: str | None) -> bool:
    return mcp_token_service.verify_token(provided_token) is not None
