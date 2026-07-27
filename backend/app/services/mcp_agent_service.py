from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any, Iterable

import psycopg2
import psycopg2.extras


MCP_AUTH_HEADER = "X-StockPro-MCP-Token"
VALID_MCP_SCOPES = {"R", "W"}
_READ_PATHS = (
    re.compile(r"^/api/market/(?:overview|research-context)$"),
    re.compile(r"^/api/strategy/(?:list|\d+)$"),
    re.compile(r"^/api/backtest/jobs(?:/[0-9a-f-]+(?:/logs)?)?$"),
    re.compile(r"^/api/backtest/runs(?:/[0-9a-f-]+)?$"),
    re.compile(r"^/api/paper/instances(?:/[0-9a-f-]+)?$"),
    re.compile(r"^/api/watch/context$"),
    re.compile(r"^/api/monitor/health$"),
    re.compile(r"^/api/review/(?:dates|\d{4}-\d{2}-\d{2})$"),
    re.compile(r"^/api/data/(?:status|datasets|snapshots)$"),
    re.compile(r"^/api/workflow/capabilities$"),
)
_WRITE_PATHS = (
    re.compile(r"^/api/backtest/jobs$"),
    re.compile(r"^/api/backtest/jobs/[0-9a-f-]+/(?:cancel|retry)$"),
)


class McpAgentError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


