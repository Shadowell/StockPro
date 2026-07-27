import asyncio
from fastapi import APIRouter, Query, Body, HTTPException
from app.services.market_service import MarketService
from app.services.market_research_service import MarketResearchService
from app.db import db_instance as db
from typing import List, Dict, Any

router = APIRouter()
research_service = MarketResearchService(db)


@router.get("/research-context")
async def get_research_context(
    snapshot_id: int | None = Query(None),
    trade_date: str | None = Query(None),
    market_scope: str = Query("all_a"),
) -> Dict[str, Any]:
    try:
        return research_service.research_context(snapshot_id, trade_date, market_scope)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/evidence-snapshots")
async def list_evidence_snapshots(
    trade_date: str | None = Query(None),
    market_scope: str | None = Query(None),
    limit: int = Query(100, ge=1, le=365),
) -> Dict[str, Any]:
    items = research_service.list_snapshots(trade_date=trade_date, market_scope=market_scope, limit=limit)
    return {"items": items, "total": len(items)}


@router.get("/sentiment")
async def get_research_sentiment(snapshot_id: int = Query(...)) -> Dict[str, Any]:
    try:
        return research_service.sentiment(snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/limit-ecosystem")
async def get_limit_ecosystem(snapshot_id: int = Query(...)) -> Dict[str, Any]:
    try:
        return research_service.limit_ecosystem(snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sector-evidence")
async def get_sector_evidence(
    snapshot_id: int = Query(...),
    classification: str = Query("tushare_limit_industry"),
) -> Dict[str, Any]:
    try:
        return research_service.sector_evidence(snapshot_id, classification)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.get("/overview")
async def get_market_overview() -> Dict[str, Any]:
    """获取市场概览数据 - 优先从数据库获取，没有则实时获取"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, MarketService.get_market_overview)

@router.get("/short-line-indices")
async def get_short_line_indices() -> List[Dict[str, Any]]:
    """获取短线指数 - 优先从数据库，没有则实时获取"""
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
    """获取热门概念板块 - 页面只读 PG 缓存/历史"""
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, lambda: MarketService.get_hot_concepts(limit, date))
    return [{**row, "source_label": row.get("source_label") or "PG 缓存；上游来源未记录"} for row in rows]

@router.get("/ths-hot")
async def get_ths_hot(
    limit: int = Query(100, ge=1, le=200),
    date: str | None = Query(None)
) -> List[Dict[str, Any]]:
    """获取同花顺热榜 - 页面只读 PG 缓存/历史"""
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, lambda: MarketService.get_ths_hot(limit, date))
    return [{**row, "source_label": row.get("source_label") or "PG 缓存；上游来源未记录"} for row in rows]

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
    """Return the stored concept-leader cache without provider side effects."""
    cached = db.get_concept_leaders_cache(name, limit)
    if not cached:
        return []
    updated_at = db.get_concept_leaders_cache_updated_at(name)
    state = "stale" if MarketService._is_stale_timestamp(updated_at, max_age_hours=36) else "fresh"
    return [
        {
            **row,
            "source_label": row.get("source_label") or "PostgreSQL concept-leader cache",
            "updated_at": row.get("updated_at") or updated_at,
            "data_status": state,
        }
        for row in cached
    ]

@router.get("/fundamentals/{symbol}")
async def get_stock_fundamentals(symbol: str) -> Dict[str, Any]:
    """Read stored fundamentals; explicit sync jobs own provider access."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.get_stock_fundamentals(symbol, cache_only=True))

@router.get("/message-stream")
async def get_message_stream(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.get_message_stream(limit=limit))

@router.post("/message-stream/sync")
async def sync_news_stream() -> Dict[str, Any]:
    """手动同步新闻数据到数据库"""
    from app.services.data_sync_service import data_sync_service
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: data_sync_service.sync_news(sources=['ths', 'cls']))

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

# =============== 复盘中心 API ===============

@router.get("/pulse/lianban-history")
async def get_lianban_history(
    days: int = Query(30, ge=1, le=90, description="获取最近几天的数据"),
    min_level: int = Query(2, ge=1, le=10, description="最低连板数")
) -> List[Dict[str, Any]]:
    """获取连板历史数据用于复盘展示"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.get_lianban_history_for_pulse(days, min_level))

@router.get("/pulse/daily-stats")
async def get_daily_stats(
    days: int = Query(30, ge=1, le=90, description="获取最近几天的数据"),
    min_change_pct: float = Query(3.0, ge=0, le=20, description="最低涨幅(%)筛选"),
    top_n: int = Query(15, ge=5, le=30, description="每天显示的板块数量")
) -> List[Dict[str, Any]]:
    """获取每日板块涨幅统计数据（从数据库读取）"""
    from app.db import db_instance
    return db_instance.get_daily_concept_sectors_multi_days(days, min_change_pct, top_n)

@router.post("/pulse/sync-today")
async def sync_today_concept_sectors() -> Dict[str, Any]:
    """手动同步今日概念板块数据"""
    from app.services.data_sync_service import data_sync_service
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, data_sync_service.sync_daily_concept_sectors)

@router.post("/pulse/backfill-history")
async def backfill_concept_history(
    days: int = Query(30, ge=1, le=90, description="回填最近多少天的数据")
) -> Dict[str, Any]:
    """
    回填历史概念板块数据
    
    通过获取每个概念板块的历史K线数据来计算历史涨幅。
    注意：此操作可能需要较长时间（约5-15分钟）
    """
    from app.services.data_sync_service import data_sync_service
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, 
        lambda: data_sync_service.backfill_concept_history(days)
    )

@router.get("/pulse/replay-notes")
async def list_replay_notes(
    limit: int = Query(60, ge=1, le=365, description="返回最近N条复盘日志")
) -> Dict[str, Any]:
    from app.db import db_instance
    return {"status": "success", "data": db_instance.list_replay_notes(limit)}

@router.get("/pulse/replay-notes/{note_date}")
async def get_replay_note(note_date: str) -> Dict[str, Any]:
    from app.db import db_instance
    item = db_instance.get_replay_note(note_date)
    if not item:
        return {"status": "success", "data": None}
    return {"status": "success", "data": item}

@router.post("/pulse/replay-notes")
async def save_replay_note(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    from app.db import db_instance
    try:
        item = db_instance.upsert_replay_note(payload)
        return {"status": "success", "data": item}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
