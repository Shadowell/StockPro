"""A-share implementation of the original BitPro strategy catalogue contract."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.contracts import ok
from app.core.config import settings
from app.domain.strategy import strategy_domain_service


router = APIRouter()
StrategyTypeQuery = Literal["all", "momentum", "mean_reversion", "multi_factor", "event", "other"]


class StrategyWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    script_content: str = Field(min_length=1, max_length=200_000)
    config: dict = Field(default_factory=dict)
    exchange: str = "CN"
    symbols: list[str] = Field(default_factory=list, max_length=500)


def _require_admin_when_auth_enabled(request: Request) -> None:
    if not settings.BITPRO_AUTH_ENABLED:
        return
    auth = getattr(request.state, "auth", None) or {}
    if auth.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员登录")
    if auth.get("auth_method") == "mcp_token" and "W" not in set(auth.get("scopes") or []):
        raise HTTPException(status_code=403, detail="MCP Token 缺少策略写入权限")


@router.get("")
async def list_strategies(
    page: int = Query(1, ge=1),
    per_page: int = Query(18, ge=1, le=60),
    search: str = Query(""),
    status: str = Query("all"),
    asset_class: str = Query("all"),
    strategy_type: StrategyTypeQuery = Query("all"),
    timeframe: str = Query("all"),
    capital: str = Query("all"),
):
    return ok(
        await strategy_domain_service.list_page(
            page=page,
            per_page=per_page,
            search=search,
            status=status,
            asset_class=asset_class,
            strategy_type=strategy_type,
            timeframe=timeframe,
            capital=capital,
        )
    )


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: str):
    item = await strategy_domain_service.get(strategy_id)
    if item is None:
        raise HTTPException(status_code=404, detail="A-share strategy version not found")
    return ok(item)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_strategy(body: StrategyWriteRequest, request: Request):
    _require_admin_when_auth_enabled(request)
    if body.exchange.upper() not in {"CN", "A_SHARE", "ASHARE"}:
        raise HTTPException(status_code=422, detail="StockPro 仅接受 A 股策略")
    try:
        return ok(await strategy_domain_service.create(body.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/{strategy_id}")
async def update_strategy(strategy_id: str, body: StrategyWriteRequest, request: Request):
    _require_admin_when_auth_enabled(request)
    if body.exchange.upper() not in {"CN", "A_SHARE", "ASHARE"}:
        raise HTTPException(status_code=422, detail="StockPro 仅接受 A 股策略")
    try:
        return ok(await strategy_domain_service.update(strategy_id, body.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{strategy_id}")
async def archive_strategy(strategy_id: str, request: Request):
    _require_admin_when_auth_enabled(request)
    try:
        return ok(await strategy_domain_service.archive(strategy_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
