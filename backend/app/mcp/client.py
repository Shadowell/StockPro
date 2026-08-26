"""HTTP client used by the local BitPro MCP server."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

import httpx

from app.mcp.schemas import DEFAULT_API_BASE


logger = logging.getLogger("bitpro.mcp.client")

# Issue #705: a poisoned keep-alive connection inside this singleton client's
# httpx pool made every subsequent tools/call hang until timeout while the
# request never reached uvicorn. The default policy therefore never reuses
# loopback connections ("Connection: close") and still self-heals when reuse
# is explicitly enabled.
MCP_HTTP_CONNECT_RETRIES: Final = 1
MCP_HTTP_KEEPALIVE_EXPIRY_SEC: Final = 30.0


def _build_http_client(timeout: float, *, keep_alive: bool) -> httpx.Client:
    headers = {} if keep_alive else {"Connection": "close"}
    return httpx.Client(
        timeout=timeout,
        headers=headers,
        transport=httpx.HTTPTransport(retries=MCP_HTTP_CONNECT_RETRIES),
        limits=httpx.Limits(keepalive_expiry=MCP_HTTP_KEEPALIVE_EXPIRY_SEC),
    )


SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "secret",
    "passphrase",
    "password",
    "token",
    "webhook",
    "authorization",
    "auth",
)


class BitProMcpError(RuntimeError):
    """Raised when BitPro's API returns an HTTP or application error."""

    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS):
                out[key] = "***"
            else:
                out[key] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class BitProMcpClient:
    """Small API client that unwraps BitPro envelopes and writes MCP audit lines."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        audit_path: str | Path | None = None,
        timeout: float = 30.0,
        http_client: Any | None = None,
        auth_token: str | None = None,
        auth_header: str | None = None,
        keep_alive: bool | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("BITPRO_MCP_API_BASE") or DEFAULT_API_BASE).rstrip("/")
        self.audit_path = Path(
            audit_path
            or os.getenv("BITPRO_MCP_AUDIT_PATH")
            or "data/mcp_tool_audit.jsonl"
        )
        self.timeout = float(timeout)
        if keep_alive is None:
            keep_alive = os.getenv("BITPRO_MCP_HTTP_KEEP_ALIVE", "").strip() == "1"
        self.keep_alive = bool(keep_alive)
        self.connect_retries: int | None = MCP_HTTP_CONNECT_RETRIES
        self.keepalive_expiry_sec: float | None = MCP_HTTP_KEEPALIVE_EXPIRY_SEC
        if http_client is not None:
            # Injected clients (tests / custom transports) keep their own policy.
            self.http_client = http_client
            self.connect_retries = None
            self.keepalive_expiry_sec = None
        else:
            self.http_client = _build_http_client(self.timeout, keep_alive=self.keep_alive)
        self.auth_token = (auth_token if auth_token is not None else os.getenv("BITPRO_MCP_API_TOKEN") or "").strip()
        self.auth_header = (
            auth_header
            or os.getenv("BITPRO_MCP_AUTH_HEADER")
            or "X-BitPro-MCP-Token"
        ).strip()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        tool_name: str,
        audit_context: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        normalized_path = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{normalized_path}"
        started_at = datetime.now(timezone.utc)
        started_monotonic = time.monotonic()
        status_code: int | None = None
        try:
            response = self.http_client.request(
                method.upper(),
                url,
                params=params,
                json=json,
                headers=self._auth_headers(),
                timeout=timeout or self.timeout,
            )
            status_code = int(response.status_code)
            payload = self._response_payload(response)
            if status_code >= 400 or (isinstance(payload, dict) and payload.get("success") is False):
                message = self._error_message(payload, status_code)
                self._audit(
                    tool_name,
                    method,
                    normalized_path,
                    params,
                    json,
                    audit_context,
                    "error",
                    status_code,
                    started_at,
                    error=message,
                )
                raise BitProMcpError(message, status_code=status_code, payload=payload)

            result = payload.get("data") if isinstance(payload, dict) and payload.get("success") is True and "data" in payload else payload
            self._audit(
                tool_name,
                method,
                normalized_path,
                params,
                json,
                audit_context,
                "success",
                status_code,
                started_at,
            )
            return result
        except BitProMcpError:
            raise
        except httpx.TimeoutException as exc:
            # Issue #705 observability: timeouts previously only surfaced as the
            # generic FastMCP "Error executing tool ...: timed out" message with
            # no trace in server logs, which made pool poisoning very hard to
            # diagnose. Log a dedicated warning before wrapping.
            elapsed_ms = int((time.monotonic() - started_monotonic) * 1000)
            logger.warning(
                "MCP internal HTTP timeout: tool=%s %s %s elapsed_ms=%d error=%s",
                tool_name,
                method.upper(),
                normalized_path,
                elapsed_ms,
                exc,
            )
            message = f"internal API request timed out after {elapsed_ms}ms: {exc}"
            self._audit(
                tool_name,
                method,
                normalized_path,
                params,
                json,
                audit_context,
                "error",
                status_code,
                started_at,
                error=message,
            )
            raise BitProMcpError(message, status_code=status_code) from exc
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - started_monotonic) * 1000)
            message = str(exc)
            logger.warning(
                "MCP internal HTTP error: tool=%s %s %s elapsed_ms=%d error=%s",
                tool_name,
                method.upper(),
                normalized_path,
                elapsed_ms,
                exc,
            )
            self._audit(
                tool_name,
                method,
                normalized_path,
                params,
                json,
                audit_context,
                "error",
                status_code,
                started_at,
                error=message,
            )
            raise BitProMcpError(message, status_code=status_code) from exc

    @staticmethod
    def _response_payload(response: httpx.Response) -> Any:
        try:
            return response.json()
        except Exception:
            text = getattr(response, "text", "")
            return {"success": False, "error": {"message": text or f"HTTP {response.status_code}"}}

    @staticmethod
    def _error_message(payload: Any, status_code: int) -> str:
        if isinstance(payload, dict):
            detail = payload.get("detail")
            error = payload.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error.get("detail") or detail or f"HTTP {status_code}")
            return str(detail or error or payload.get("message") or f"HTTP {status_code}")
        return f"HTTP {status_code}: {payload}"

    def _audit(
        self,
        tool_name: str,
        method: str,
        path: str,
        params: dict[str, Any] | None,
        payload: dict[str, Any] | None,
        audit_context: dict[str, Any] | None,
        status: str,
        http_status: int | None,
        started_at: datetime,
        *,
        error: str | None = None,
    ) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "started_at": started_at.isoformat(),
            "tool": tool_name,
            "method": method.upper(),
            "path": path,
            "status": status,
            "http_status": http_status,
            "request": _redact({"params": params or {}, "json": payload or {}}),
            "context": _redact(audit_context or {}),
        }
        if error:
            entry["error"] = error[:1000]
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception:
            # MCP tool execution should not fail just because audit storage is temporarily unavailable.
            return

    def _auth_headers(self) -> dict[str, str] | None:
        if not self.auth_token:
            return None
        return {self.auth_header: self.auth_token}
