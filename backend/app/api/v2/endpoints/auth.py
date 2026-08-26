"""Authentication endpoints for admin and temporary guest-code access."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.contracts import ok
from app.core.errors import AppError
from app.domain.auth.login_limiter import LoginAttemptLimiter, LoginRateLimitError
from app.domain.auth.service import ActiveAuthConfigError, ActiveAuthError, active_auth_service as auth_service


router = APIRouter()
login_limiter = LoginAttemptLimiter(max_failures=10, window_seconds=15 * 60)


class AuthRequestError(AppError):
    code = "AUTH_ERROR"

    def __init__(self, message: str, *, status_code: int = 403):
        super().__init__(message)
        self.status_code = status_code


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class GuestLoginRequest(BaseModel):
    code: str


class GuestCodeCreateRequest(BaseModel):
    note: str = ""
    expires_in_minutes: int = Field(default=60, ge=1, le=60 * 24 * 30)
    max_backtests_per_day: int = Field(default=10, ge=0, le=500)
    max_concurrent_backtests: int = Field(default=1, ge=1, le=10)
    max_backtest_days: int = Field(default=365, ge=1, le=3650)


def _client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip", "").strip() or (
        request.client.host if request.client else ""
    )


def _user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")


def _login_key(request: Request) -> str:
    return _client_ip(request) or "unknown"


def _check_login_budget(key: str, now: datetime) -> None:
    try:
        login_limiter.check(key, now=now)
    except LoginRateLimitError as exc:
        raise AuthRequestError(str(exc), status_code=exc.status_code) from exc


def _set_session_cookie(response: Response, session: dict) -> None:
    response.set_cookie(
        settings.BITPRO_AUTH_COOKIE_NAME,
        session["token"],
        httponly=True,
        secure=bool(settings.BITPRO_AUTH_COOKIE_SECURE),
        samesite="strict",
        max_age=max(60, int((session.get("max_age") or 0) or 60 * 60 * 24)),
        path="/",
    )


def _public_session(session: Optional[dict], *, auth_enabled: bool) -> dict:
    if not auth_enabled:
        return {
            "auth_enabled": False,
            "authenticated": True,
            "role": "admin",
            "permissions": ["admin"],
        }
    if not session:
        return {"auth_enabled": True, "authenticated": False, "role": None, "permissions": []}
    role = session.get("role")
    permissions = ["admin"] if role == "admin" else ["read", "backtest"]
    return {
        "auth_enabled": True,
        "authenticated": True,
        "role": role,
        "permissions": permissions,
        "expires_at": session.get("expires_at"),
        "session_id": session.get("session_id"),
        "guest_code_id": session.get("guest_code_id"),
        "max_backtests_per_day": session.get("max_backtests_per_day"),
        "max_concurrent_backtests": session.get("max_concurrent_backtests"),
        "max_backtest_days": session.get("max_backtest_days"),
    }


def _require_admin(request: Request) -> None:
    auth = getattr(request.state, "auth", None) or {}
    if auth.get("role") != "admin":
        raise AuthRequestError("需要管理员登录", status_code=403)


@router.get("/me")
async def me(request: Request):
    token = request.cookies.get(settings.BITPRO_AUTH_COOKIE_NAME)
    session = auth_service.get_session(token) if settings.BITPRO_AUTH_ENABLED else None
    return ok(_public_session(session, auth_enabled=bool(settings.BITPRO_AUTH_ENABLED)))


@router.post("/admin/login")
async def admin_login(payload: AdminLoginRequest, request: Request, response: Response):
    if not settings.BITPRO_AUTH_ENABLED:
        return ok(_public_session(None, auth_enabled=False))
    login_key = _login_key(request)
    now = datetime.now(timezone.utc)
    _check_login_budget(login_key, now)
    try:
        auth_service.validate_admin_config(
            enabled=True,
            username=settings.BITPRO_ADMIN_USERNAME,
            password_hash=settings.BITPRO_ADMIN_PASSWORD_HASH,
        )
        session = auth_service.login_admin(
            username=payload.username,
            password=payload.password,
            expected_username=str(settings.BITPRO_ADMIN_USERNAME or ""),
            expected_password_hash=str(settings.BITPRO_ADMIN_PASSWORD_HASH or ""),
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
            session_hours=int(settings.BITPRO_ADMIN_SESSION_HOURS),
        )
    except ActiveAuthError as exc:
        if exc.status_code == 401:
            login_limiter.record_failure(login_key, now=now)
        raise AuthRequestError(str(exc), status_code=exc.status_code) from exc
    except ActiveAuthConfigError as exc:
        raise AuthRequestError(str(exc), status_code=getattr(exc, "status_code", 503)) from exc
    login_limiter.clear(login_key)
    _set_session_cookie(response, session)
    return ok(_public_session(session, auth_enabled=True))


@router.post("/guest/login")
async def guest_login(payload: GuestLoginRequest, request: Request, response: Response):
    if not settings.BITPRO_AUTH_ENABLED:
        return ok(_public_session(None, auth_enabled=False))
    login_key = _login_key(request)
    now = datetime.now(timezone.utc)
    _check_login_budget(login_key, now)
    try:
        session = auth_service.login_guest(
            payload.code,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except ActiveAuthError as exc:
        if exc.status_code == 401:
            login_limiter.record_failure(login_key, now=now)
        raise AuthRequestError(str(exc), status_code=exc.status_code) from exc
    login_limiter.clear(login_key)
    _set_session_cookie(response, session)
    return ok(_public_session(session, auth_enabled=True))


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(settings.BITPRO_AUTH_COOKIE_NAME)
    auth_service.revoke_session(token)
    response.delete_cookie(settings.BITPRO_AUTH_COOKIE_NAME, path="/")
    return ok({"logged_out": True})


@router.get("/guest-codes")
async def list_guest_codes(request: Request):
    _require_admin(request)
    return ok({"items": auth_service.list_guest_codes()})


@router.post("/guest-codes")
async def create_guest_code(payload: GuestCodeCreateRequest, request: Request):
    _require_admin(request)
    created = auth_service.create_guest_code(
        note=payload.note,
        expires_in_minutes=payload.expires_in_minutes,
        max_backtests_per_day=payload.max_backtests_per_day,
        max_concurrent_backtests=payload.max_concurrent_backtests,
        max_backtest_days=payload.max_backtest_days,
        created_by=(getattr(request.state, "auth", None) or {}).get("session_id") or "admin",
    )
    return ok(created)


@router.delete("/guest-codes/{code_id}")
async def revoke_guest_code(code_id: int, request: Request):
    _require_admin(request)
    return ok(auth_service.revoke_guest_code(code_id))
