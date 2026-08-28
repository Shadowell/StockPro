"""Derive live A-share research modules from already-persisted market facts.

Used when sealed materialization tables (phase / RPS / abnormal) are empty so
the workstation can still show saturated Chinese labels instead of unknown/empty.
GET paths stay read-only: no provider calls and no writes.
"""
from __future__ import annotations

from typing import Any, Mapping

from app.domain.market.research_metrics import (
    ABNORMALITY_DEFINITION_VERSION,
    MARKET_PHASE_DEFINITION_VERSION,
    SECTOR_RPS_DEFINITION_VERSION,
    compute_market_phase,
)


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _index_change(overview: Mapping[str, Any]) -> float | None:
    items = ((overview.get("indices") or {}).get("items") or [])
    preferred = ("000300.SH", "000001.SH", "399001.SZ")
    by_symbol = {str(item.get("symbol") or ""): item for item in items if isinstance(item, dict)}
    for symbol in preferred:
        change = _float((by_symbol.get(symbol) or {}).get("change_percent"))
        if change is not None:
            return change
    for item in items:
        if isinstance(item, dict):
            change = _float(item.get("change_percent"))
            if change is not None:
                return change
    return None


def derive_market_phase(
    overview: Mapping[str, Any],
    limit_ladder: Mapping[str, Any],
    industry: Mapping[str, Any],
) -> dict[str, Any]:
    breadth = overview.get("breadth") or {}
    activity = overview.get("activity") or {}
    pools = (limit_ladder.get("pools") or {}) if isinstance(limit_ladder.get("pools"), dict) else {}
    industries = industry.get("industries") or []
    limit_up = len(pools.get("up") or [])
    failed_limit = len(pools.get("broken") or [])
    limit_down = len(pools.get("down") or [])
    measured = [row for row in industries if isinstance(row, dict) and _float(row.get("change_1d")) is not None]
    sector_diffusion = (
        sum(1 for row in measured if float(row["change_1d"]) > 0) / len(measured) * 100.0
        if measured else None
    )
    volume_ratio = _float(activity.get("average_volume_ratio"))
    trade_date = (
        (overview.get("evidence") or {}).get("trade_date")
        or overview.get("trade_date")
        or limit_ladder.get("pool_trade_date")
        or industry.get("trade_date")
    )
    result = compute_market_phase(
        trade_date=str(trade_date or "")[:10] or "1970-01-01",
        metrics={
            "index_change_pct": _index_change(overview),
            "advance_ratio": _float(breadth.get("advance_ratio_pct")),
            "turnover_change_pct": (volume_ratio - 1.0) * 100.0 if volume_ratio is not None else None,
            "limit_up_count": float(limit_up),
            "failed_limit_count": float(failed_limit),
            "sector_diffusion_pct": sector_diffusion,
            "profit_effect_pct": _float(breadth.get("advance_ratio_pct")),
            "risk_appetite": max(0.0, min(
                100.0,
                50.0 + (limit_up - limit_down) * 0.35 - failed_limit * 0.25,
            )),
        },
        source_snapshot_id=(overview.get("evidence") or {}).get("source_snapshot_id"),
    )
    if result.get("phase") == "unknown":
        result["phase"] = "待计算"
    result["source_lineage"] = {
        "mode": "live_derived",
        "inputs": ["market_overview", "limit_ladder", "industry_analysis"],
    }
    result["definition_version"] = MARKET_PHASE_DEFINITION_VERSION
    return result


def _rank_items(rows: list[dict[str, Any]], score_key: str) -> list[dict[str, Any]]:
    scored = [row for row in rows if _float(row.get(score_key)) is not None]
    scored.sort(key=lambda row: float(row[score_key]), reverse=True)
    total = len(scored)
    for index, row in enumerate(scored, start=1):
        row["rank"] = index
        row["rps_percentile"] = round((total - index + 1) / total * 100.0, 1) if total else None
        row["strength_score"] = round(float(row[score_key]), 2)
    return scored


def derive_industry_rps(industry: Mapping[str, Any], *, limit: int = 1000) -> dict[str, Any]:
    trade_date = industry.get("trade_date")
    items: list[dict[str, Any]] = []
    for row in industry.get("industries") or []:
        if not isinstance(row, dict):
            continue
        leader = row.get("top_member") or {}
        score = _float(row.get("change_20d"))
        if score is None:
            score = _float(row.get("change_5d"))
        if score is None:
            score = _float(row.get("change_1d"))
        if score is None:
            continue
        count = int(row.get("count") or 0)
        gainers = int(row.get("gainers_1d") or 0)
        items.append({
            "trade_date": trade_date,
            "classification_system": "industry",
            "sector_code": row.get("code") or row.get("name"),
            "sector_name": row.get("name") or row.get("code"),
            "strength_score": score,
            "rps_percentile": None,
            "rank": None,
            "rank_change": None,
            "strong_days": None,
            "member_coverage": 1.0 if count else None,
            "leader_symbol": (leader or {}).get("symbol"),
            "status": "ok",
            "missing_inputs": [],
            "return_5d": _float(row.get("change_5d")),
            "return_10d": None,
            "return_20d": _float(row.get("change_20d")),
            "return_60d": None,
            "up_ratio": (gainers / count * 100.0) if count else None,
            "member_count": count,
            "leader_contribution_pct": None,
            "definition_version": SECTOR_RPS_DEFINITION_VERSION,
            "source_lineage": {"mode": "live_derived", "window": "20d_equal_weight"},
        })
    ranked = _rank_items(items, "strength_score")[: max(1, min(int(limit), 1000))]
    return {
        "items": ranked,
        "data_status": "ok" if ranked else "empty",
        "unavailable_reason": None if ranked else "无可用行业涨跌事实",
        "trade_date": trade_date,
        "definition_version": SECTOR_RPS_DEFINITION_VERSION,
    }


