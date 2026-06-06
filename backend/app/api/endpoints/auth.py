from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.admin_auth import authenticate_admin, create_admin_token, require_admin
from app.core.config import settings

router = APIRouter()


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str


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
