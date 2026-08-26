"""Read-only PostgreSQL verifier for MCP Agent tokens."""
from __future__ import annotations

import hashlib
import secrets

import psycopg2.extras

from app.core.config import settings
from app.domain.auth.repository import PostgresAuthRepository


SCOPE_TOOL_GROUPS = {
    "R": "read",
    "W": "research_backtest_paper_mutation",
    "L": "live_diagnostic",
    "T": "live_mutation",
}


class PostgresMcpTokenVerifier:
    def __init__(self, repository: PostgresAuthRepository | None = None) -> None:
        self.repository = repository or PostgresAuthRepository()

    def verify_token(self, token: str | None) -> dict | None:
        value = str(token or "").strip()
        if not value:
            return None
        env_token = str(settings.BITPRO_MCP_API_TOKEN or "").strip()
        if env_token and secrets.compare_digest(value, env_token):
            return {
                "authenticated": True,
                "role": "admin",
                "auth_enabled": bool(settings.BITPRO_AUTH_ENABLED),
                "auth_method": "mcp_token",
                "token_source": "env",
                "tool_groups": list(SCOPE_TOOL_GROUPS.values()),
                "scopes": list(SCOPE_TOOL_GROUPS),
            }
        token_hash = hashlib.sha256(value.encode()).hexdigest()
        with self.repository._connect(readonly=False) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """SELECT id,name,token_hint,scopes,created_by,created_at,last_used_at
                       FROM mcp_agent_tokens
                       WHERE token_hash=%s AND revoked_at IS NULL""",
                    (token_hash,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                cursor.execute("UPDATE mcp_agent_tokens SET last_used_at=NOW() WHERE id=%s", (row["id"],))
        scopes = [str(scope) for scope in row.get("scopes") or [] if str(scope) in SCOPE_TOOL_GROUPS]
        return {
            "authenticated": True,
            "role": "admin",
            "auth_enabled": bool(settings.BITPRO_AUTH_ENABLED),
            "auth_method": "mcp_token",
            "token_source": "postgresql",
            "token_id": int(row["id"]),
            "token_name": row.get("name"),
            "token_prefix": row.get("token_hint"),
            "scopes": scopes,
            "tool_groups": [SCOPE_TOOL_GROUPS[scope] for scope in scopes],
        }


postgres_mcp_token_verifier = PostgresMcpTokenVerifier()
