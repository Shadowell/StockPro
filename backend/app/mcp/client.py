from __future__ import annotations

import os
from typing import Any

import httpx

from app.mcp.schemas import DEFAULT_API_BASE, DEFAULT_AUTH_HEADER


class StockProMcpError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class StockProMcpClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        auth_token: str | None = None,
        http_client: Any | None = None,
        timeout: float = 30,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("STOCKPRO_MCP_API_BASE") or DEFAULT_API_BASE
        ).rstrip("/")
        self.auth_token = (
            auth_token
            if auth_token is not None
            else os.getenv("STOCKPRO_MCP_API_TOKEN") or ""
        ).strip()
        self.http_client = http_client or httpx.Client(timeout=timeout)
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        tool_name: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        if not self.auth_token:
            raise StockProMcpError("STOCKPRO_MCP_API_TOKEN 未配置", status_code=401)
        headers = {
            DEFAULT_AUTH_HEADER: self.auth_token,
            "X-StockPro-MCP-Tool": tool_name,
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        response = self.http_client.request(
            method,
            f"{self.base_url}{path}",
            params=params,
            json=json,
            headers=headers,
            timeout=self.timeout,
        )
        try:
            payload = response.json()
        except Exception:
            payload = {"detail": response.text or f"HTTP {response.status_code}"}
        if response.status_code >= 400:
            detail = payload.get("detail") if isinstance(payload, dict) else payload
            raise StockProMcpError(str(detail), status_code=response.status_code)
        return payload
