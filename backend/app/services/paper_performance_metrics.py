"""Shared paper-equity performance calculations for cards and detail dashboards."""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable


ROLLING_DRAWDOWN_DAYS = 30
ROLLING_DRAWDOWN_WINDOW_MS = ROLLING_DRAWDOWN_DAYS * 24 * 60 * 60 * 1000


def equity_curve_risk_metrics(samples: Iterable[Dict[str, Any]]) -> Dict[str, float]:
    """Calculate Sharpe and rolling 30-day drawdown from positive equity samples."""
    equities: list[float] = []
    timestamped_equities: list[tuple[int, float]] = []
    for item in samples:
        try:
            value = float(item.get("equity") or 0)
        except (AttributeError, TypeError, ValueError):
            value = 0.0
        if value > 0 and math.isfinite(value):
            equities.append(value)
            try:
                timestamp = int(item.get("timestamp"))
            except (AttributeError, TypeError, ValueError):
                continue
            if timestamp >= 0:
                timestamped_equities.append((timestamp, value))

    drawdown_equities = equities
    if timestamped_equities:
        latest_timestamp = max(timestamp for timestamp, _ in timestamped_equities)
        cutoff_timestamp = latest_timestamp - ROLLING_DRAWDOWN_WINDOW_MS
        drawdown_equities = [
            value
            for timestamp, value in timestamped_equities
            if timestamp >= cutoff_timestamp
        ]

    max_drawdown = 0.0
    peak = 0.0
    for value in drawdown_equities:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value) / peak * 100)

    returns = [
        (cur - prev) / prev
        for prev, cur in zip(equities, equities[1:])
        if prev > 0
    ]
    sharpe_ratio = 0.0
    if len(returns) >= 2:
        mean_return = sum(returns) / len(returns)
        variance = sum((value - mean_return) ** 2 for value in returns) / (len(returns) - 1)
        std_return = math.sqrt(variance)
        if std_return > 0:
            sharpe_ratio = mean_return / std_return * math.sqrt(len(returns))

    return {
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
    }
