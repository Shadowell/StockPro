"""PostgreSQL persistence for operator settings and MCP Agent tokens."""
from __future__ import annotations

from typing import Callable

import psycopg2
import psycopg2.extras

from app.core.config import settings


class PostgresSettingsRepository:
    def __init__(
        self,
        database_url: str | None = None,
        *,
        connection_factory: Callable[..., object] = psycopg2.connect,
    ) -> None:
        self.database_url = database_url or settings.DATABASE_URL
        self.connection_factory = connection_factory

    def _connect(self, *, readonly: bool):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for settings")
        connection = self.connection_factory(self.database_url)
        connection.set_session(readonly=readonly, autocommit=False)
        return connection

    def get_setting(self, key: str) -> dict | None:
        with self._connect(readonly=True) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT value FROM app_settings WHERE key=%s", (key,))
                row = cursor.fetchone()
        value = (row or {}).get("value")
        return dict(value) if isinstance(value, dict) else None

    def set_setting(self, key: str, value: dict, *, updated_by: str) -> None:
        with self._connect(readonly=False) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO app_settings(key,value,updated_by,updated_at)
                       VALUES (%s,%s,%s,NOW())
                       ON CONFLICT (key) DO UPDATE SET
                         value=EXCLUDED.value,
                         updated_by=EXCLUDED.updated_by,
                         updated_at=NOW()""",
                    (key, psycopg2.extras.Json(value), updated_by),
                )

    def list_mcp_tokens(self) -> list[dict]:
        with self._connect(readonly=True) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """SELECT id,name,token_prefix,scopes,tool_groups,rate_limit_per_min,
                              expires_at,created_by,created_at,last_used_at,revoked_at
                       FROM mcp_agent_tokens
                       WHERE revoked_at IS NULL
                         AND (expires_at IS NULL OR expires_at>NOW())
                       ORDER BY created_at DESC,id DESC"""
                )
                return [dict(row) for row in cursor.fetchall()]

    def create_mcp_token(self, payload: dict) -> dict:
        with self._connect(readonly=False) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """INSERT INTO mcp_agent_tokens
                       (name,token_hash,token_hint,token_prefix,scopes,tool_groups,
                        rate_limit_per_min,expires_at,created_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       RETURNING id,name,token_prefix,token_hash,scopes,tool_groups,
                                 rate_limit_per_min,expires_at,created_by,created_at,
                                 last_used_at,revoked_at""",
                    (
                        payload["name"],
                        payload["token_hash"],
                        payload["token_prefix"],
                        payload["token_prefix"],
                        payload["scopes"],
                        psycopg2.extras.Json(payload["tool_groups"]),
                        payload["rate_limit_per_min"],
                        payload["expires_at"],
                        payload["created_by"],
                    ),
                )
                return dict(cursor.fetchone())

    def revoke_mcp_token(self, token_id: int) -> dict:
        with self._connect(readonly=False) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """UPDATE mcp_agent_tokens SET revoked_at=NOW()
                       WHERE id=%s AND revoked_at IS NULL
                       RETURNING id,revoked_at""",
                    (int(token_id),),
                )
                row = cursor.fetchone()
        return dict(row) if row else {"id": int(token_id), "revoked_at": None}
