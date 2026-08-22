"""Scheduled real live-account profit card push service."""
from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from app.db.local_db import db_instance as db
from app.services.feishu_notifier import feishu_notifier
from app.services import live_account_service
from app.services.live_signal_execution_service import live_signal_execution_service
from app.services.strategy_profit_push_service import (
    as_float,
    clamp_interval_minutes,
    iso,
    parse_dt,
    utcnow,
)
from app.services.trading_service import trading_service


LIVE_PROFIT_TIMEZONE_NAME = "Asia/Shanghai"
LIVE_PROFIT_TIMEZONE = ZoneInfo(LIVE_PROFIT_TIMEZONE_NAME)
LIVE_PROFIT_DAILY_BASELINE_KEY = "live_profit_daily_baseline_v1"
LIVE_PROFIT_ORDER_HISTORY_LIMIT = 1000
LIVE_PROFIT_BASELINE_GRACE = timedelta(minutes=5)


def _upper_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _extract_symbols(row: Optional[Dict[str, Any]]) -> List[str]:
    if not row:
        return []
    cfg = row.get("config") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    raw = cfg.get("trade_symbols") or cfg.get("symbols") or row.get("symbols") or []
    if not isinstance(raw, list):
        raw = [raw] if raw else []
    return [str(item) for item in raw if str(item or "").strip()]


def _position_symbol(position: Dict[str, Any]) -> str:
    return str(position.get("symbol") or position.get("instId") or position.get("currency") or "")


def _position_side(position: Dict[str, Any]) -> str:
    side = str(position.get("side") or position.get("posSide") or position.get("pos_side") or "").lower()
    if side in {"long", "short"}:
        return side
    size = as_float(
        position.get("contracts")
        or position.get("size")
        or position.get("base_qty")
        or position.get("baseQty")
        or position.get("amount")
    )
    return "short" if size < 0 else "long"


def _position_size(position: Dict[str, Any]) -> float:
    return abs(
        as_float(
            position.get("contracts")
            or position.get("contractSize")
            or position.get("size")
            or position.get("base_qty")
            or position.get("baseQty")
            or position.get("amount")
        )
    )


