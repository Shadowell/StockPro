"""A-share backtest review adapter for BitPro's original review dashboard."""
from datetime import datetime, timezone
from statistics import median

from fastapi import APIRouter, Query

from app.core.contracts import ok
from app.domain.backtest import backtest_domain_service


router = APIRouter()


@router.get("/summary")
async def review_summary(window: str = Query("24h"), bucket: str = Query("1h")):
    runs = await backtest_domain_service.list_results(limit=100, offset=0, query="", sort_by="created", sort_dir="desc")
    completed = [run for run in runs if run.get("status") == "completed"]
    strategy_rows = []
    for run in completed:
        ret = float(run.get("total_return") or 0); drawdown = float(run.get("max_drawdown") or 0)
        score = max(0.0, min(100.0, 50 + ret - drawdown))
        verdict = "观察" if score >= 55 else "复审"
        strategy_rows.append({"strategy_id": int(run.get("strategy_id") or 0), "name": run.get("strategy_name") or "A股策略", "score": score, "return_pct": ret, "max_drawdown_pct": drawdown, "win_rate": float(run.get("win_rate") or 0), "profit_factor": float(run.get("profit_factor") or 0), "trade_count": int(run.get("total_trades") or 0), "sample_count": 1, "tags": ["A股", "1D"], "verdict": verdict})
    unique_rows = {}
    for row in strategy_rows:
        unique_rows.setdefault((row["strategy_id"], row["name"]), row)
    strategy_rows = list(unique_rows.values())
    returns = [row["return_pct"] for row in strategy_rows]; drawdowns = [row["max_drawdown_pct"] for row in strategy_rows]
    observe = sorted([row for row in strategy_rows if row["verdict"] == "观察"], key=lambda row: row["score"], reverse=True)[:20]
    review = sorted([row for row in strategy_rows if row["verdict"] == "复审"], key=lambda row: row["score"])[:20]
    group = {"group_key": "ashare:stock:1d", "asset_class": "stock", "timeframe": "1d", "strategy_type": "mixed", "capital_version": "CNY", "strategy_count": len(strategy_rows), "sample_strategy_count": len(strategy_rows), "return_pct": sum(returns)/len(returns) if returns else 0, "max_drawdown_pct": max(drawdowns, default=0), "win_rate": sum(row["win_rate"] for row in strategy_rows)/len(strategy_rows) if strategy_rows else 0, "profit_factor": 0, "trade_count": sum(row["trade_count"] for row in strategy_rows), "score": sum(row["score"] for row in strategy_rows)/len(strategy_rows) if strategy_rows else 0, "verdict": "A股历史回测证据", "strategies": strategy_rows[:30]}
    return ok({"overview": {"review_window": window, "bucket": bucket, "updated_at": datetime.now(timezone.utc).isoformat(), "strategy_count": len(strategy_rows), "sample_strategy_count": len(strategy_rows), "overall_return_pct": sum(returns)/len(returns) if returns else 0, "median_return_pct": median(returns) if returns else 0, "max_drawdown_pct": max(drawdowns, default=0), "observe_count": len(observe), "review_count": len(review), "sample_health_pct": 100 if strategy_rows else 0}, "groups": [group] if strategy_rows else [], "leaderboard": {"observe": [{**row, "group_key": "ashare:stock:1d"} for row in observe], "review": [{**row, "group_key": "ashare:stock:1d"} for row in review]}, "heatmap": [], "tags": [{"label": "A股", "count": len(strategy_rows)}, {"label": "1D", "count": len(strategy_rows)}], "next_actions": ["优先复审高回撤策略", "只将通过完整门禁的回测候选晋级 Paper"]})
