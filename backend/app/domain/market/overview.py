"""Read-only A-share market overview calculations.

The overview deliberately consumes facts already persisted in PostgreSQL.  It
does not fetch providers, create snapshots, or fill missing values with zero.
"""
from __future__ import annotations

from collections import defaultdict
from math import isfinite
from statistics import mean, median
from typing import Any, Iterable, Mapping


MARKET_OVERVIEW_DEFINITION_VERSION = "ashare-market-overview.v1"
TREND_DEFINITION_VERSION = "ashare-trend-strength.v1"
TREND_REQUIRED_HISTORY_DAYS = 60
STRONG_MOVE_THRESHOLD_PCT = 3.0
HIGH_TURNOVER_THRESHOLD_PCT = 8.0
VOLUME_RATIO_THRESHOLD = 1.5

INDEX_SPECS: tuple[dict[str, Any], ...] = (
    {"symbol": "000001.SH", "name": "上证指数", "aliases": ("000001", "000001.SH", "上证指数")},
    {"symbol": "399001.SZ", "name": "深证成指", "aliases": ("399001", "399001.SZ", "深证成指")},
    {"symbol": "399006.SZ", "name": "创业板指", "aliases": ("399006", "399006.SZ", "创业板指")},
    {"symbol": "000300.SH", "name": "沪深300", "aliases": ("000300", "000300.SH", "沪深300", "沪深 300")},
)

_DISTRIBUTION_BUCKETS: tuple[tuple[str, str], ...] = (
    ("lt_-5", "<-5%"),
    ("-5_to_-3", "-5%~-3%"),
    ("-3_to_-1", "-3%~-1%"),
    ("-1_to_0", "-1%~0"),
    ("0_to_1", "0~1%"),
    ("1_to_3", "1%~3%"),
    ("3_to_5", "3%~5%"),
    ("gt_5", ">5%"),
)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _canonical_symbol(raw: Any) -> str:
    value = str(raw or "").strip().upper()
    if not value:
        return ""
    if "_" in value:
        exchange, digits = value.split("_", 1)
        return f"{digits}.{exchange}"
    if "." in value:
        return value
    if value.isdigit() and len(value) == 6:
        exchange = "SH" if value.startswith(("5", "6", "9")) else "BJ" if value.startswith(("4", "8")) else "SZ"
        return f"{value}.{exchange}"
    return value


