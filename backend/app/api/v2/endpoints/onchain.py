"""A-share point-in-time fundamental research endpoints."""
from datetime import datetime, timezone
import asyncio

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.contracts import ok
from app.domain.fundamentals import fundamental_service


router = APIRouter()


class FundamentalSyncRequest(BaseModel):
    symbol: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ|BJ)$")
    years: int = Field(default=3, ge=1, le=10)


def _require_admin(request: Request) -> None:
    if not settings.BITPRO_AUTH_ENABLED:
        return
    auth = getattr(request.state, "auth", None) or {}
    if auth.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员登录")


@router.get("/summary")
async def summary(
    symbol: str = Query("600519.SH", pattern=r"^[0-9]{6}\.(SH|SZ|BJ)$"),
    as_of: str | None = Query(None, description="ISO-8601 knowledge cutoff"),
):
    cutoff = None
    if as_of:
        try:
            cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="as_of must be ISO-8601") from exc
    return ok(await asyncio.to_thread(fundamental_service.summary, symbol, as_of=cutoff))


@router.post("/sync")
async def sync(payload: FundamentalSyncRequest, request: Request):
    _require_admin(request)
    try:
        return ok(await asyncio.to_thread(fundamental_service.sync, payload.symbol, years=payload.years))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"A-share fundamental sync failed: {type(exc).__name__}") from exc
