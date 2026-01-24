import asyncio
from fastapi import APIRouter, Query
from app.services.market_service import MarketService
from app.db.local_db import db_instance as db
from typing import List, Dict, Any

router = APIRouter()

@router.get("/overview")
async def get_market_overview() -> Dict[str, Any]:
    """获取市场概览数据 - 优先从数据库获取，没有则实时获取"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, MarketService.get_market_overview)

@router.get("/short-line-indices")
async def get_short_line_indices() -> List[Dict[str, Any]]:
    """获取短线指数 - 优先从数据库，没有则实时获取"""
    result = db.get_short_line_indices_realtime()
    if result:
        return result
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, MarketService.get_short_line_indices)

@router.get("/sectors")
async def get_market_sectors() -> List[Dict[str, Any]]:
    """获取热门板块 - 实时获取"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, MarketService.get_all_sectors)

@router.get("/stocks")
async def get_market_stocks() -> List[Dict[str, Any]]:
    """获取全部股票 - 实时获取"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, MarketService.get_all_stocks)

@router.get("/hot-concepts")
async def get_hot_concepts(
    limit: int = Query(50, ge=1, le=200),
    date: str | None = Query(None)
) -> List[Dict[str, Any]]:
    """获取热门概念板块 - 实时获取"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.get_hot_concepts(limit, date))

@router.get("/ths-hot")
async def get_ths_hot(
    limit: int = Query(100, ge=1, le=200),
    date: str | None = Query(None)
) -> List[Dict[str, Any]]:
    """获取同花顺热榜 - 实时获取"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.get_ths_hot(limit, date))

@router.get("/lianban-ladder")
async def get_lianban_ladder(date: str | None = Query(None)) -> Dict[str, Any]:
    """获取连板天梯 - 实时获取"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.get_lianban_ladder(date))

@router.get("/hot-concept/intraday")
async def get_hot_concept_intraday(
    name: str = Query(..., min_length=1),
    period: str = Query("1"),
    date: str | None = Query(None)
) -> List[Dict[str, Any]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.get_concept_intraday_kline(name=name, period=period, date=date))

@router.get("/hot-concept/leaders")
async def get_hot_concept_leaders(
    name: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=200),
    date: str | None = Query(None)
) -> List[Dict[str, Any]]:
    """获取概念板块龙头股 - 优先从数据库读取缓存，更快"""
    # 优先从数据库读取
    cached = db.get_concept_leaders_cache(name, limit)
    if cached and len(cached) > 0:
        return cached
    
    # 数据库没有则从API获取
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.get_concept_leading_stocks(name=name, limit=limit, date=date))

@router.get("/fundamentals/{symbol}")
async def get_stock_fundamentals(symbol: str) -> Dict[str, Any]:
    """获取股票基本面数据 - 实时获取"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.get_stock_fundamentals(symbol))

@router.get("/message-stream")
async def get_message_stream(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.get_message_stream(limit=limit))

@router.get("/calendar")
async def get_market_calendar(
    start: str | None = Query(None),
    end: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
) -> List[Dict[str, Any]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.get_market_calendar_events(start=start, end=end, limit=limit))

@router.post("/calendar/refresh")
async def refresh_market_calendar(months: int = Query(6, ge=1, le=24)) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.refresh_market_calendar(months=months))

@router.post("/calendar/refresh-free")
async def refresh_market_calendar_with_free_data(months: int = Query(6, ge=1, le=24)) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.refresh_market_calendar_with_free_data(months=months))

@router.post("/calendar/generate-with-ai")
async def generate_market_calendar_with_ai(
    start_date: str = Query(..., description="开始日期 (YYYY-MM-DD)"),
    end_date: str = Query(..., description="结束日期 (YYYY-MM-DD)")
) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.generate_market_calendar_with_ai(start_date=start_date, end_date=end_date))
