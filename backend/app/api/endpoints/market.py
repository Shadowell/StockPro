import asyncio
import logging
import time
from fastapi import APIRouter, Query, Body, HTTPException
from app.services.market_service import MarketService
from app.services.market_research_service import MarketResearchService
from app.services.market_watchlist_service import MarketWatchlistService
from app.db import db_instance as db
from typing import Any, Dict, List

router = APIRouter()
logger = logging.getLogger(__name__)
research_service = MarketResearchService(db)
watchlist_service = MarketWatchlistService(db)
_OVERVIEW_CACHE: Dict[str, Any] = {"at": 0.0, "payload": None}


@router.get("/watchlist")
async def get_watchlist() -> Dict[str, Any]:
    return await asyncio.to_thread(watchlist_service.list_entries)


@router.post("/watchlist/items")
async def add_watchlist_item(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(watchlist_service.add_entry, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/watchlist/items/{entry_id}")
async def delete_watchlist_item(entry_id: int) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(watchlist_service.delete_entry, entry_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _get_hot_concept_leaders_cached(name: str, limit: int) -> List[Dict[str, Any]]:
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


def _fetch_concept_leaders_em_delayed(name: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch concept members from the delayed eastmoney quote cluster.

    Fallback for ``_fetch_concept_leaders_from_api`` when the realtime push2
    cluster is unreachable (blocked network/proxy). Data is delayed ~15min;
    callers must label the source accordingly.
    """
    import requests

    session = requests.Session()
    session.trust_env = False
    headers = {"User-Agent": "Mozilla/5.0"}
    suggest = session.get(
        "https://searchadapter.eastmoney.com/api/suggest/get",
        params={"input": name, "type": "14"},
        headers=headers,
        timeout=8,
    )
    suggest.raise_for_status()
    table = (suggest.json() or {}).get("QuotationCodeTable") or {}
    board_code = None
    for item in table.get("Data") or []:
        if str(item.get("Classify") or "").upper() == "BK" and item.get("Code"):
            board_code = str(item["Code"])
            break
    if not board_code:
        return []
    quote = session.get(
        "https://push2delay.eastmoney.com/api/qt/clist/get",
        params={
            "pn": 1,
            "pz": 100,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fs": f"b:{board_code}",
            "fields": "f2,f3,f6,f8,f12,f14",
        },
        headers=headers,
        timeout=10,
    )
    quote.raise_for_status()
    diff = ((quote.json() or {}).get("data") or {}).get("diff") or []
    rows: List[Dict[str, Any]] = []
    for item in diff:
        code = str(item.get("f12") or "").strip()
        stock_name = str(item.get("f14") or "").strip()
        if not code or not stock_name:
            continue
        rows.append(
            {
                "code": code,
                "name": stock_name,
                "price": float(item.get("f2") or 0.0),
                "change_percent": float(item.get("f3") or 0.0),
                "amount": float(item.get("f6") or 0.0),
                "turnover": float(item.get("f8") or 0.0),
            }
        )
    return rows[: max(1, min(int(limit), 200))]


def _sync_concept_leaders(name: str | None, limit: int) -> Dict[str, Any]:
    """Explicit leader-cache sync: page reads stay cache-only, this is the write path."""
    import time as _time

    names: List[str] = []
    if name:
        names = [str(name).strip()]
    else:
        concepts = db.get_hot_concepts_realtime(limit=max(1, min(int(limit), 50))) or []
        names = [str(item.get("name") or "").strip() for item in concepts]
        names = [item for item in names if item]
    synced: List[str] = []
    empty: List[str] = []
    failed: Dict[str, str] = {}
    sources: Dict[str, str] = {}
    for index, concept_name in enumerate(names):
        if index:
            _time.sleep(0.3)
        try:
            leaders = MarketService._fetch_concept_leaders_from_api(concept_name, 20)
            source = "eastmoney-realtime"
            if not leaders:
                try:
                    leaders = _fetch_concept_leaders_em_delayed(concept_name, 20)
                    source = "eastmoney-delayed" if leaders else "unavailable"
                except Exception as fallback_exc:
                    logger.warning("Delayed leader fallback failed for %s: %s", concept_name, fallback_exc)
                    source = "unavailable"
            if leaders:
                db.update_concept_leaders_cache(concept_name, leaders)
                synced.append(concept_name)
                sources[concept_name] = source
            else:
                empty.append(concept_name)
                sources[concept_name] = source
        except Exception as exc:
            failed[concept_name] = str(exc)
            sources[concept_name] = "unavailable"
    return {
        "synced": synced,
        "synced_count": len(synced),
        "empty": empty,
        "failed": failed,
        "sources": sources,
        "total_concepts": len(names),
    }


@router.get("/research-context")
async def get_research_context(
    snapshot_id: int | None = Query(None),
    trade_date: str | None = Query(None),
    market_scope: str = Query("all_a"),
) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(
            research_service.research_context,
            snapshot_id,
            trade_date,
            market_scope,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/evidence-snapshots")
async def list_evidence_snapshots(
    trade_date: str | None = Query(None),
    market_scope: str | None = Query(None),
    limit: int = Query(100, ge=1, le=365),
) -> Dict[str, Any]:
    items = await asyncio.to_thread(
        research_service.list_snapshots,
        trade_date=trade_date,
        market_scope=market_scope,
        limit=limit,
    )
    return {"items": items, "total": len(items)}


@router.get("/sentiment")
async def get_research_sentiment(snapshot_id: int = Query(...)) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(research_service.sentiment, snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/limit-ecosystem")
async def get_limit_ecosystem(snapshot_id: int = Query(...)) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(research_service.limit_ecosystem, snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sector-evidence")
async def get_sector_evidence(
    snapshot_id: int = Query(...),
    classification: str = Query("tushare_limit_industry"),
) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(
            research_service.sector_evidence,
            snapshot_id,
            classification,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.get("/overview")
async def get_market_overview() -> Dict[str, Any]:
    """获取市场概览数据 - 优先从数据库获取，没有则实时获取"""
    now = time.monotonic()
    cached = _OVERVIEW_CACHE.get("payload")
    if cached and now - float(_OVERVIEW_CACHE.get("at") or 0) < 30:
        return cached
    loop = asyncio.get_running_loop()
    payload = await loop.run_in_executor(None, MarketService.get_market_overview)
    _OVERVIEW_CACHE["at"] = time.monotonic()
    _OVERVIEW_CACHE["payload"] = payload
    return payload

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


@router.get("/sector-fund-flow")
async def get_sector_fund_flow(
    limit: int = Query(30, ge=1, le=50),
) -> Dict[str, Any]:
    """Homepage sector inflow/outflow board from PG hot-concept money-flow cache."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.get_sector_fund_flow(limit))


@router.get("/limit-board")
async def get_limit_board(
    trade_date: str | None = Query(None, description="YYYY-MM-DD；默认取最新封存快照"),
) -> Dict[str, Any]:
    """Homepage limit-up / limit-down member list for K-line + intraday drill-down."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.get_limit_board(trade_date))


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
    return await asyncio.to_thread(_get_hot_concept_leaders_cached, name, limit)


@router.post("/hot-concept/leaders/sync")
async def sync_hot_concept_leaders(
    name: str | None = Query(None, description="概念名；缺省则同步热门概念榜前 N 名"),
    limit: int = Query(30, ge=1, le=50),
) -> Dict[str, Any]:
    """手动同步概念龙头股缓存；页面读取仍保持 cache-only。"""
    if limit > 50:
        limit = 50
    return await asyncio.to_thread(_sync_concept_leaders, name, limit)

@router.get("/fundamentals/{symbol}")
async def get_stock_fundamentals(symbol: str) -> Dict[str, Any]:
    """Read stored fundamentals; explicit sync jobs own provider access."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.get_stock_fundamentals(symbol, cache_only=True))


@router.get("/order-book/{symbol}")
async def get_order_book(symbol: str) -> Dict[str, Any]:
    """Live five-level bid/ask for one symbol (TuShare quotes → East Money fallback)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.get_order_book(symbol))

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


@router.get("/trading-calendar")
async def get_trading_calendar(
    start: str | None = Query(None),
    end: str | None = Query(None),
) -> Dict[str, Any]:
    """Month grid: open/closed sessions, futures delivery and macro tags per day."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: MarketService.get_trading_calendar(start=start, end=end))

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
    return await asyncio.to_thread(
        db_instance.get_daily_concept_sectors_multi_days,
        days,
        min_change_pct,
        top_n,
    )

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
