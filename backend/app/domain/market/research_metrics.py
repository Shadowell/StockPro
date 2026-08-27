"""Deterministic A-share research metrics for market phase, RPS and movers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite, sqrt
from statistics import mean
from typing import Any, Iterable, Mapping


MARKET_PHASE_DEFINITION_VERSION = "ashare-market-phase.v1"
SECTOR_RPS_DEFINITION_VERSION = "ashare-sector-rps.v1"
ABNORMALITY_DEFINITION_VERSION = "ashare-abnormality.v1"
FUNDAMENTAL_PIT_DEFINITION_VERSION = "ashare-fundamental-pit.v1"
CN_TZ = timezone(timedelta(hours=8))
ABNORMAL_WINDOW_KEYS = ("3d", "10d", "30d")


@dataclass(frozen=True)
class AbnormalRule:
    """A-share abnormal-move thresholds expressed as ratios."""

    board: str
    st: bool
    thresholds: dict[int, tuple[float, float]]


_MAIN_ABNORMAL_THRESHOLDS = {3: (0.20, 0.20), 10: (1.00, 0.50), 30: (2.00, 0.70)}
_GEM_STAR_ABNORMAL_THRESHOLDS = {3: (0.30, 0.30), 10: (1.00, 0.50), 30: (2.00, 0.70)}
_BSE_ABNORMAL_THRESHOLDS = {3: (0.40, 0.40), 10: (1.00, 0.50), 30: (2.00, 0.70)}


def board_of(symbol: str, board: str | None = None) -> str:
    """Return the explicit instrument board or the conservative code-prefix fallback."""
    explicit = str(board or "").strip()
    if explicit:
        if "北交" in explicit or explicit.upper() in {"BSE", "BJ"}:
            return "北交所"
        if "创业" in explicit or explicit.upper() in {"GEM", "CYB"}:
            return "创业板"
        if "科创" in explicit or explicit.upper() in {"STAR", "KCB"}:
            return "科创板"
        if "主板" in explicit:
            return "主板"
    raw = str(symbol or "").strip().upper()
    code = raw.split(".", 1)[0].split("_", 1)[-1]
    exchange = raw.rsplit(".", 1)[-1] if "." in raw else ""
    if exchange == "BJ" or code[:2] in {"43", "83", "87", "92"}:
        return "北交所"
    if code.startswith("68"):
        return "科创板"
    if code.startswith("30"):
        return "创业板"
    return "主板"


def is_st_name(name: str | None) -> bool:
    return bool(name) and "ST" in str(name).upper()


def abnormal_rule_for(symbol: str, name: str | None = None, board: str | None = None) -> AbnormalRule:
    """Resolve the exchange disclosure rule for one A-share instrument.

    Since 2026-07-06, main-board ST/*ST instruments use the ordinary main-board
    abnormal-volatility thresholds; the ST flag remains visible as context.
    """
    normalized_board = board_of(symbol, board)
    st = is_st_name(name)
    if normalized_board == "北交所":
        thresholds = _BSE_ABNORMAL_THRESHOLDS
    elif normalized_board in {"创业板", "科创板"}:
        thresholds = _GEM_STAR_ABNORMAL_THRESHOLDS
    else:
        thresholds = _MAIN_ABNORMAL_THRESHOLDS
    return AbnormalRule(normalized_board, st, dict(thresholds))


def _abnormal_status(closeness: float) -> str:
    if closeness >= 1.0:
        return "triggered"
    if closeness >= 0.7:
        return "edge"
    return "watch"


def build_abnormal_windows(
    deviations: Mapping[str, Any],
    rule: AbnormalRule,
    *,
    values_are_percent: bool = False,
) -> dict[str, dict[str, Any]]:
    """Build directional threshold/closeness facts for 3/10/30-day deviations.

    The canonical ``value`` and ``threshold`` fields are ratios (0.20 = 20%).
    ``value_pct`` and ``threshold_pct`` are included for operator-facing UIs.
    ``values_are_percent`` preserves the existing research function's percentage
    return fields while keeping this contract unit-safe.
    """
    windows: dict[str, dict[str, Any]] = {}
    for key in ABNORMAL_WINDOW_KEYS:
        try:
            window = int(key[:-1])
        except ValueError:
            continue
        raw = _as_float(deviations.get(key))
        if raw is None:
            raw = _as_float(deviations.get(f"deviate_{key}"))
        if raw is None:
            raw = _as_float(deviations.get(f"benchmark_deviation_{key}"))
        if raw is None:
            continue
        value = raw / 100.0 if values_are_percent else raw
        up_threshold, down_threshold = rule.thresholds[window]
        threshold = up_threshold if value >= 0 else down_threshold
        closeness = abs(value) / threshold if threshold > 0 else 0.0
        windows[key] = {
            "value": round(value, 6),
            "value_pct": round(value * 100.0, 4),
            "threshold": threshold,
            "threshold_pct": round(threshold * 100.0, 4),
            "closeness": round(closeness, 4),
            "direction": "up" if value > 0 else "down" if value < 0 else "flat",
            "status": _abnormal_status(closeness),
        }
    return windows


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def valid_price_limit_pair(up_limit: Any, down_limit: Any) -> bool:
    """Reject provider sentinels while retaining every current A-share limit band."""
    up = _as_float(up_limit)
    down = _as_float(down_limit)
    return bool(up is not None and down is not None and up > 0 and down > 0 and up >= down and up / down <= 2.0)


def _pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous <= 0:
        return None
    return (current / previous - 1.0) * 100.0


def _available_after_close(trade_date: date | str) -> datetime:
    day = date.fromisoformat(str(trade_date)[:10]) if not isinstance(trade_date, date) else trade_date
    return datetime.combine(day, time(17, 30), tzinfo=CN_TZ)


def compute_market_phase(
    *,
    trade_date: date | str,
    metrics: Mapping[str, Any],
    source_snapshot_id: int | None = None,
    available_at: datetime | None = None,
    knowledge_cutoff_at: datetime | None = None,
) -> dict[str, Any]:
    """Classify a six-stage A-share market phase from observed market breadth facts."""
    required = {
        "index_change_pct": "指数涨跌缺失",
        "advance_ratio": "上涨家数占比缺失",
        "turnover_change_pct": "成交额变化缺失",
        "limit_up_count": "涨停家数缺失",
        "failed_limit_count": "炸板家数缺失",
        "sector_diffusion_pct": "行业/概念扩散缺失",
        "profit_effect_pct": "赚钱效应缺失",
        "risk_appetite": "风险偏好缺失",
    }
    missing = [label for key, label in required.items() if _as_float(metrics.get(key)) is None]
    available = available_at or _available_after_close(trade_date)
    cutoff = knowledge_cutoff_at or available
    if missing:
        return {
            "trade_date": str(trade_date)[:10],
            "phase": "unknown",
            "status": "partial",
            "confidence": 0.0,
            "reasons": [],
            "missing_inputs": missing,
            "definition_version": MARKET_PHASE_DEFINITION_VERSION,
            "source_snapshot_id": source_snapshot_id,
            "input_trade_date": str(trade_date)[:10],
            "available_at": available.isoformat(),
            "knowledge_cutoff_at": cutoff.isoformat(),
        }

    index_change = float(metrics["index_change_pct"])
    advance_ratio = float(metrics["advance_ratio"])
    turnover_change = float(metrics["turnover_change_pct"])
    limit_up = float(metrics["limit_up_count"])
    failed_limit = float(metrics["failed_limit_count"])
    sector_diffusion = float(metrics["sector_diffusion_pct"])
    profit_effect = float(metrics["profit_effect_pct"])
    risk_appetite = float(metrics["risk_appetite"])
    fail_ratio = failed_limit / max(limit_up + failed_limit, 1.0)

    score = (
        50.0
        + index_change * 6.0
        + (advance_ratio - 50.0) * 0.55
        + turnover_change * 0.22
        + (sector_diffusion - 50.0) * 0.28
        + (profit_effect - 50.0) * 0.32
        + (risk_appetite - 50.0) * 0.22
        + min(limit_up, 120.0) * 0.10
        - fail_ratio * 22.0
    )
    score = max(0.0, min(100.0, score))
    divergence = fail_ratio >= 0.42 and limit_up >= 20
    if score < 30:
        phase = "冰点"
    elif score < 45:
        phase = "退潮" if index_change < 0 or advance_ratio < 40 else "修复"
    elif score < 60:
        phase = "修复" if index_change < 0 and turnover_change < 0 else "启动"
    elif score < 76:
        phase = "主升"
    elif divergence:
        phase = "退潮"
    else:
        phase = "高潮"
    reasons = [
        f"指数涨跌 {index_change:.2f}%",
        f"上涨占比 {advance_ratio:.1f}%",
        f"成交额变化 {turnover_change:.1f}%",
        f"涨停 {limit_up:.0f} / 炸板 {failed_limit:.0f}",
        f"扩散 {sector_diffusion:.1f}%",
        f"赚钱效应 {profit_effect:.1f}%",
    ]
    if divergence:
        reasons.append(f"高位分歧：炸板率 {fail_ratio * 100:.1f}%")
    return {
        "trade_date": str(trade_date)[:10],
        "phase": phase,
        "status": "ok",
        "confidence": round(score / 100.0, 4),
        "reasons": reasons,
        "missing_inputs": [],
        "definition_version": MARKET_PHASE_DEFINITION_VERSION,
        "source_snapshot_id": source_snapshot_id,
        "input_trade_date": str(trade_date)[:10],
        "available_at": available.isoformat(),
        "knowledge_cutoff_at": cutoff.isoformat(),
    }


def compute_sector_rps(
    rows: Iterable[Mapping[str, Any]],
    *,
    trade_date: date | str,
    classification_system: str,
    previous_ranks: Mapping[str, int] | None = None,
    source_snapshot_id: int | None = None,
) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for row in rows:
        code = str(row.get("sector_code") or row.get("code") or "").strip()
        if not code:
            continue
        returns = [
            _as_float(row.get("return_5d")),
            _as_float(row.get("return_10d")),
            _as_float(row.get("return_20d")),
            _as_float(row.get("return_60d")),
        ]
        amount_change = _as_float(row.get("amount_change_pct"))
        breadth = _as_float(row.get("up_ratio") if row.get("up_ratio") is not None else row.get("breadth"))
        limit_up_count = _as_float(row.get("limit_up_count"))
        leader_contribution = _as_float(row.get("leader_contribution_pct"))
        coverage = _as_float(row.get("member_coverage"))
        missing = []
        if any(value is None for value in returns):
            missing.append("板块 5/10/20/60 日收益缺失")
        if amount_change is None:
            missing.append("成交额变化缺失")
        if breadth is None:
            missing.append("上涨占比缺失")
        if limit_up_count is None:
            missing.append("涨停数量缺失")
        if leader_contribution is None:
            missing.append("龙头贡献缺失")
        if coverage is None or coverage < 0.8:
            missing.append("成员行情覆盖不足")
        if missing:
            score = None
        else:
            r5, r10, r20, r60 = [float(value) for value in returns]
            score = (
                r5 * 0.25
                + r10 * 0.25
                + r20 * 0.20
                + r60 * 0.10
                + float(amount_change) * 0.08
                + (float(breadth) - 50.0) * 0.06
                + min(float(limit_up_count), 20.0) * 0.80
                + float(leader_contribution) * 0.06
            )
        scored.append({
            "trade_date": str(trade_date)[:10],
            "classification_system": classification_system,
            "sector_code": code,
            "sector_name": str(row.get("sector_name") or row.get("name") or code),
            "strength_score": None if score is None else round(float(score), 6),
            "return_5d": returns[0],
            "return_10d": returns[1],
            "return_20d": returns[2],
            "return_60d": returns[3],
            "amount_change_pct": amount_change,
            "up_ratio": breadth,
            "limit_up_count": int(limit_up_count) if limit_up_count is not None else None,
            "member_count": int(row.get("member_count") or 0),
            "source_snapshot_id": source_snapshot_id,
            "leader_symbol": row.get("leader_symbol"),
            "leader_contribution_pct": leader_contribution,
            "member_coverage": coverage,
            "missing_inputs": missing,
        })
    valid_scores = sorted(
        [item for item in scored if item["strength_score"] is not None],
        key=lambda item: float(item["strength_score"]),
        reverse=True,
    )
    rank_by_code = {item["sector_code"]: idx + 1 for idx, item in enumerate(valid_scores)}
    count = max(len(valid_scores), 1)
    previous_ranks = previous_ranks or {}
    for item in scored:
        rank = rank_by_code.get(item["sector_code"])
        if rank is None:
            percentile = None
            rank_change = None
            status = "partial"
        else:
            percentile = 100.0 if count == 1 else (count - rank) / (count - 1) * 100.0
            previous = previous_ranks.get(item["sector_code"])
            rank_change = None if previous is None else previous - rank
            status = "ok"
        item.update({
            "rank": rank,
            "rank_change": rank_change,
            "rps_percentile": None if percentile is None else round(percentile, 4),
            "strong_days": int(item.get("strong_days") or (1 if percentile is not None and percentile >= 80 else 0)),
            "status": status,
            "definition_version": SECTOR_RPS_DEFINITION_VERSION,
            "available_at": _available_after_close(trade_date).isoformat(),
            "knowledge_cutoff_at": _available_after_close(trade_date).isoformat(),
        })
    return sorted(scored, key=lambda item: (item["rank"] is None, item["rank"] or 999999, item["sector_code"]))


def compute_symbol_abnormality(
    bars: list[Mapping[str, Any]],
    *,
    symbol: str,
    name: str | None = None,
    board: str | None = None,
    trade_date: date | str,
    benchmark_bars: list[Mapping[str, Any]] | None = None,
    sector_bars: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    ordered = sorted(bars, key=lambda row: str(row.get("date") or row.get("trade_date") or ""))
    target_day = str(trade_date)[:10]
    upto = [row for row in ordered if str(row.get("date") or row.get("trade_date") or "")[:10] <= target_day]
    current = upto[-1] if upto else {}
    missing: list[str] = []

    def close_at(offset: int) -> float | None:
        if len(upto) <= offset:
            return None
        return _as_float(upto[-1 - offset].get("close"))

    current_close = close_at(0)
    returns = {f"return_{window}d": _pct(current_close, close_at(window)) for window in (3, 10, 30)}
    for key, value in returns.items():
        if value is None:
            missing.append(f"{key} 窗口不足或价格缺失")

    def window_amount_ratio(short: int, long: int) -> float | None:
        if len(upto) < long:
            return None
        amounts = [
            _as_float(row.get("amount") if row.get("amount") is not None else row.get("turnover") if row.get("turnover") is not None else row.get("quote_volume"))
            for row in upto[-long:]
        ]
        if any(value is None for value in amounts):
            return None
        short_mean = mean([float(value) for value in amounts[-short:]])
        long_mean = mean([float(value) for value in amounts])
        return None if long_mean <= 0 else short_mean / long_mean

    amount_ratio_5d = window_amount_ratio(5, 20)
    if amount_ratio_5d is None:
        missing.append("5/20 日成交额窗口缺失")
    highs = [_as_float(row.get("high")) for row in upto[-60:]]
    lows = [_as_float(row.get("low")) for row in upto[-60:]]
    highs = [float(value) for value in highs if value is not None]
    lows = [float(value) for value in lows if value is not None]
    previous_high = max(highs[:-1]) if len(highs) > 1 else None
    previous_low = min(lows[:-1]) if len(lows) > 1 else None
    distance_high = None if current_close is None or previous_high is None or previous_high <= 0 else (current_close / previous_high - 1.0) * 100.0
    distance_low = None if current_close is None or previous_low is None or previous_low <= 0 else (current_close / previous_low - 1.0) * 100.0
    if distance_high is None or distance_low is None:
        missing.append("关键前高/前低窗口缺失")

    benchmark_deviation = {f"benchmark_deviation_{w}d": None for w in (3, 10, 30)}
    if benchmark_bars:
        benchmark = compute_symbol_abnormality(benchmark_bars, symbol="benchmark", trade_date=trade_date)
        for window in (3, 10, 30):
            own = returns[f"return_{window}d"]
            base = benchmark[f"return_{window}d"]
            benchmark_deviation[f"benchmark_deviation_{window}d"] = None if own is None or base is None else own - base
    else:
        missing.append("基准对照缺失")

    sector_deviation = {f"sector_deviation_{w}d": None for w in (3, 10, 30)}
    if sector_bars:
        sector = compute_symbol_abnormality(sector_bars, symbol="sector", trade_date=trade_date)
        for window in (3, 10, 30):
            own = returns[f"return_{window}d"]
            base = sector[f"return_{window}d"]
            sector_deviation[f"sector_deviation_{window}d"] = None if own is None or base is None else own - base
    else:
        missing.append("行业/概念对照缺失")

    rule = abnormal_rule_for(symbol, name, board)
    windows = build_abnormal_windows(
        {
            f"benchmark_deviation_{window}d": benchmark_deviation[f"benchmark_deviation_{window}d"]
            for window in (3, 10, 30)
        },
        rule,
        values_are_percent=True,
    )
    # A row with any missing relative evidence is useful for diagnostics, but
    # must not enter the normal abnormality ranking or alert evaluation.
    if missing or len(windows) != len(ABNORMAL_WINDOW_KEYS):
        windows = {}
    max_closeness = max((float(item["closeness"]) for item in windows.values()), default=None)
    tags: list[str] = []
    if returns["return_3d"] is not None and abs(float(returns["return_3d"])) >= 9.0:
        tags.append("价格异动")
    if amount_ratio_5d is not None and amount_ratio_5d >= 1.8:
        tags.append("量能异动")
    if distance_high is not None and -3.0 <= distance_high <= 1.0:
        tags.append("接近前高")
    if distance_low is not None and -1.0 <= distance_low <= 3.0:
        tags.append("接近前低")
    if not tags and missing:
        tags.append("缺失数据")
    elif not tags:
        tags.append("常规波动")

    return {
        "symbol": symbol,
        "name": name,
        "board": rule.board,
        "st": rule.st,
        "trade_date": target_day,
        **returns,
        **benchmark_deviation,
        **sector_deviation,
        "amount_ratio_5d": None if amount_ratio_5d is None else round(amount_ratio_5d, 6),
        "distance_to_60d_high_pct": None if distance_high is None else round(distance_high, 6),
        "distance_to_60d_low_pct": None if distance_low is None else round(distance_low, 6),
        "windows": windows,
        "max_closeness": max_closeness,
        "abnormal_status": _abnormal_status(max_closeness) if max_closeness is not None else None,
        "eligible": bool(windows) and not missing,
        "tags": tags,
        "data_status": "partial" if missing else "ok",
        "status": "partial" if missing else "ok",
        "missing_inputs": missing,
        "definition_version": ABNORMALITY_DEFINITION_VERSION,
        "available_at": _available_after_close(trade_date).isoformat(),
        "knowledge_cutoff_at": _available_after_close(trade_date).isoformat(),
    }


@dataclass(frozen=True)
class FundamentalRevision:
    symbol: str
    factor_code: str
    report_period: str
    announcement_available_at: datetime | str | None
    revision: int
    value: float | None
    source_lineage: Mapping[str, Any]


def select_pit_fundamental_revision(
    revisions: Iterable[FundamentalRevision | Mapping[str, Any]],
    *,
    simulated_at: datetime,
) -> dict[str, Any] | None:
    """Return the latest financial factor revision known at simulated_at."""
    candidates: list[dict[str, Any]] = []
    for revision in revisions:
        row = revision.__dict__ if isinstance(revision, FundamentalRevision) else dict(revision)
        available_raw = row.get("announcement_available_at")
        if not available_raw:
            continue
        available = available_raw if isinstance(available_raw, datetime) else datetime.fromisoformat(str(available_raw).replace("Z", "+00:00"))
        if available.tzinfo is None:
            available = available.replace(tzinfo=timezone.utc)
        cutoff = simulated_at if simulated_at.tzinfo else simulated_at.replace(tzinfo=timezone.utc)
        if available <= cutoff:
            next_row = dict(row)
            next_row["announcement_available_at"] = available.isoformat()
            candidates.append(next_row)
    if not candidates:
        return None
    candidates.sort(key=lambda item: (str(item["announcement_available_at"]), int(item.get("revision") or 0)))
    selected = candidates[-1]
    selected["definition_version"] = FUNDAMENTAL_PIT_DEFINITION_VERSION
    return selected
