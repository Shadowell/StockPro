"""Monitor/alert endpoints for API v2."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.contracts import ok
from app.core.errors import BadRequestError, NotFoundError, UpstreamError
from app.exchange import exchange_manager
from app.exchange.okx_response import first_okx_data_row, open_interest_base_units
from app.services.alert_service import alert_service
from app.services.strategy_service import strategy_service

router = APIRouter()

STRATEGY_ALERT_TYPES = {"strategy_return_below", "strategy_liquidation_risk"}


@router.get("/live-strategy-summaries")
async def live_strategy_summaries():
    """Return server-attributed metrics for active live strategy subscriptions."""
    from app.services.live_profit_push_service import live_profit_push_service

    snapshot = await live_profit_push_service.build_snapshot()
    as_of = str(snapshot.get("generated_at") or "")
    statistics_period = {
        "kind": "asia_shanghai_calendar_day",
        "timezone": snapshot.get("statistics_timezone"),
        "date": snapshot.get("statistics_date"),
        "start": snapshot.get("statistics_start"),
        "end": snapshot.get("statistics_end"),
        "complete": bool(snapshot.get("statistics_complete")),
        "note": str(snapshot.get("statistics_note") or ""),
        "realized_order_history_limit": 1000,
    }
    strategies = []
    for strategy in snapshot.get("strategies") or []:
        if not isinstance(strategy, dict):
            continue
        closing_trade_count = int(strategy.get("closing_trades") or 0)
        trade_count = int(strategy.get("total_trades") or 0)
        strategies.append(
            {
                "strategy_id": int(strategy.get("strategy_id") or 0),
                "name": str(strategy.get("name") or ""),
                "status": str(strategy.get("subscription_status") or strategy.get("status") or "unknown"),
                "return_pct": strategy.get("return_pct"),
                "total_pnl": strategy.get("pnl"),
                "max_drawdown": None,
                "max_drawdown_pct": None,
                "max_drawdown_available": False,
                "win_rate": strategy.get("win_rate") if closing_trade_count > 0 else None,
                "win_rate_available": closing_trade_count > 0,
                "trade_count": trade_count,
                "closing_trade_count": closing_trade_count,
                "trade_count_available": True,
                "statistics_period": {
                    **statistics_period,
                    "complete": bool(strategy.get("statistics_complete")),
                    "baseline_started_at": strategy.get("statistics_started_at"),
                },
                "as_of": as_of,
                "includes_unrealized_pnl": True,
                "unrealized_pnl": strategy.get("unrealized_pnl"),
                "current_unrealized_pnl": strategy.get("unrealized_pnl"),
                "daily_realized_pnl": strategy.get("daily_realized_pnl"),
                "daily_unrealized_change": strategy.get("daily_unrealized_change"),
            }
        )
    limitations = [
        (
            "total_pnl is the Asia/Shanghai calendar-day result: attributed realized PnL "
            "plus the change in attributed unrealized PnL from the daily baseline."
        ),
        "max_drawdown is unavailable until a live strategy equity curve is persisted.",
    ]
    if not statistics_period["complete"]:
        limitations.insert(1, f"Daily statistics are partial: {statistics_period['note'] or 'coverage is incomplete'}.")
    return ok(
        {
            "report_scope": "active_live_strategy_subscriptions",
            "as_of": as_of,
            "includes_unrealized_pnl": True,
            "statistics_period": statistics_period,
            "strategies": strategies,
            "skipped_account_ids": snapshot.get("skipped_account_ids") or [],
            "limitations": limitations,
        }
    )


def _okx_swap_inst_id(symbol: str) -> str:
    s = str(symbol or "").strip().upper()
    if s.endswith("-SWAP"):
        return s
    base = s.split("/", 1)[0] if "/" in s else s.split("-", 1)[0]
    quote_part = s.split("/", 1)[1] if "/" in s else "USDT"
    quote = quote_part.split(":", 1)[0].split("-", 1)[0] or "USDT"
    return f"{base}-{quote}-SWAP"


def _okx_ratio_currency(symbol: str) -> str:
    return _okx_swap_inst_id(symbol).split("-", 1)[0]


def _first_okx_row(response: Any) -> Any:
    if isinstance(response, dict):
        data = response.get("data")
        if isinstance(data, list) and data:
            return data[0]
    if isinstance(response, list) and response:
        return response[0]
    return None


def _parse_okx_long_short_row(row: Any) -> tuple[float, int]:
    ratio_raw: Any = None
    ts_raw: Any = None
    if isinstance(row, dict):
        ratio_raw = (
            row.get("longShortRatio")
            or row.get("long_short_ratio")
            or row.get("ratio")
            or row.get("lsr")
        )
        ts_raw = row.get("ts") or row.get("timestamp") or row.get("time")
    elif isinstance(row, (list, tuple)) and row:
        ts_raw = row[0]
        if len(row) >= 2:
            ratio_raw = row[1]
    return float(ratio_raw or 0), int(ts_raw or 0)


def _parse_okx_open_interest_row(row: Any, market: Dict[str, Any]) -> tuple[float, float, Optional[int]]:
    if not isinstance(row, dict):
        raise UpstreamError("Unexpected open interest response")
    oi_raw = float(row.get("oi") or row.get("openInterest") or 0)
    oi_base_raw = row.get("oiCcy") or row.get("openInterestAmount") or row.get("openInterestBtc")
    oi_base = float(oi_base_raw) if oi_base_raw not in (None, "") else open_interest_base_units(oi_raw, market)
    ts_val: int | None = None
    ts_raw = row.get("ts") or row.get("time") or row.get("timestamp")
    if ts_raw is not None:
        ts_val = int(float(ts_raw))
    return oi_raw, oi_base, ts_val


class AlertCreateRequest(BaseModel):
    name: str
    type: str
    exchange: str = "okx"
    symbol: Optional[str] = None
    threshold: float
    strategy_id: Optional[int] = None
    cooldown_sec: Optional[int] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    webhook_url: Optional[str] = None


@router.get("/alerts")
async def alerts():
    return ok(alert_service.get_alerts())


@router.post("/alerts")
async def create_alert(payload: AlertCreateRequest):
    if payload.type in STRATEGY_ALERT_TYPES:
        if payload.strategy_id is None:
            raise BadRequestError(f"strategy_id is required for {payload.type}")
        if payload.type == "strategy_liquidation_risk" and payload.threshold <= 0:
            raise BadRequestError("threshold must be positive for strategy_liquidation_risk")
        from app.db.local_db import db_instance as db

        strategy = db.get_strategy_by_id(int(payload.strategy_id))
        condition = {
            "scope": "strategy",
            "strategy_id": int(payload.strategy_id),
            "strategy_name": (strategy or {}).get("name") or f"策略 #{payload.strategy_id}",
            "threshold": payload.threshold,
            "cooldown_sec": int(payload.cooldown_sec or 3600),
        }
        if payload.type == "strategy_liquidation_risk":
            condition["metric"] = "liquidation_buffer_pct"
    else:
        if not payload.symbol:
            raise BadRequestError("symbol is required")
        condition = {
            "exchange": payload.exchange,
            "symbol": payload.symbol,
            "threshold": payload.threshold,
        }
        if payload.cooldown_sec is not None:
            condition["cooldown_sec"] = int(payload.cooldown_sec)
    notification: Dict[str, Any] = {}
    if payload.telegram_bot_token and payload.telegram_chat_id:
        notification["telegram"] = {
            "bot_token": payload.telegram_bot_token,
            "chat_id": payload.telegram_chat_id,
        }
    if payload.webhook_url:
        notification["webhook"] = {"url": payload.webhook_url}

    alert_id = await alert_service.create_alert(
        name=payload.name,
        alert_type=payload.type,
        condition=condition,
        notification=notification,
    )
    return ok({"id": alert_id})


@router.put("/alerts/{alert_id}")
async def update_alert(alert_id: int, enabled: bool = Query(...)):
    exists = any(item.get("id") == alert_id for item in alert_service.get_alerts())
    if not exists:
        raise NotFoundError("Alert not found")
    await alert_service.toggle_alert(alert_id, enabled)
    return ok({"id": alert_id, "enabled": enabled})


@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: int):
    exists = any(item.get("id") == alert_id for item in alert_service.get_alerts())
    if not exists:
        raise NotFoundError("Alert not found")
    await alert_service.delete_alert(alert_id)
    return ok({"deleted": True})


@router.get("/running-strategies")
async def running_strategies():
    return ok(await strategy_service.get_all_running(refresh_marks=False))


@router.get("/active_strategies")
async def active_strategies():
    """监控大盘 — 返回运行中策略的实时权益、浮动盈亏、持仓详情。"""
    return ok(await strategy_service.get_all_running(refresh_marks=False))


@router.get("/long-short-ratio")
async def get_long_short_ratio(
    exchange: str = Query("okx", description="交易所"),
    symbol: str = Query("BTC/USDT:USDT", description="交易对"),
):
    ex = exchange_manager.get_exchange(exchange)
    if not ex:
        raise BadRequestError(f"Exchange {exchange} not supported")

    if exchange != "okx" or not hasattr(ex.exchange, "publicGetRubikStatContractsLongShortAccountRatio"):
        raise BadRequestError("Not supported for this exchange")

    try:
        response = await asyncio.to_thread(
            ex.exchange.publicGetRubikStatContractsLongShortAccountRatio,
            {"ccy": _okx_ratio_currency(symbol), "period": "5m"},
        )
        if not response:
            raise UpstreamError("No data from exchange")
        item = _first_okx_row(response)
        if item is None:
            raise UpstreamError("No data from exchange")
        ratio, ts = _parse_okx_long_short_row(item)
        if ratio <= 0:
            raise UpstreamError("No valid long-short ratio from exchange")
        long_ratio = ratio / (1 + ratio)
        short_ratio = 1 / (1 + ratio)
        return ok(
            {
                "exchange": exchange,
                "symbol": symbol,
                "long_ratio": long_ratio,
                "short_ratio": short_ratio,
                "long_short_ratio": ratio,
                "ratio": ratio,
                "timestamp": ts,
            }
        )
    except Exception as exc:
        raise UpstreamError(f"获取多空比失败: {exc}") from exc


@router.get("/open-interest")
async def get_open_interest(
    exchange: str = Query("okx", description="交易所"),
    symbol: str = Query("BTC/USDT:USDT", description="交易对"),
):
    ex = exchange_manager.get_exchange(exchange)
    if not ex:
        raise BadRequestError(f"Exchange {exchange} not supported")

    if exchange != "okx":
        raise BadRequestError("Not supported for this exchange")
    if not (
        hasattr(ex.exchange, "publicGetPublicOpenInterest")
        or hasattr(ex.exchange, "fapiPublicGetOpenInterest")
    ):
        raise BadRequestError("Not supported for this exchange")

    try:
        await asyncio.to_thread(ex.load_markets)
        market = await asyncio.to_thread(ex.exchange.market, symbol)
        if hasattr(ex.exchange, "publicGetPublicOpenInterest"):
            response = await asyncio.to_thread(
                ex.exchange.publicGetPublicOpenInterest,
                {"instType": "SWAP", "instId": str(market.get("id") or _okx_swap_inst_id(symbol))},
            )
        elif hasattr(ex.exchange, "fapiPublicGetOpenInterest"):
            response = await asyncio.to_thread(
                ex.exchange.fapiPublicGetOpenInterest,
                {"symbol": market["id"]},
            )
        row = first_okx_data_row(response)
        if row is None and isinstance(response, dict):
            row = response
        oi_raw, oi_btc, ts_val = _parse_okx_open_interest_row(row, market)

        return ok(
            {
                "exchange": exchange,
                "symbol": symbol,
                "open_interest": oi_raw,
                "open_interest_btc": oi_btc,
                "timestamp": ts_val,
            }
        )
    except Exception as exc:
        raise UpstreamError(f"获取持仓量失败: {exc}") from exc
