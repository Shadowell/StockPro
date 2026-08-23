"""Compose persisted strategy evidence into the instance diagnostic log contract."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.services.dynamic_pool_presentation import normalize_dynamic_pool_view


_POOL_TRADE_WINDOW_MS = 30 * 60 * 1000


def _timestamp(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _short_symbol(value: Any) -> str:
    symbol = str(value or "").strip()
    return symbol.split("/")[0] if "/" in symbol else symbol


def _side(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"1", "long", "buy", "open_long", "close_long"}:
        return "long"
    if raw in {"-1", "short", "sell", "open_short", "close_short"}:
        return "short"
    return raw


def _runtime_event_id(event: Mapping[str, Any]) -> str:
    explicit = str(event.get("event_id") or "").strip()
    if explicit:
        return f"runtime:{explicit}"
    encoded = json.dumps(dict(event), ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return f"runtime:{hashlib.sha256(encoded).hexdigest()[:20]}"


def _runtime_logs(events: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for raw in events:
        if not isinstance(raw, Mapping):
            continue
        event = dict(raw)
        event["source"] = "runtime_log"
        event["event_id"] = _runtime_event_id(raw)
        event["timestamp"] = _timestamp(raw.get("bar_ts_ms") or raw.get("timestamp"))
        output.append(event)
    return output


def _pool_level(tone: Any) -> str:
    value = str(tone or "").lower()
    if value in {"error", "danger"}:
        return "error"
    if value in {"warning", "down"}:
        return "warning"
    return "info"


def _raw_pool_events(state: Mapping[str, Any]) -> Tuple[Mapping[str, Any], List[Mapping[str, Any]]]:
    raw_view = state.get("_dynamic_pool_view")
    view = dict(raw_view) if isinstance(raw_view, Mapping) else {}
    runtime = state.get("_dynamic_pool_runtime")
    runtime_events = runtime.get("events") if isinstance(runtime, Mapping) else None
    view_events = view.get("events")
    selected = runtime_events if isinstance(runtime_events, list) else view_events
    events = [item for item in (selected or []) if isinstance(item, Mapping)]
    view["events"] = events
    return view, events


def _pool_logs(state: Mapping[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    view, raw_events = _raw_pool_events(state)
    if not raw_events:
        return [], []
    normalized = normalize_dynamic_pool_view(view).get("events") or []
    by_id = {
        str(item.get("event_id")): item
        for item in normalized
        if isinstance(item, Mapping) and item.get("event_id")
    }
    output: List[Dict[str, Any]] = []
    trade_signatures: List[Dict[str, Any]] = []
    for raw in raw_events:
        raw_id = str(raw.get("event_id") or "").strip()
        item = by_id.get(raw_id)
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or raw.get("kind") or "")
        ts = _timestamp(item.get("ts") or raw.get("ts"))
        message = str(item.get("message") or "").strip()
        event = {
            "event_id": f"dynamic_pool:{raw_id}",
            "source": "dynamic_pool",
            "event_kind": kind,
            "type": "log",
            "level": _pool_level(item.get("tone")),
            "timestamp": ts,
            "message": message,
            "summary": message,
            "symbol": raw.get("symbol"),
            "side": _side(raw.get("side") or raw.get("direction")),
        }
        output.append(event)
        if kind in {"position_open", "position_close"}:
            trade_signatures.append(
                {
                    "kind": kind,
                    "timestamp": ts,
                    "symbol": str(raw.get("symbol") or ""),
                    "side": event["side"],
                }
            )
    return output, trade_signatures


def _trade_kind(side: Any) -> Optional[str]:
    value = str(side or "").lower()
    if value.startswith("open_") or value in {"buy", "spot_buy"}:
        return "position_open"
    if value.startswith("close_") or value.startswith("liquidation_") or value in {"sell", "spot_sell"}:
        return "position_close"
    return None


def _trade_side(side: Any) -> str:
    value = str(side or "").lower()
    if value in {"buy", "spot_buy"}:
        return "spot"
    if value in {"sell", "spot_sell"}:
        return "spot"
    if value.startswith("liquidation_"):
        return _side(value.removeprefix("liquidation_"))
    return _side(value)


def _trade_is_projected(trade: Mapping[str, Any], signatures: Sequence[Mapping[str, Any]]) -> bool:
    kind = _trade_kind(trade.get("side"))
    symbol = str(trade.get("symbol") or "")
    side = _trade_side(trade.get("side"))
    ts = _timestamp(trade.get("timestamp"))
    return any(
        signature.get("kind") == kind
        and str(signature.get("symbol") or "") == symbol
        and str(signature.get("side") or "") == side
        and abs(_timestamp(signature.get("timestamp")) - ts) <= _POOL_TRADE_WINDOW_MS
        for signature in signatures
    )


def _format_quantity(value: Any) -> str:
    number = _number(value)
    return f"{number:.8f}".rstrip("0").rstrip(".")


def _format_price(value: Any) -> str:
    number = _number(value)
    return f"{number:.10f}".rstrip("0").rstrip(".")


def _trade_message(trade: Mapping[str, Any]) -> str:
    raw_side = str(trade.get("side") or "").lower()
    symbol = _short_symbol(trade.get("symbol"))
    quantity = _format_quantity(trade.get("quantity"))
    price = _format_price(trade.get("price"))
    side = _trade_side(raw_side)
    if raw_side in {"buy", "spot_buy"}:
        action = "买入"
    elif raw_side in {"sell", "spot_sell"}:
        action = "卖出"
    elif raw_side.startswith("liquidation_"):
        action = f"{'多头' if side == 'long' else '空头'}爆仓"
    else:
        direction = "多头" if side == "long" else "空头"
        action = f"{direction}{'开仓' if _trade_kind(raw_side) == 'position_open' else '平仓'}"
    message = f"{symbol} {action} {quantity} @ {price}"
    if _trade_kind(raw_side) == "position_close":
        pnl = _number(trade.get("pnl"))
        message += f"，盈亏 {pnl:+.2f}U"
    return message


def _trade_logs(
    trades: Iterable[Mapping[str, Any]],
    pool_signatures: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for raw in trades:
        if not isinstance(raw, Mapping) or _trade_kind(raw.get("side")) is None:
            continue
        if _trade_is_projected(raw, pool_signatures):
            continue
        message = _trade_message(raw)
        pnl = _number(raw.get("pnl"))
        kind = _trade_kind(raw.get("side")) or "strategy_trade"
        output.append(
            {
                "event_id": f"strategy_trade:{raw.get('id')}",
                "source": "strategy_trade",
                "event_kind": kind,
                "type": "log",
                "level": (
                    "error"
                    if str(raw.get("side") or "").lower().startswith("liquidation_")
                    else "warning" if kind == "position_close" and pnl < 0 else "info"
                ),
                "timestamp": _timestamp(raw.get("timestamp")),
                "message": message,
                "summary": message,
                "symbol": raw.get("symbol"),
                "side": _trade_side(raw.get("side")),
                "trade_id": raw.get("id"),
            }
        )
    return output


def _load_state(raw: Any) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        return raw
    try:
        parsed = json.loads(str(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, Mapping) else {}


def compose_strategy_diagnostic_events(
    *,
    runtime_events: Iterable[Mapping[str, Any]],
    runtime_state: Any,
    trades: Iterable[Mapping[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    """Merge runtime logs, current dynamic-pool events, and persisted trades."""

    state = _load_state(runtime_state)
    pool_events, pool_signatures = _pool_logs(state)
    combined = [
        *_runtime_logs(runtime_events),
        *pool_events,
        *_trade_logs(trades, pool_signatures),
    ]
    by_id: Dict[str, Dict[str, Any]] = {}
    for event in combined:
        event_id = str(event.get("event_id") or "")
        if event_id and event_id not in by_id:
            by_id[event_id] = event
    ordered = sorted(by_id.values(), key=lambda item: _timestamp(item.get("timestamp")), reverse=True)
    return ordered[: max(1, int(limit))]


__all__ = ["compose_strategy_diagnostic_events"]
