from datetime import datetime, time
from typing import Any, Dict, List, Optional

import psycopg2.extras
from fastapi import APIRouter, Query

from app.db.local_db import db_instance as db
from app.services.market_service import MarketService

router = APIRouter()


def _fetch_all(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]


def _fetch_one(query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    rows = _fetch_all(query, params)
    return rows[0] if rows else None


def _normalize_symbol(symbol: str) -> str:
    text = str(symbol or "").strip().upper().replace(".", "_")
    if text.startswith(("SH_", "SZ_", "BJ_")):
        return text
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return text
    if digits.startswith("6"):
        return f"SH_{digits}"
    if digits.startswith(("8", "4")):
        return f"BJ_{digits}"
    return f"SZ_{digits}"


def _is_market_open() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    current = now.time()
    return time(9, 30) <= current <= time(11, 30) or time(13, 0) <= current <= time(15, 0)


def _message_stream_snapshot(limit: int) -> Dict[str, Any]:
    rows = _fetch_all(
        """
        SELECT code, name, COALESCE(change_percent, 0) AS change_percent
        FROM all_stocks_realtime
        WHERE change_percent IS NOT NULL
        ORDER BY ABS(COALESCE(change_percent, 0)) DESC NULLS LAST
        LIMIT %s
        """,
        (max(limit * 4, 50),),
    )
    triggered: List[Dict[str, Any]] = []
    near: List[Dict[str, Any]] = []
    for row in rows:
        code = _normalize_symbol(str(row.get("code") or ""))
        name = str(row.get("name") or code)
        change_percent = float(row.get("change_percent") or 0)
        rule = MarketService._threshold_for_stock(code, name)
        threshold = float(rule.get("threshold_pct") or 10)
        item = {
            "code": code,
            "name": name,
            "exchange": rule.get("exchange") or "",
            "rule_id": rule.get("rule_id") or "unknown",
            "threshold_pct": threshold,
            "change_percent": change_percent,
            "direction": "UP" if change_percent >= 0 else "DOWN",
        }
        if abs(change_percent) >= threshold:
            triggered.append(item)
        elif abs(change_percent) >= max(0.0, threshold - 1.0):
            near.append(item)

    return {
        "updated_at": datetime.now().isoformat(),
        "abnormal": {
            "rules": MarketService._abnormal_rules(),
            "triggered": triggered[:limit],
            "near": near[:limit],
        },
        "mergers": [],
        "good_news": [],
        "bad_news": [],
        "cailian_news": [],
        "xueqiu_news": [],
        "eastmoney_news": [],
    }


@router.get("/admin/task-status")
async def get_task_status() -> Dict[str, Any]:
    return {"is_running": False, "total": 0, "processed": 0, "message": "PG 缓存就绪"}


@router.get("/market/overview")
async def get_market_overview() -> Dict[str, Any]:
    indices = _fetch_all(
        """
        SELECT name, code, COALESCE(price, 0) AS price,
               COALESCE(change_amount, 0) AS change_amount,
               COALESCE(change_percent, 0) AS change_percent,
               updated_at
        FROM market_indices_realtime
        ORDER BY id ASC
        LIMIT 12
        """
    )
    breadth = _fetch_one(
        """
        SELECT
            COUNT(*) FILTER (WHERE change_percent > 0) AS up,
            COUNT(*) FILTER (WHERE change_percent < 0) AS down,
            COUNT(*) FILTER (WHERE change_percent = 0 OR change_percent IS NULL) AS flat
        FROM all_stocks_realtime
        """
    ) or {"up": 0, "down": 0, "flat": 0}
    hot_sectors = await get_hot_sectors(limit=8)
    updated = _fetch_one(
        """
        SELECT MAX(updated_at) AS updated_at FROM (
            SELECT updated_at FROM market_indices_realtime
            UNION ALL
            SELECT updated_at FROM all_stocks_realtime
            UNION ALL
            SELECT updated_at FROM hot_concepts_realtime
        ) t
        """
    )
    return {
        "indices": indices,
        "hot_sectors": hot_sectors,
        "market_breadth": {
            "up": int(breadth.get("up") or 0),
            "down": int(breadth.get("down") or 0),
            "flat": int(breadth.get("flat") or 0),
        },
        "is_open": _is_market_open(),
        "updated_at": str(updated.get("updated_at")) if updated and updated.get("updated_at") else None,
    }


@router.get("/market/hot-concepts")
async def get_hot_concepts(limit: int = Query(50, ge=1, le=200), date: str | None = None) -> List[Dict[str, Any]]:
    return _fetch_all(
        """
        SELECT rank, name, COALESCE(change_percent, 0) AS change_percent,
               COALESCE(inflow, 0) AS inflow,
               COALESCE(outflow, 0) AS outflow,
               COALESCE(net_inflow, 0) AS net_inflow
        FROM hot_concepts_realtime
        ORDER BY rank NULLS LAST, change_percent DESC NULLS LAST
        LIMIT %s
        """,
        (limit,),
    )


@router.get("/sectors/hot")
async def get_hot_sectors(limit: int = Query(20, ge=1, le=100)) -> List[Dict[str, Any]]:
    return _fetch_all(
        """
        SELECT h.name, COALESCE(h.change_percent, 0) AS change_percent,
               0 AS up_count, 0 AS down_count,
               COALESCE(l.stock_name, '') AS leader_stock
        FROM hot_concepts_realtime h
        LEFT JOIN LATERAL (
            SELECT stock_name
            FROM concept_leaders_cache
            WHERE concept_name = h.name
            ORDER BY rank NULLS LAST, change_percent DESC NULLS LAST
            LIMIT 1
        ) l ON TRUE
        ORDER BY h.rank NULLS LAST, h.change_percent DESC NULLS LAST
        LIMIT %s
        """,
        (limit,),
    )


@router.get("/market/hot-concept/leaders")
async def get_hot_concept_leaders(
    name: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=200),
    date: str | None = None,
) -> List[Dict[str, Any]]:
    return _fetch_all(
        """
        SELECT stock_code AS code, stock_name AS name,
               COALESCE(price, 0) AS price,
               COALESCE(change_percent, 0) AS change_percent,
               COALESCE(amount, 0) AS amount,
               COALESCE(turnover, 0) AS turnover
        FROM concept_leaders_cache
        WHERE concept_name = %s
        ORDER BY rank NULLS LAST, change_percent DESC NULLS LAST
        LIMIT %s
        """,
        (name, limit),
    )


