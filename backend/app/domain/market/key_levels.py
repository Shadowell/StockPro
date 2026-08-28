"""个股关键价位计算 —— 纯函数模块，无 IO / 无存储。

11 类关键价位的设计移植自开源项目 tick-stock-panel
(``backend/app/indicators/levels.py``，MIT) 的纯函数口径，按 StockPro 现有
numpy 指标库（``app/services/indicators.py``）重写：

- ``sr`` 成交密集区（筹码分布，换手率衰减模型；无换手率时退化为量堆积）
- ``pivot`` 经典枢轴点 P/R1-R3/S1-S3
- ``extreme`` 60/250 日极值 + 近期 swing 高低点
- ``boll`` 布林上中下轨
- ``keltner_s/m/l`` MA20±2ATR / MA60±2.5ATR / MA120±3ATR
- ``atr_stop`` close±1.5/2 ATR 波动通道
- ``gap`` 近期未回补跳空缺口
- ``fib`` 斐波那契回撤（自动判断波段方向）
- ``round`` 整数关口（价格量级自适应步长）

输入为已按日期升序排列的日线行列表（字段与 ``get_klines_with_status("1d")``
的 items 一致，可选 ``turnover_rate``），输出为可直接序列化的分组价位点。
停牌/坏 bar（open、high 同时 <=0 或 OHLC 非有限值）在入口过滤，
不污染均线与 ATR。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from app.services.indicators import ATR, BBANDS, SMA

LEVEL_TYPES: Dict[str, str] = {
    "sr": "压力支撑",
    "pivot": "枢轴点",
    "extreme": "前高前低",
    "boll": "布林带",
    "keltner_s": "Keltner短期",
    "keltner_m": "Keltner中期",
    "keltner_l": "Keltner长期",
    "atr_stop": "ATR波动通道",
    "gap": "缺口位",
    "fib": "斐波那契",
    "round": "整数关口",
}

MIN_ROWS = 5


def _ok(value: Any) -> bool:
    """数值有效（非空 / 非 NaN / 非 Inf / 正数）。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _side(level: float, close: float) -> str:
    if level > close * 1.001:
        return "resistance"
    if level < close * 0.999:
        return "support"
    return "neutral"


def _aggregate_levels(values: List[float], tol: float) -> List[float]:
    """相近价位聚合（±tol），返回去重后的代表值（保留更近期的）。"""
    if not values:
        return []
    values = sorted(values)
    out: List[float] = [values[0]]
    for value in values[1:]:
        if abs(value - out[-1]) / out[-1] <= tol:
            out[-1] = value
        else:
            out.append(value)
    return out


def _filter_rows(rows: Sequence[dict]) -> List[dict]:
    """过滤停牌与坏 bar：OHLC 非有限值或 open/high 同时 <=0 的行不参与计算。"""
    clean: List[dict] = []
    for row in rows:
        try:
            open_ = float(row.get("open"))
            high = float(row.get("high"))
            low = float(row.get("low"))
            close = float(row.get("close"))
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in (open_, high, low, close)):
            continue
        if open_ <= 0 and high <= 0:
            continue
        clean.append(row)
    return clean


def _support_resistance(
    high: np.ndarray,
    low: np.ndarray,
    volume: np.ndarray,
    turnover_rate: Optional[np.ndarray],
    close: float,
    bins: int = 40,
) -> List[dict]:
    """筹码分布（换手率衰减模型）—— A 股支撑/压力位口径。

    逐日迭代：当日收盘后各价位筹码 = 前一日筹码 × (1 - 当日换手率)
    + 当日新增成交（按 high~low 区间分摊到价位桶）。无换手率时退化为
    纯量堆积（等价海外 Volume Profile 的无衰减口径），调用方需在 meta
    标注 ``turnover_source``。输出 POC（strong）+ 至多 2 个高密集区（medium）。
    """
    n = len(high)
    if n < 20:
        return []
    hi = float(high.max())
    lo = float(low.min())
    if not (hi > lo > 0):
        return []

    step = (hi - lo) / bins
    edges = [lo + i * step for i in range(bins + 1)]
    chips = [0.0] * bins
    for i in range(n):
        if turnover_rate is not None:
            turnover = float(turnover_rate[i]) if math.isfinite(turnover_rate[i]) else 0.0
            decay_ratio = 1.0 - max(0.0, min(turnover, 100.0)) / 100.0
            if decay_ratio < 1.0:
                for k in range(bins):
                    chips[k] *= decay_ratio
        vol = float(volume[i]) if math.isfinite(volume[i]) else 0.0
        if vol > 0:
            k_low = min(int((low[i] - lo) / step), bins - 1)
            k_high = min(int((high[i] - lo) / step), bins - 1)
            if k_low > k_high:
                k_low, k_high = k_high, k_low
            k_low = max(k_low, 0)
            if k_high < 0 or k_low >= bins:
                continue
            share = vol / (k_high - k_low + 1)
            for k in range(k_low, k_high + 1):
                chips[k] += share

    occupied = [k for k in range(bins) if chips[k] > 0]
    if not occupied:
        return []
    values = [chips[k] for k in occupied]
    mean_value = sum(values) / len(values)

    def bin_mid(bin_id: int) -> float:
        return (edges[bin_id] + edges[bin_id + 1]) / 2

    out: List[dict] = []
    poc_pos = max(range(len(values)), key=lambda idx: values[idx])
    poc_mid = bin_mid(occupied[poc_pos])
    out.append({
        "value": round(poc_mid, 2), "label": "成交密集区(POC)",
        "type": "sr", "side": _side(poc_mid, close), "strength": "strong",
    })
    candidates = [
        (idx, value) for idx, value in enumerate(values)
        if value > mean_value and idx != poc_pos
    ]
    candidates.sort(key=lambda item: item[1], reverse=True)
    for idx, _value in candidates[:2]:
        mid = bin_mid(occupied[idx])
        out.append({
            "value": round(mid, 2), "label": "成交密集区",
            "type": "sr", "side": _side(mid, close), "strength": "medium",
        })
    return out


