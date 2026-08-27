"""API authentication middleware for BitPro."""
from __future__ import annotations

from typing import Iterable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.domain.auth.service import ActiveAuthService, active_auth_service as default_auth_service
from app.domain.auth.mcp_tokens import postgres_mcp_token_verifier


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "error": {"code": code, "message": message}},
    )


def _matches_prefix(path: str, prefixes: Iterable[str]) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes)


def guest_can_access(path: str, method: str) -> bool:
    method = method.upper()
    if _matches_prefix(path, ("/api/v2/settings", "/api/v2/arc")):
        return False
    if method in {"GET", "HEAD"}:
        return path.startswith("/api/v2/")
    if method == "POST" and path == "/api/v2/backtest/run_job":
        return True
    if method == "POST" and path.startswith("/api/v2/backtest/job/") and path.endswith("/cancel"):
        return True
    return False


def mcp_token_auth(request: Request) -> dict[str, object] | None:
    primary_header = str(getattr(settings, "STOCKPRO_MCP_AUTH_HEADER", "X-StockPro-MCP-Token") or "").strip()
    legacy_header = str(getattr(settings, "BITPRO_MCP_AUTH_HEADER", "X-BitPro-MCP-Token") or "").strip()
    provided = str(request.headers.get(primary_header, "") or "").strip()
    if not provided and legacy_header and legacy_header.lower() != primary_header.lower():
        provided = str(request.headers.get(legacy_header, "") or "").strip()
    return postgres_mcp_token_verifier.verify_token(provided)


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth_service: ActiveAuthService | None = None):
        super().__init__(app)
        self.auth_service = auth_service or default_auth_service

    async def dispatch(self, request: Request, call_next):
        request.state.auth_service = self.auth_service
        if not settings.BITPRO_AUTH_ENABLED:
            request.state.auth = {"authenticated": True, "role": "admin", "auth_enabled": False}
            return await call_next(request)

        path = request.url.path
        method = request.method.upper()
        public_auth_paths = {
            "/api/auth/me",
            "/api/auth/admin/login",
            "/api/auth/guest/login",
            "/api/auth/logout",
            "/api/v2/auth/me",
            "/api/v2/auth/admin/login",
            "/api/v2/auth/guest/login",
            "/api/v2/auth/logout",
        }
        if method == "OPTIONS" or path in public_auth_paths or path in {"/api/v2/system/health", "/"}:
            return await call_next(request)

        if not path.startswith(("/api/v2/", "/api/auth/")):
            return await call_next(request)

        mcp_auth = mcp_token_auth(request)
        if mcp_auth:
            request.state.auth = mcp_auth
            return await call_next(request)

        token = request.cookies.get(settings.BITPRO_AUTH_COOKIE_NAME)
        session = self.auth_service.get_session(token)
        if not session:
            return _error(401, "UNAUTHORIZED", "请先登录")
        request.state.auth = session
        if session.get("role") == "admin":
            return await call_next(request)
        if session.get("role") == "guest" and guest_can_access(path, method):
            return await call_next(request)
        return _error(403, "FORBIDDEN", "访客邀请码允许查看全站页面和受限回测，但不能执行实盘、策略暂停或其他写操作")
