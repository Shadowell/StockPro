"""Pure builders for persisted A-share market research metrics."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from statistics import mean
from typing import Any

from app.domain.market.research_metrics import (
    compute_market_phase,
    compute_sector_rps,
    compute_symbol_abnormality,
    valid_price_limit_pair,
)


CN_TZ = timezone(timedelta(hours=8))
MARKET_SENTIMENT_DEFINITION_VERSION = "ashare-market-sentiment.v1"


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _ordered_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: str(row.get("trade_date") or row.get("date") or ""))


def _available_after_close(trade_date: str) -> str:
    day = date.fromisoformat(str(trade_date)[:10])
    return datetime.combine(day, time(17, 30), tzinfo=CN_TZ).isoformat()


def _at_limit(value: Any, limit: Any, *, direction: str) -> bool:
    observed = _number(value)
    boundary = _number(limit)
    if observed is None or boundary is None or boundary <= 0:
        return False
    tolerance = max(0.001, abs(boundary) * 0.00001)
    return observed >= boundary - tolerance if direction == "up" else observed <= boundary + tolerance


def build_market_sentiment(
    *,
    daily_rows: list[dict[str, Any]],
    price_limit_rows: list[dict[str, Any]],
    trade_dates: list[str],
    trade_date: str,
) -> dict[str, Any]:
    """Build the latest limit-price and consecutive-board facts from persisted rows."""
    target = str(trade_date)[:10]
    ordered_dates = sorted({str(item)[:10] for item in trade_dates if str(item).strip()})
    rows_by_key = {
        (str(row.get("symbol") or ""), str(row.get("trade_date") or "")[:10]): row
        for row in daily_rows
        if row.get("symbol") and row.get("trade_date")
    }
    limits_by_key = {
        (str(row.get("symbol") or ""), str(row.get("trade_date") or "")[:10]): row
        for row in price_limit_rows
        if row.get("symbol") and row.get("trade_date")
    }
    target_rows = [row for (symbol, day), row in rows_by_key.items() if day == target and symbol]
    closed_up: set[str] = set()
    closed_down: set[str] = set()
    failed_up: set[str] = set()
    one_word: set[str] = set()
    missing_limits = 0
    for row in target_rows:
        symbol = str(row.get("symbol") or "")
        limits = limits_by_key.get((symbol, target))
        if not limits or not valid_price_limit_pair(limits.get("up_limit"), limits.get("down_limit")):
            missing_limits += 1
            continue
        hit_up = _at_limit(row.get("high"), limits.get("up_limit"), direction="up")
        seal_up = _at_limit(row.get("close"), limits.get("up_limit"), direction="up")
        if seal_up:
            closed_up.add(symbol)
            if all(_at_limit(row.get(field), limits.get("up_limit"), direction="up") for field in ("open", "high", "low", "close")):
                one_word.add(symbol)
        elif hit_up:
            failed_up.add(symbol)
        if _at_limit(row.get("close"), limits.get("down_limit"), direction="down"):
            closed_down.add(symbol)

    streaks: dict[str, int] = {}
    for symbol in closed_up:
        streak = 0
        for day in reversed([item for item in ordered_dates if item <= target]):
            row = rows_by_key.get((symbol, day))
            limits = limits_by_key.get((symbol, day))
            if not row or not limits or not valid_price_limit_pair(limits.get("up_limit"), limits.get("down_limit")) or not _at_limit(row.get("close"), limits.get("up_limit"), direction="up"):
                break
            streak += 1
        streaks[symbol] = streak

    previous_closed_up: set[str] = set()
    previous_dates = [item for item in ordered_dates if item < target]
    previous_target = previous_dates[-1] if previous_dates else None
    if previous_target:
        for (symbol, day), row in rows_by_key.items():
            limits = limits_by_key.get((symbol, day))
            if day == previous_target and limits and valid_price_limit_pair(limits.get("up_limit"), limits.get("down_limit")) and _at_limit(row.get("close"), limits.get("up_limit"), direction="up"):
                previous_closed_up.add(symbol)

    ladder: list[dict[str, Any]] = []
    for height in sorted(set(streaks.values()), reverse=True):
        symbols = [symbol for symbol, streak in streaks.items() if streak == height]
        leader = max(
            symbols,
            key=lambda symbol: float(_number(rows_by_key[(symbol, target)].get("amount")) or 0),
        )
        ladder.append({
            "height": height,
            "count": len(symbols),
            "leader_symbol": leader,
            "symbols": sorted(symbols),
            "amount_cny": sum(float(_number(rows_by_key[(symbol, target)].get("amount")) or 0) for symbol in symbols),
        })

    observed_limits = max(0, len(target_rows) - missing_limits)
    coverage = observed_limits / len(target_rows) if target_rows else 0.0
    missing_inputs = [] if coverage >= 0.8 else ["涨跌停价格覆盖不足 80%"]
    attempts = len(closed_up) + len(failed_up)
    seal_rate = len(closed_up) / attempts * 100.0 if attempts else None
    highest_streak = max(streaks.values(), default=0)
    ladder_width = sum(1 for streak in streaks.values() if streak >= 2)
    promotion_rate = (
        len(previous_closed_up & closed_up) / len(previous_closed_up) * 100.0
        if previous_closed_up else None
    )
    ladder_completeness = (
        len(set(streaks.values())) / highest_streak * 100.0
        if highest_streak > 0 else None
    )
    weak_market_veto = len(closed_down) > len(closed_up) or (seal_rate is not None and seal_rate < 50.0)
    return {
        "trade_date": target,
        "status": "ok" if target_rows and not missing_inputs else "partial",
        "limit_up_count": len(closed_up),
        "limit_down_count": len(closed_down),
        "failed_limit_count": len(failed_up),
        "one_word_limit_count": len(one_word),
        "seal_rate_pct": round(seal_rate, 4) if seal_rate is not None else None,
        "highest_streak": highest_streak,
        "ladder_width": ladder_width,
        "promotion_rate_pct": round(promotion_rate, 4) if promotion_rate is not None else None,
        "ladder_completeness_pct": round(ladder_completeness, 4) if ladder_completeness is not None else None,
        "weak_market_veto": weak_market_veto,
        "ladder": ladder,
        "price_limit_coverage": round(coverage, 6),
        "missing_inputs": missing_inputs,
        "definition_version": MARKET_SENTIMENT_DEFINITION_VERSION,
        "available_at": _available_after_close(target),
        "knowledge_cutoff_at": _available_after_close(target),
        "source_lineage": {"daily": "tushare.daily", "price_limits": "tushare.stk_limit"},
        "orders_created": 0,
        "paper_mutated": False,
    }


def build_market_phase_result(
    *,
    daily_rows: list[dict[str, Any]],
    benchmark_rows: list[dict[str, Any]],
    instruments: list[dict[str, Any]],
    sentiment: dict[str, Any],
    trade_date: str,
) -> dict[str, Any]:
    """Build the six-stage phase only when every market input is observed."""
    target = str(trade_date)[:10]
    target_rows = [row for row in daily_rows if str(row.get("trade_date") or "")[:10] == target]
    dates = sorted({str(row.get("trade_date") or "")[:10] for row in daily_rows if row.get("trade_date")})
    previous_date = dates[dates.index(target) - 1] if target in dates and dates.index(target) > 0 else None
    previous_rows = [row for row in daily_rows if str(row.get("trade_date") or "")[:10] == previous_date]
    benchmark = next((
        row for row in benchmark_rows
        if str(row.get("trade_date") or "")[:10] == target
        and str(row.get("symbol") or row.get("ts_code") or "").upper() == "000300.SH"
    ), None)
    index_change = _number((benchmark or {}).get("change_percent"))
    if index_change is None and benchmark:
        close = _number(benchmark.get("close"))
        previous = _number(benchmark.get("pre_close"))
        if close is not None and previous is not None and previous > 0:
            index_change = (close / previous - 1.0) * 100.0
    valid_changes = [_number(row.get("change_percent")) for row in target_rows]
    valid_changes = [value for value in valid_changes if value is not None]
    advance_ratio = sum(1 for value in valid_changes if value > 0) / len(valid_changes) * 100.0 if valid_changes else None
    target_amount = sum(float(_number(row.get("amount")) or 0) for row in target_rows)
    previous_amount = sum(float(_number(row.get("amount")) or 0) for row in previous_rows)
    turnover_change = (target_amount / previous_amount - 1.0) * 100.0 if previous_amount > 0 else None
    industry_by_symbol = {
        str(row.get("symbol") or ""): str(row.get("industry") or "").strip()
        for row in instruments
        if str(row.get("symbol") or "") and str(row.get("industry") or "").strip()
    }
    industry_changes: dict[str, list[float]] = defaultdict(list)
    for row in target_rows:
        industry = industry_by_symbol.get(str(row.get("symbol") or ""))
        change = _number(row.get("change_percent"))
        if industry and change is not None:
            industry_changes[industry].append(change)
    sector_diffusion = (
        sum(1 for values in industry_changes.values() if mean(values) > 0) / len(industry_changes) * 100.0
        if industry_changes else None
    )
    rows_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in daily_rows:
        rows_by_symbol[str(row.get("symbol") or "")].append(row)
    positive_5d = eligible_5d = 0
    for rows in rows_by_symbol.values():
        ordered = _ordered_rows(rows)
        index = next((idx for idx, row in enumerate(ordered) if str(row.get("trade_date") or "")[:10] == target), None)
        if index is None or index < 5:
            continue
        current = _number(ordered[index].get("close"))
        previous = _number(ordered[index - 5].get("close"))
        if current is None or previous is None or previous <= 0:
            continue
        eligible_5d += 1
        positive_5d += int(current > previous)
    profit_effect = positive_5d / eligible_5d * 100.0 if eligible_5d else None
    if sentiment.get("status") != "ok":
        limit_up = failed_limit = risk_appetite = None
    else:
        limit_up = _number(sentiment.get("limit_up_count"))
        failed_limit = _number(sentiment.get("failed_limit_count"))
        limit_down = float(_number(sentiment.get("limit_down_count")) or 0)
        denominator = max(len(target_rows), 1)
        failed_ratio = float(failed_limit or 0) / max(float(limit_up or 0) + float(failed_limit or 0), 1.0)
        risk_appetite = max(0.0, min(
            100.0,
            50.0 + (float(limit_up or 0) - limit_down) / denominator * 500.0 - failed_ratio * 25.0,
        ))
    result = compute_market_phase(
        trade_date=target,
        metrics={
            "index_change_pct": index_change,
            "advance_ratio": advance_ratio,
            "turnover_change_pct": turnover_change,
            "limit_up_count": limit_up,
            "failed_limit_count": failed_limit,
            "sector_diffusion_pct": sector_diffusion,
            "profit_effect_pct": profit_effect,
            "risk_appetite": risk_appetite,
        },
    )
    if sentiment.get("weak_market_veto") and result.get("phase") in {"主升", "高潮"}:
        result["phase"] = "退潮"
        result["reasons"].append("弱市否决：跌停/炸板结构不支持主升或高潮")
    if sentiment.get("status") != "ok" and "涨跌停价格覆盖不足" not in result["missing_inputs"]:
        result["missing_inputs"].append("涨跌停价格覆盖不足")
    result["source_lineage"] = {
        "daily": "tushare.daily",
        "benchmark": "tushare.index_daily",
        "price_limits": "tushare.stk_limit",
        "industry": "tushare.stock_basic.industry",
    }
    return result


def _sector_memberships(
    instruments: list[dict[str, Any]],
    classification_system: str,
) -> tuple[dict[str, set[str]], dict[str, str]]:
    members: dict[str, set[str]] = defaultdict(set)
    names: dict[str, str] = {}
    for instrument in instruments:
        if str(instrument.get("list_status") or "L").upper() not in {"L", "P"}:
            continue
        symbol = str(instrument.get("symbol") or "")
        if classification_system == "industry":
            raw_values = [instrument.get("industry")]
        else:
            raw = instrument.get("concepts") or []
            raw_values = raw if isinstance(raw, list) else [raw]
        for raw_value in raw_values:
            sector = str(raw_value or "").strip()
            if symbol and sector:
                members[sector].add(symbol)
                names[sector] = sector
    return members, names


def build_sector_rps_history(
    *,
    daily_rows: list[dict[str, Any]],
    price_limit_rows: list[dict[str, Any]],
    instruments: list[dict[str, Any]],
    classification_system: str,
) -> dict[str, list[dict[str, Any]]]:
    """Build auditable 5/10/20/60-day sector rankings from one membership snapshot."""
    if classification_system not in {"industry", "concept"}:
        raise ValueError("classification_system must be industry or concept")
    sector_members, sector_names = _sector_memberships(instruments, classification_system)
    bars_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in daily_rows:
        symbol = str(row.get("symbol") or "")
        if symbol:
            bars_by_symbol[symbol].append(dict(row))
    for symbol in bars_by_symbol:
        bars_by_symbol[symbol] = _ordered_rows(bars_by_symbol[symbol])
    row_index = {
        (symbol, str(row.get("trade_date") or "")[:10]): index
        for symbol, rows in bars_by_symbol.items()
        for index, row in enumerate(rows)
    }
    dates = sorted({str(row.get("trade_date") or "")[:10] for row in daily_rows if row.get("trade_date")})
    limits_by_key = {
        (str(row.get("symbol") or ""), str(row.get("trade_date") or "")[:10]): row
        for row in price_limit_rows
        if row.get("symbol") and row.get("trade_date")
    }
    previous_ranks: dict[str, int] = {}
    strong_streaks: dict[str, int] = defaultdict(int)
    results: list[dict[str, Any]] = []
    for date_index, target in enumerate(dates):
        if date_index < 60:
            continue
        sector_rows: list[dict[str, Any]] = []
        for sector_code, members in sorted(sector_members.items()):
            eligible: list[tuple[str, list[dict[str, Any]], int]] = []
            for symbol in members:
                index = row_index.get((symbol, target))
                if index is not None and index >= 60:
                    eligible.append((symbol, bars_by_symbol[symbol], index))
            coverage = len(eligible) / len(members) if members else 0.0

            def member_return(rows: list[dict[str, Any]], index: int, window: int) -> float | None:
                current = _number(rows[index].get("close"))
                previous = _number(rows[index - window].get("close")) if index >= window else None
                if current is None or previous is None or previous <= 0:
                    return None
                return (current / previous - 1.0) * 100.0

            returns_by_window: dict[int, list[float]] = {window: [] for window in (5, 10, 20, 60)}
            latest_amount = 0.0
            previous_amounts: list[float] = []
            positive = 0
            leader_returns: dict[str, float] = {}
            limit_up_count: int | None = 0 if price_limit_rows else None
            observed_price_limits = 0
            for symbol, rows, index in eligible:
                for window in returns_by_window:
                    value = member_return(rows, index, window)
                    if value is not None:
                        returns_by_window[window].append(value)
                change = _number(rows[index].get("change_percent"))
                if change is not None and change > 0:
                    positive += 1
                latest_amount += float(_number(rows[index].get("amount")) or 0)
                history_amount = [float(_number(item.get("amount")) or 0) for item in rows[max(0, index - 5):index]]
                if history_amount:
                    previous_amounts.append(mean(history_amount))
                return_20d = member_return(rows, index, 20)
                if return_20d is not None:
                    leader_returns[symbol] = return_20d
                if limit_up_count is not None:
                    limits = limits_by_key.get((symbol, target))
                    if limits and valid_price_limit_pair(limits.get("up_limit"), limits.get("down_limit")):
                        observed_price_limits += 1
                        if _at_limit(rows[index].get("close"), limits.get("up_limit"), direction="up"):
                            limit_up_count += 1
            if eligible and observed_price_limits / len(eligible) < 0.8:
                limit_up_count = None
            leader_symbol = max(leader_returns, key=leader_returns.get) if leader_returns else None
            total_abs_return = sum(abs(value) for value in leader_returns.values())
            leader_contribution = (
                abs(leader_returns[leader_symbol]) / total_abs_return * 100.0
                if leader_symbol and total_abs_return > 0 else None
            )
            previous_amount = sum(previous_amounts)
            amount_change = (latest_amount / previous_amount - 1.0) * 100.0 if previous_amount > 0 else None
            sector_rows.append({
                "sector_code": sector_code,
                "sector_name": sector_names[sector_code],
                **{
                    f"return_{window}d": mean(values) if len(values) == len(eligible) and values else None
                    for window, values in returns_by_window.items()
                },
                "amount_change_pct": amount_change,
                "up_ratio": positive / len(eligible) * 100.0 if eligible else None,
                "limit_up_count": limit_up_count,
                "leader_symbol": leader_symbol,
                "leader_contribution_pct": leader_contribution,
                "member_coverage": coverage,
                "member_count": len(members),
            })
        ranked = compute_sector_rps(
            sector_rows,
            trade_date=target,
            classification_system=classification_system,
            previous_ranks=previous_ranks,
        )
        previous_ranks = {
            str(item["sector_code"]): int(item["rank"])
            for item in ranked
            if item.get("rank") is not None
        }
        for item in ranked:
            code = str(item["sector_code"])
            if item.get("rps_percentile") is not None and float(item["rps_percentile"]) >= 80.0:
                strong_streaks[code] += 1
            else:
                strong_streaks[code] = 0
            item["strong_days"] = strong_streaks[code]
        results.extend(ranked)

    latest_date = dates[-1] if dates else None
    membership_source = "tushare.stock_basic.industry" if classification_system == "industry" else "akshare.eastmoney.concept"
    memberships = [
        {
            "trade_date": latest_date,
            "classification_system": classification_system,
            "sector_code": sector_code,
            "sector_name": sector_names[sector_code],
            "symbol": symbol,
            "source": membership_source,
            "membership_bias": "current_membership_applied_to_history",
        }
        for sector_code, members in sorted(sector_members.items())
        for symbol in sorted(members)
    ]
    return {"results": results, "memberships": memberships}


def _industry_bars(
    daily_rows: list[dict[str, Any]],
    industry_by_symbol: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    changes: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in daily_rows:
        symbol = str(row.get("symbol") or "")
        industry = industry_by_symbol.get(symbol)
        trade_date = str(row.get("trade_date") or "")[:10]
        change = _number(row.get("change_percent"))
        if industry and trade_date and change is not None:
            changes[(industry, trade_date)].append(change)

    dates_by_industry: dict[str, list[str]] = defaultdict(list)
    for industry, trade_date in changes:
        dates_by_industry[industry].append(trade_date)

    result: dict[str, list[dict[str, Any]]] = {}
    for industry, observed_dates in dates_by_industry.items():
        level = 100.0
        bars = []
        for trade_date in sorted(set(observed_dates)):
            level *= 1.0 + mean(changes[(industry, trade_date)]) / 100.0
            bars.append({
                "trade_date": trade_date,
                "open": level,
                "high": level,
                "low": level,
                "close": level,
                "amount": 1.0,
            })
        result[industry] = bars
    return result


def build_symbol_abnormal_metrics(
    *,
    daily_rows: list[dict[str, Any]],
    benchmark_rows: list[dict[str, Any]],
    instruments: list[dict[str, Any]],
    trade_date: str,
) -> list[dict[str, Any]]:
    """Build latest-day rows ready for symbol_abnormal_metrics upsert."""
    instrument_by_symbol = {str(row.get("symbol") or ""): row for row in instruments}
    industry_by_symbol = {
        symbol: str(row.get("industry") or "").strip()
        for symbol, row in instrument_by_symbol.items()
        if str(row.get("industry") or "").strip()
    }
    bars_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in daily_rows:
        symbol = str(row.get("symbol") or "")
        if symbol:
            bars_by_symbol[symbol].append(dict(row))
    benchmark = _ordered_rows([
        dict(row)
        for row in benchmark_rows
        if str(row.get("symbol") or row.get("ts_code") or "").upper() == "000300.SH"
    ])
    sector_bars = _industry_bars(daily_rows, industry_by_symbol)

    metrics = []
    for symbol, rows in sorted(bars_by_symbol.items()):
        instrument = instrument_by_symbol.get(symbol, {})
        industry = industry_by_symbol.get(symbol)
        payload = compute_symbol_abnormality(
            _ordered_rows(rows),
            symbol=symbol,
            name=str(instrument.get("name") or "") or None,
            board=str(instrument.get("board") or "") or None,
            trade_date=trade_date,
            benchmark_bars=benchmark or None,
            sector_bars=sector_bars.get(industry or "") or None,
        )
        payload.update({
            "benchmark_code": "000300.SH",
            "sector_code": industry,
            "source_snapshot_id": None,
            "source_lineage": {
                "stock_source": "tushare.daily",
                "benchmark_source": "tushare.index_daily",
                "sector_source": "industry_member_equal_weight",
            },
        })
        metrics.append(payload)
    return metrics
