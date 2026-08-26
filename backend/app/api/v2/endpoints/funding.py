"""Funding endpoints for API v2."""
from typing import Optional

from fastapi import APIRouter, Query

from app.core.contracts import ok, page_meta
from app.core.errors import NotFoundError
from app.domain.funding import funding_domain_service

router = APIRouter()


@router.get("/rates")
async def rates(
    exchange: str = Query("okx", description="交易所"),
    symbols: Optional[str] = Query(None, description="逗号分隔交易对"),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
    items = await funding_domain_service.get_funding_rates(exchange, symbol_list)
    total = len(items)
    paged = items[offset : offset + limit]
    return ok(paged, meta=page_meta(total=total, offset=offset, limit=limit))


@router.get("/rate/{symbol}")
async def rate(symbol: str, exchange: str = Query("okx", description="交易所")):
    data = await funding_domain_service.get_funding_rate(exchange, symbol)
    if not data:
        raise NotFoundError("Symbol not found")
    return ok(data)


@router.get("/history")
async def history(
    exchange: str = Query(..., description="交易所"),
    symbol: str = Query(..., description="交易对"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    items = await funding_domain_service.get_funding_history(exchange, symbol, limit + offset)
    paged = items[offset : offset + limit]
    return ok(paged, meta=page_meta(total=len(items), offset=offset, limit=limit))


@router.get("/opportunities")
async def opportunities(
    exchange: str = Query("okx", description="交易所"),
    min_rate: float = Query(0.0001),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
):
    items = await funding_domain_service.get_opportunities(exchange, min_rate, limit + offset)
    paged = items[offset : offset + limit]
    return ok(paged, meta=page_meta(total=len(items), offset=offset, limit=limit))


@router.get("/summary")
async def summary():
    return ok(await funding_domain_service.get_summary())
