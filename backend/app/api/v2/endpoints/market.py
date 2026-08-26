"""Market endpoints for API v2."""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.contracts import ok, page_meta
from app.domain.market import market_domain_service
from app.domain.market.sector_taxonomy import enrich_market_ticker
router = APIRouter()


def _parse_periods(raw: str, param_name: str = "ema_periods") -> List[int]:
    periods: List[int] = []
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        try:
            period = int(value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"{param_name} must be comma-separated integers") from exc
        if period <= 0 or period > 500:
            raise HTTPException(status_code=400, detail="indicator period must be between 1 and 500")
        periods.append(period)
    return periods or [5, 10, 20, 30]


@router.get("/ticker")
async def get_ticker(
    exchange: str = Query(..., description="交易所"),
    symbol: str = Query(..., description="交易对"),
):
    return ok(await market_domain_service.get_ticker(exchange, symbol))


@router.get("/tickers")
async def get_tickers(
    exchange: str = Query(..., description="交易所"),
    symbols: Optional[str] = Query(None, description="逗号分隔交易对"),
    quote: Optional[str] = Query(None, description="按计价币种筛选，例如 USDT"),
    market_type: Optional[str] = Query(None, description="按市场类型筛选，例如 swap"),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
    if symbol_list and market_type:
        raise HTTPException(status_code=400, detail="不能同时指定 symbols 与 market_type")
    if market_type:
        symbol_list = await market_domain_service.get_symbols(
            exchange,
            (quote or "USDT").strip().upper(),
            market_type.strip().lower(),
        )
    items = await market_domain_service.get_tickers(exchange, symbol_list)
    total = len(items)
    paged = [enrich_market_ticker(item) for item in items[offset: offset + limit]]
    return ok(paged, meta=page_meta(total=total, offset=offset, limit=limit))


@router.get("/klines")
async def get_klines(
    exchange: str = Query(..., description="交易所"),
    symbol: str = Query(..., description="交易对"),
    timeframe: str = Query("1h", description="周期"),
    limit: int = Query(100, ge=1, le=1000),
    start: Optional[int] = Query(None, description="开始时间戳(毫秒)"),
    end: Optional[int] = Query(None, description="结束时间戳(毫秒)"),
):
    return ok(await market_domain_service.get_klines(exchange, symbol, timeframe, limit, start, end))


@router.get("/indicators")
async def get_technical_indicators(
    exchange: str = Query(..., description="交易所"),
    symbol: str = Query(..., description="交易对"),
    timeframe: str = Query("1h", description="周期"),
    limit: int = Query(100, ge=1, le=1000),
    start: Optional[int] = Query(None, description="开始时间戳(毫秒)"),
    end: Optional[int] = Query(None, description="结束时间戳(毫秒)"),
    ema_periods: Optional[str] = Query(None, description="逗号分隔 EMA 周期"),
):
    periods = _parse_periods(ema_periods or "5,10,20,30", "ema_periods")
    payload = await market_domain_service.get_technical_indicators(
        exchange,
        symbol,
        timeframe,
        limit,
        start,
        end,
        ema_periods=periods,
    )
    return ok(payload)


@router.get("/orderbook")
async def get_orderbook(
    exchange: str = Query(..., description="交易所"),
    symbol: str = Query(..., description="交易对"),
    limit: int = Query(20, ge=1, le=1000),
):
    return ok(await market_domain_service.get_orderbook(exchange, symbol, limit))


@router.get("/trades")
async def get_trades(
    exchange: str = Query(..., description="交易所"),
    symbol: str = Query(..., description="交易对"),
    limit: int = Query(50, ge=1, le=500),
):
    return ok(await market_domain_service.get_trades(exchange, symbol, limit))


@router.get("/symbols")
async def get_symbols(
    exchange: str = Query(..., description="交易所"),
    quote: str = Query("USDT", description="计价币种"),
    market_type: str = Query("spot", description="市场类型: spot/swap/future/all"),
):
    symbols = await market_domain_service.get_symbols(exchange, quote, market_type)
    return ok({"symbols": symbols})
