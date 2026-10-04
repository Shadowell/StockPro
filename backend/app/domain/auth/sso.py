"""Verify shared browser sessions at the fixed HyperMonitor HTTPS authority."""
from __future__ import annotations

import re

import httpx
from fastapi import Request

from app.core.config import settings
from app.core.errors import AppError
from app.domain.auth.service import ActiveAuthService

SSO_COOKIE_NAME = "notenap_session"
SSO_COOKIE_DOMAIN = ".notenap.com"
SSO_SESSION_URL = "https://monitor.notenap.com/api/auth/sso/session"
STOCKPRO_ORIGIN = "https://stockpro.notenap.com"
_COOKIE_VALUE = re.compile(r"[A-Za-z0-9._-]{1,1024}")


class SsoAuthError(AppError):
    def __init__(self, message: str, *, status_code: int, code: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def require_same_origin(request: Request) -> None:
    """A sibling domain is same-site but must not authorize StockPro writes."""
    origins = request.headers.getlist("origin")
    if origins and origins != [STOCKPRO_ORIGIN]:
        raise SsoAuthError("请求来源不受信任", status_code=403, code="FORBIDDEN")


def _shared_cookie(request: Request) -> str | None:
    values = []
    for header in request.headers.getlist("cookie"):
        for part in header.split(";"):
            name, separator, value = part.strip().partition("=")
            if name.strip() == SSO_COOKIE_NAME:
                values.append(value if separator else "")
    if not values:
        return None
    if len(values) != 1 or not _COOKIE_VALUE.fullmatch(values[0]):
        raise SsoAuthError("统一登录会话无效", status_code=401, code="UNAUTHORIZED")
    return values[0]


async def resolve_browser_session(request: Request, auth_service: ActiveAuthService) -> dict | None:
    """Preserve local roles before considering a centrally verified admin."""
    session = auth_service.get_session(request.cookies.get(settings.BITPRO_AUTH_COOKIE_NAME))
    if session:
        return session
    token = _shared_cookie(request)
    if token is None:
        return None
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        require_same_origin(request)
    try:
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=False, trust_env=False) as client:
            response = await client.get(
                SSO_SESSION_URL,
                headers={"Cookie": f"{SSO_COOKIE_NAME}={token}", "Accept": "application/json"},
            )
        if response.status_code == 401:
            return None
        if response.status_code != 200:
            raise ValueError("unexpected status")
        payload = response.json()
        if (
            not isinstance(payload, dict)
            or payload.get("authenticated") is not True
            or payload.get("role") != "admin"
            or not isinstance(payload.get("user"), str)
            or not payload["user"].strip()
        ):
            raise ValueError("invalid identity")
    except (httpx.HTTPError, ValueError):
        # Do not surface upstream bodies, URLs, request headers, or credentials.
        raise SsoAuthError("统一登录服务暂不可用，请稍后重试", status_code=503, code="SSO_UNAVAILABLE") from None
    return {"authenticated": True, "role": "admin", "user": payload["user"], "auth_method": "hypermonitor_sso"}
