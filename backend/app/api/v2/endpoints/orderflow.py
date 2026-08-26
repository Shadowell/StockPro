"""订单流大单分析 API：明细查询、bar 级聚合、采集状态。

数据源：okx_large_trades 表（okx_large_trade_stream_service 实时写入）。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from app.core.contracts import ok
from app.db.local_db import db_instance as local_db
from app.services.okx_large_trade_stream_service import okx_large_trade_stream_service

router = APIRouter()


def _parse_ts_hours_ago(hours: Optional[float]) -> int:
    if hours is None:
        hours = 24.0
    return int((time.time() - hours * 3600) * 1000)


@router.get("/large-trades")
async def list_large_trades(
    inst_id: str = Query(..., description="合约 ID，如 BTC/USDT:USDT"),
    hours: float = Query(24.0, gt=0, le=24 * 90, description="回看小时数"),
    min_notional: float = Query(0.0, ge=0, description="名义下限过滤（≥采集阈值内再筛）"),
    side: Optional[str] = Query(None, pattern="^(buy|sell)$"),
    limit: int = Query(500, ge=1, le=5000),
):
    since = _parse_ts_hours_ago(hours)
    sql = (
        "SELECT inst_id, trade_id, px, sz_base, notional_usdt, side, trade_ts "
        "FROM okx_large_trades WHERE inst_id = ? AND trade_ts >= ?"
    )
    params: List[Any] = [inst_id, since]
    if min_notional > 0:
        sql += " AND notional_usdt >= ?"
        params.append(min_notional)
    if side:
        sql += " AND side = ?"
        params.append(side)
    sql += " ORDER BY trade_ts DESC LIMIT ?"
    params.append(limit)
    conn = local_db.get_connection()
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    return ok({"items": rows, "count": len(rows)})


@router.get("/bars")
async def large_trade_bars(
    inst_id: str = Query(...),
    bar_minutes: int = Query(60, ge=1, le=1440, description="聚合 bar 宽（分钟）"),
    hours: float = Query(72.0, gt=0, le=24 * 90),
):
    since = _parse_ts_hours_ago(hours)
    bar_ms = bar_minutes * 60_000
    sql = (
        "SELECT (trade_ts / ?) * ? AS bar_ts, "
        "SUM(CASE WHEN side = 'buy' THEN notional_usdt ELSE 0 END) AS buy_notional, "
        "SUM(CASE WHEN side = 'sell' THEN notional_usdt ELSE 0 END) AS sell_notional, "
        "SUM(CASE WHEN side = 'buy' THEN notional_usdt ELSE -notional_usdt END) AS delta, "
        "COUNT(*) AS trade_count, "
        "SUM(notional_usdt * px) / NULLIF(SUM(notional_usdt), 0) AS vwap, "
        "MIN(px) AS low_px, MAX(px) AS high_px "
        "FROM okx_large_trades WHERE inst_id = ? AND trade_ts >= ? "
        "GROUP BY bar_ts ORDER BY bar_ts ASC"
    )
    conn = local_db.get_connection()
    rows = [dict(r) for r in conn.execute(sql, [bar_ms, bar_ms, inst_id, since]).fetchall()]
    # 累积 CVD
    cum = 0.0
    for r in rows:
        cum += float(r.get("delta") or 0.0)
        r["cum_delta"] = cum
    return ok({"items": rows, "bar_minutes": bar_minutes, "count": len(rows)})


@router.get("/symbols")
async def large_trade_symbols(hours: float = Query(168.0, gt=0, le=24 * 90)):
    since = _parse_ts_hours_ago(hours)
    sql = (
        "SELECT inst_id, COUNT(*) AS trade_count, SUM(notional_usdt) AS total_notional, "
        "MAX(trade_ts) AS last_ts "
        "FROM okx_large_trades WHERE trade_ts >= ? "
        "GROUP BY inst_id ORDER BY total_notional DESC"
    )
    conn = local_db.get_connection()
    rows = [dict(r) for r in conn.execute(sql, [since]).fetchall()]
    return ok({"items": rows, "count": len(rows)})


@router.get("/stream-status")
async def large_trade_stream_status():
    return ok(okx_large_trade_stream_service.get_status())
