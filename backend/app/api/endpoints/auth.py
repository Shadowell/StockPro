from datetime import datetime, timezone

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.admin_auth import (
    authenticate_admin,
    create_admin_token,
    create_guest_token,
    require_admin,
    require_authenticated,
)
from app.core.config import settings
from app.db import db_instance
from app.services.guest_access_service import GuestAccessError, GuestAccessService

router = APIRouter()
guest_service = GuestAccessService(db_instance)


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str
    role: str = "admin"
    permissions: list[str] = Field(default_factory=lambda: ["read", "write", "admin"])


class GuestLoginRequest(BaseModel):
    code: str = Field(min_length=4, max_length=128)


class GuestCodeRequest(BaseModel):
    note: str = Field(default="", max_length=200)
    expires_in_minutes: int = Field(default=1440, ge=1, le=525600)
    max_backtests_per_day: int = Field(default=10, ge=0, le=500)
    max_concurrent_backtests: int = Field(default=1, ge=1, le=20)
    max_backtest_days: int = Field(default=365, ge=1, le=3650)


@router.post("/admin/login", response_model=AdminLoginResponse)
async def admin_login(payload: AdminLoginRequest) -> AdminLoginResponse:
    if not authenticate_admin(payload.username, payload.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials.",
        )

    return AdminLoginResponse(
        access_token=create_admin_token(payload.username),
        expires_in=settings.ADMIN_TOKEN_TTL_SECONDS,
        username=payload.username,
    )


@router.get("/admin/me")
async def admin_me(username: str = Depends(require_admin)) -> dict[str, str]:
    return {"username": username}


@router.post("/guest/login")
async def guest_login(payload: GuestLoginRequest) -> dict[str, object]:
    try:
        code = guest_service.authenticate_code(payload.code)
        token, session_id = create_guest_token(code)
    except GuestAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    expires_at = str(code["expires_at"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": max(
            0,
            int(
                (
                    datetime.fromisoformat(expires_at)
                    - datetime.now(timezone.utc)
                ).total_seconds()
            ),
        ),
        "role": "guest",
        "session_id": session_id,
        "permissions": ["read", "backtest:run"],
        "guest_code_id": code["id"],
        "max_backtests_per_day": code["max_backtests_per_day"],
        "max_concurrent_backtests": code["max_concurrent_backtests"],
        "max_backtest_days": code["max_backtest_days"],
        "expires_at": expires_at,
    }


@router.get("/me")
async def auth_me(
    principal: dict[str, object] = Depends(require_authenticated),
) -> dict[str, object]:
    return principal


@router.post("/guest-codes")
async def create_guest_code(
    payload: GuestCodeRequest,
    username: str = Depends(require_admin),
) -> dict[str, object]:
    try:
        return guest_service.create_code(
            note=payload.note,
            expires_in_minutes=payload.expires_in_minutes,
            max_backtests_per_day=payload.max_backtests_per_day,
            max_concurrent_backtests=payload.max_concurrent_backtests,
            max_backtest_days=payload.max_backtest_days,
            created_by=username,
        )
    except GuestAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/guest-codes")
async def list_guest_codes(_username: str = Depends(require_admin)) -> dict[str, object]:
    return {"items": guest_service.list_codes()}


@router.delete("/guest-codes/{code_id}")
async def revoke_guest_code(
    code_id: int,
    username: str = Depends(require_admin),
) -> dict[str, object]:
    try:
        return guest_service.revoke_code(code_id, username)
    except GuestAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
