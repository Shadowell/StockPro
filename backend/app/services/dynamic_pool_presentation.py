"""动态标的池 dashboard 展示合同适配器。

策略运行时继续保存各自的原始 ``_dynamic_pool_view``。本模块只在读取边界把
旧动量池、1H 因子池和已有 schema 4 快照归一化为同一个页面合同。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Dict, List, Optional


SCHEMA_VERSION = 4
MAX_EVENTS = 200
_TONES = {"neutral", "info", "success", "warning", "danger", "up", "down"}


def _safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _safe_int(value: Any, default: int = 0) -> int:
    number = _safe_float(value)
    return int(number) if number is not None else int(default)


def _optional_int(value: Any) -> Optional[int]:
    number = _safe_float(value)
    return int(number) if number is not None else None


def _format_number(value: Any, digits: int = 1) -> str:
    number = _safe_float(value)
    if number is None:
        return "—"
    text = f"{number:.{digits}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _format_signed_pct(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "—"
    return f"{number:+.1f}%"


def _format_usdt(value: Any) -> str:
    number = _safe_float(value)
    return f"{number:.2f}U" if number is not None else "—"


def _symbol(row: Mapping[str, Any]) -> Optional[str]:
    symbol = str(row.get("symbol") or "").strip()
    return symbol or None


def _short_symbol(symbol: str) -> str:
    return symbol.split("/", 1)[0] or symbol


def _tone(value: Any, default: str = "neutral") -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in _TONES else default


def _metric(
    label: str,
    value: Any,
    display: Optional[str] = None,
    tone: str = "neutral",
) -> Dict[str, Any]:
    number = _safe_float(value)
    normalized_value: Any = number if number is not None else value
    if value is None:
        normalized_value = None
    return {
        "label": str(label),
        "value": normalized_value,
        "display": str(display if display is not None else (normalized_value if normalized_value is not None else "—")),
        "tone": _tone(tone),
    }


def _badge(label: str, tone: str = "neutral") -> Dict[str, str]:
    return {"label": str(label), "tone": _tone(tone)}


def _rows(value: Any) -> List[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _direction(value: Any) -> Optional[int]:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"long", "buy", "多", "1", "+1"}:
            return 1
        if normalized in {"short", "sell", "空", "-1"}:
            return -1
    number = _safe_float(value)
    if number is None or number == 0:
        return None
    return 1 if number > 0 else -1


def _direction_badge(direction: Optional[int]) -> List[Dict[str, str]]:
    if direction == 1:
        return [_badge("多", "up")]
    if direction == -1:
        return [_badge("空", "down")]
    return []


def _tier_badge(tier: Any) -> List[Dict[str, str]]:
    normalized = str(tier or "").strip().lower()
    if normalized == "normal":
        return [_badge("正常仓", "success")]
    if normalized == "probe":
        return [_badge("探测仓", "info")]
    return []


def _first_reason(row: Mapping[str, Any]) -> Optional[str]:
    reason = str(row.get("reason") or "").strip()
    if reason:
        return reason
    reasons = row.get("reasons")
    if isinstance(reasons, Sequence) and not isinstance(reasons, (str, bytes, bytearray)):
        for item in reasons:
            text = str(item or "").strip()
            if text:
                return text
    return None


def _timestamp_payload(raw: Mapping[str, Any]) -> Dict[str, Optional[int]]:
    return {
        "last_evaluated_at_ms": _optional_int(
            raw.get("last_evaluated_at_ms", raw.get("last_scan_ms"))
        ),
        "next_evaluation_at_ms": _optional_int(
            raw.get("next_evaluation_at_ms", raw.get("next_scan_ms"))
        ),
        "updated_at_ms": _optional_int(raw.get("updated_at_ms")),
    }


def _count_value(value: Any) -> int:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return len(value)
    return max(0, _safe_int(value))


def _base_view(
    *,
    status: str,
    summary: str,
    timestamps: Optional[Mapping[str, Any]] = None,
    counts: Optional[Mapping[str, Any]] = None,
    candidates: Optional[List[Dict[str, Any]]] = None,
    members: Optional[List[Dict[str, Any]]] = None,
    positions: Optional[List[Dict[str, Any]]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    candidate_rows = candidates or []
    member_rows = members or []
    position_rows = positions or []
    count_source = counts or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "status": str(status or "empty"),
        "summary": str(summary or "暂无可展示的动态池数据"),
        "timestamps": {
            "last_evaluated_at_ms": _optional_int((timestamps or {}).get("last_evaluated_at_ms")),
            "next_evaluation_at_ms": _optional_int((timestamps or {}).get("next_evaluation_at_ms")),
            "updated_at_ms": _optional_int((timestamps or {}).get("updated_at_ms")),
        },
        "counts": {
            "candidates": max(0, _safe_int(count_source.get("candidates"), len(candidate_rows))),
            "eligible": max(0, _safe_int(count_source.get("eligible"), 0)),
            "members": len(member_rows),
            "positions": len(position_rows),
        },
        "candidates": candidate_rows,
        "members": member_rows,
        "positions": position_rows,
        "events": (events or [])[-MAX_EVENTS:],
    }


def _empty_view(status: str = "empty", summary: str = "暂无可展示的动态池数据") -> Dict[str, Any]:
    return _base_view(status=status, summary=summary)


def _legacy_candidate(row: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    symbol = _symbol(row)
    if not symbol:
        return None
    momentum = _safe_float(row.get("momentum_pct"))
    direction = _direction(row.get("direction"))
    if direction is None and momentum not in (None, 0):
        direction = 1 if momentum and momentum > 0 else -1
    metrics: List[Dict[str, Any]] = []
    gap = _safe_float(row.get("gap_to_enter_pct"))
    if gap is not None:
        metrics.append(_metric("距门槛", gap, f"{gap:.1f}%"))
    reason = _first_reason(row)
    return {
        "id": f"candidate:{symbol}",
        "symbol": symbol,
        "direction": direction,
        "primary_metric": _metric(
            "24h 动量",
            momentum,
            _format_signed_pct(momentum),
            "up" if momentum is not None and momentum >= 0 else "down",
        ),
        "badges": _direction_badge(direction),
        "metrics": metrics,
        "openable": False,
        "reason": reason,
    }


def _factor_candidate(row: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    symbol = _symbol(row)
    if not symbol:
        return None
    score = _safe_float(row.get("score"))
    direction = _direction(row.get("direction"))
    metrics: List[Dict[str, Any]] = []
    gap = _safe_float(row.get("gap_to_enter_score"))
    if gap is not None:
        metrics.append(_metric("距门槛", gap, _format_number(gap)))
    rank = _optional_int(row.get("rank"))
    if rank is not None:
        metrics.append(_metric("排名", rank, f"第 {rank} 名"))
    confirmed = _optional_int(row.get("confirmed"))
    if confirmed is not None:
        metrics.append(_metric("确认", confirmed, f"{confirmed} 次"))
    return {
        "id": f"candidate:{symbol}",
        "symbol": symbol,
        "direction": direction,
        "primary_metric": _metric("综合分", score, _format_number(score), "warning"),
        "badges": _direction_badge(direction) + _tier_badge(row.get("tier")),
        "metrics": metrics,
        "openable": bool(row.get("openable", False)),
        "reason": _first_reason(row),
    }


def _legacy_member(row: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    symbol = _symbol(row)
    if not symbol:
        return None
    momentum = _safe_float(row.get("momentum_pct"))
    direction = _direction(row.get("direction"))
    metrics: List[Dict[str, Any]] = []
    for label, key, digits, suffix in (
        ("ADX", "adx", 0, ""),
        ("EMA Gap/ATR", "ema_gap_atr", 2, ""),
        ("ATR%", "atr_pct", 1, "%"),
    ):
        value = _safe_float(row.get(key))
        if value is not None:
            metrics.append(_metric(label, value, f"{_format_number(value, digits)}{suffix}"))
    return {
        "id": f"member:{symbol}",
        "symbol": symbol,
        "direction": direction,
        "primary_metric": _metric(
            "24h 动量",
            momentum,
            _format_signed_pct(momentum),
            "up" if momentum is not None and momentum >= 0 else "down",
        ),
        "badges": _direction_badge(direction),
        "metrics": metrics,
        "openable": bool(row.get("openable", False)),
        "reason": _first_reason(row),
    }


def _factor_member(row: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    symbol = _symbol(row)
    if not symbol:
        return None
    direction = _direction(row.get("direction"))
    score = _safe_float(row.get("score"))
    metrics: List[Dict[str, Any]] = []
    metric_specs = (
        ("ADX", "adx", 0, ""),
        ("EMA Gap/ATR", "ema_gap_atr", 2, ""),
        ("ATR%", "atr_pct", 1, "%"),
        ("趋势效率", "efficiency", 2, ""),
        ("确认", "confirmed", 0, " 次"),
        ("趋势分", "trend_score", 1, ""),
        ("适配分", "fit_score", 1, ""),
    )
    for label, key, digits, suffix in metric_specs:
        value = _safe_float(row.get(key))
        if value is not None:
            metrics.append(_metric(label, value, f"{_format_number(value, digits)}{suffix}"))
    return {
        "id": f"member:{symbol}",
        "symbol": symbol,
        "direction": direction,
        "primary_metric": _metric("综合分", score, _format_number(score), "success"),
        "badges": _direction_badge(direction) + _tier_badge(row.get("tier")),
        "metrics": metrics,
        "openable": bool(row.get("openable", False)),
        "reason": _first_reason(row),
    }


def _position(row: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    symbol = _symbol(row)
    if not symbol:
        return None
    direction = _direction(row.get("direction", row.get("side")))
    metrics: List[Dict[str, Any]] = []
    entry_price = _safe_float(row.get("entry_price"))
    if entry_price is not None:
        metrics.append(_metric("入场价", entry_price, _format_number(entry_price, 6)))
    notional = _safe_float(row.get("notional_usdt"))
    if notional is not None:
        metrics.append(_metric("名义金额", notional, _format_usdt(notional)))
    badges = _direction_badge(direction) + _tier_badge(row.get("tier"))
    pyramid_adds = _optional_int(row.get("pyramid_adds"))
    if pyramid_adds is not None and pyramid_adds > 0:
        badges.append(_badge(f"加仓 {pyramid_adds} 次", "info"))
    side = "long" if direction == 1 else "short" if direction == -1 else "unknown"
    return {
        "id": f"position:{symbol}:{side}",
        "symbol": symbol,
        "direction": direction,
        "badges": badges,
        "metrics": metrics,
    }


def _event_side(row: Mapping[str, Any]) -> str:
    return "空头" if _direction(row.get("side", row.get("direction"))) == -1 else "多头"


def _event_tier(value: Any) -> str:
    return "探测仓" if str(value or "").lower() == "probe" else "正常仓"


def _event_reason(value: Any) -> str:
    raw = str(value or "").strip()
    labels = {
        "stop_loss_or_profit_trailing": "止损或浮盈跟踪",
        "hard_take_profit": "硬止盈",
        "completed_1h_ema_reversal": "1H EMA反转",
        "completed_1h_profit_decay": "利润衰减",
        "portfolio_ratchet_floor_breach": "组合棘轮底线",
    }
    return labels.get(raw, raw or "策略退出")


def _format_clock_ms(value: Any) -> str:
    timestamp = _optional_int(value)
    return str(timestamp) if timestamp is not None else "—"


def _event(row: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    kind = str(row.get("kind") or "").strip()
    timestamp = _optional_int(row.get("ts"))
    if not kind or timestamp is None:
        return None
    symbol = _symbol(row)
    symbol_kinds = {
        "candidate_enter",
        "candidate_exit",
        "pool_enter",
        "pool_exit",
        "pyramid_add",
        "antimartingale_add",
        "position_open",
        "probe_upgrade",
        "position_close",
        "cooldown",
    }
    if kind in symbol_kinds and not symbol:
        return None

    base = _short_symbol(symbol or "组合")
    label = "池事件"
    message = f"{base} {kind}"
    tone = "neutral"
    if kind == "candidate_enter":
        label, tone = "进候选", "info"
        rank = _optional_int(row.get("rank"))
        message = f"{base} 进入候选{f'（成交额第 {rank} 名）' if rank else ''}"
    elif kind == "candidate_exit":
        label, tone, message = "出候选", "neutral", f"{base} 跌出候选"
    elif kind == "pool_enter":
        label, tone = "入池", "success"
        score = _safe_float(row.get("score"))
        if score is not None:
            message = f"{base} {_event_side(row)}入池（综合分 {_format_number(score)}，{_event_tier(row.get('tier'))}）"
        else:
            message = f"{base} {_event_side(row)}入池（24h {_format_signed_pct(row.get('momentum_pct'))}）"
    elif kind == "pool_exit":
        label, tone, message = "踢出", "warning", f"{base} 被踢出趋势池"
    elif kind == "pyramid_add":
        label, tone = "加仓", "info"
        message = (
            f"{base} 第 {_optional_int(row.get('add_index')) or '?'} 次金字塔加仓 "
            f"{_format_usdt(row.get('notional_usdt'))}（{_format_number(row.get('r_multiple'), 2)}R）"
        )
    elif kind == "antimartingale_add":
        label, tone = "反马丁加仓", "info"
        message = (
            f"{base} 第 {_optional_int(row.get('add_number')) or '?'} 次反马丁加仓 "
            f"{_format_usdt(row.get('notional_usdt'))}（峰值 {_format_number(row.get('peak_r'), 2)}R）"
        )
    elif kind == "position_open":
        label, tone = "开仓", "info"
        score = _safe_float(row.get("score"))
        score_text = f"（综合分 {_format_number(score)}）" if score is not None else ""
        message = (
            f"{base} {_event_side(row)}{_event_tier(row.get('tier'))}开仓 "
            f"{_format_usdt(row.get('notional_usdt'))}{score_text}"
        )
    elif kind == "probe_upgrade":
        label, tone = "探测升级", "info"
        multiple = _safe_float(row.get("r_multiple"))
        multiple_text = f"（{_format_number(multiple, 2)}R）" if multiple is not None else ""
        message = f"{base} 探测仓升级为正常仓，追加 {_format_usdt(row.get('notional_usdt'))}{multiple_text}"
    elif kind == "position_close":
        label, tone = "平仓", "warning"
        pnl = _safe_float(row.get("pnl"))
        pnl_text = f"，盈亏 {pnl:+.2f}U" if pnl is not None else ""
        message = f"{base} {_event_side(row)}平仓：{_event_reason(row.get('reason'))}{pnl_text}"
    elif kind == "cooldown":
        label, tone, message = "冷却", "info", f"{base} 连亏冷却至 {_format_clock_ms(row.get('until_ms'))}"
    elif kind in {"ratchet_up", "ratchet_breach"}:
        label = "棘轮抬升" if kind == "ratchet_up" else "棘轮触发"
        tone = "danger" if kind == "ratchet_breach" else "success"
        if kind == "ratchet_breach":
            message = (
                f"组合权益 {_format_usdt(row.get('equity'))} 跌破锁利底线 "
                f"{_format_usdt(row.get('floor_equity'))}，暂停新仓"
            )
        else:
            message = f"组合锁利底线抬升至 {_format_usdt(row.get('floor_equity', row.get('floor')))}"
    elif kind == "ratchet_rebase":
        label, tone = "棘轮重置", "info"
        message = f"组合棘轮以 {_format_usdt(row.get('base_equity'))} 重置新周期"
    elif kind == "equity_floor_up":
        label, tone = "权益地板", "success"
        message = (
            f"组合权益 {_format_usdt(row.get('equity'))}，锁利地板抬升至 "
            f"{_format_usdt(row.get('floor'))}"
        )
    elif kind == "daily_pause":
        label, tone = "日损暂停", "warning"
        message = f"组合权益 {_format_usdt(row.get('equity'))} 触发当日亏损暂停"
    elif kind == "challenge_terminal":
        label, tone = "挑战结束", "danger"
        reason_labels = {
            "target_200": "达到200U目标",
            "equity_floor_60": "触及60U失败线",
            "ratchet_exit": "跌破锁利地板",
            "challenge_expired": "7日到期",
        }
        reason = reason_labels.get(str(row.get("reason") or ""), _event_reason(row.get("reason")))
        message = f"组合权益 {_format_usdt(row.get('equity'))}，{reason}"

    event_id = str(row.get("event_id") or f"{kind}:{timestamp}:{symbol or 'portfolio'}")
    return {
        "event_id": event_id,
        "ts": timestamp,
        "label": label,
        "message": message,
        "tone": tone,
        "kind": kind,
    }


def _normalize_legacy_view(raw: Mapping[str, Any]) -> Dict[str, Any]:
    candidates = [item for row in _rows(raw.get("candidates_near")) if (item := _legacy_candidate(row))]
    members = [item for row in _rows(raw.get("members")) if (item := _legacy_member(row))]
    positions = [item for row in _rows(raw.get("positions")) if (item := _position(row))]
    events = [item for row in _rows(raw.get("events")) if (item := _event(row))]
    candidates_total = _count_value(raw.get("candidates_total"))
    has_content = bool(candidates or members or positions or events or candidates_total)
    status = str(raw.get("status") or ("ready" if has_content else "empty"))
    enter_rank = max(0, _safe_int(raw.get("candidate_enter_rank"), 60))
    enter_pct = _format_number(raw.get("momentum_enter_pct", 7.0))
    exit_pct = _format_number(raw.get("momentum_exit_pct", 2.0))
    summary = (
        f"候选 Top{enter_rank} · |24h 动量| ≥ {enter_pct}% 入池 · <{exit_pct}% 踢出"
        if has_content
        else "暂无可展示的动态池数据"
    )
    return _base_view(
        status=status,
        summary=summary,
        timestamps=_timestamp_payload(raw),
        counts={"candidates": candidates_total, "eligible": 0},
        candidates=candidates,
        members=members,
        positions=positions,
        events=events,
    )


def _normalize_factor_view(raw: Mapping[str, Any]) -> Dict[str, Any]:
    candidates = [item for row in _rows(raw.get("candidates_near")) if (item := _factor_candidate(row))]
    members = [item for row in _rows(raw.get("members")) if (item := _factor_member(row))]
    positions = [item for row in _rows(raw.get("positions")) if (item := _position(row))]
    events = [item for row in _rows(raw.get("events")) if (item := _event(row))]
    candidates_total = _count_value(raw.get("candidates_total"))
    eligible = _count_value(raw.get("eligible_symbols"))
    has_content = bool(candidates or members or positions or events or candidates_total or eligible)
    status = str(raw.get("status") or ("ready" if has_content else "empty"))
    summary = str(raw.get("selection_summary") or "").strip()
    if not summary:
        summary = "1H 因子评分动态池" if has_content or status == "warming" else "暂无可展示的动态池数据"
    return _base_view(
        status=status,
        summary=summary,
        timestamps=_timestamp_payload(raw),
        counts={"candidates": candidates_total, "eligible": eligible},
        candidates=candidates,
        members=members,
        positions=positions,
        events=events,
    )


def _normalize_display_metric(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    label = str(value.get("label") or "").strip()
    if not label:
        return None
    raw_value = value.get("value")
    display = str(value.get("display") if value.get("display") is not None else raw_value or "—")
    return _metric(label, raw_value, display, _tone(value.get("tone")))


def _normalize_display_badge(value: Any) -> Optional[Dict[str, str]]:
    if not isinstance(value, Mapping):
        return None
    label = str(value.get("label") or "").strip()
    return _badge(label, _tone(value.get("tone"))) if label else None


def _normalize_display_row(value: Any, prefix: str) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    symbol = _symbol(value)
    primary = _normalize_display_metric(value.get("primary_metric"))
    if not symbol or primary is None:
        return None
    badges = [item for row in _rows(value.get("badges")) if (item := _normalize_display_badge(row))]
    metrics = [item for row in _rows(value.get("metrics")) if (item := _normalize_display_metric(row))]
    return {
        "id": str(value.get("id") or f"{prefix}:{symbol}"),
        "symbol": symbol,
        "direction": _direction(value.get("direction")),
        "primary_metric": primary,
        "badges": badges,
        "metrics": metrics,
        "openable": bool(value.get("openable", False)),
        "reason": str(value.get("reason") or "").strip() or None,
    }


def _normalize_display_position(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    symbol = _symbol(value)
    if not symbol:
        return None
    direction = _direction(value.get("direction"))
    badges = [item for row in _rows(value.get("badges")) if (item := _normalize_display_badge(row))]
    metrics = [item for row in _rows(value.get("metrics")) if (item := _normalize_display_metric(row))]
    return {
        "id": str(value.get("id") or f"position:{symbol}:{direction or 0}"),
        "symbol": symbol,
        "direction": direction,
        "badges": badges,
        "metrics": metrics,
    }


def _normalize_display_event(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    timestamp = _optional_int(value.get("ts"))
    label = str(value.get("label") or "").strip()
    message = str(value.get("message") or "").strip()
    if timestamp is None or not label or not message:
        return None
    kind = str(value.get("kind") or "unknown")
    return {
        "event_id": str(value.get("event_id") or f"{kind}:{timestamp}"),
        "ts": timestamp,
        "label": label,
        "message": message,
        "tone": _tone(value.get("tone")),
        "kind": kind,
    }


def _normalize_schema_v4(raw: Mapping[str, Any]) -> Dict[str, Any]:
    candidates = [
        item for row in _rows(raw.get("candidates")) if (item := _normalize_display_row(row, "candidate"))
    ]
    members = [
        item for row in _rows(raw.get("members")) if (item := _normalize_display_row(row, "member"))
    ]
    positions = [
        item for row in _rows(raw.get("positions")) if (item := _normalize_display_position(row))
    ]
    events = [item for row in _rows(raw.get("events")) if (item := _normalize_display_event(row))]
    timestamps = raw.get("timestamps") if isinstance(raw.get("timestamps"), Mapping) else {}
    counts = raw.get("counts") if isinstance(raw.get("counts"), Mapping) else {}
    has_content = bool(candidates or members or positions or events or _count_value(counts.get("candidates")))
    return _base_view(
        status=str(raw.get("status") or ("ready" if has_content else "empty")),
        summary=str(raw.get("summary") or ("动态池展示快照" if has_content else "暂无可展示的动态池数据")),
        timestamps=timestamps,
        counts=counts,
        candidates=candidates,
        members=members,
        positions=positions,
        events=events,
    )


def normalize_dynamic_pool_view(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """把策略原始动态池快照归一化为 dashboard schema 4。

    函数是纯读取转换：不会修改传入字典，也不会持久化任何结果。
    """

    if not isinstance(raw, Mapping):
        return _empty_view()
    if _safe_int(raw.get("schema_version")) == SCHEMA_VERSION:
        return _normalize_schema_v4(raw)
    if raw.get("mode") == "ema_factor_adaptive":
        return _normalize_factor_view(raw)
    return _normalize_legacy_view(raw)


__all__ = ["normalize_dynamic_pool_view"]
