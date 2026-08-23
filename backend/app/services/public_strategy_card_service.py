"""Safe public Paper metrics behind stable aliases."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from app.services.paper_performance_metrics import equity_curve_risk_metrics


SCHEMA_VERSION = 1
MAPPING_PREFIX = "public_strategy_card_alias:"
STALE_AFTER_SECONDS = 2 * 60 * 60
ALIAS_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _mapping_key(alias: str) -> str:
    normalized = str(alias or "").strip().lower()
    if not ALIAS_PATTERN.fullmatch(normalized):
        raise ValueError("公开策略卡 alias 只能包含小写字母、数字和连字符")
    return f"{MAPPING_PREFIX}{normalized}"


def configure_mapping(database: Any, *, alias: str, strategy_id: int) -> dict[str, Any]:
    sid = int(strategy_id)
    row = database.get_strategy_by_id(sid)
    if not row:
        raise ValueError("Strategy not found")
    config = row.get("config") if isinstance(row.get("config"), dict) else {}
    if not bool(config.get("is_paper_trading", True)):
        raise ValueError("公开策略卡只允许映射 Paper 策略")
    instance_id = str(config.get("paper_instance_id") or "").strip()
    instance = database.get_paper_instance(instance_id) if instance_id else None
    if not instance or int(instance.get("strategy_id") or 0) != sid:
        raise ValueError("目标策略没有可用的 Paper 会话")
    normalized_alias = str(alias).strip().lower()
    database.set_app_setting(
        _mapping_key(normalized_alias),
        json.dumps({"strategy_id": sid}, separators=(",", ":"), sort_keys=True),
    )
    return {
        "alias": normalized_alias,
        "strategy_id": sid,
        "mode": "paper",
        "configured": True,
    }


def _mapped_strategy_id(database: Any, alias: str) -> int | None:
    raw = database.get_app_setting(_mapping_key(alias), "")
    try:
        payload = json.loads(raw or "{}")
        sid = int(payload.get("strategy_id"))
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return sid if sid > 0 else None


def _unavailable(*, state: str = "unavailable", now: datetime | None = None) -> dict[str, Any]:
    generated = (now or _utc_now()).astimezone(timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "state": state,
        "mode": "paper",
        "data": None,
        "as_of": generated.isoformat(),
    }


def _initial_capital(config: dict[str, Any]) -> float:
    for key in ("initial_capital", "initial_equity", "paper_capital"):
        try:
            value = float(config.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0 and math.isfinite(value):
            return value
    return 0.0


def _trade_metrics(rows: list[dict[str, Any]]) -> tuple[float, float]:
    closes: list[float] = []
    for row in rows:
        side = str(row.get("side") or "").strip().lower().replace("-", "_").replace(" ", "_")
        if side not in {"sell", "spot_sell", "close_long", "close_short"}:
            continue
        try:
            closes.append(float(row.get("pnl") or 0))
        except (TypeError, ValueError):
            closes.append(0.0)
    winners = [value for value in closes if value > 0]
    losses = [abs(value) for value in closes if value < 0]
    win_rate = len(winners) / len(closes) * 100 if closes else 0.0
    profit_factor = sum(winners) / sum(losses) if losses and sum(losses) > 0 else 0.0
    return round(win_rate, 4), round(profit_factor, 4)


def _curve_payload(samples: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    equity_curve: list[dict[str, Any]] = []
    drawdown_curve: list[dict[str, Any]] = []
    peak = 0.0
    for sample in samples:
        try:
            equity = float(sample.get("equity") or 0)
        except (AttributeError, TypeError, ValueError):
            continue
        if equity <= 0 or not math.isfinite(equity):
            continue
        at = str(sample.get("time") or "")
        if not at:
            continue
        peak = max(peak, equity)
        drawdown = ((equity - peak) / peak * 100) if peak > 0 else 0.0
        equity_curve.append({"at": at, "value": round(equity, 6)})
        drawdown_curve.append({"at": at, "value_pct": round(drawdown, 6)})
    return equity_curve, drawdown_curve


def build_public_snapshot(
    database: Any,
    engine: Any,
    *,
    alias: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    generated = (now or _utc_now()).astimezone(timezone.utc)
    try:
        strategy_id = _mapped_strategy_id(database, alias)
    except ValueError:
        return _unavailable(now=generated)
    if strategy_id is None:
        return _unavailable(now=generated)
    row = database.get_strategy_by_id(strategy_id)
    if not row:
        return _unavailable(now=generated)
    config = row.get("config") if isinstance(row.get("config"), dict) else {}
    if not bool(config.get("is_paper_trading", True)):
        return _unavailable(state="not-paper", now=generated)
    instance_id = str(config.get("paper_instance_id") or "").strip()
    instance = database.get_paper_instance(instance_id) if instance_id else None
    if not instance or int(instance.get("strategy_id") or 0) != strategy_id:
        return _unavailable(now=generated)
    session_config = instance.get("config_snapshot") if isinstance(instance.get("config_snapshot"), dict) else config
    initial = _initial_capital(session_config)
    samples = database.get_paper_instance_equity_samples(instance, limit=400)
    if initial <= 0 or not samples:
        return _unavailable(now=generated)

    runtime = engine.get_strategy_status(strategy_id) or {}
    status = str(runtime.get("status") or instance.get("status") or "stopped").lower()
    if status not in {"running", "paused", "stopped"}:
        status = "stopped"
    sampled_equity = float(samples[-1].get("equity") or 0)
    try:
        runtime_equity = float(runtime.get("equity") or 0)
    except (TypeError, ValueError):
        runtime_equity = 0.0
    equity = runtime_equity if runtime_equity > 0 else sampled_equity

    started_at = _parse_utc(instance.get("started_at") or instance.get("configured_at"))
    ended_at = _parse_utc(instance.get("ended_at"))
    runtime_end = ended_at or generated
    runtime_seconds = max(0, int((runtime_end - started_at).total_seconds())) if started_at else 0
    start_ms = int(started_at.timestamp() * 1000) if started_at else 0
    trades = database.get_strategy_trades_since(strategy_id, start_ms)
    if ended_at:
        end_ms = int(ended_at.timestamp() * 1000)
        trades = [row for row in trades if int(row.get("timestamp") or 0) <= end_ms]
    win_rate, profit_factor = _trade_metrics(trades)
    risk = equity_curve_risk_metrics(samples)
    equity_curve, drawdown_curve = _curve_payload(samples)

    latest_at = _parse_utc(samples[-1].get("time"))
    state = "ok"
    if status == "running" and latest_at and (generated - latest_at).total_seconds() > STALE_AFTER_SECONDS:
        state = "stale"
    if state != "ok":
        return _unavailable(state=state, now=generated)

    symbols = row.get("symbols") if isinstance(row.get("symbols"), list) else []
    assumptions = session_config
    data = {
        "status": status,
        "currency": "USDT",
        "account_equity": round(equity, 6),
        "total_pnl": round(equity - initial, 6),
        "return_pct": round((equity - initial) / initial * 100, 6),
        "sharpe": round(float(risk.get("sharpe_ratio") or 0), 6),
        "win_rate_pct": win_rate,
        "profit_factor": profit_factor,
        "trade_count": int(database.get_paper_instance_trade_count(instance)),
        "max_drawdown_30d_pct": round(float(risk.get("max_drawdown") or 0), 6),
        "runtime_seconds": runtime_seconds,
        "symbols": [str(symbol) for symbol in symbols if str(symbol).strip()],
        "equity_curve": equity_curve,
        "drawdown_curve": drawdown_curve,
        "includes_fees": any(
            assumptions.get(key) is not None for key in ("maker_fee_bps", "taker_fee_bps", "fee_bps", "commission_rate")
        ),
        "includes_slippage": any(
            assumptions.get(key) is not None for key in ("slippage_bps", "slippage_rate", "slippage")
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "state": "ok",
        "mode": "paper",
        "data": data,
        "as_of": generated.isoformat(),
    }