def _exchange_for_symbol(symbol: str) -> str:
    exchange = symbol.rsplit(".", 1)[-1] if "." in symbol else ""
    return {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(exchange, exchange or "CN")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _module_meta(evidence: Mapping[str, Any], status: str, missing_inputs: Iterable[str] = ()) -> dict[str, Any]:
    missing = [str(item) for item in missing_inputs if str(item).strip()]
    return {
        "trade_date": evidence.get("trade_date"),
        "data_mode": evidence.get("data_mode"),
        "provider": evidence.get("provider"),
        "source_snapshot_id": evidence.get("source_snapshot_id"),
        "available_at": evidence.get("available_at"),
        "knowledge_cutoff_at": evidence.get("knowledge_cutoff_at"),
        "last_success_at": evidence.get("last_success_at"),
        "status": status,
        "data_status": status,
        "missing_inputs": missing,
    }


def _normalize_fact(row: Mapping[str, Any]) -> dict[str, Any] | None:
    symbol = _canonical_symbol(_first(row, "symbol", "code", "ts_code"))
    if not symbol:
        return None
    price = _number(_first(row, "price", "last", "last_price", "close"))
    change = _number(_first(row, "change_percent", "changePercent", "pct_chg", "change_percent_today"))
    amount = _number(_first(row, "amount_cny", "amount", "quote_volume", "quoteVolume"))
    turnover = _number(_first(row, "turnover_rate_pct", "turnover_rate", "turnover"))
    volume_ratio = _number(_first(row, "volume_ratio", "volumeRatio"))
    pe = _number(_first(row, "pe_ttm", "pe_dynamic", "pe"))
    pb = _number(_first(row, "pb"))
    market_cap = _number(_first(row, "total_market_cap_cny", "total_market_cap"))
    suspended = bool(_first(row, "suspended", "is_suspended")) or str(_first(row, "status") or "").strip() in {"停牌", "suspended", "SUSPENDED"}

    invalid_reason: str | None = None
    if suspended:
        invalid_reason = "suspended"
    elif price is None or price <= 0:
        invalid_reason = "no_price"
    elif change is None:
        invalid_reason = "no_change"
    elif abs(change) > 1000:
        invalid_reason = "invalid_change"
    elif amount is not None and amount < 0:
        invalid_reason = "invalid_amount"
    elif turnover is not None and turnover < 0:
        invalid_reason = "invalid_turnover"
    elif volume_ratio is not None and volume_ratio < 0:
        invalid_reason = "invalid_volume_ratio"

    return {
        "symbol": symbol,
        "name": str(_first(row, "name", "display_name") or symbol).strip() or symbol,
        "exchange": str(_first(row, "exchange") or _exchange_for_symbol(symbol)),
        "price": price,
        "change_percent": change,
        "amount_cny": amount,
        "turnover_rate_pct": turnover,
        "volume_ratio": volume_ratio,
        "pe_ttm": pe,
        "pb": pb,
        "total_market_cap_cny": market_cap,
        "trade_date": _iso(_first(row, "trade_date", "date")),
        "source": _first(row, "source") or "PostgreSQL",
        "source_updated_at": _iso(_first(row, "source_updated_at", "updated_at", "collected_at")),
        "eligible": invalid_reason is None,
        "invalid_reason": invalid_reason,
    }


def _ranking_item(fact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "symbol": fact["symbol"],
        "name": fact["name"],
        "exchange": fact["exchange"],
        "price": fact["price"],
        "change_percent": fact["change_percent"],
        "amount_cny": fact["amount_cny"],
        "turnover_rate_pct": fact["turnover_rate_pct"],
        "volume_ratio": fact["volume_ratio"],
        "trade_date": fact["trade_date"],
        "source": fact["source"],
        "source_updated_at": fact["source_updated_at"],
    }


def _distribution_key(change: float) -> str:
    if change < -5:
        return "lt_-5"
    if change < -3:
        return "-5_to_-3"
    if change < -1:
        return "-3_to_-1"
    if change < 0:
        return "-1_to_0"
    if change < 1:
        return "0_to_1"
    if change < 3:
        return "1_to_3"
    if change <= 5:
        return "3_to_5"
    return "gt_5"


def _distribution(changes: list[float]) -> list[dict[str, Any]]:
    counts = {key: 0 for key, _label in _DISTRIBUTION_BUCKETS}
    for change in changes:
        counts[_distribution_key(change)] += 1
    total = len(changes)
    return [
        {
            "key": key,
            "label": label,
            "count": counts[key] if total else None,
            "percentage": (counts[key] / total * 100.0) if total else None,
        }
        for key, label in _DISTRIBUTION_BUCKETS
    ]


def _index_spec(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    raw_symbol = str(_first(raw, "symbol", "code", "ts_code") or "").strip().upper()
    raw_name = str(_first(raw, "name", "index_name") or "").strip()
    normalized_raw = _canonical_symbol(raw_symbol)
    match = next(
        (
            spec
            for spec in INDEX_SPECS
            if normalized_raw in spec["aliases"] or raw_symbol in spec["aliases"] or raw_name in spec["aliases"]
        ),
        None,
    )
    if match is None:
        return None
    price = _number(_first(raw, "price", "last", "close"))
    change = _number(_first(raw, "change_percent", "changePercent", "pct_chg"))
    change_amount = _number(_first(raw, "change_amount", "change"))
    symbol = str(match["symbol"])
    return {
        "symbol": symbol,
        "code": symbol,
        "name": str(match["name"]),
        "asset_class": "index",
        "exchange": _exchange_for_symbol(symbol),
        "price": price,
        "change_percent": change,
        "change_amount": change_amount,
        "trade_date": _iso(_first(raw, "trade_date", "date")),
        "source": _first(raw, "source") or "PostgreSQL",
        "source_snapshot_id": _first(raw, "source_snapshot_id"),
        "available_at": _iso(_first(raw, "available_at", "updated_at", "source_updated_at")),
        "status": "ready" if price is not None and change is not None else "partial",
    }


def _normalize_indices(rows: Iterable[Mapping[str, Any]], evidence: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str, list[str]]:
    by_symbol: dict[str, dict[str, Any]] = {}
    for raw in rows:
        item = _index_spec(raw)
        if item is not None and item["symbol"] not in by_symbol:
            item["trade_date"] = item["trade_date"] or evidence.get("trade_date")
            item["source_snapshot_id"] = item["source_snapshot_id"] or evidence.get("source_snapshot_id")
            by_symbol[item["symbol"]] = item
    items = [by_symbol[str(spec["symbol"])] for spec in INDEX_SPECS if str(spec["symbol"]) in by_symbol]
    if not items:
        return [], "empty", ["没有可用的真实指数日线或缓存"]
    missing = [str(spec["name"]) for spec in INDEX_SPECS if str(spec["symbol"]) not in by_symbol]
    invalid = [str(item["name"]) for item in items if item["status"] != "ready"]
    missing.extend(f"{name}点位或涨跌缺失" for name in invalid)
    return items, "ready" if len(items) == len(INDEX_SPECS) and not invalid else "partial", missing


def _trend_row_from_raw(
    rows: Iterable[Mapping[str, Any]],
    *,
    required_history_days: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[tuple[str, float, float, float]]] = defaultdict(list)
    for raw in rows:
        symbol = _canonical_symbol(_first(raw, "symbol", "code", "ts_code"))
        day = _iso(_first(raw, "date", "trade_date"))
        close = _number(_first(raw, "close", "price"))
        high = _number(_first(raw, "high", "close", "price"))
        low = _number(_first(raw, "low", "close", "price"))
        if symbol and day and close is not None and close > 0 and high is not None and low is not None and high >= low:
            grouped[symbol].append((day[:10], close, high, low))
    result: list[dict[str, Any]] = []
    for symbol, values in grouped.items():
        ordered = sorted(values, key=lambda item: item[0])
        closes = [item[1] for item in ordered]
        recent = closes[-required_history_days:]
        latest = closes[-1]
        result.append({
            "symbol": symbol,
            "history_days": len(closes),
            "latest_close": latest,
            "ma5": mean(recent[-5:]) if len(recent) >= 5 else None,
            "ma20": mean(recent[-20:]) if len(recent) >= 20 else None,
            "ma60": mean(recent) if len(recent) >= required_history_days else None,
            "period_high_60d": max(recent) if recent else None,
            "period_low_60d": min(recent) if recent else None,
        })
    return result


def compute_trend_strength(
    rows: Iterable[Mapping[str, Any]],
    *,
    required_history_days: int = TREND_REQUIRED_HISTORY_DAYS,
) -> dict[str, Any]:
    """Calculate cross-sectional trend counts without guessing missing history."""
    raw_rows = [dict(row) for row in rows]
    has_aggregates = any("history_days" in row for row in raw_rows)
    normalized: list[dict[str, Any]] = raw_rows if has_aggregates else _trend_row_from_raw(
        raw_rows,
        required_history_days=required_history_days,
    )
    normalized = [
        {
            **row,
            "symbol": _canonical_symbol(_first(row, "symbol", "code", "ts_code")),
            "history_days": int(_number(row.get("history_days")) or 0),
            "latest_close": _number(_first(row, "latest_close", "close", "price")),
            "ma5": _number(_first(row, "ma5", "ma_5")),
            "ma20": _number(_first(row, "ma20", "ma_20")),
            "ma60": _number(_first(row, "ma60", "ma_60")),
            "period_high_60d": _number(_first(row, "period_high_60d", "high_60d", "max_close_60d")),
            "period_low_60d": _number(_first(row, "period_low_60d", "low_60d", "min_close_60d")),
        }
        for row in normalized
        if _canonical_symbol(_first(row, "symbol", "code", "ts_code"))
    ]
    max_history = max((int(row["history_days"]) for row in normalized), default=0)
    covered = [row for row in normalized if row["history_days"] >= required_history_days and row["latest_close"] is not None]
    total_symbols = len(normalized)
    if not covered:
        status = "blocked" if max_history else "empty"
        missing = [
            f"趋势强度需要至少 {required_history_days} 个确认交易日；当前最多 {max_history} 日" if max_history else "没有可用的历史日线"
        ]
        return {
            "status": status,
            "data_status": status,
            "definition_version": TREND_DEFINITION_VERSION,
            "required_history_days": required_history_days,
            "available_history_days": max_history,
            "total_symbols": total_symbols,
            "covered_symbols": 0,
            "denominator": f"至少 {required_history_days} 个确认交易日且收盘价有效的 A 股",
            "above_ma5": {"count": None, "percentage": None},
            "above_ma20": {"count": None, "percentage": None},
            "above_ma60": {"count": None, "percentage": None},
            "new_high_60d": {"count": None, "percentage": None},
            "new_low_60d": {"count": None, "percentage": None},
            "new_high_low_ratio": None,
            "missing_inputs": missing,
        }

    denominator = len(covered)

    def count_where(predicate) -> dict[str, Any]:
        count = sum(1 for row in covered if predicate(row))
        return {"count": count, "percentage": count / denominator * 100.0}

    above_ma5 = count_where(lambda row: row["ma5"] is not None and row["latest_close"] >= row["ma5"])
    above_ma20 = count_where(lambda row: row["ma20"] is not None and row["latest_close"] >= row["ma20"])
    above_ma60 = count_where(lambda row: row["ma60"] is not None and row["latest_close"] >= row["ma60"])
    new_high = count_where(lambda row: row["period_high_60d"] is not None and row["latest_close"] >= row["period_high_60d"])
    new_low = count_where(lambda row: row["period_low_60d"] is not None and row["latest_close"] <= row["period_low_60d"])
    status = "ready" if len(covered) == total_symbols else "partial"
    missing = [] if status == "ready" else [f"{total_symbols - len(covered)} 个标的历史不足 {required_history_days} 日"]
    return {
        "status": status,
        "data_status": status,
        "definition_version": TREND_DEFINITION_VERSION,
        "required_history_days": required_history_days,
        "available_history_days": max_history,
        "total_symbols": total_symbols,
        "covered_symbols": denominator,
        "denominator": f"至少 {required_history_days} 个确认交易日且收盘价有效的 A 股",
        "above_ma5": above_ma5,
        "above_ma20": above_ma20,
        "above_ma60": above_ma60,
        "new_high_60d": new_high,
        "new_low_60d": new_low,
        "new_high_low_ratio": new_high["count"] / new_low["count"] if new_low["count"] else None,
        "missing_inputs": missing,
    }


def build_market_overview(
    *,
    ticker_rows: Iterable[Mapping[str, Any]],
    index_rows: Iterable[Mapping[str, Any]],
    trend_rows: Iterable[Mapping[str, Any]],
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the single read-only market overview consumed by the home page."""
    base_evidence = {
        "trade_date": None,
        "data_mode": "盘后快照",
        "provider": "PostgreSQL",
        "source_snapshot_id": None,
        "available_at": None,
        "knowledge_cutoff_at": None,
        "last_success_at": None,
        "status": "ready",
        "missing_inputs": [],
    }
    base_evidence.update(dict(evidence or {}))

    facts_by_symbol: dict[str, dict[str, Any]] = {}
    for raw in ticker_rows:
        fact = _normalize_fact(raw)
        if fact is not None:
            facts_by_symbol.setdefault(fact["symbol"], fact)
    facts = list(facts_by_symbol.values())
    eligible = [fact for fact in facts if fact["eligible"] and fact["change_percent"] is not None]
    changes = [float(fact["change_percent"]) for fact in eligible]

    excluded_reasons: dict[str, int] = defaultdict(int)
    for fact in facts:
        if not fact["eligible"]:
            excluded_reasons[str(fact["invalid_reason"])] += 1
    rise = sum(1 for value in changes if value > 0)
    fall = sum(1 for value in changes if value < 0)
    flat = sum(1 for value in changes if value == 0)
    breadth_missing: list[str] = []
    if not facts:
        breadth_missing.append("没有可用的 A 股行情事实")
    elif not eligible:
        breadth_missing.append("价格或当日涨跌全部缺失/无效")
    breadth_status = "ready" if eligible else "empty"
    breadth = {
        **_module_meta(base_evidence, breadth_status, breadth_missing),
        "definition_version": MARKET_OVERVIEW_DEFINITION_VERSION,
        "universe_count": len(facts),
        "eligible_count": len(eligible),
        "excluded_count": len(facts) - len(eligible),
        "excluded_reasons": dict(sorted(excluded_reasons.items())),
        "gainers": rise,
        "losers": fall,
        "flat": flat,
        "advance_ratio_pct": rise / len(eligible) * 100.0 if eligible else None,
        "strong_count": sum(1 for value in changes if value >= STRONG_MOVE_THRESHOLD_PCT),
        "weak_count": sum(1 for value in changes if value <= -STRONG_MOVE_THRESHOLD_PCT),
        "mean_change_pct": mean(changes) if changes else None,
        "median_change_pct": median(changes) if changes else None,
        "strong_move_threshold_pct": STRONG_MOVE_THRESHOLD_PCT,
        "denominator": "有效价格与当日涨跌均存在的 A 股",
    }
    distribution = {
        **_module_meta(base_evidence, breadth_status, breadth_missing),
        "definition_version": MARKET_OVERVIEW_DEFINITION_VERSION,
        "buckets": _distribution(changes),
        "total_count": len(changes) if changes else None,
        "boundary_definition": "左闭右开；0 归入 0~1%，5 归入 3%~5%",
        "denominator": "同市场宽度 eligible_count",
    }

    rankings_missing = [] if eligible else ["没有可用于排行的有效价格与涨跌数据"]
    ranking_status = "ready" if eligible else "empty"
    ranking_items = [_ranking_item(fact) for fact in eligible]
    rankings = {
        **_module_meta(base_evidence, ranking_status, rankings_missing),
        "definition_version": MARKET_OVERVIEW_DEFINITION_VERSION,
        "limit": 10,
        "top_gainers": sorted(ranking_items, key=lambda item: (-float(item["change_percent"]), item["symbol"]))[:10],
        "top_losers": sorted(ranking_items, key=lambda item: (float(item["change_percent"]), item["symbol"]))[:10],
        "turnover_leaders": sorted(
            [item for item in ranking_items if item["amount_cny"] is not None and item["amount_cny"] > 0],
            key=lambda item: (-float(item["amount_cny"]), item["symbol"]),
        )[:10],
        "active_leaders": sorted(
            [item for item in ranking_items if item["turnover_rate_pct"] is not None and item["turnover_rate_pct"] > 0],
            key=lambda item: (-float(item["turnover_rate_pct"]), item["symbol"]),
        )[:10],
    }

    amount_values = [float(fact["amount_cny"]) for fact in eligible if fact["amount_cny"] is not None and fact["amount_cny"] >= 0]
    turnover_values = [float(fact["turnover_rate_pct"]) for fact in eligible if fact["turnover_rate_pct"] is not None and fact["turnover_rate_pct"] >= 0]
    ratio_values = [float(fact["volume_ratio"]) for fact in eligible if fact["volume_ratio"] is not None and fact["volume_ratio"] >= 0]
    activity_missing: list[str] = []
    if not amount_values:
        activity_missing.append("成交额缺失")
    if not turnover_values:
        activity_missing.append("换手率缺失")
    if not ratio_values:
        activity_missing.append("量比缺失")
    activity_status = "ready" if amount_values else "partial" if eligible else "empty"
    activity = {
        **_module_meta(base_evidence, activity_status, activity_missing),
        "definition_version": MARKET_OVERVIEW_DEFINITION_VERSION,
        "total_amount_cny": sum(amount_values) if amount_values else None,
        "average_amount_cny": mean(amount_values) if amount_values else None,
        "amount_unit": "CNY",
        "amount_denominator": "有有效成交额的 eligible 股票",
        "average_turnover_rate_pct": mean(turnover_values) if turnover_values else None,
        "turnover_unit": "%",
        "turnover_denominator": "有有效换手率的 eligible 股票；TuShare daily_basic.turnover_rate",
        "high_turnover_count": sum(1 for value in turnover_values if value >= HIGH_TURNOVER_THRESHOLD_PCT) if turnover_values else None,
        "high_turnover_threshold_pct": HIGH_TURNOVER_THRESHOLD_PCT,
        "average_volume_ratio": mean(ratio_values) if ratio_values else None,
        "volume_ratio_unit": "倍",
        "volume_ratio_denominator": "20日平均成交量",
        "volume_expansion_count": sum(1 for value in ratio_values if value >= VOLUME_RATIO_THRESHOLD) if ratio_values else None,
        "volume_ratio_threshold": VOLUME_RATIO_THRESHOLD,
    }
    pe_values = [float(fact["pe_ttm"]) for fact in eligible if fact.get("pe_ttm") is not None and float(fact["pe_ttm"]) > 0]
    pb_values = [float(fact["pb"]) for fact in eligible if fact.get("pb") is not None and float(fact["pb"]) > 0]
    cap_values = [
        float(fact["total_market_cap_cny"])
        for fact in eligible
        if fact.get("total_market_cap_cny") is not None and float(fact["total_market_cap_cny"]) > 0
    ]
    valuation_missing: list[str] = []
    if not pe_values:
        valuation_missing.append("动态市盈率缺失")
    if not pb_values:
        valuation_missing.append("市净率缺失")
    valuation_status = "ready" if pe_values or pb_values else "empty"
    valuation = {
        **_module_meta(base_evidence, valuation_status, valuation_missing),
        "definition_version": MARKET_OVERVIEW_DEFINITION_VERSION,
        "covered_symbols": max(len(pe_values), len(pb_values)),
        "eligible_symbols": len(eligible),
        "median_pe_ttm": median(pe_values) if pe_values else None,
        "median_pb": median(pb_values) if pb_values else None,
        "total_market_cap_cny": sum(cap_values) if cap_values else None,
        "source": "all_stocks_realtime.pe_dynamic / pb",
    }
    amount = {
        **_module_meta(base_evidence, activity_status, ["成交额缺失"] if not amount_values else []),
        "total_cny": activity["total_amount_cny"],
        "average_cny": activity["average_amount_cny"],
        "unit": "CNY",
        "denominator": activity["amount_denominator"],
    }

    trend = compute_trend_strength(trend_rows)
    trend = {
        **_module_meta(base_evidence, trend["status"], trend.get("missing_inputs", [])),
        **trend,
    }
    indices, index_status, index_missing = _normalize_indices(index_rows, base_evidence)
    index_module = {
        **_module_meta(base_evidence, index_status, index_missing),
        "definition_version": MARKET_OVERVIEW_DEFINITION_VERSION,
        "items": indices,
        "required_count": len(INDEX_SPECS),
        "available_count": len(indices),
        "denominator": "真实指数点位与当日涨跌",
    }

    top_missing = list(dict.fromkeys([
        *[str(item) for item in base_evidence.get("missing_inputs") or []],
        *breadth.get("missing_inputs", []),
        *index_missing,
        *trend.get("missing_inputs", []),
    ]))
    if str(base_evidence.get("status")) in {"error", "stale"}:
        overall_status = str(base_evidence["status"])
    elif not eligible and not indices:
        overall_status = "empty"
    elif index_status != "ready" or trend["status"] in {"blocked", "partial"}:
        overall_status = "partial"
    else:
        overall_status = "ready"
    top_evidence = {
        **_module_meta(base_evidence, overall_status, top_missing),
        "definition_version": MARKET_OVERVIEW_DEFINITION_VERSION,
    }
    activity["amount"] = amount
    activity["turnover"] = {
        "average_rate_pct": activity["average_turnover_rate_pct"],
        "high_count": activity["high_turnover_count"],
        "unit": "%",
        "threshold_pct": HIGH_TURNOVER_THRESHOLD_PCT,
    }
    activity["volume_ratio"] = {
        "average": activity["average_volume_ratio"],
        "expansion_count": activity["volume_expansion_count"],
        "unit": "倍",
        "threshold": VOLUME_RATIO_THRESHOLD,
        "denominator": "20日平均成交量",
    }
    return {
        **top_evidence,
        "evidence": top_evidence,
        "indices": index_module,
        "breadth": breadth,
        "distribution": distribution,
        "trend": trend,
        "activity": activity,
        "valuation": valuation,
        "amount": amount,
        "rankings": rankings,
        "top_gainers": rankings["top_gainers"],
        "top_losers": rankings["top_losers"],
        "turnover_leaders": rankings["turnover_leaders"],
        "active_leaders": rankings["active_leaders"],
    }


def unavailable_market_overview(reason: str) -> dict[str, Any]:
    return build_market_overview(
        ticker_rows=[],
        index_rows=[],
        trend_rows=[],
        evidence={"status": "error", "missing_inputs": [reason], "provider": "PostgreSQL"},
    )