@router.get("/market/short-line-indices")
async def get_short_line_indices() -> List[Dict[str, Any]]:
    return _fetch_all(
        """
        SELECT code, name, COALESCE(price, 0) AS price,
               COALESCE(change_percent, 0) AS change_percent,
               COALESCE(change_amount, 0) AS change_amount
        FROM short_line_indices_realtime
        ORDER BY id ASC
        """
    )


@router.get("/market/ths-hot")
async def get_ths_hot(limit: int = Query(100, ge=1, le=200), date: str | None = None) -> List[Dict[str, Any]]:
    return _fetch_all(
        """
        SELECT rank, code, name,
               COALESCE(hot_value, 0) AS hot,
               COALESCE(change_percent, 0) AS change_percent,
               COALESCE(price, 0) AS price,
               COALESCE(reason, '') AS reason,
               COALESCE(tags, '') AS tags
        FROM ths_hot_realtime
        ORDER BY rank NULLS LAST, hot_value DESC NULLS LAST
        LIMIT %s
        """,
        (limit,),
    )


@router.get("/market/lianban-ladder")
async def get_lianban_ladder(date: str | None = None) -> Dict[str, Any]:
    return {"date": date, "prev_date": None, "levels": []}


@router.get("/market/hot-concept/intraday")
async def get_hot_concept_intraday(name: str, period: str = "1", date: str | None = None) -> List[Dict[str, Any]]:
    return []


