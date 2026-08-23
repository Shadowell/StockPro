from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.admin_auth import create_auth_dependency
from app.core.app_context import AppContext
from app.domain.auth.models import AuthProfile
from app.services.research_application_service import ResearchApplicationService


class WatchlistRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    note: str = Field(default="", max_length=200)


def _owner(profile: AuthProfile) -> str:
    return profile.username or f"guest:{profile.session_id}"


def create_market_router(context: AppContext) -> APIRouter:
    router = APIRouter()
    service = ResearchApplicationService(context.repositories.market)
    require_authenticated = create_auth_dependency(context)

    @router.get("/overview")
    async def overview(
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, object]:
        return asdict(service.market_overview())

    @router.get("/instruments")
    async def instruments(
        q: str = Query(default="", max_length=64),
        asset_class: Literal["stock", "etf", "index"] | None = None,
        limit: int = Query(default=30, ge=1, le=100),
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, object]:
        return {
            "items": [asdict(item) for item in service.search_instruments(q, asset_class, limit)],
            "query": q,
            "asset_class": asset_class,
        }

    @router.get("/instruments/{symbol}")
    async def instrument_detail(
        symbol: str,
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, object]:
        item = service.instrument_detail(symbol)
        if item is None:
            raise HTTPException(status_code=404, detail="Instrument not found.")
        return asdict(item)

    @router.get("/instruments/{symbol}/daily")
    async def daily(
        symbol: str,
        limit: int = Query(default=500, ge=1, le=2000),
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, object]:
        items = service.daily_bars(symbol, limit)
        return {
            "items": items,
            "adjustment": "unadjusted",
            "source_label": "PostgreSQL stock_history",
            "data_status": "fresh" if items else "empty",
        }

    @router.get("/instruments/{symbol}/intraday")
    async def intraday(
        symbol: str,
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, object]:
        return {
            "items": [],
            "source_label": None,
            "source_updated_at": None,
            "data_status": "empty",
            "unavailable_reason": "隔离库尚无分时缓存",
        }

    @router.get("/instruments/{symbol}/order-book")
    async def order_book(
        symbol: str,
        _profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, object]:
        return {
            "bids": [],
            "asks": [],
            "source_label": None,
            "source_updated_at": None,
            "data_status": "empty",
            "unavailable_reason": "隔离库尚无盘口缓存",
        }

    @router.get("/watchlist")
    async def watchlist(
        profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, object]:
        return {"items": service.list_watchlist(_owner(profile))}

    @router.post("/watchlist")
    async def add_watchlist(
        body: WatchlistRequest,
        profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, object]:
        if profile.role != "admin":
            raise HTTPException(status_code=403, detail="Admin permission required.")
        try:
            return service.upsert_watchlist(_owner(profile), body.symbol, body.note)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.delete("/watchlist/{entry_id}")
    async def delete_watchlist(
        entry_id: int,
        profile: AuthProfile = Depends(require_authenticated),
    ) -> dict[str, object]:
        if profile.role != "admin":
            raise HTTPException(status_code=403, detail="Admin permission required.")
        if not service.delete_watchlist(_owner(profile), entry_id):
            raise HTTPException(status_code=404, detail="Watchlist entry not found.")
        return {"deleted": True, "id": entry_id}

    return router
