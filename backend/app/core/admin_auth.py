from __future__ import annotations

from typing import Annotated, Callable

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile
from app.services.auth_service import AuthError, AuthService


_BEARER = HTTPBearer(auto_error=False)


def create_auth_dependency(
    context: AppContext,
) -> Callable[..., AuthProfile]:
    service = AuthService(context)

    def require_authenticated(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
    ) -> AuthProfile:
        if not bool(getattr(context.settings, "AUTH_ENABLED", True)):
            return AuthProfile(
                role="admin",
                username=str(getattr(context.settings, "ADMIN_USERNAME", "admin")),
                permissions=("read", "write", "admin"),
                session_id="auth-disabled",
                expires_at="",
            )
        token = ""
        if credentials is not None and credentials.scheme.lower() == "bearer":
            token = credentials.credentials
        if not token:
            cookie_name = str(
                getattr(context.settings, "AUTH_COOKIE_NAME", "stockpro_session")
            )
            token = str(request.cookies.get(cookie_name) or "")
        if not token:
            raise HTTPException(status_code=401, detail="Login required.")
        try:
            profile = service.resolve(token)
        except AuthError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        request.state.auth_principal = profile
        return profile

    return require_authenticated


def create_optional_auth_dependency(
    context: AppContext,
) -> Callable[..., AuthProfile | None]:
    service = AuthService(context)

    def resolve_optional(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
    ) -> AuthProfile | None:
        if not bool(getattr(context.settings, "AUTH_ENABLED", True)):
            return AuthProfile(
                role="admin",
                username=str(getattr(context.settings, "ADMIN_USERNAME", "admin")),
                permissions=("read", "write", "admin"),
                session_id="auth-disabled",
                expires_at="",
            )
        token = ""
        if credentials is not None and credentials.scheme.lower() == "bearer":
            token = credentials.credentials
        if not token:
            cookie_name = str(
                getattr(context.settings, "AUTH_COOKIE_NAME", "stockpro_session")
            )
            token = str(request.cookies.get(cookie_name) or "")
        if not token:
            return None
        try:
            return service.resolve(token)
        except AuthError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error

    return resolve_optional