def derive_concept_rps(concept: Mapping[str, Any], *, limit: int = 1000) -> dict[str, Any]:
    trade_date = concept.get("trade_date")
    items: list[dict[str, Any]] = []
    for row in concept.get("sectors") or []:
        if not isinstance(row, dict):
            continue
        score = _float(row.get("change_percent"))
        if score is None:
            continue
        up_count = int(row.get("up_count") or 0)
        down_count = int(row.get("down_count") or 0)
        members = up_count + down_count
        items.append({
            "trade_date": trade_date,
            "classification_system": "concept",
            "sector_code": row.get("sector_code") or row.get("sector_name"),
            "sector_name": row.get("sector_name") or row.get("sector_code"),
            "strength_score": score,
            "rps_percentile": None,
            "rank": row.get("rank"),
            "rank_change": None,
            "strong_days": None,
            "member_coverage": 1.0 if members else None,
            "leader_symbol": row.get("leader_stock"),
            "status": "ok",
            "missing_inputs": [],
            "return_5d": None,
            "return_10d": None,
            "return_20d": score,
            "return_60d": None,
            "up_ratio": (up_count / members * 100.0) if members else None,
            "member_count": members or None,
            "leader_contribution_pct": _float(row.get("leader_change")),
            "definition_version": SECTOR_RPS_DEFINITION_VERSION,
            "source_lineage": {"mode": "live_derived", "window": "concept_1d"},
        })
    ranked = _rank_items(items, "strength_score")[: max(1, min(int(limit), 1000))]
    return {
        "items": ranked,
        "data_status": "ok" if ranked else "empty",
        "unavailable_reason": None if ranked else "无可用概念涨跌事实",
        "trade_date": trade_date,
        "definition_version": SECTOR_RPS_DEFINITION_VERSION,
    }


def derive_movers_from_overview(overview: Mapping[str, Any], *, limit: int = 10) -> dict[str, Any]:
    rankings = overview.get("rankings") or {}
    trade_date = (overview.get("evidence") or {}).get("trade_date") or overview.get("trade_date")
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for tag, rows in (
        ("涨幅领先", rankings.get("top_gainers") or []),
        ("跌幅领先", rankings.get("top_losers") or []),
        ("成交活跃", rankings.get("turnover_leaders") or []),
        ("换手活跃", rankings.get("active_leaders") or []),
    ):
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").strip()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            change = _float(row.get("change_percent"))
            closeness = min(1.0, abs(change or 0) / 5.0)
            status = "triggered" if closeness >= 1 else "edge" if closeness >= 0.6 else "watch"
            items.append({
                "symbol": symbol,
                "name": row.get("name"),
                "trade_date": trade_date,
                "return_3d": change,
                "return_10d": None,
                "return_30d": None,
                "tags": [tag],
                "status": "ok",
                "data_status": "ok",
                "abnormal_status": status,
                "max_closeness": closeness,
                "eligible": True,
                "windows": {
                    "3d": {
                        "value_pct": change,
                        "threshold_pct": 5.0,
                        "closeness": closeness,
                        "status": status,
                    },
                },
                "definition_version": ABNORMALITY_DEFINITION_VERSION,
                "source_lineage": {"mode": "live_derived", "from": "market_overview.rankings"},
            })
            if len(items) >= max(1, min(int(limit), 40)):
                break
        if len(items) >= max(1, min(int(limit), 40)):
            break
    return {
        "items": items,
        "data_status": "ok" if items else "empty",
        "unavailable_reason": None if items else "无可用排行事实",
        "observed_count": len(items),
        "eligible_count": len(items),
        "definition_version": ABNORMALITY_DEFINITION_VERSION,
    }


def derive_sentiment_from_ladder(limit_ladder: Mapping[str, Any]) -> dict[str, Any]:
    pools = (limit_ladder.get("pools") or {}) if isinstance(limit_ladder.get("pools"), dict) else {}
    up = len(pools.get("up") or [])
    down = len(pools.get("down") or [])
    broken = len(pools.get("broken") or [])
    has_any = up or down or broken or bool(limit_ladder.get("levels"))
    return {
        "trade_date": limit_ladder.get("pool_trade_date") or limit_ladder.get("ladder_date"),
        "status": "ok" if has_any else "empty",
        "limit_up_count": up,
        "limit_down_count": down,
        "failed_limit_count": broken,
        "highest_streak": max((int(level.get("level") or 0) for level in (limit_ladder.get("levels") or [])), default=None),
        "ladder_width": int(limit_ladder.get("ladder_total") or 0) or None,
        "missing_inputs": [] if has_any else ["涨跌停池为空"],
        "definition_version": "ashare-market-sentiment.v1",
        "source_lineage": {"mode": "live_derived", "from": "limit_ladder"},
    }
