"""A-share review summary with explicit sample-health gates."""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any

from fastapi import APIRouter, Query

from app.core.contracts import ok
from app.domain.backtest import backtest_domain_service


router = APIRouter()

WINDOW_GATES = {
    "24h": {"min_trading_days": 2, "min_equity_points": 2, "min_closed_trades": 1},
    "7d": {"min_trading_days": 5, "min_equity_points": 5, "min_closed_trades": 3},
    "30d": {"min_trading_days": 20, "min_equity_points": 20, "min_closed_trades": 10},
}


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _health(run: dict[str, Any], gates: dict[str, int]) -> dict[str, Any]:
    equity_points = int(_number(run.get("sample_days")) or 0)
    trading_days = equity_points
    closed_trades = int(_number(run.get("closed_trade_count")) or 0)
    watermark_ready = bool(
        run.get("start_date")
        and run.get("end_date")
        and run.get("timeframe")
        and run.get("data_quality_status") not in {"invalidated", "warning"}
    )
    components = {
        "trading_days": {"actual": trading_days, "minimum": gates["min_trading_days"]},
        "equity_points": {"actual": equity_points, "minimum": gates["min_equity_points"]},
        "closed_trades": {"actual": closed_trades, "minimum": gates["min_closed_trades"]},
        "data_watermark": {"actual": int(watermark_ready), "minimum": 1},
    }
    ratios = [min(1.0, item["actual"] / item["minimum"]) for item in components.values()]
    missing = [key for key, item in components.items() if item["actual"] < item["minimum"]]
    return {
        "status": "eligible" if not missing and run.get("metric_status") == "eligible" else "insufficient_sample",
        "health_pct": round(sum(ratios) / len(ratios) * 100, 1),
        "missing_ratio_pct": round(len(missing) / len(components) * 100, 1),
        "components": components,
        "missing": missing,
    }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


