"""
"真实 K 线 vs AI 预测" 可视化服务
=====================================================================

输出 ECharts JSON 配置（前端 React ECharts 直接消费）。

图表视觉要素：
1. 主图表 — 真实 1m K 线蜡烛图（红涨绿跌）
2. 预测轨迹 — 从最后一根真实 K 线收盘价向右延伸 30 个点
   使用橙色虚线（dashed line）绘制
3. 预测区高亮 — markArea 将未来 30 分钟框出浅蓝色半透明背景，
   标注 "AI 预测区 (h30)"
4. 对比复盘 — 若时间已走过预测期，同时画出"当时预测虚线"和
   "后来实际 K 线"，让用户一眼看出偏差

时间轴对齐规则：
- 预测轨迹第一个点的时间 = last_real_bar_time + 1 minute
- 预测第一个点的数值平滑连接真实 K 线的最后一根收盘价
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def build_prediction_chart(
    real_klines: List[Dict[str, Any]],
    prediction: Dict[str, Any],
    actual_after: Optional[List[Dict[str, Any]]] = None,
    symbol: str = "BTC/USDT",
    timeframe: str = "1m",
) -> Dict[str, Any]:
    """
    构建"真实 K 线 vs AI 预测"的 ECharts 配置。

    Args:
        real_klines: 真实 K 线列表，每个元素包含
                     {timestamp, open, high, low, close, volume}。
                     建议传最近 200-300 根。
        prediction:  KairosPredictor 的预测结果 dict，需包含
                     predicted_prices / predicted_ohlcv / predicted_timestamps /
                     score / direction / current_close / timestamp_ms。
        actual_after: 预测期之后实际发生的 K 线（用于对比复盘），可为空。
        symbol:      交易对名称。
        timeframe:   K 线周期。

    Returns:
        完整的 ECharts option dict，前端 setOption(option) 即可渲染。
    """

    # ======================== 时间轴 ========================
    x_categories: List[str] = []
    date_fmt = "%m-%d %H:%M"

    # 真实 K 线时间
    for k in real_klines:
        ts = k["timestamp"]
        dt = datetime.fromtimestamp(ts / 1000) if ts > 1e12 else datetime.fromtimestamp(ts)
        x_categories.append(dt.strftime(date_fmt))

    # 预测时间（向右延伸）
    pred_timestamps = prediction.get("predicted_timestamps", [])
    pred_x_labels: List[str] = []
    for ts in pred_timestamps:
        dt = datetime.fromtimestamp(ts / 1000) if ts > 1e12 else datetime.fromtimestamp(ts)
        label = dt.strftime(date_fmt)
        pred_x_labels.append(label)
        x_categories.append(label)

    # 如果有对比复盘数据，也加入时间轴
    actual_x_labels: List[str] = []
    if actual_after:
        for k in actual_after:
            ts = k["timestamp"]
            dt = datetime.fromtimestamp(ts / 1000) if ts > 1e12 else datetime.fromtimestamp(ts)
            label = dt.strftime(date_fmt)
            actual_x_labels.append(label)
            if label not in x_categories:
                x_categories.append(label)

    real_count = len(real_klines)

    # ======================== 蜡烛图数据 ========================
    # ECharts candlestick 格式: [open, close, low, high]
    candlestick_data: List[Any] = []
    for k in real_klines:
        candlestick_data.append([
            round(k["open"], 2),
            round(k["close"], 2),
            round(k["low"], 2),
            round(k["high"], 2),
        ])

    # 预测区域的 K 线数据用空值占位
    for _ in pred_timestamps:
        candlestick_data.append("-")

    # ======================== 预测轨迹线 ========================
    predicted_prices = prediction.get("predicted_prices", [])
    current_close = prediction.get("current_close", 0)
    score = prediction.get("score", 0.5)
    direction = prediction.get("direction", "neutral")

    # 构建预测线数据（前面用 None 占位对齐真实 K 线区域）
    pred_line_data: List[Any] = [None] * (real_count - 1)
    # 平滑连接点：最后一根真实 K 线的收盘价
    pred_line_data.append(round(current_close, 2))
    for p in predicted_prices:
        pred_line_data.append(round(p, 2))

    # ======================== 对比复盘线（可选） ========================
    actual_line_data: List[Any] = []
    if actual_after and actual_x_labels:
        actual_line_data = [None] * (real_count - 1)
        actual_line_data.append(round(current_close, 2))
        for k in actual_after:
            actual_line_data.append(round(k["close"], 2))
        # 补齐到与 x_categories 等长
        while len(actual_line_data) < len(x_categories):
            actual_line_data.append(None)

    # ======================== 预测区 markArea ========================
    mark_area_data = []
    if pred_x_labels:
        mark_area_data = [[
            {
                "name": f"AI 预测区 (h{len(predicted_prices)})",
                "xAxis": pred_x_labels[0],
                "itemStyle": {
                    "color": "rgba(100, 149, 237, 0.12)",
                    "borderColor": "rgba(100, 149, 237, 0.4)",
                    "borderWidth": 1,
                    "borderType": "dashed",
                },
                "label": {
                    "show": True,
                    "position": "insideTop",
                    "color": "#6495ED",
                    "fontSize": 12,
                    "fontWeight": "bold",
                },
            },
            {"xAxis": pred_x_labels[-1]},
        ]]

    # ======================== 构建 ECharts option ========================
    # 预测线颜色
    pred_color = "#FF6600"  # 橙色

    # 方向标注
    dir_emoji = {"bullish": "↑ 看涨", "bearish": "↓ 看跌", "neutral": "→ 中性"}
    is_mock_label = " [Mock]" if prediction.get("is_mock") else ""
    subtitle = (
        f"Score: {score:.3f}  |  {dir_emoji.get(direction, direction)}"
        f"  |  预测 {len(predicted_prices)} bars{is_mock_label}"
    )

    option: Dict[str, Any] = {
        "title": {
            "text": f"{symbol} {timeframe} — AI 预测 vs 真实",
            "subtext": subtitle,
            "left": "center",
            "textStyle": {"color": "#E0E0E0", "fontSize": 16},
            "subtextStyle": {"color": "#AAAAAA", "fontSize": 12},
        },
        "tooltip": {
            "trigger": "axis",
            "axisPointer": {"type": "cross"},
        },
        "legend": {
            "data": ["K 线", "AI 预测轨迹"],
            "top": 50,
            "textStyle": {"color": "#CCCCCC"},
        },
        "grid": {
            "left": "8%",
            "right": "8%",
            "top": 90,
            "bottom": 80,
        },
        "xAxis": {
            "type": "category",
            "data": x_categories,
            "axisLabel": {
                "color": "#999",
                "rotate": 30,
                "fontSize": 10,
            },
            "splitLine": {"show": False},
        },
        "yAxis": {
            "type": "value",
            "scale": True,
            "axisLabel": {"color": "#999"},
            "splitLine": {
                "lineStyle": {"color": "rgba(255,255,255,0.05)"},
            },
        },
        "dataZoom": [
            {
                "type": "inside",
                "xAxisIndex": 0,
                "start": max(0, (1 - 100 / max(len(x_categories), 1)) * 100),
                "end": 100,
            },
            {
                "type": "slider",
                "xAxisIndex": 0,
                "bottom": 10,
                "height": 20,
            },
        ],
        "series": [],
    }

    # Series 1: 真实 K 线蜡烛图
    option["series"].append({
        "name": "K 线",
        "type": "candlestick",
        "data": candlestick_data,
        "itemStyle": {
            "color": "#ef5350",       # 涨 — 红
            "color0": "#26a69a",      # 跌 — 绿
            "borderColor": "#ef5350",
            "borderColor0": "#26a69a",
        },
    })

    # Series 2: AI 预测轨迹（虚线）
    option["series"].append({
        "name": "AI 预测轨迹",
        "type": "line",
        "data": pred_line_data,
        "smooth": True,
        "symbol": "circle",
        "symbolSize": 4,
        "lineStyle": {
            "type": "dashed",
            "color": pred_color,
            "width": 2.5,
        },
        "itemStyle": {"color": pred_color},
        "markArea": {"data": mark_area_data} if mark_area_data else {},
        "z": 10,
    })

    # Series 3: 对比复盘线（可选，实线绿色）
    if actual_line_data:
        option["legend"]["data"].append("实际走势")
        option["series"].append({
            "name": "实际走势",
            "type": "line",
            "data": actual_line_data,
            "smooth": False,
            "symbol": "diamond",
            "symbolSize": 3,
            "lineStyle": {
                "type": "solid",
                "color": "#00E676",
                "width": 1.5,
            },
            "itemStyle": {"color": "#00E676"},
            "z": 5,
        })

    return option


def build_multi_prediction_chart(
    real_klines: List[Dict[str, Any]],
    predictions: List[Dict[str, Any]],
    symbol: str = "BTC/USDT",
    timeframe: str = "1m",
) -> Dict[str, Any]:
    """
    叠加多条历史预测轨迹到同一张图上（对比复盘模式）。

    每条预测轨迹用不同透明度的虚线绘制，最新一条最醒目。
    """
    if not predictions:
        return build_prediction_chart(real_klines, {
            "predicted_prices": [],
            "predicted_timestamps": [],
            "score": 0.5,
            "direction": "neutral",
            "current_close": real_klines[-1]["close"] if real_klines else 0,
            "timestamp_ms": real_klines[-1]["timestamp"] if real_klines else 0,
        }, symbol=symbol, timeframe=timeframe)

    # 用最新一条预测作为主图
    latest = predictions[-1]
    option = build_prediction_chart(real_klines, latest, symbol=symbol, timeframe=timeframe)

    # 叠加历史预测轨迹
    colors = ["#B388FF", "#80DEEA", "#FFD54F", "#FF8A65", "#AED581"]
    for idx, pred in enumerate(predictions[:-1]):
        pred_prices = pred.get("predicted_prices", [])
        pred_ts = pred.get("predicted_timestamps", [])
        pred_close = pred.get("current_close", 0)
        pred_ts_ms = pred.get("timestamp_ms", 0)
        if not pred_prices:
            continue

        date_fmt = "%m-%d %H:%M"
        x_cats = option["xAxis"]["data"]

        start_dt = datetime.fromtimestamp(pred_ts_ms / 1000) if pred_ts_ms > 1e12 else datetime.fromtimestamp(pred_ts_ms)
        start_label = start_dt.strftime(date_fmt)

        line_data: List[Any] = []
        found = False
        for cat in x_cats:
            if cat == start_label and not found:
                line_data.append(round(pred_close, 2))
                found = True
            elif found and len(line_data) - 1 < len(pred_prices):
                line_data.append(round(pred_prices[len(line_data) - 1], 2))
            else:
                line_data.append(None)

        color = colors[idx % len(colors)]
        name = f"预测 #{idx + 1}"
        option["series"].append({
            "name": name,
            "type": "line",
            "data": line_data,
            "smooth": True,
            "symbol": "none",
            "lineStyle": {
                "type": "dashed",
                "color": color,
                "width": 1,
                "opacity": 0.5,
            },
            "z": 3,
        })

    return option
