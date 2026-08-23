from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.admin_auth import create_auth_dependency, create_optional_auth_dependency
from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile
from app.services.auth_service import AuthError, AuthService, auth_response


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


class GuestLoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128)


class AuthAttemptLimiter:
    def __init__(self, *, max_failures: int = 10, window_seconds: int = 900) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.failures: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, now: datetime) -> None:
        attempts = self.failures[key]
        cutoff = now.timestamp() - self.window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if len(attempts) >= self.max_failures:
            raise HTTPException(status_code=429, detail="Too many login attempts.")

    def record_failure(self, key: str, now: datetime) -> None:
        self.failures[key].append(now.timestamp())

    def clear(self, key: str) -> None:
        self.failures.pop(key, None)


def _profile_payload(profile: AuthProfile) -> dict[str, object]:
    return {
        **asdict(profile),
        "auth_enabled": True,
        "authenticated": True,
    }


def create_auth_router(context: AppContext) -> APIRouter:
    router = APIRouter()
    service = AuthService(context)
    require_authenticated = create_auth_dependency(context)
    resolve_optional = create_optional_auth_dependency(context)
    limiter = AuthAttemptLimiter()

    def attempt_key(request: Request, flow: str) -> str:
        client_host = request.client.host if request.client else "unknown"
        return f"{flow}:{client_host}"

    def login_response(token, profile) -> JSONResponse:
        response = JSONResponse(auth_response(token, profile))
        response.set_cookie(
            key=str(getattr(context.settings, "AUTH_COOKIE_NAME", "stockpro_session")),
            value=token.access_token,
            max_age=token.expires_in,
            httponly=True,
            secure=bool(getattr(context.settings, "AUTH_COOKIE_SECURE", False)),
            samesite="strict",
            path="/",
        )
        return response

    @router.post("/admin/login")
    async def admin_login(body: AdminLoginRequest, request: Request) -> JSONResponse:
        key = attempt_key(request, "admin")
        now = context.clock()
        limiter.check(key, now)
        try:
            token, profile = service.login_admin(body.username, body.password)
        except AuthError as error:
            if error.status_code == 401:
                limiter.record_failure(key, now)
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        limiter.clear(key)
        return login_response(token, profile)

    @router.post("/guest/login")
    async def guest_login(body: GuestLoginRequest, request: Request) -> JSONResponse:
        key = attempt_key(request, "guest")
        now = context.clock()
        limiter.check(key, now)
        try:
            token, profile = service.login_guest(body.code)
        except AuthError as error:
            if error.status_code == 401:
                limiter.record_failure(key, now)
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        limiter.clear(key)
        return login_response(token, profile)

    @router.get("/me")
    async def me(
        profile: AuthProfile | None = Depends(resolve_optional),
    ) -> dict[str, object]:
        if profile is None:
            return {
                "auth_enabled": True,
                "authenticated": False,
                "role": None,
                "permissions": [],
            }
        return _profile_payload(profile)

    @router.post("/logout")
    async def logout() -> JSONResponse:
        response = JSONResponse({"logged_out": True})
        response.delete_cookie(
            key=str(getattr(context.settings, "AUTH_COOKIE_NAME", "stockpro_session")),
            path="/",
            httponly=True,
            secure=bool(getattr(context.settings, "AUTH_COOKIE_SECURE", False)),
            samesite="strict",
        )
        return response

    return router
