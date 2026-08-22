"""Scheduled running-strategy profit card push service."""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from app.db.local_db import db_instance as db
from app.services.feishu_notifier import feishu_notifier
from app.services.strategy_engine import strategy_engine


MIN_INTERVAL_MINUTES = 1
MAX_INTERVAL_MINUTES = 24 * 60
DEFAULT_INTERVAL_MINUTES = 60


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if out.tzinfo is None:
        out = out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


def clamp_interval_minutes(value: Any) -> int:
    try:
        interval = int(float(value))
    except (TypeError, ValueError):
        interval = DEFAULT_INTERVAL_MINUTES
    return max(MIN_INTERVAL_MINUTES, min(interval, MAX_INTERVAL_MINUTES))


class StrategyProfitPushService:
    """Build and push Feishu profit cards for currently running strategies."""

    def __init__(
        self,
        *,
        database: Any = db,
        engine: Any = strategy_engine,
        notifier: Any = feishu_notifier,
        now_fn: Callable[[], datetime] = utcnow,
    ) -> None:
        self.db = database
        self.engine = engine
        self.notifier = notifier
        self.now_fn = now_fn
        self._run_lock = asyncio.Lock()

    def get_config(self) -> Dict[str, Any]:
        cfg = self.db.get_monitor_profit_push_config()
        cfg["interval_minutes"] = clamp_interval_minutes(cfg.get("interval_minutes"))
        cfg["notify_ready"] = self._notify_ready()
        return cfg

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if "enabled" in updates and updates.get("enabled") is not None:
            payload["enabled"] = bool(updates.get("enabled"))
        if "interval_minutes" in updates and updates.get("interval_minutes") is not None:
            payload["interval_minutes"] = clamp_interval_minutes(updates.get("interval_minutes"))
        cfg = self.db.update_monitor_profit_push_config(payload)
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
            return {"started": False, "skipped": "not_due"}

        return await self.run_once(force=False, config=cfg)

    async def run_once(self, *, force: bool = False, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self._run_lock.locked():
            return {"started": False, "running": True, "message": "收益卡片推送正在运行"}

        async with self._run_lock:
            cfg = config or self.get_config()
            if not force and not bool(cfg.get("enabled")):
                return {"started": False, "running": False, "skipped": "disabled"}

            started_at = iso(self.now_fn())
            self.db.set_monitor_profit_push_runtime(
                running=True,
                last_started_at=started_at,
                last_error=None,
                last_skip_reason=None,
            )
            try:
                snapshot = self.build_snapshot()
                await self._enrich_market_metrics(snapshot)
                if int(snapshot.get("running_count") or 0) <= 0:
                    self.db.set_monitor_profit_push_runtime(
                        running=False,
                        last_finished_at=iso(self.now_fn()),
                        last_error=None,
                        last_skip_reason="no_running_strategies",
                    )
                    return {
                        "started": True,
                        "running": False,
                        "sent": False,
                        "skipped": "no_running_strategies",
                    }

                sent = await self.notifier.notify_strategy_profit_report(snapshot)
                finished_at = iso(self.now_fn())
                if sent:
                    self.db.set_monitor_profit_push_runtime(
                        running=False,
                        last_sent_at=finished_at,
                        last_finished_at=finished_at,
                        last_error=None,
                        last_skip_reason=None,
                    )
                else:
                    self.db.set_monitor_profit_push_runtime(
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
                self.db.set_monitor_profit_push_runtime(
                    running=False,
                    last_finished_at=iso(self.now_fn()),
                    last_error=str(exc),
                    last_skip_reason=None,
                )
                raise

    def build_snapshot(self) -> Dict[str, Any]:
        try:
            raw_items = list(self.engine.get_all_running(refresh_marks=True) or [])
        except TypeError:
            raw_items = list(self.engine.get_all_running() or [])
        strategies = [self._normalize_strategy(item) for item in raw_items]
        strategies.sort(key=lambda item: as_float(item.get("return_pct")), reverse=True)

        total_equity = sum(as_float(item.get("equity")) for item in strategies)
        total_initial = sum(as_float(item.get("initial_capital")) for item in strategies)
        total_pnl = sum(as_float(item.get("pnl")) for item in strategies)
        total_unrealized = sum(as_float(item.get("unrealized_pnl")) for item in strategies)
        total_position_notional = sum(as_float(item.get("position_notional_usdt")) for item in strategies)
        total_trades = sum(int(item.get("total_trades") or 0) for item in strategies)
        closing_trades = sum(int(item.get("closing_trades") or 0) for item in strategies)
        winning_trades = sum(int(item.get("winning_trades") or 0) for item in strategies)
        gross_profit = sum(as_float(item.get("gross_profit")) for item in strategies)
        gross_loss = sum(as_float(item.get("gross_loss")) for item in strategies)
        position_strategy_count = sum(1 for item in strategies if as_float(item.get("position_notional_usdt")) > 1e-6)
        if total_initial > 0:
            total_return_pct = (total_equity - total_initial) / total_initial * 100
        else:
            total_return_pct = 0.0
        if closing_trades > 0:
            win_rate = winning_trades / closing_trades * 100
        else:
            fallback_weight = sum(int(item.get("total_trades") or 0) for item in strategies if as_float(item.get("win_rate")) > 0)
            win_rate = (
                sum(as_float(item.get("win_rate")) * int(item.get("total_trades") or 0) for item in strategies)
                / fallback_weight
                if fallback_weight > 0
                else 0.0
            )
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        else:
            fallback_weight = sum(int(item.get("total_trades") or 0) for item in strategies if as_float(item.get("profit_factor")) > 0)
            profit_factor = (
                sum(as_float(item.get("profit_factor")) * int(item.get("total_trades") or 0) for item in strategies)
                / fallback_weight
                if fallback_weight > 0
                else 0.0
            )
        active_alerts = 0
        total_alerts = 0
        try:
            from app.services.alert_service import alert_service

            alerts = list(alert_service.get_alerts() or [])
            total_alerts = len(alerts)
            active_alerts = sum(1 for item in alerts if bool(item.get("enabled")))
        except Exception:
            active_alerts = 0
            total_alerts = 0

        return {
            "report_scope": "paper",
            "title": "模拟收益卡片",
            "generated_at": iso(self.now_fn()),
            "running_count": len(strategies),
            "total_equity": round(total_equity, 6),
            "total_initial_capital": round(total_initial, 6),
            "total_pnl": round(total_pnl, 6),
            "total_unrealized_pnl": round(total_unrealized, 6),
            "total_return_pct": round(total_return_pct, 6),
            "total_position_notional_usdt": round(total_position_notional, 6),
            "position_strategy_count": position_strategy_count,
            "total_trades": total_trades,
            "closing_trades": closing_trades,
            "winning_trades": winning_trades,
            "gross_profit": round(gross_profit, 6),
            "gross_loss": round(gross_loss, 6),
            "win_rate": round(win_rate, 6),
            "profit_factor": round(profit_factor, 6),
            "active_alerts": active_alerts,
            "total_alerts": total_alerts,
            "strategies": strategies,
        }

    async def _enrich_market_metrics(self, snapshot: Dict[str, Any]) -> None:
        if snapshot.get("long_short_ratio") is not None:
            return
        try:
            ratio = await asyncio.wait_for(asyncio.to_thread(self._fetch_okx_btc_long_short_ratio), timeout=5)
        except Exception:
            ratio = None
        if ratio and ratio > 0:
            snapshot["long_short_ratio"] = round(float(ratio), 6)

    @staticmethod
    def _fetch_okx_btc_long_short_ratio() -> Optional[float]:
        try:
            from app.exchange import exchange_manager

            ex = exchange_manager.get_exchange("okx")
            if not ex or not hasattr(ex.exchange, "publicGetRubikStatContractsLongShortAccountRatio"):
                return None
            response = ex.exchange.publicGetRubikStatContractsLongShortAccountRatio({"ccy": "BTC", "period": "5m"})
            row: Any = None
            if isinstance(response, dict):
                data = response.get("data")
                if isinstance(data, list) and data:
                    row = data[0]
            elif isinstance(response, list) and response:
                row = response[0]
            if isinstance(row, dict):
                return float(
                    row.get("longShortRatio")
                    or row.get("long_short_ratio")
                    or row.get("ratio")
                    or row.get("lsr")
                    or 0
                )
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                return float(row[1] or 0)
        except Exception:
            return None
        return None

    def _normalize_strategy(self, item: Dict[str, Any]) -> Dict[str, Any]:
        symbols = item.get("symbols") or []
        if not isinstance(symbols, list):
            symbols = [str(symbols)] if symbols else []
        positions = item.get("positions") or {}
        if not isinstance(positions, dict):
            positions = {}
        normalized_positions = []
        position_notional_usdt = 0.0
        for symbol, pos in positions.items():
            if not isinstance(pos, dict):
                continue
            size = as_float(pos.get("size"))
            if size <= 1e-12:
                continue
            mark_price = as_float(pos.get("mark_price"))
            entry_price = as_float(pos.get("entry_price"))
            notional = as_float(pos.get("notional_usdt") or pos.get("notional") or pos.get("value"))
            if notional <= 0:
                notional = abs(size) * (mark_price or entry_price)
            position_notional_usdt += abs(notional)
            normalized_positions.append(
                {
                    "symbol": str(symbol),
                    "side": str(pos.get("side") or "long"),
                    "size": round(size, 10),
                    "entry_price": round(entry_price, 10),
                    "mark_price": round(mark_price, 10),
                    "notional_usdt": round(abs(notional), 6),
                    "unrealized_pnl": round(as_float(pos.get("unrealized_pnl")), 6),
                }
            )
        equity = as_float(item.get("equity"))
        pnl = as_float(item.get("pnl"))
        initial = as_float(item.get("initial_capital"))
        if initial <= 0 and equity > 0:
            initial = equity - pnl
        return {
            "strategy_id": int(item.get("strategy_id") or item.get("id") or 0),
            "name": str(item.get("name") or ""),
            "status": str(item.get("status") or ""),
            "exchange": str(item.get("exchange") or ""),
            "symbols": [str(s) for s in symbols if s],
            "pnl": round(pnl, 6),
            "return_pct": round(as_float(item.get("return_pct")), 6),
            "equity": round(equity, 6),
            "initial_capital": round(initial, 6),
            "balance": round(as_float(item.get("balance")), 6),
            "unrealized_pnl": round(as_float(item.get("unrealized_pnl")), 6),
            "total_trades": int(item.get("total_trades") or 0),
            "closing_trades": int(item.get("closing_trades") or 0),
            "winning_trades": int(item.get("winning_trades") or 0),
            "gross_profit": round(as_float(item.get("gross_profit")), 6),
            "gross_loss": round(as_float(item.get("gross_loss")), 6),
            "win_rate": round(as_float(item.get("win_rate")), 6),
            "profit_factor": round(as_float(item.get("profit_factor")), 6),
            "position_notional_usdt": round(position_notional_usdt, 6),
            "positions_count": len(normalized_positions),
            "positions": normalized_positions,
        }


strategy_profit_push_service = StrategyProfitPushService()