def _pivot_points(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> List[dict]:
    """经典 Pivot：P=(H+L+C)/3，基于最后一根 K（上一交易日）。"""
    if len(close) == 0:
        return []
    h, l, c = float(high[-1]), float(low[-1]), float(close[-1])
    if not (_ok(h) and _ok(l) and _ok(c)):
        return []
    p = (h + l + c) / 3
    points = [
        (p, "枢轴位 P", "neutral", "strong", 0),
        (2 * p - l, "压力位 R1", "resistance", "medium", 1),
        (p + (h - l), "压力位 R2", "resistance", "medium", 2),
        (h + 2 * (p - l), "压力位 R3", "resistance", "weak", 3),
        (2 * p - h, "支撑位 S1", "support", "medium", 1),
        (p - (h - l), "支撑位 S2", "support", "medium", 2),
        (l - 2 * (h - p), "支撑位 S3", "support", "weak", 3),
    ]
    return [
        {
            "value": round(value, 2), "label": label, "type": "pivot",
            "side": side, "strength": strength, "rank": rank,
        }
        for value, label, side, strength, rank in points
        if value > 0
    ]


def _extreme_levels(
    high: np.ndarray, low: np.ndarray, close: np.ndarray,
) -> List[dict]:
    """60/250 日极值 + 近期 swing 高低点（每侧取距当前价最近的 2 个）。"""
    n = len(close)
    if n == 0:
        return []
    current = float(close[-1])
    out: List[dict] = []
    for window in (60, 250):
        if n < window:
            continue
        tail_high = float(high[-window:].max())
        tail_low = float(low[-window:].min())
        if _ok(tail_high):
            out.append({
                "value": round(tail_high, 2), "label": f"{window}日新高",
                "type": "extreme", "side": "resistance", "strength": "strong",
            })
        if _ok(tail_low):
            out.append({
                "value": round(tail_low, 2), "label": f"{window}日新低",
                "type": "extreme", "side": "support", "strength": "strong",
            })

    win = 5
    if n > win * 2:
        swing_highs: List[float] = []
        swing_lows: List[float] = []
        for i in range(win, n - win):
            if high[i] == high[i - win:i + win + 1].max():
                swing_highs.append(float(high[i]))
            if low[i] == low[i - win:i + win + 1].min():
                swing_lows.append(float(low[i]))
        agg_highs = [v for v in _aggregate_levels(swing_highs, 0.01) if v > current * 1.001]
        agg_highs.sort(key=lambda v: abs(v - current))
        for value in agg_highs[:2]:
            out.append({
                "value": round(value, 2), "label": "前高",
                "type": "extreme", "side": "resistance", "strength": "medium",
            })
        agg_lows = [v for v in _aggregate_levels(swing_lows, 0.01) if v < current * 0.999]
        agg_lows.sort(key=lambda v: abs(v - current))
        for value in agg_lows[:2]:
            out.append({
                "value": round(value, 2), "label": "前低",
                "type": "extreme", "side": "support", "strength": "medium",
            })
    return out


def _keltner_points(
    label: str, type_key: str, ma_value: Optional[float], atr_value: Optional[float], multiple: float,
) -> List[dict]:
    if ma_value is None or atr_value is None or ma_value <= 0 or atr_value <= 0:
        return []
    upper = ma_value + multiple * atr_value
    lower = ma_value - multiple * atr_value
    side_ref = ma_value
    return [
        {
            "value": round(upper, 2), "label": f"{label}通道上轨",
            "type": type_key, "side": _side(upper, side_ref), "strength": "medium",
        },
        {
            "value": round(lower, 2), "label": f"{label}通道下轨",
            "type": type_key, "side": _side(lower, side_ref), "strength": "medium",
        },
    ]


def _last_value(values: np.ndarray) -> Optional[float]:
    if len(values) == 0:
        return None
    value = float(values[-1])
    return value if math.isfinite(value) and value > 0 else None


def _gap_levels(high: np.ndarray, low: np.ndarray, close: np.ndarray, lookback: int = 120) -> List[dict]:
    """近期未回补跳空缺口。回补判定：后续某根 K 线高低区间完整覆盖缺口真空带。"""
    n = len(high)
    if n < 5:
        return []
    current = float(close[-1])
    start = max(0, n - lookback)
    highs = [float(v) for v in high[start:]]
    lows = [float(v) for v in low[start:]]
    up_gaps: List[tuple[int, float, float]] = []
    down_gaps: List[tuple[int, float, float]] = []
    for i in range(1, len(highs)):
        if not (_ok(highs[i]) and _ok(lows[i]) and _ok(highs[i - 1]) and _ok(lows[i - 1])):
            continue
        if lows[i] > highs[i - 1]:
            up_gaps.append((i, highs[i - 1], lows[i]))
        elif highs[i] < lows[i - 1]:
            down_gaps.append((i, highs[i], lows[i - 1]))

    def unfilled_mids(gaps: List[tuple[int, float, float]]) -> List[float]:
        mids: List[float] = []
        for formed_at, gap_low, gap_high in gaps:
            filled = False
            for j in range(formed_at + 1, len(highs)):
                if lows[j] <= gap_high and highs[j] >= gap_low:
                    filled = True
                    break
            if not filled:
                mids.append((gap_low + gap_high) / 2)
        aggregated = _aggregate_levels(mids, 0.005)
        aggregated.sort(key=lambda v: abs(v - current))
        return aggregated[:3]

    out: List[dict] = []
    for mid in unfilled_mids(up_gaps):
        out.append({
            "value": round(mid, 2), "label": "向上缺口",
            "type": "gap", "side": _side(mid, current), "strength": "medium",
        })
    for mid in unfilled_mids(down_gaps):
        out.append({
            "value": round(mid, 2), "label": "向下缺口",
            "type": "gap", "side": _side(mid, current), "strength": "medium",
        })
    return out


def _fibonacci_levels(high: np.ndarray, low: np.ndarray, close: np.ndarray, window: int = 120) -> List[dict]:
    """基于近期波段方向的斐波那契回撤位（0.236~0.786）。"""
    n = len(close)
    if n < 10:
        return []
    current = float(close[-1])
    tail_high = high[-window:] if n > window else high
    tail_low = low[-window:] if n > window else low
    hi_pos = int(tail_high.argmax())
    lo_pos = int(tail_low.argmin())
    hi_value = float(tail_high[hi_pos])
    lo_value = float(tail_low[lo_pos])
    if not (_ok(hi_value) and _ok(lo_value)) or hi_value <= lo_value:
        return []
    rng = hi_value - lo_value
    up_trend = hi_pos > lo_pos
    out: List[dict] = []
    for ratio in (0.236, 0.382, 0.5, 0.618, 0.786):
        value = hi_value - rng * ratio if up_trend else lo_value + rng * ratio
        out.append({
            "value": round(value, 2), "label": f"Fib {ratio * 100:.1f}%",
            "type": "fib", "side": _side(value, current), "strength": "medium",
        })
    return out


def _round_numbers(close_value: float, pct: float = 0.10, max_count: int = 8) -> List[dict]:
    """当前价附近的整数心理关口，步长按价格量级自适应。"""
    if not _ok(close_value):
        return []
    if close_value < 10:
        step = 0.5
    elif close_value < 20:
        step = 1.0
    elif close_value < 100:
        step = 5.0
    elif close_value < 500:
        step = 10.0
    else:
        step = 50.0
    lo = close_value * (1 - pct)
    hi = close_value * (1 + pct)
    start = (int(lo / step) + (1 if lo % step > 0 else 0)) * step
    candidates: List[float] = []
    value = start
    while value <= hi:
        if value > 0:
            candidates.append(round(value, 2))
        value += step
    candidates.sort(key=lambda v: abs(v - close_value))
    out: List[dict] = []
    for value in candidates[:max_count]:
        if abs(value - close_value) / close_value < 0.01:
            continue
        out.append({
            "value": value, "label": f"整数关口 {value:g}",
            "type": "round", "side": _side(value, close_value), "strength": "weak",
        })
    return out


def compute_key_levels(rows: Sequence[dict]) -> Dict[str, Any]:
    """从日线行列表计算 11 类关键价位。

    行字段：open/high/low/close/volume（必需），可选 turnover_rate（0-100 百分数）。
    返回 ``{"close", "rows_used", "groups"}``；groups 固定包含 LEVEL_TYPES 全部 key。
    """
    groups: Dict[str, List[dict]] = {key: [] for key in LEVEL_TYPES}
    clean = _filter_rows(rows)
    n = len(clean)
    result: Dict[str, Any] = {
        "close": float(clean[-1]["close"]) if n else None,
        "rows_used": n,
        "groups": groups,
    }
    if n < MIN_ROWS:
        return result

    open_ = np.array([float(r["open"]) for r in clean], dtype=float)
    high = np.array([float(r["high"]) for r in clean], dtype=float)
    low = np.array([float(r["low"]) for r in clean], dtype=float)
    close = np.array([float(r["close"]) for r in clean], dtype=float)
    volume = np.array([float(r.get("volume") or 0) for r in clean], dtype=float)
    turnover_values = [r.get("turnover_rate") for r in clean]
    has_turnover = any(
        isinstance(v, (int, float)) and math.isfinite(float(v)) and float(v) > 0
        for v in turnover_values
    )
    turnover = (
        np.array([float(v or 0) for v in turnover_values], dtype=float)
        if has_turnover else None
    )

    current = float(close[-1])
    try:
        ma20_values, ma60_values, ma120_values = SMA(close, 20), SMA(close, 60), SMA(close, 120)
        atr_values = ATR(high, low, close, 14)
        boll_upper, _boll_mid, boll_lower = BBANDS(close, 20, 2.0)
    except Exception:
        return result

    ma20, ma60, ma120 = _last_value(ma20_values), _last_value(ma60_values), _last_value(ma120_values)
    atr14 = _last_value(atr_values)
    boll_up, boll_low = _last_value(boll_upper), _last_value(boll_lower)

    groups["sr"] = _support_resistance(high, low, volume, turnover, current)
    groups["pivot"] = _pivot_points(high, low, close)
    groups["extreme"] = _extreme_levels(high, low, close)
    if boll_up is not None and boll_low is not None and ma20 is not None:
        groups["boll"] = [
            {"value": round(boll_up, 2), "label": "布林上轨", "type": "boll",
             "side": _side(boll_up, current), "strength": "medium"},
            {"value": round(ma20, 2), "label": "布林中轨", "type": "boll",
             "side": _side(ma20, current), "strength": "medium"},
            {"value": round(boll_low, 2), "label": "布林下轨", "type": "boll",
             "side": _side(boll_low, current), "strength": "medium"},
        ]
    groups["keltner_s"] = _keltner_points("短期", "keltner_s", ma20, atr14, 2.0)
    groups["keltner_m"] = _keltner_points("中期", "keltner_m", ma60, atr14, 2.5)
    groups["keltner_l"] = _keltner_points("长期", "keltner_l", ma120, atr14, 3.0)
    if current > 0 and atr14 is not None and atr14 > 0:
        groups["atr_stop"] = [
            {"value": round(current + 2 * atr14, 2), "label": "ATR 上轨(+2)",
             "type": "atr_stop", "side": "resistance", "strength": "medium"},
            {"value": round(current + 1.5 * atr14, 2), "label": "ATR 上轨(+1.5)",
             "type": "atr_stop", "side": "resistance", "strength": "weak"},
            {"value": round(current - 1.5 * atr14, 2), "label": "ATR 下轨(-1.5)",
             "type": "atr_stop", "side": "support", "strength": "weak"},
            {"value": round(current - 2 * atr14, 2), "label": "ATR 下轨(-2)",
             "type": "atr_stop", "side": "support", "strength": "medium"},
        ]
    groups["gap"] = _gap_levels(high, low, close)
    groups["fib"] = _fibonacci_levels(high, low, close)
    groups["round"] = _round_numbers(current)
    result["close"] = current
    return result


def summarize_levels(levels: Dict[str, List[dict]], close: Optional[float]) -> str:
    """生成紧凑的价位摘要文本（用于面板展示与 AI 上下文）。"""
    if not close:
        return "无价位数据"
    parts: List[str] = [f"当前价 {close:.2f}"]
    for key, label in LEVEL_TYPES.items():
        points = levels.get(key) or []
        if not points:
            continue
        ranked = sorted(points, key=lambda p: abs(p["value"] - close))[:2]
        desc = "、".join(f"{p['label']}={p['value']}" for p in ranked)
        parts.append(f"{label}: {desc}")
    return " · ".join(parts)
