"""首页「加密原生数据」聚合端点。

只读聚合已落库的真实数据，不做任何网络请求：
- okx_rubik_stats：taker 资金流（最近一日买卖量与买入占比）、多空账户比（最新）
- funding_rate_history（exchange='okx'）：最新资金费率
- open_interest_history：OI 最新快照与 24h 变化（okx 前向积累 + binanceusdm 回填）
- pipeline：各数据源的积累进度（行数与时间覆盖），如实反映数据边界
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List

from fastapi import APIRouter

from app.core.contracts import ok
from app.db.local_db import db_instance as db

router = APIRouter()

CORE_CCYS = ["BTC", "ETH", "SOL"]
DAY_MS = 86_400_000


def _rows(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn = db.get_connection()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def _scalar(sql: str, params: tuple = ()) -> Any:
    conn = db.get_connection()
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None
    except Exception:
        return None
    finally:
        conn.close()


def _core_symbol_payload(ccy: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"ccy": ccy, "symbol": f"{ccy}/USDT:USDT"}

    # taker flow: latest daily row (value=sell vol, value2=buy vol)
    flow = _rows(
        "SELECT timestamp, value, value2 FROM okx_rubik_stats "
        "WHERE metric='taker_volume' AND ccy=? ORDER BY timestamp DESC LIMIT 1",
        (ccy,),
    )
    if flow:
        row = flow[0]
        sell, buy = float(row["value"] or 0), float(row["value2"] or 0)
        total = sell + buy
        payload["taker"] = {
            "date": datetime_str(row["timestamp"]),
            "sell_vol": sell,
            "buy_vol": buy,
            "buy_ratio": round(buy / total, 4) if total > 0 else None,
        }

    # long/short account ratio: latest
    lsr = _rows(
        "SELECT timestamp, value FROM okx_rubik_stats "
        "WHERE metric='long_short_ratio' AND ccy=? ORDER BY timestamp DESC LIMIT 1",
        (ccy,),
    )
    if lsr:
        payload["long_short_ratio"] = {
            "date": datetime_str(lsr[0]["timestamp"]),
            "value": float(lsr[0]["value"]),
        }

    # funding rate: latest okx row (alias forms: BTC-USDT-SWAP or BTC/USDT:USDT)
    funding = _rows(
        "SELECT timestamp, funding_rate FROM funding_rate_history "
        "WHERE exchange='okx' AND symbol IN (?, ?) ORDER BY timestamp DESC LIMIT 1",
        (f"{ccy}-USDT-SWAP", f"{ccy}/USDT:USDT"),
    )
    if funding:
        payload["funding_rate"] = {
            "date": datetime_str(funding[0]["timestamp"]),
            "value": float(funding[0]["funding_rate"]),
        }

    # OI: latest snapshot per exchange + 24h change (binanceusdm hourly backfill preferred)
    for exchange in ("binanceusdm", "okx"):
        latest = _rows(
            "SELECT timestamp, open_interest, open_interest_value FROM open_interest_history "
            "WHERE exchange=? AND symbol=? ORDER BY timestamp DESC LIMIT 1",
            (exchange, payload["symbol"]),
        )
        if not latest:
            continue
        latest_ts = int(latest[0]["timestamp"])
        prev = _rows(
            "SELECT open_interest FROM open_interest_history "
            "WHERE exchange=? AND symbol=? AND timestamp<=? AND timestamp>? "
            "ORDER BY timestamp DESC LIMIT 1",
            (exchange, payload["symbol"], latest_ts - DAY_MS + 3_600_000, latest_ts - DAY_MS - 3_600_000),
        )
        change_pct = None
        if prev and float(prev[0]["open_interest"] or 0) > 0:
            change_pct = round(
                (float(latest[0]["open_interest"]) - float(prev[0]["open_interest"]))
                / float(prev[0]["open_interest"]) * 100,
                2,
            )
        payload["oi"] = {
            "exchange": exchange,
            "date": datetime_str(latest_ts),
            "open_interest": float(latest[0]["open_interest"]),
            "open_interest_usd": float(latest[0]["open_interest_value"] or 0),
            "change_24h_pct": change_pct,
        }
        break
    return payload


def datetime_str(ts_ms: Any) -> str:
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def _pipeline_payload() -> Dict[str, Any]:
    def span(table: str, where: str = "", params: tuple = ()) -> Dict[str, Any]:
        rows = _rows(
            f"SELECT COUNT(*) AS n, MIN(timestamp) AS t0, MAX(timestamp) AS t1 "
            f"FROM {table} {where}",
            params,
        )
        if not rows or not rows[0]["n"]:
            return {"rows": 0, "from": "", "to": ""}
        return {
            "rows": int(rows[0]["n"]),
            "from": datetime_str(rows[0]["t0"]),
            "to": datetime_str(rows[0]["t1"]),
        }

    return {
        "rubik_taker_volume": span("okx_rubik_stats", "WHERE metric='taker_volume'"),
        "rubik_long_short": span("okx_rubik_stats", "WHERE metric='long_short_ratio'"),
        "oi_okx_forward": span("open_interest_history", "WHERE exchange='okx'"),
        "oi_binance_backfill": span("open_interest_history", "WHERE exchange='binanceusdm'"),
        "funding_okx": span("funding_rate_history", "WHERE exchange='okx'"),
    }


@router.get("/native-sentiment")
async def native_sentiment():
    core = [_core_symbol_payload(ccy) for ccy in CORE_CCYS]
    return ok({"core": core, "pipeline": _pipeline_payload()})
