"""Strategy review dashboard endpoints."""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from app.core.contracts import ok
from app.core.errors import BadRequestError
from app.db.local_db import db_instance as db

router = APIRouter()

WINDOW_HOURS = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}
CLOSE_SIDES = {"sell", "spot_sell", "close_long", "close_short"}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        num = float(value)
        return num if math.isfinite(num) else default
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return default


def _round(value: Any, digits: int = 4) -> float:
    return round(_as_float(value), digits)


def _normal_timeframe(value: Any) -> str:
    raw = str(value or "").strip().lower()
    mapping = {
        "1min": "1m",
        "5min": "5m",
        "15min": "15m",
        "30min": "30m",
        "60m": "1h",
        "1hour": "1h",
        "4hour": "4h",
        "12hour": "12h",
        "1day": "1d",
    }
    return mapping.get(raw, raw)


def _name_timeframe(name: str) -> str:
    match = re.search(r"\[(1M|5M|15M|30M|1H|4H|12H|1D)\]", str(name or "").upper())
    return match.group(1).lower() if match else ""


def _asset_class(strategy: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    market_type = str(cfg.get("market_type") or cfg.get("marketType") or "").lower()
    name = str(strategy.get("name") or "")
    symbols = strategy.get("symbols") if isinstance(strategy.get("symbols"), list) else []
    if market_type in {"swap", "future", "futures", "contract", "perp", "perpetual"}:
        return "contract"
    if name.startswith("[合约]") or any(":USDT" in str(sym).upper() for sym in symbols):
        return "contract"
    return "spot"


def _strategy_type(strategy: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    name = str(strategy.get("name") or "").lower()
    configured = str(cfg.get("strategy_type") or cfg.get("strategyType") or cfg.get("type") or "").lower()
    key = str(cfg.get("strategy_key") or cfg.get("strategyKey") or "").lower()
    text = " ".join([name, configured, key])
    if "martingale" in text or "马丁" in name:
        return "martingale"
    if "[ai]" in name or configured == "ai" or "自主" in name:
        return "ai"
    if "arbitrage" in text or "套利" in name:
        return "arbitrage"
    if "grid" in text or "网格" in name:
        return "grid"
    if "cta" in text or "趋势" in name:
        return "cta"
    if "market_making" in text or "做市" in name:
        return "market_making"
    return "other"


def _strategy_type_label(bucket: str) -> str:
    return {
        "cta": "CTA",
        "martingale": "马丁",
        "ai": "AI",
        "arbitrage": "套利",
        "grid": "网格",
        "market_making": "做市",
    }.get(bucket, "其他")


def _capital_version(strategy: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    for key in ("initial_capital", "initialCapital", "initial_equity", "initialEquity"):
        value = _as_float(cfg.get(key), 0.0)
        if value > 0:
            return f"{int(round(value))}U"
    match = re.search(r"(\d+(?:\.\d+)?)U", str(strategy.get("name") or "").upper())
    if match:
        parsed = _as_float(match.group(1), 0.0)
        if parsed > 0:
            return f"{int(round(parsed))}U"
    return "--"


def _metadata(strategy: Dict[str, Any]) -> Dict[str, str]:
    cfg = strategy.get("config") if isinstance(strategy.get("config"), dict) else {}
    asset = _asset_class(strategy, cfg)
    timeframe = _normal_timeframe(cfg.get("timeframe") or cfg.get("kline_timeframe")) or _name_timeframe(str(strategy.get("name") or "")) or "--"
    type_bucket = _strategy_type(strategy, cfg)
    capital = _capital_version(strategy, cfg)
    asset_label = "合约" if asset == "contract" else "现货"
    timeframe_label = timeframe.upper() if timeframe != "--" else "--"
    type_label = _strategy_type_label(type_bucket)
    return {
        "asset_class": asset,
        "asset_label": asset_label,
        "timeframe": timeframe,
        "timeframe_label": timeframe_label,
        "strategy_type": type_bucket,
        "strategy_type_label": type_label,
        "capital_version": capital,
        "group_key": f"[{asset_label}][{timeframe_label}][{type_label}] · {capital}",
    }


def _is_paper_strategy(strategy: Dict[str, Any]) -> bool:
    cfg = strategy.get("config") if isinstance(strategy.get("config"), dict) else {}
    return _as_bool(cfg.get("is_paper_trading", cfg.get("dry_run", True)), True)


def _is_running_strategy(strategy: Dict[str, Any]) -> bool:
    return str(strategy.get("status") or "").strip().lower() == "running"


def _is_running_paper_strategy(strategy: Dict[str, Any]) -> bool:
    return _is_running_strategy(strategy) and _is_paper_strategy(strategy)


def _max_drawdown_pct(equities: List[float]) -> float:
    peak = 0.0
    drawdown = 0.0
    for value in equities:
        if value <= 0:
            continue
        peak = max(peak, value)
        if peak > 0:
            drawdown = max(drawdown, (peak - value) / peak * 100)
    return drawdown


def _hour_key(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime("%m-%d %H:00")


def _hour_label(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime("%H")


def _score(return_pct: float, drawdown_pct: float, win_rate: float, profit_factor: float, sample_count: int, trade_count: int) -> int:
    value = 55.0
    value += max(min(return_pct * 1.8, 26), -30)
    value -= min(drawdown_pct * 1.4, 28)
    value += max(min((win_rate - 50) * 0.18, 8), -8)
    if profit_factor > 0:
        value += max(min((profit_factor - 1.0) * 8, 12), -12)
    if sample_count < 3:
        value -= 18
    if trade_count == 0:
        value -= 8
    return int(max(0, min(100, round(value))))


def _verdict(
    score: int,
    return_pct: float,
    drawdown_pct: float,
    strategy_type: str,
    sample_count: int,
    trade_count: int,
) -> str:
    if sample_count < 3 or trade_count < 2:
        return "样本偏少" if score >= 45 else "等待样本"
    if strategy_type == "martingale" and drawdown_pct >= 12:
        return "复查降仓"
    if score >= 75:
        return "继续观察"
    if score >= 60:
        return "稳健低频"
    if score >= 45:
        return "样本偏少"
    if return_pct < 0 or drawdown_pct >= 15:
        return "暂停复查"
    return "复查降仓"


def _tags(item: Dict[str, Any]) -> List[str]:
    tags: List[str] = []
    low_sample = item["sample_count"] < 3 or item["trade_count"] < 2
    if low_sample:
        tags.append("样本不足")
    if item["return_pct"] > 0 and item["max_drawdown_pct"] <= 6 and item["score"] >= 70:
        tags.append("稳健盈利")
    if item["return_pct"] > 8 and item["max_drawdown_pct"] > 10:
        tags.append("高收益高回撤")
    if item["return_pct"] < 0:
        tags.append("权益回落" if low_sample else "持续失血")
    if item["win_rate"] >= 65 and item["profit_factor"] < 1:
        tags.append("胜率高但赔率差")
    if item["strategy_type"] == "martingale" and item["max_drawdown_pct"] >= 8:
        tags.append("马丁回撤风险")
    if not tags:
        tags.append("待继续观察")
    return tags


def _tone(value: float) -> str:
    if value > 0.2:
        return "positive"
    if value < -0.2:
        return "negative"
    return "flat"


def _latest_sample_timestamp(strategy_ids: List[int]) -> Optional[int]:
    if not strategy_ids:
        return None
    conn = db.get_connection()
    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in strategy_ids)
    cursor.execute(
        f"""
        SELECT MAX(timestamp) AS latest
        FROM strategy_equity_samples
        WHERE equity > 0 AND strategy_id IN ({placeholders})
        """,
        [int(strategy_id) for strategy_id in strategy_ids],
    )
    row = cursor.fetchone()
    conn.close()
    if not row or row["latest"] is None:
        return None
    return int(row["latest"])


def _build_strategy_items(strategies: List[Dict[str, Any]], samples: List[Dict[str, Any]], trades: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    strategy_by_id = {int(item["id"]): item for item in strategies if _is_running_paper_strategy(item)}
    samples_by_id: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        sid = int(sample["strategy_id"])
        if sid in strategy_by_id:
            samples_by_id[sid].append(sample)

    items: List[Dict[str, Any]] = []
    for sid, strategy in strategy_by_id.items():
        seq = samples_by_id.get(sid, [])
        if not seq:
            continue
        equities = [_as_float(row.get("equity"), 0.0) for row in seq]
        first_equity = next((value for value in equities if value > 0), 0.0)
        last_equity = next((value for value in reversed(equities) if value > 0), 0.0)
        return_pct = ((last_equity - first_equity) / first_equity * 100) if first_equity > 0 else 0.0
        drawdown = _max_drawdown_pct(equities)
        meta = _metadata(strategy)
        trade = trades.get(sid, {})
        win_rate = _as_float(trade.get("win_rate"), 0.0)
        profit_factor = _as_float(trade.get("profit_factor"), 0.0)
        trade_count = int(trade.get("total_trades") or 0)
        score = _score(return_pct, drawdown, win_rate, profit_factor, len(seq), trade_count)

        hourly: List[Dict[str, Any]] = []
        for prev, cur in zip(seq, seq[1:]):
            prev_equity = _as_float(prev.get("equity"), 0.0)
            cur_equity = _as_float(cur.get("equity"), 0.0)
            pct = ((cur_equity - prev_equity) / prev_equity * 100) if prev_equity > 0 else 0.0
            ts = int(cur["timestamp"])
            hourly.append({"hour": _hour_label(ts), "key": _hour_key(ts), "return_pct": pct, "tone": _tone(pct)})

        item = {
            "strategy_id": sid,
            "name": strategy.get("name") or f"策略 #{sid}",
            **meta,
            "sample_count": len(seq),
            "first_equity": first_equity,
            "last_equity": last_equity,
            "return_pct": return_pct,
            "max_drawdown_pct": drawdown,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "trade_count": trade_count,
            "score": score,
            "hourly": hourly,
        }
        item["verdict"] = _verdict(score, return_pct, drawdown, item["strategy_type"], len(seq), trade_count)
        item["tags"] = _tags(item)
        items.append(item)
    return items


def _group_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[item["group_key"]].append(item)

    def pick_member(member: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "strategy_id": member["strategy_id"],
            "name": member["name"],
            "score": member["score"],
            "return_pct": _round(member["return_pct"]),
            "max_drawdown_pct": _round(member["max_drawdown_pct"]),
            "win_rate": _round(member["win_rate"]),
            "profit_factor": _round(member["profit_factor"]),
            "trade_count": member["trade_count"],
            "sample_count": member["sample_count"],
            "tags": member["tags"],
            "verdict": member["verdict"],
        }

    rows: List[Dict[str, Any]] = []
    for key, members in grouped.items():
        return_pct = sum(member["return_pct"] for member in members) / len(members)
        drawdown = max(member["max_drawdown_pct"] for member in members)
        win_rate = sum(member["win_rate"] for member in members) / len(members)
        profit_factor_values = [member["profit_factor"] for member in members if member["profit_factor"] > 0]
        profit_factor = sum(profit_factor_values) / len(profit_factor_values) if profit_factor_values else 0.0
        score = int(round(sum(member["score"] for member in members) / len(members)))
        trade_count = sum(member["trade_count"] for member in members)
        sample_count = sum(member["sample_count"] for member in members)
        verdict = _verdict(score, return_pct, drawdown, members[0]["strategy_type"], sample_count, trade_count)
        rows.append(
            {
                "group_key": key,
                "asset_class": members[0]["asset_class"],
                "timeframe": members[0]["timeframe"],
                "strategy_type": members[0]["strategy_type"],
                "capital_version": members[0]["capital_version"],
                "strategy_count": len(members),
                "sample_strategy_count": sum(1 for member in members if member["sample_count"] >= 2),
                "return_pct": _round(return_pct),
                "max_drawdown_pct": _round(drawdown),
                "win_rate": _round(win_rate),
                "profit_factor": _round(profit_factor),
                "trade_count": trade_count,
                "score": score,
                "verdict": verdict,
                "strategies": [
                    pick_member(member)
                    for member in sorted(members, key=lambda item: (-item["score"], -item["return_pct"], item["name"]))
                ],
            }
        )
    return sorted(rows, key=lambda row: (-row["score"], row["group_key"]))


def _heatmap(groups: List[Dict[str, Any]], items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_group: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_group[item["group_key"]].append(item)

    rows: List[Dict[str, Any]] = []
    for group in groups[:8]:
        buckets: Dict[str, List[float]] = defaultdict(list)
        labels: Dict[str, str] = {}
        for item in by_group.get(group["group_key"], []):
            for point in item["hourly"]:
                buckets[point["key"]].append(point["return_pct"])
                labels[point["key"]] = point["hour"]
        row_buckets = []
        for key in sorted(buckets):
            avg = sum(buckets[key]) / len(buckets[key])
            row_buckets.append({"hour": labels[key], "return_pct": _round(avg), "tone": _tone(avg)})
        rows.append({"group_key": group["group_key"], "label": group["group_key"].replace(" · ", " "), "buckets": row_buckets})
    return rows


def _tag_summary(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = defaultdict(int)
    for item in items:
        for tag in item["tags"]:
            counts[tag] += 1
    order = ["稳健盈利", "高收益高回撤", "持续失血", "权益回落", "交易过少", "胜率高但赔率差", "样本不足", "马丁回撤风险", "待继续观察"]
    return [{"label": label, "count": counts[label]} for label in order if counts.get(label)]


def _overview(
    window: str,
    bucket: str,
    items: List[Dict[str, Any]],
    latest_ts: Optional[int],
    total_strategy_count: Optional[int] = None,
) -> Dict[str, Any]:
    returns = [item["return_pct"] for item in items]
    sample_count = sum(1 for item in items if item["sample_count"] >= 2)
    strategy_count = int(total_strategy_count if total_strategy_count is not None else len(items))
    observe_count = sum(1 for item in items if item["score"] >= 75)
    review_count = sum(
        1
        for item in items
        if item["score"] < 55
        or "持续失血" in item["tags"]
        or "权益回落" in item["tags"]
        or "马丁回撤风险" in item["tags"]
    )
    initial_total = sum(item["first_equity"] for item in items)
    latest_total = sum(item["last_equity"] for item in items)
    overall_return = ((latest_total - initial_total) / initial_total * 100) if initial_total > 0 else 0.0
    return {
        "review_window": window,
        "bucket": bucket,
        "updated_at": datetime.fromtimestamp(latest_ts / 1000, tz=timezone.utc).isoformat() if latest_ts else None,
        "strategy_count": strategy_count,
        "sample_strategy_count": sample_count,
        "overall_return_pct": _round(overall_return),
        "median_return_pct": _round(median(returns) if returns else 0.0),
        "max_drawdown_pct": _round(max((item["max_drawdown_pct"] for item in items), default=0.0)),
        "observe_count": observe_count,
        "review_count": review_count,
        "sample_health_pct": _round((sample_count / strategy_count * 100) if strategy_count else 0.0, 2),
    }


def _leaderboard(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    def pick(item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "strategy_id": item["strategy_id"],
            "name": item["name"],
            "group_key": item["group_key"],
            "score": item["score"],
            "return_pct": _round(item["return_pct"]),
            "max_drawdown_pct": _round(item["max_drawdown_pct"]),
            "win_rate": _round(item["win_rate"]),
            "profit_factor": _round(item["profit_factor"]),
            "trade_count": item["trade_count"],
            "tags": item["tags"],
            "verdict": item["verdict"],
        }

    observe_candidates = [
        item
        for item in items
        if item["score"] >= 60
        and "持续失血" not in item["tags"]
        and "权益回落" not in item["tags"]
        and "马丁回撤风险" not in item["tags"]
    ]
    review_candidates = [
        item
        for item in items
        if item["score"] < 55
        or "持续失血" in item["tags"]
        or "权益回落" in item["tags"]
        or "马丁回撤风险" in item["tags"]
    ]
    observe = sorted(observe_candidates, key=lambda item: (-item["score"], -item["return_pct"], item["max_drawdown_pct"]))[:5]
    review = sorted(review_candidates, key=lambda item: (item["score"], item["return_pct"], -item["max_drawdown_pct"]))[:5]
    return {"observe": [pick(item) for item in observe], "review": [pick(item) for item in review]}


def _next_actions(tags: List[Dict[str, Any]], groups: List[Dict[str, Any]]) -> List[str]:
    actions: List[str] = []
    risky = next((group for group in groups if group["strategy_type"] == "martingale" and group["max_drawdown_pct"] >= 8), None)
    if risky:
        actions.append(f"优先复核 {risky['group_key']}，检查补仓层数、单笔名义和回撤保护。")
    low_sample = next((tag for tag in tags if tag["label"] == "样本不足"), None)
    if low_sample:
        actions.append(f"{low_sample['count']} 个策略样本不足，建议等成交或权益采样满 20 个小时桶后再定级。")
    strong = next((group for group in groups if group["score"] >= 75), None)
    if strong:
        actions.append(f"保留 {strong['group_key']} 观察，继续积累跨行情样本。")
    return actions or ["暂无明确复查动作；继续按小时积累模拟盘样本。"]


@router.get("/summary")
async def review_summary(
    window: str = Query("24h", description="复盘窗口：24h / 7d / 30d"),
    bucket: str = Query("1h", description="聚合粒度：当前只支持 1h"),
):
    normalized_window = str(window or "24h").lower()
    normalized_bucket = str(bucket or "1h").lower()
    if normalized_window not in WINDOW_HOURS:
        raise BadRequestError("window must be one of 24h, 7d, 30d")
    if normalized_bucket != "1h":
        raise BadRequestError("bucket must be 1h")

    strategies = db.get_strategies()
    running_paper_strategies = [item for item in strategies if _is_running_paper_strategy(item)]
    running_paper_ids = [int(item["id"]) for item in running_paper_strategies]
    paper_strategy_count = len(running_paper_strategies)
    latest_ts = _latest_sample_timestamp(running_paper_ids)
    if latest_ts is None:
        return ok(
            {
                "overview": _overview(normalized_window, normalized_bucket, [], None, paper_strategy_count),
                "groups": [],
                "leaderboard": {"observe": [], "review": []},
                "heatmap": [],
                "tags": [],
                "next_actions": ["暂无运行中模拟盘权益采样；启动策略后复盘中心会自动聚合。"],
            }
        )

    since_ts = latest_ts - WINDOW_HOURS[normalized_window] * 60 * 60 * 1000
    samples = db.get_all_strategy_equity_samples_since(since_ts)
    trades = db.get_strategy_trade_counts_since(since_ts)
    items = _build_strategy_items(running_paper_strategies, samples, trades)
    groups = _group_items(items)
    tags = _tag_summary(items)
    return ok(
        {
            "overview": _overview(normalized_window, normalized_bucket, items, latest_ts, paper_strategy_count),
            "groups": groups,
            "leaderboard": _leaderboard(items),
            "heatmap": _heatmap(groups, items),
            "tags": tags,
            "next_actions": _next_actions(tags, groups),
        }
    )