def _position_price(position: Dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = as_float(position.get(key))
        if value > 0:
            return value
    return 0.0


def _position_notional(position: Dict[str, Any]) -> float:
    notional = as_float(
        position.get("notional_usdt")
        or position.get("notionalUsdt")
        or position.get("notional")
        or position.get("value")
    )
    if notional > 0:
        return abs(notional)
    mark = _position_price(position, "mark_price", "markPrice", "markPx", "last")
    entry = _position_price(position, "entry_price", "entryPrice", "avgPx")
    return abs(_position_size(position) * (mark or entry))


def _order_symbol(order: Dict[str, Any]) -> str:
    return str(order.get("symbol") or order.get("instrument_id") or order.get("instrumentId") or order.get("instId") or "")


def _order_source_id(order: Dict[str, Any]) -> int:
    try:
        return int(order.get("source_strategy_id") or order.get("sourceStrategyId") or 0)
    except (TypeError, ValueError):
        return 0


def _order_timestamp_ms(order: Dict[str, Any]) -> Optional[int]:
    for key in ("timestamp", "created_timestamp", "createdTimestamp", "updateTime", "time"):
        raw = order.get(key)
        if raw is None:
            continue
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value * 1000 if value < 10_000_000_000 else value
    for key in ("datetime", "created_datetime", "createdDatetime", "created_at"):
        raw = str(order.get(key) or "").strip()
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    return None


def _order_pnl_values(orders: List[Dict[str, Any]]) -> List[float]:
    values: List[float] = []
    for order in orders:
        raw = (
            order.get("pnl")
            if order.get("pnl") is not None
            else order.get("realized_pnl")
            if order.get("realized_pnl") is not None
            else order.get("realizedPnl")
        )
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    return values


def _positive_capital(value: Any) -> float:
    out = as_float(value)
    return out if out > 0 and math.isfinite(out) else 0.0


def _configured_live_initial_capital(
    row: Optional[Dict[str, Any]],
    subscription: Optional[Dict[str, Any]],
    *,
    fallback_equity: float,
    total_pnl: float,
) -> float:
    candidates: List[Any] = []
    risk = (subscription or {}).get("risk_config") if subscription else {}
    if isinstance(risk, dict):
        candidates.extend(
            risk.get(key)
            for key in (
                "trial_initial_equity",
                "trialInitialEquity",
                "initial_equity",
                "initialEquity",
                "initial_capital",
                "initialCapital",
                "live_initial_capital",
                "liveInitialCapital",
            )
        )
    cfg = (row or {}).get("config") if row else {}
    if not isinstance(cfg, dict):
        cfg = {}
    promotion = cfg.get("promotion")
    if isinstance(promotion, dict):
        candidates.extend(
            promotion.get(key)
            for key in (
                "trial_initial_equity",
                "trialInitialEquity",
                "initial_equity",
                "initialEquity",
            )
        )
    candidates.extend(
        cfg.get(key)
        for key in (
            "live_initial_capital",
            "liveInitialCapital",
            "initial_capital",
            "initialCapital",
            "initial_equity",
            "initialEquity",
        )
    )
    for candidate in candidates:
        capital = _positive_capital(candidate)
        if capital > 0:
            return capital
    return max(as_float(fallback_equity) - as_float(total_pnl), 0.0)


class LiveProfitPushService:
    """Build and push Feishu profit cards for BitPro live execution accounts."""

    def __init__(
        self,
        *,
        database: Any = db,
        account_service: Any = live_account_service,
        live_execution_service: Any = live_signal_execution_service,
        trading_service: Any = trading_service,
        notifier: Any = feishu_notifier,
        now_fn: Callable[[], datetime] = utcnow,
    ) -> None:
        self.db = database
        self.account_service = account_service
        self.live_execution_service = live_execution_service
        self.trading_service = trading_service
        self.notifier = notifier
        self.now_fn = now_fn
        self._run_lock = asyncio.Lock()

    def get_config(self) -> Dict[str, Any]:
        cfg = self.db.get_live_profit_push_config()
        cfg["interval_minutes"] = clamp_interval_minutes(cfg.get("interval_minutes"))
        cfg["notify_ready"] = self._notify_ready()
        return cfg

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if "enabled" in updates and updates.get("enabled") is not None:
            payload["enabled"] = bool(updates.get("enabled"))
        if "interval_minutes" in updates and updates.get("interval_minutes") is not None:
            payload["interval_minutes"] = clamp_interval_minutes(updates.get("interval_minutes"))
        cfg = self.db.update_live_profit_push_config(payload)
        cfg["notify_ready"] = self._notify_ready()
        return cfg

    def _notify_ready(self) -> bool:
        is_ready = getattr(self.notifier, "is_ready", None)
        if not callable(is_ready):
            return False
        try:
            return bool(is_ready(require_enabled=False))
        except TypeError:
            return bool(is_ready())

    async def run_due(self) -> Dict[str, Any]:
        cfg = self.get_config()
        if not bool(cfg.get("enabled")):
            return {"started": False, "skipped": "disabled"}

        interval = clamp_interval_minutes(cfg.get("interval_minutes"))
        now = self.now_fn()
        last_attempt = parse_dt(cfg.get("last_finished_at") or cfg.get("last_sent_at"))
        if last_attempt and (now - last_attempt) < timedelta(minutes=interval):
            baseline_captured = await self.ensure_daily_baseline()
            return {
                "started": False,
                "skipped": "not_due",
                "daily_baseline_captured": baseline_captured,
            }

        return await self.run_once(force=False, config=cfg)

    async def ensure_daily_baseline(self) -> bool:
        now = self.now_fn()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        local_date = now.astimezone(LIVE_PROFIT_TIMEZONE).date().isoformat()
        stored = self._load_daily_baseline()
        if stored.get("date") == local_date:
            return False
        await self.build_snapshot()
        return self._load_daily_baseline().get("date") == local_date

    async def run_once(self, *, force: bool = False, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self._run_lock.locked():
            return {"started": False, "running": True, "message": "实盘收益卡片推送正在运行"}

        async with self._run_lock:
            cfg = config or self.get_config()
            if not force and not bool(cfg.get("enabled")):
                return {"started": False, "running": False, "skipped": "disabled"}

            started_at = iso(self.now_fn())
            self.db.set_live_profit_push_runtime(
                running=True,
                last_started_at=started_at,
                last_error=None,
                last_skip_reason=None,
            )
            try:
                snapshot = await self.build_snapshot()
                if int(snapshot.get("running_count") or 0) <= 0:
                    self.db.set_live_profit_push_runtime(
                        running=False,
                        last_finished_at=iso(self.now_fn()),
                        last_error=None,
                        last_skip_reason="no_live_positions",
                    )
                    return {
                        "started": True,
                        "running": False,
                        "sent": False,
                        "skipped": "no_live_positions",
                    }

                sent = await self.notifier.notify_strategy_profit_report(snapshot)
                finished_at = iso(self.now_fn())
                if sent:
                    self.db.set_live_profit_push_runtime(
                        running=False,
                        last_sent_at=finished_at,
                        last_finished_at=finished_at,
                        last_error=None,
                        last_skip_reason=None,
                    )
                else:
                    self.db.set_live_profit_push_runtime(
                        running=False,
                        last_finished_at=finished_at,
                        last_error="飞书推送未启用、Webhook 未配置或发送失败",
                        last_skip_reason=None,
                    )
                return {
                    "started": True,
                    "running": False,
                    "sent": bool(sent),
                    "running_count": snapshot.get("running_count", 0),
                    "total_pnl": snapshot.get("total_pnl", 0),
                    "total_return_pct": snapshot.get("total_return_pct", 0),
                }
            except Exception as exc:
                self.db.set_live_profit_push_runtime(
                    running=False,
                    last_finished_at=iso(self.now_fn()),
                    last_error=str(exc),
                    last_skip_reason=None,
                )
                raise

    async def build_snapshot(self) -> Dict[str, Any]:
        generated_at = self.now_fn()
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        generated_at = generated_at.astimezone(timezone.utc)
        local_now = generated_at.astimezone(LIVE_PROFIT_TIMEZONE)
        local_day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_start_ms = int(local_day_start.timestamp() * 1000)
        generated_at_ms = int(generated_at.timestamp() * 1000)
        baseline = self._load_daily_baseline()
        if baseline.get("date") != local_now.date().isoformat():
            baseline = {
                "date": local_now.date().isoformat(),
                "timezone": LIVE_PROFIT_TIMEZONE_NAME,
                "strategies": {},
            }
        baseline_strategies = baseline.get("strategies")
        if not isinstance(baseline_strategies, dict):
            baseline_strategies = {}
            baseline["strategies"] = baseline_strategies
        baseline_changed = False
        accounts = [
            account
            for account in (self.account_service.list_accounts() or [])
            if account.get("enabled") and account.get("configured")
        ]
        configured_account_ids = {str(account.get("account_id") or "default") for account in accounts}
        subscriptions = list(
            self.live_execution_service.list_subscriptions(
                statuses=sorted(getattr(self.live_execution_service, "ACTIVE_STATUSES", {"running", "deployed"}))
            )
            or []
        )
        rows_by_strategy = {
            int(sub.get("source_strategy_id") or 0): self.db.get_strategy_by_id(int(sub.get("source_strategy_id") or 0))
            for sub in subscriptions
            if int(sub.get("source_strategy_id") or 0) > 0
        }
        account_payloads = await asyncio.gather(
            *[self._load_account_payload(account) for account in accounts],
            return_exceptions=True,
        )

        positions_by_account: Dict[str, List[Dict[str, Any]]] = {}
        orders_by_account: Dict[str, List[Dict[str, Any]]] = {}
        equity_by_account: Dict[str, float] = {}
        balance_by_account: Dict[str, float] = {}
        failed_account_ids: set[str] = set()
        truncated_account_ids: set[str] = set()
        for account, payload in zip(accounts, account_payloads):
            account_id = str(account.get("account_id") or "default")
            if isinstance(payload, Exception):
                failed_account_ids.add(account_id)
                continue
            positions_by_account[account_id] = payload.get("positions") or []
            orders_by_account[account_id] = payload.get("orders") or []
            equity_by_account[account_id] = as_float(payload.get("equity"))
            balance_by_account[account_id] = as_float(payload.get("balance"))
            if payload.get("orders_truncated"):
                truncated_account_ids.add(account_id)

        strategies: List[Dict[str, Any]] = []
        missing_timestamp_order_count = 0
        assigned_position_keys_by_account: Dict[str, set[tuple[str, str]]] = {}
        for sub in subscriptions:
            strategy_id = int(sub.get("source_strategy_id") or 0)
            account_id = str(sub.get("account_id") or "default")
            if account_id not in configured_account_ids or account_id in failed_account_ids:
                continue
            row = rows_by_strategy.get(strategy_id)
            symbols = _extract_symbols(row)
            candidate_positions = self._filter_positions(positions_by_account.get(account_id, []), symbols)
            assigned_position_keys = assigned_position_keys_by_account.setdefault(account_id, set())
            related_positions = []
            for position in candidate_positions:
                symbol_key = _upper_symbol(position.get("symbol"))
                side_key = str(position.get("side") or "").strip().lower()
                position_key = (symbol_key, side_key)
                if not symbol_key or position_key in assigned_position_keys:
                    continue
                assigned_position_keys.add(position_key)
                related_positions.append(position)
            attributed_orders = [
                order
                for order in orders_by_account.get(account_id, [])
                if _order_source_id(order) == strategy_id
            ]
            related_orders: List[Dict[str, Any]] = []
            for order in attributed_orders:
                timestamp_ms = _order_timestamp_ms(order)
                if timestamp_ms is None:
                    missing_timestamp_order_count += 1
                    continue
                if day_start_ms <= timestamp_ms <= generated_at_ms:
                    related_orders.append(order)
            account_meta = next((item for item in accounts if str(item.get("account_id") or "") == account_id), {})
            baseline_key = f"{account_id}:{strategy_id}"
            baseline_entry = baseline_strategies.get(baseline_key)
            if not isinstance(baseline_entry, dict):
                current_unrealized = sum(as_float(item.get("unrealized_pnl")) for item in related_positions)
                current_equity = equity_by_account.get(account_id, 0.0) or max(
                    sum(as_float(item.get("notional_usdt")) for item in related_positions)
                    + balance_by_account.get(account_id, 0.0),
                    0.0,
                )
                baseline_initial_capital = _configured_live_initial_capital(
                    row,
                    sub,
                    fallback_equity=current_equity,
                    total_pnl=0.0,
                )
                subscription_started_at = parse_dt((sub or {}).get("created_at"))
                started_today = bool(
                    subscription_started_at
                    and local_day_start <= subscription_started_at.astimezone(LIVE_PROFIT_TIMEZONE) <= local_now
                )
                baseline_entry = {
                    "unrealized_pnl": 0.0 if started_today else round(current_unrealized, 6),
                    "initial_capital": round(baseline_initial_capital, 6),
                    "captured_at": iso(subscription_started_at if started_today else generated_at),
                    "complete": bool(
                        started_today or local_now <= local_day_start + LIVE_PROFIT_BASELINE_GRACE
                    ),
                }
                baseline_strategies[baseline_key] = baseline_entry
                baseline_changed = True
            strategies.append(
                self._normalize_live_strategy(
                    strategy_id=strategy_id,
                    row=row,
                    subscription=sub,
                    account=account_meta,
                    positions=related_positions,
                    orders=related_orders,
                    baseline=baseline_entry,
                    account_equity=equity_by_account.get(account_id, 0.0),
                    account_balance=balance_by_account.get(account_id, 0.0),
                )
            )

        if baseline_changed or self._load_daily_baseline().get("date") != baseline.get("date"):
            baseline["captured_at"] = iso(generated_at)
            self.db.set_app_setting(
                LIVE_PROFIT_DAILY_BASELINE_KEY,
                json.dumps(baseline, ensure_ascii=False, separators=(",", ":")),
            )

        strategies.sort(key=lambda item: as_float(item.get("pnl")), reverse=True)
        included_account_ids = {str(item.get("account_id") or "default") for item in strategies}
        account_equity_totals: Dict[str, float] = {}
        for account_id in included_account_ids:
            equity = as_float(equity_by_account.get(account_id))
            if equity <= 0:
                equity = max(
                    [as_float(item.get("equity")) for item in strategies if str(item.get("account_id") or "default") == account_id]
                    or [0.0]
                )
            account_equity_totals[account_id] = equity
        total_equity = sum(account_equity_totals.values())
        total_initial = sum(as_float(item.get("initial_capital")) for item in strategies)
        total_unrealized = sum(as_float(item.get("unrealized_pnl")) for item in strategies)
        daily_realized = sum(as_float(item.get("daily_realized_pnl")) for item in strategies)
        daily_unrealized_change = sum(as_float(item.get("daily_unrealized_change")) for item in strategies)
        total_pnl = sum(as_float(item.get("pnl")) for item in strategies)
        total_position_notional = sum(as_float(item.get("position_notional_usdt")) for item in strategies)
        total_trades = sum(int(item.get("total_trades") or 0) for item in strategies)
        closing_trades = sum(int(item.get("closing_trades") or 0) for item in strategies)
        winning_trades = sum(int(item.get("winning_trades") or 0) for item in strategies)
        gross_profit = sum(as_float(item.get("gross_profit")) for item in strategies)
        gross_loss = sum(as_float(item.get("gross_loss")) for item in strategies)

        total_return_pct = 0.0
        if total_initial > 0 and math.isfinite(total_initial):
            total_return_pct = total_pnl / total_initial * 100
        win_rate = winning_trades / closing_trades * 100 if closing_trades > 0 else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
        incomplete_baseline_count = sum(1 for item in strategies if not bool(item.get("statistics_complete")))
        statistics_complete = not (
            incomplete_baseline_count
            or missing_timestamp_order_count
            or truncated_account_ids
            or failed_account_ids
        )
        statistics_period_label = (
            f"{local_day_start.strftime('%Y-%m-%d %H:%M')}–{local_now.strftime('%H:%M')} "
            f"({LIVE_PROFIT_TIMEZONE_NAME})"
        )
        incomplete_reasons: List[str] = []
        if incomplete_baseline_count:
            incomplete_reasons.append(f"{incomplete_baseline_count} 个策略的日初浮盈基线在零点后首次建立")
        if missing_timestamp_order_count:
            incomplete_reasons.append(f"{missing_timestamp_order_count} 笔归因订单缺少成交时间，未计入")
        if truncated_account_ids:
            incomplete_reasons.append("交易所订单历史达到单次读取上限")
        if failed_account_ids:
            incomplete_reasons.append("部分账户读取失败")
        statistics_note = "；".join(incomplete_reasons)
        footer = (
            f"统计区间：{statistics_period_label}"
            + (f" · 部分统计：{statistics_note}" if statistics_note else "")
            + " · 数据来自实盘账户 + BitPro 运行中实盘订阅"
        )

        return {
            "report_scope": "live",
            "title": "实盘当日收益卡片",
            "pnl_label": "今日策略归因盈亏",
            "summary_pnl_label": "今日策略盈亏",
            "trade_count_label": f"今日 {total_trades} 笔交易",
            "return_basis_label": "按日初实盘订阅资金基准",
            "footer": footer,
            "generated_at": iso(generated_at),
            "statistics_timezone": LIVE_PROFIT_TIMEZONE_NAME,
            "statistics_date": local_now.date().isoformat(),
            "statistics_start": local_day_start.isoformat(),
            "statistics_end": local_now.replace(second=0, microsecond=0).isoformat(),
            "statistics_period_label": statistics_period_label,
            "statistics_complete": statistics_complete,
            "statistics_note": statistics_note,
            "running_count": len(strategies),
            "total_equity": round(total_equity, 6),
            "total_initial_capital": round(total_initial, 6),
            "total_pnl": round(total_pnl, 6),
            "total_unrealized_pnl": round(total_unrealized, 6),
            "daily_realized_pnl": round(daily_realized, 6),
            "daily_unrealized_change": round(daily_unrealized_change, 6),
            "total_return_pct": round(total_return_pct, 6),
            "total_position_notional_usdt": round(total_position_notional, 6),
            "position_strategy_count": sum(1 for item in strategies if as_float(item.get("position_notional_usdt")) > 1e-6),
            "total_trades": total_trades,
            "closing_trades": closing_trades,
            "winning_trades": winning_trades,
            "gross_profit": round(gross_profit, 6),
            "gross_loss": round(gross_loss, 6),
            "win_rate": round(win_rate, 6),
            "profit_factor": round(profit_factor, 6),
            "win_rate_available": closing_trades > 0,
            "profit_factor_available": gross_loss > 0,
            "active_alerts": 0,
            "total_alerts": 0,
            "strategies": strategies,
            "skipped_account_ids": sorted(failed_account_ids),
            "truncated_account_ids": sorted(truncated_account_ids),
            "missing_timestamp_order_count": missing_timestamp_order_count,
        }

    def _load_daily_baseline(self) -> Dict[str, Any]:
        raw = self.db.get_app_setting(LIVE_PROFIT_DAILY_BASELINE_KEY)
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    async def _load_account_payload(self, account: Dict[str, Any]) -> Dict[str, Any]:
        account_id = str(account.get("account_id") or "default")
        exchange = self.account_service.exchange_alias_for_account(account_id)
        positions_raw, balance_detail, orders_raw = await asyncio.gather(
            self.trading_service.get_positions(exchange, None),
            self.trading_service.get_balance_detail(exchange),
            self.trading_service.get_order_history(exchange, None, LIVE_PROFIT_ORDER_HISTORY_LIMIT),
        )
        positions = [self._normalize_position(item) for item in positions_raw or []]
        positions = [item for item in positions if item.get("size", 0) > 1e-12]
        orders = self.live_execution_service.enrich_orders_with_attribution(
            account_id=account_id,
            orders=list(orders_raw or []),
        )
        trading_balances = list((balance_detail or {}).get("trading") or [])
        usdt = next((item for item in trading_balances if str(item.get("currency") or "").upper() == "USDT"), {})
        return {
            "positions": positions,
            "orders": list(orders or []),
            "orders_truncated": len(list(orders_raw or [])) >= LIVE_PROFIT_ORDER_HISTORY_LIMIT,
            "equity": as_float(usdt.get("total")),
            "balance": as_float(usdt.get("free")),
        }

    @staticmethod
    def _normalize_position(position: Dict[str, Any]) -> Dict[str, Any]:
        entry = _position_price(position, "entry_price", "entryPrice", "avgPx")
        mark = _position_price(position, "mark_price", "markPrice", "markPx", "last") or entry
        upnl = as_float(position.get("unrealized_pnl") or position.get("unrealizedPnl") or position.get("upl"))
        return {
            "symbol": _position_symbol(position),
            "side": _position_side(position),
            "size": round(_position_size(position), 10),
            "entry_price": round(entry, 10),
            "mark_price": round(mark, 10),
            "notional_usdt": round(_position_notional(position), 6),
            "unrealized_pnl": round(upnl, 6),
        }

    @staticmethod
    def _filter_positions(positions: List[Dict[str, Any]], symbols: List[str]) -> List[Dict[str, Any]]:
        if not symbols:
            return []
        symbol_set = {_upper_symbol(symbol) for symbol in symbols}
        bases = {symbol.split("/")[0].upper() for symbol in symbols if "/" in symbol}
        out = []
        for position in positions:
            symbol = _upper_symbol(position.get("symbol"))
            if symbol in symbol_set or any(symbol.startswith(f"{base}/") or symbol.startswith(f"{base}-") for base in bases):
                out.append(position)
        return out

    def _normalize_live_strategy(
        self,
        *,
        strategy_id: int,
        row: Optional[Dict[str, Any]],
        subscription: Optional[Dict[str, Any]],
        account: Dict[str, Any],
        positions: List[Dict[str, Any]],
        orders: List[Dict[str, Any]],
        baseline: Dict[str, Any],
        account_equity: float,
        account_balance: float,
    ) -> Dict[str, Any]:
        position_notional = sum(as_float(item.get("notional_usdt")) for item in positions)
        unrealized = sum(as_float(item.get("unrealized_pnl")) for item in positions)
        order_pnls = _order_pnl_values(orders)
        realized = sum(order_pnls)
        baseline_unrealized = as_float(baseline.get("unrealized_pnl"))
        daily_unrealized_change = unrealized - baseline_unrealized
        total_pnl = daily_unrealized_change + realized
        equity = account_equity or max(position_notional + account_balance, 0)
        initial_capital = _configured_live_initial_capital(
            row,
            subscription,
            fallback_equity=equity,
            total_pnl=total_pnl,
        )
        baseline_initial_capital = _positive_capital(baseline.get("initial_capital"))
        if baseline_initial_capital > 0:
            initial_capital = baseline_initial_capital
        return_pct = (total_pnl / initial_capital * 100) if initial_capital > 0 else 0.0
        closing_trades = len(order_pnls)
        winning_trades = sum(1 for value in order_pnls if value > 0)
        gross_profit = sum(value for value in order_pnls if value > 0)
        gross_loss = sum(abs(value) for value in order_pnls if value < 0)
        win_rate = winning_trades / closing_trades * 100 if closing_trades > 0 else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
        symbols = _extract_symbols(row)
        name = str(row.get("name") or "") if row else ""
        if not name:
            subscription_name = str(
                (subscription or {}).get("source_strategy_name")
                or (subscription or {}).get("strategy_name")
                or ""
            ).strip()
            if subscription_name:
                name = subscription_name
            elif strategy_id > 0:
                name = f"已删除策略 #{strategy_id}"
            else:
                name = f"实盘订阅 #{(subscription or {}).get('id') or 'unknown'}"
        return {
            "strategy_id": int(strategy_id),
            "name": name,
            "status": "live",
            "subscription_status": str((subscription or {}).get("status") or "unknown"),
            "subscription_started_at": (subscription or {}).get("created_at"),
            "exchange": "okx",
            "account_id": str(account.get("account_id") or "default"),
            "account_name": str(account.get("name") or account.get("account_id") or "default"),
            "symbols": symbols,
            "pnl": round(total_pnl, 6),
            "daily_realized_pnl": round(realized, 6),
            "daily_unrealized_change": round(daily_unrealized_change, 6),
            "baseline_unrealized_pnl": round(baseline_unrealized, 6),
            "statistics_complete": bool(baseline.get("complete")),
            "statistics_started_at": baseline.get("captured_at"),
            "trade_count_label": f"今日 {len(orders)} 笔交易",
            "return_pct": round(return_pct, 6),
            "equity": round(equity, 6),
            "initial_capital": round(initial_capital, 6),
            "balance": round(account_balance, 6),
            "unrealized_pnl": round(unrealized, 6),
            "total_trades": len(orders),
            "closing_trades": closing_trades,
            "winning_trades": winning_trades,
            "gross_profit": round(gross_profit, 6),
            "gross_loss": round(gross_loss, 6),
            "win_rate": round(win_rate, 6),
            "profit_factor": round(profit_factor, 6),
            "position_notional_usdt": round(position_notional, 6),
            "positions_count": len(positions),
            "positions": positions,
        }


live_profit_push_service = LiveProfitPushService()