@router.get("/market/message-stream")
async def get_message_stream(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    return _message_stream_snapshot(limit)


@router.get("/market/fundamentals/{symbol}")
async def get_stock_fundamentals(symbol: str) -> Dict[str, Any]:
    normalized = _normalize_symbol(symbol)
    code_digits = normalized.split("_")[-1]
    row = _fetch_one(
        """
        SELECT code, name, price AS current_price, change_percent, turnover AS turnover_rate,
               volume_ratio, pe_dynamic, pb, total_market_cap, float_market_cap,
               amplitude, updated_at
        FROM all_stocks_realtime
        WHERE code IN (%s, %s)
        LIMIT 1
        """,
        (normalized, code_digits),
    )
    return row or {"code": normalized, "name": None}


@router.get("/stocks/search")
async def search_stocks(q: str = Query("", min_length=0), limit: int = Query(20, ge=1, le=100)) -> List[Dict[str, Any]]:
    keyword = f"%{q.strip()}%"
    return _fetch_all(
        """
        SELECT code, name
        FROM all_stocks_realtime
        WHERE (%s = '%%' OR code ILIKE %s OR name ILIKE %s)
        ORDER BY code ASC
        LIMIT %s
        """,
        (keyword, keyword, keyword, limit),
    )


@router.get("/stocks/filter")
async def get_filtered_stocks(limit: int = Query(200, ge=1, le=1000)) -> Dict[str, Any]:
    stocks = _fetch_all(
        """
        SELECT code, name, COALESCE(price, 0) AS current_price,
               COALESCE(change_percent, 0) AS change_percent,
               COALESCE(volume, 0) AS volume,
               COALESCE(total_market_cap, 0) AS market_cap,
               FALSE AS is_short,
               updated_at
        FROM all_stocks_realtime
        ORDER BY total_market_cap DESC NULLS LAST
        LIMIT %s
        """,
        (limit,),
    )
    total = _fetch_one("SELECT COUNT(*) AS count FROM all_stocks_realtime") or {"count": 0}
    return {"stocks": stocks, "total_count": int(total["count"] or 0), "filter_time": datetime.now().isoformat()}


@router.get("/market/stocks")
async def get_market_stocks(limit: int = Query(300, ge=1, le=1000)) -> List[Dict[str, Any]]:
    return _fetch_all(
        """
        SELECT code, name, COALESCE(price, 0) AS price,
               COALESCE(change_percent, 0) AS change_percent,
               COALESCE(volume, 0) AS volume,
               COALESCE(amount, 0) AS amount,
               COALESCE(turnover, 0) AS turnover
        FROM all_stocks_realtime
        ORDER BY amount DESC NULLS LAST
        LIMIT %s
        """,
        (limit,),
    )


@router.get("/market/sectors")
async def get_market_sectors() -> List[Dict[str, Any]]:
    return await get_hot_sectors()


@router.get("/charts/daily/{symbol}")
async def get_daily_chart(symbol: str, limit: int = Query(120, ge=1, le=500)) -> List[Dict[str, Any]]:
    normalized = _normalize_symbol(symbol)
    rows = db.get_kline_history(normalized, timeframe="1d", limit=limit)
    return [
        {
            "date": row["date"],
            "open": row["open"],
            "close": row["close"],
            "high": row["high"],
            "low": row["low"],
            "volume": row["volume"],
        }
        for row in rows[-limit:]
    ]


@router.get("/charts/intraday/{symbol}")
async def get_intraday_chart(symbol: str) -> List[Dict[str, Any]]:
    rows = db.get_kline_history(_normalize_symbol(symbol), timeframe="1d", limit=1)
    latest = rows[-1] if rows else None
    if not latest:
        return []
    return [
        {
            "time": "15:00",
            "price": latest.get("close") or 0,
            "volume": latest.get("volume") or 0,
            "amount": latest.get("turnover") or 0,
        }
    ]