class McpAgentService:
    def __init__(self, database) -> None:
        self.database = database

    def create_token(
        self,
        *,
        name: str,
        scopes: Iterable[str],
        created_by: str,
    ) -> dict[str, Any]:
        normalized_scopes = sorted({str(scope).upper() for scope in scopes})
        if not normalized_scopes or not set(normalized_scopes) <= VALID_MCP_SCOPES:
            raise McpAgentError("Agent scope 只能包含 R 或 W")
        token = f"sp_mcp_{secrets.token_urlsafe(32)}"
        token_hint = f"{token[:11]}…{token[-4:]}"
        with self.database.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO mcp_agent_tokens
                        (name, token_hash, token_hint, scopes, created_by)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, name, token_hint, scopes, created_by,
                              created_at, last_used_at, revoked_at
                    """,
                    (
                        name.strip() or "StockPro Agent",
                        _hash_token(token),
                        token_hint,
                        normalized_scopes,
                        created_by,
                    ),
                )
                row = dict(cursor.fetchone())
            conn.commit()
        row["token"] = token
        return self._serialize(row)

    def list_tokens(self) -> list[dict[str, Any]]:
        return self._rows(
            """
            SELECT id, name, token_hint, scopes, created_by,
                   created_at, last_used_at, revoked_at
            FROM mcp_agent_tokens
            ORDER BY created_at DESC, id DESC
            """,
            (),
        )

    def revoke_token(self, token_id: int) -> dict[str, Any]:
        with self.database.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE mcp_agent_tokens
                    SET revoked_at = COALESCE(revoked_at, NOW())
                    WHERE id = %s
                    RETURNING id, name, token_hint, scopes, created_by,
                              created_at, last_used_at, revoked_at
                    """,
                    (token_id,),
                )
                row = cursor.fetchone()
                if not row:
                    raise McpAgentError("Agent token 不存在", 404)
            conn.commit()
        return self._serialize(dict(row))

    def authenticate(
        self,
        token: str,
        *,
        method: str,
        path: str,
        tool_name: str | None,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        token_hash = _hash_token(token)
        with self.database.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, name, token_hint, scopes, revoked_at
                    FROM mcp_agent_tokens
                    WHERE token_hash = %s
                    FOR UPDATE
                    """,
                    (token_hash,),
                )
                row = cursor.fetchone()
                if not row or row["revoked_at"] is not None:
                    self._audit(
                        cursor,
                        token_id=int(row["id"]) if row else None,
                        tool_name=tool_name,
                        method=method,
                        path=path,
                        decision="denied",
                        reason="invalid_or_revoked_token",
                        idempotency_key=idempotency_key,
                    )
                    conn.commit()
                    raise McpAgentError("Agent token 无效或已撤销", 401)
                token_row = dict(row)
                required_scope = "R" if method.upper() in {"GET", "HEAD", "OPTIONS"} else "W"
                scopes = set(token_row.get("scopes") or [])
                if not self._path_allowed(method, path):
                    self._audit(
                        cursor,
                        token_id=int(token_row["id"]),
                        tool_name=tool_name,
                        method=method,
                        path=path,
                        decision="denied",
                        reason="tool_path_not_allowed",
                        idempotency_key=idempotency_key,
                    )
                    conn.commit()
                    raise McpAgentError("该接口不在 stockpro-mcp-v1 工具合同内", 403)
                if required_scope not in scopes:
                    self._audit(
                        cursor,
                        token_id=int(token_row["id"]),
                        tool_name=tool_name,
                        method=method,
                        path=path,
                        decision="denied",
                        reason=f"missing_scope:{required_scope}",
                        idempotency_key=idempotency_key,
                    )
                    conn.commit()
                    raise McpAgentError(f"Agent token 缺少 {required_scope} 权限", 403)
                if required_scope == "W":
                    key = str(idempotency_key or "").strip()
                    if not key:
                        self._audit(
                            cursor,
                            token_id=int(token_row["id"]),
                            tool_name=tool_name,
                            method=method,
                            path=path,
                            decision="denied",
                            reason="missing_idempotency_key",
                            idempotency_key=None,
                        )
                        conn.commit()
                        raise McpAgentError("Agent 写操作必须提供 Idempotency-Key", 400)
                    try:
                        cursor.execute(
                            """
                            INSERT INTO mcp_idempotency_records
                                (token_id, tool_name, idempotency_key, path)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (
                                token_row["id"],
                                tool_name or f"{method.upper()} {path}",
                                key,
                                path,
                            ),
                        )
                    except psycopg2.errors.UniqueViolation as exc:
                        conn.rollback()
                        self._audit(
                            cursor,
                            token_id=int(token_row["id"]),
                            tool_name=tool_name,
                            method=method,
                            path=path,
                            decision="denied",
                            reason="duplicate_idempotency_key",
                            idempotency_key=key,
                        )
                        conn.commit()
                        raise McpAgentError("重复的 Agent Idempotency-Key", 409) from exc
                cursor.execute(
                    "UPDATE mcp_agent_tokens SET last_used_at = NOW() WHERE id = %s",
                    (token_row["id"],),
                )
                self._audit(
                    cursor,
                    token_id=int(token_row["id"]),
                    tool_name=tool_name,
                    method=method,
                    path=path,
                    decision="authorized",
                    reason=None,
                    idempotency_key=idempotency_key,
                )
            conn.commit()
        return {
            "role": "agent",
            "agent_token_id": int(token_row["id"]),
            "agent_name": str(token_row["name"]),
            "permissions": sorted(scopes),
        }

    @staticmethod
    def _path_allowed(method: str, path: str) -> bool:
        patterns = (
            _READ_PATHS
            if method.upper() in {"GET", "HEAD", "OPTIONS"}
            else _WRITE_PATHS
        )
        return any(pattern.fullmatch(path) for pattern in patterns)

    @staticmethod
    def _audit(
        cursor,
        *,
        token_id: int | None,
        tool_name: str | None,
        method: str,
        path: str,
        decision: str,
        reason: str | None,
        idempotency_key: str | None,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO mcp_agent_audit
                (token_id, tool_name, method, path, decision, reason, idempotency_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                token_id,
                tool_name,
                method.upper(),
                path,
                decision,
                reason,
                idempotency_key,
            ),
        )

    def _rows(self, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self.database.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [self._serialize(dict(row)) for row in cursor.fetchall()]

    @staticmethod
    def _serialize(row: dict[str, Any]) -> dict[str, Any]:
        for key, value in list(row.items()):
            if hasattr(value, "isoformat"):
                row[key] = value.isoformat()
        return row