@router.get("/summary")
async def review_summary(
    window: str = Query("24h", pattern="^(24h|7d|30d)$"),
    bucket: str = Query("1h", pattern="^1h$"),
):
    gates = WINDOW_GATES.get(str(window), WINDOW_GATES["24h"])
    runs = await backtest_domain_service.list_results(
        limit=100,
        offset=0,
        query="",
        sort_by="created",
        sort_dir="desc",
    )
    completed = [run for run in runs if run.get("status") == "completed"]
    strategy_rows: list[dict[str, Any]] = []
    for run in completed:
        health = _health(run, gates)
        eligible = health["status"] == "eligible"
        ret = _number(run.get("total_return")) if eligible else None
        drawdown = _number(run.get("max_drawdown")) if eligible else None
        score = max(0.0, min(100.0, 50 + ret - drawdown)) if ret is not None and drawdown is not None else None
        verdict = "观察" if score is not None and score >= 55 else "复审" if score is not None else "样本不足/不可判定"
        strategy_rows.append({
            "strategy_id": int(run.get("strategy_id") or 0),
            "name": run.get("strategy_name") or "A股策略",
            "score": score,
            "return_pct": ret,
            "max_drawdown_pct": drawdown,
            "win_rate": _number(run.get("win_rate")) if eligible else None,
            "profit_factor": _number(run.get("profit_factor")) if eligible else None,
            "trade_count": int(run.get("fill_count") or run.get("total_trades") or 0),
            "closed_trade_count": int(run.get("closed_trade_count") or 0),
            "order_count": run.get("order_count"),
            "sample_count": int(run.get("sample_days") or 0),
            "coverage_start": run.get("start_date"),
            "coverage_end": run.get("end_date"),
            "sample_health_status": health["status"],
            "sample_health_pct": health["health_pct"],
            "missing_ratio_pct": health["missing_ratio_pct"],
            "health_components": health["components"],
            "diagnostics": health["missing"],
            "tags": ["A股", "1D", "样本不足"] if not eligible else ["A股", "1D"],
            "verdict": verdict,
        })

    unique_rows: dict[tuple[int, str], dict[str, Any]] = {}
    for row in strategy_rows:
        unique_rows.setdefault((row["strategy_id"], str(row["name"])), row)
    strategy_rows = list(unique_rows.values())
    eligible_rows = [row for row in strategy_rows if row["sample_health_status"] == "eligible"]
    insufficient_rows = [row for row in strategy_rows if row["sample_health_status"] != "eligible"]
    returns = [row["return_pct"] for row in eligible_rows if row["return_pct"] is not None]
    drawdowns = [row["max_drawdown_pct"] for row in eligible_rows if row["max_drawdown_pct"] is not None]
    observe = sorted([row for row in eligible_rows if row["verdict"] == "观察"], key=lambda row: row["score"], reverse=True)[:20]
    review = sorted([row for row in eligible_rows if row["verdict"] == "复审"], key=lambda row: row["score"])[:20]
    scores = [row["score"] for row in eligible_rows if row["score"] is not None]
    coverage_starts = [str(row["coverage_start"]) for row in strategy_rows if row["coverage_start"]]
    coverage_ends = [str(row["coverage_end"]) for row in strategy_rows if row["coverage_end"]]
    health_values = [float(row["sample_health_pct"]) for row in strategy_rows]
    equity_points = sum(int(row["sample_count"]) for row in strategy_rows)
    closed_trades = sum(int(row["closed_trade_count"]) for row in strategy_rows)
    fill_count = sum(int(row["trade_count"]) for row in strategy_rows)
    diagnostics: list[str] = []
    if not strategy_rows:
        diagnostics.append("当前窗口没有可复盘的已完成回测")
    if equity_points == 0:
        diagnostics.append("无权益采样点，无法计算权益变化或风险")
    if closed_trades == 0 and strategy_rows:
        diagnostics.append("闭合交易为 0，胜率、盈亏比和策略评分不可判定")
    equity_gap_count = sum("equity_points" in row["diagnostics"] for row in insufficient_rows)
    closed_gap_count = sum("closed_trades" in row["diagnostics"] for row in insufficient_rows)
    if equity_gap_count:
        diagnostics.append(f"{equity_gap_count} 个策略未达到当前窗口最低权益采样点")
    if closed_gap_count:
        diagnostics.append(f"{closed_gap_count} 个策略未达到当前窗口最低闭合交易数")
    diagnostics.append("小时权益桶为 0：当前证据为日线 backtest_daily_equity，不能生成 1H 热力图")

    group = {
        "group_key": "ashare:stock:1d",
        "asset_class": "stock",
        "timeframe": "1d",
        "strategy_type": "mixed",
        "capital_version": "CNY",
        "strategy_count": len(strategy_rows),
        "sample_strategy_count": len(eligible_rows),
        "return_pct": _mean(returns),
        "max_drawdown_pct": max(drawdowns) if drawdowns else None,
        "win_rate": _mean([row["win_rate"] for row in eligible_rows if row["win_rate"] is not None]),
        "profit_factor": _mean([row["profit_factor"] for row in eligible_rows if row["profit_factor"] is not None]),
        "trade_count": fill_count,
        "closed_trade_count": closed_trades,
        "score": _mean(scores),
        "verdict": "A股历史回测证据" if eligible_rows else "样本不足/不可判定",
        "strategies": strategy_rows[:30],
    }
    return ok({
        "overview": {
            "review_window": window,
            "bucket": bucket,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "strategy_count": len(strategy_rows),
            "sample_strategy_count": len(eligible_rows),
            "insufficient_strategy_count": len(insufficient_rows),
            "overall_return_pct": _mean(returns),
            "median_return_pct": median(returns) if returns else None,
            "max_drawdown_pct": max(drawdowns) if drawdowns else None,
            "observe_count": len(observe),
            "review_count": len(review),
            "sample_health_pct": round(_mean(health_values) or 0, 1),
            "sample_health_status": (
                "healthy" if strategy_rows and not insufficient_rows
                else "mixed" if eligible_rows and insufficient_rows
                else "insufficient_sample"
            ),
            "health_denominator": {**gates, "component_count": 4},
            "coverage_start": min(coverage_starts) if coverage_starts else None,
            "coverage_end": max(coverage_ends) if coverage_ends else None,
            "equity_sample_count": equity_points,
            "closed_trade_count": closed_trades,
            "fill_count": fill_count,
        },
        "groups": [group] if strategy_rows else [],
        "leaderboard": {
            "observe": [{**row, "group_key": "ashare:stock:1d"} for row in observe],
            "review": [{**row, "group_key": "ashare:stock:1d"} for row in review],
            "insufficient": [{**row, "group_key": "ashare:stock:1d"} for row in insufficient_rows[:20]],
        },
        "heatmap": [],
        "tags": [
            {"label": "A股", "count": len(strategy_rows)},
            {"label": "1D", "count": len(strategy_rows)},
            {"label": "样本不足", "count": len(insufficient_rows)},
        ],
        "diagnostics": diagnostics,
        "next_actions": (
            [
                f"补齐至少 {gates['min_trading_days']} 个交易日和 {gates['min_equity_points']} 个权益点",
                f"积累至少 {gates['min_closed_trades']} 笔闭合交易后再进入好坏榜",
            ]
            if insufficient_rows else
            ["优先复审高回撤策略", "只将通过完整门禁的回测候选晋级 Paper"]
        ),
    })
