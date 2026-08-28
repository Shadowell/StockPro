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
    symbol: str = Query(..., description="A 股证券代码"),
):
    return ok(await market_domain_service.get_ticker(exchange, symbol))


@router.get("/overview")
async def get_market_overview(
    trade_date: Optional[str] = Query(None, description="交易日 YYYY-MM-DD；为空返回最新已持久化事实"),
):
    """Return the single read-only foundation contract used by the home page."""
    return ok(await market_domain_service.get_market_overview(trade_date))


@router.get("/dashboard")
async def get_home_market_dashboard(
    trade_date: Optional[str] = Query(None, description="交易日 YYYY-MM-DD；为空返回最新封存结果"),
):
    return ok(await market_domain_service.get_home_dashboard(trade_date))


@router.get("/tickers")
async def get_tickers(
    exchange: str = Query(..., description="交易所"),
    symbols: Optional[str] = Query(None, description="逗号分隔 A 股证券代码"),
    quote: Optional[str] = Query(None, description="兼容字段；A 股固定为 CNY"),
    market_type: Optional[str] = Query(None, description="资产类型：stock/etf/index/all"),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
    if symbol_list and market_type:
        raise HTTPException(status_code=400, detail="不能同时指定 symbols 与 market_type")
    if market_type:
        symbol_list = await market_domain_service.get_symbols(
            exchange,
            (quote or "CNY").strip().upper(),
            market_type.strip().lower(),
        )
    items = await market_domain_service.get_tickers(exchange, symbol_list)
    total = len(items)
    paged = [enrich_market_ticker(item) for item in items[offset: offset + limit]]
    return ok(paged, meta=page_meta(total=total, offset=offset, limit=limit))


@router.get("/klines")
async def get_klines(
    exchange: str = Query(..., description="交易所"),
    symbol: str = Query(..., description="A 股证券代码"),
    timeframe: str = Query("1h", description="周期"),
    limit: int = Query(100, ge=1, le=1000),
    start: Optional[int] = Query(None, description="开始时间戳(毫秒)"),
    end: Optional[int] = Query(None, description="结束时间戳(毫秒)"),
):
    payload = await market_domain_service.get_klines_payload(exchange, symbol, timeframe, limit, start, end)
    meta = {key: value for key, value in payload.items() if key != "items"}
    return ok(payload.get("items", []), meta=meta)


@router.get("/indicators")
async def get_technical_indicators(
    exchange: str = Query(..., description="交易所"),
    symbol: str = Query(..., description="A 股证券代码"),
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
    symbol: str = Query(..., description="A 股证券代码"),
    limit: int = Query(20, ge=1, le=1000),
):
    return ok(await market_domain_service.get_orderbook(exchange, symbol, limit))


@router.get("/trades")
async def get_trades(
    exchange: str = Query(..., description="交易所"),
    symbol: str = Query(..., description="A 股证券代码"),
    limit: int = Query(50, ge=1, le=500),
):
    payload = await market_domain_service.get_trades_payload(exchange, symbol, limit)
    meta = {key: value for key, value in payload.items() if key != "items"}
    return ok(payload.get("items", []), meta=meta)


@router.get("/symbols")
async def get_symbols(
    exchange: str = Query(..., description="交易所"),
    quote: str = Query("CNY", description="计价币种，A 股固定为 CNY"),
    market_type: str = Query("stock", description="资产类型: stock/etf/index/all"),
):
    instruments = await market_domain_service.get_instruments(exchange, quote, market_type)
    return ok({"symbols": [item["symbol"] for item in instruments], "instruments": instruments})


@router.get("/symbol-names")
async def lookup_symbol_names(symbols: str = Query("", max_length=10000)):
    requested = [item.strip() for item in symbols.split(",") if item.strip()][:500]
    names = await market_domain_service.lookup_names(requested)
    return ok({"names": names, "total": len(names)})


@router.get("/phase")
async def get_market_phase(
    trade_date: Optional[str] = Query(None, description="交易日 YYYY-MM-DD；为空返回最新"),
):
    return ok(await market_domain_service.get_market_phase(trade_date))


@router.get("/sentiment")
async def get_market_sentiment(
    trade_date: Optional[str] = Query(None, description="交易日 YYYY-MM-DD；为空返回最新"),
):
    return ok(await market_domain_service.get_market_sentiment(trade_date))


@router.get("/timeline")
async def get_market_timeline(limit: int = Query(60, ge=1, le=250)):
    return ok(await market_domain_service.list_market_timeline(limit=limit))


@router.get("/sector-rps")
async def get_sector_rps(
    trade_date: Optional[str] = Query(None, description="交易日 YYYY-MM-DD；为空返回最新"),
    classification_system: str = Query("industry", pattern="^(industry|concept)$"),
    limit: int = Query(20, ge=1, le=1000),
):
    payload = await market_domain_service.list_sector_rps(
        trade_date=trade_date,
        classification_system=classification_system,
        limit=limit,
    )
    meta = {key: value for key, value in payload.items() if key != "items"}
    return ok(payload.get("items", []), meta=meta)


@router.get("/sector-rps/{sector_code}/history")
async def get_sector_rps_history(
    sector_code: str,
    classification_system: str = Query("industry", pattern="^(industry|concept)$"),
    limit: int = Query(60, ge=1, le=250),
):
    payload = await market_domain_service.get_sector_rps_history(
        sector_code,
        classification_system=classification_system,
        limit=limit,
    )
    meta = {key: value for key, value in payload.items() if key != "items"}
    return ok(payload.get("items", []), meta=meta)


@router.get("/sector-rps/{sector_code}/members")
async def get_sector_members(
    sector_code: str,
    classification_system: str = Query("industry", pattern="^(industry|concept)$"),
    trade_date: Optional[str] = Query(None, description="成员快照交易日；为空返回最新"),
    limit: int = Query(500, ge=1, le=2000),
):
    payload = await market_domain_service.list_sector_members(
        sector_code,
        classification_system=classification_system,
        trade_date=trade_date,
        limit=limit,
    )
    meta = {key: value for key, value in payload.items() if key != "items"}
    return ok(payload.get("items", []), meta=meta)


@router.get("/movers")
async def get_market_movers(
    trade_date: Optional[str] = Query(None, description="交易日 YYYY-MM-DD；为空返回最新"),
    limit: int = Query(20, ge=1, le=200),
):
    payload = await market_domain_service.list_symbol_abnormalities(trade_date=trade_date, limit=limit)
    meta = {key: value for key, value in payload.items() if key != "items"}
    return ok(payload.get("items", []), meta=meta)


@router.get("/movers/{symbol}")
async def get_symbol_mover(
    symbol: str,
    trade_date: Optional[str] = Query(None, description="交易日 YYYY-MM-DD；为空返回最新"),
):
    return ok(await market_domain_service.get_symbol_abnormality(symbol, trade_date=trade_date))


@router.get("/sector-heatmap")
async def get_sector_heatmap(
    window: str = Query("1d", description="涨跌窗口: 1d/5d/20d", pattern="^(1d|5d|20d)$"),
):
    """板块热力图（只读）：行业 × 等权涨跌，面积 = 标的数。GET 不写库、不调 Provider。"""
    return ok(await market_domain_service.get_sector_heatmap(window))


@router.get("/key-levels")
async def get_symbol_key_levels(
    exchange: str = Query(..., description="交易所"),
    symbol: str = Query(..., description="A 股证券代码"),
    limit: int = Query(500, ge=20, le=2000, description="参与计算的日线根数"),
):
    """个股关键价位（只读）：11 类价位分组 + 摘要，基于 1d 日线实时计算。"""
    return ok(await market_domain_service.get_key_levels(exchange, symbol, limit))
