"""Versioned, provider-free performance metrics for persisted daily backtests."""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


CALCULATION_VERSION = "backtest-metrics.v1"
TRADING_DAYS = 252.0


def _mean(values: Sequence[float]) -> Optional[float]:
    return statistics.fmean(values) if values else None


def _stdev(values: Sequence[float]) -> Optional[float]:
    return statistics.stdev(values) if len(values) >= 2 else None


def _safe_div(numerator: float, denominator: float) -> Optional[float]:
    return numerator / denominator if denominator else None


def drawdown_series(nav: Sequence[float]) -> Tuple[List[float], Optional[float], Optional[int], Optional[int]]:
    if not nav:
        return [], None, None, None
    peak = float(nav[0])
    peak_index = 0
    maximum = 0.0
    maximum_peak = 0
    maximum_trough = 0
    result: List[float] = []
    for index, raw in enumerate(nav):
        value = float(raw)
        if value > peak:
            peak = value
            peak_index = index
        drawdown = (peak - value) / peak if peak > 0 else 0.0
        result.append(drawdown)
        if drawdown > maximum:
            maximum = drawdown
            maximum_peak = peak_index
            maximum_trough = index
    return result, maximum, maximum_peak, maximum_trough


def monthly_returns(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["trade_date"])[:7]].append(row)
    output = []
    for month in sorted(grouped):
        values = grouped[month]
        start_nav = float(values[0]["strategy_nav"])
        end_nav = float(values[-1]["strategy_nav"])
        output.append({"month": month, "return": _safe_div(end_nav, start_nav) - 1 if start_nav else None})
    return output


def calculate_backtest_metrics(
    equity_rows: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]],
    orders: Sequence[Mapping[str, Any]],
    *,
    initial_cash: float,
    total_commission: float = 0.0,
    total_tax: float = 0.0,
    total_transfer_fee: float = 0.0,
    total_slippage_cost: float = 0.0,
    turnover_amount: float = 0.0,
    peak_single_symbol_weight: float = 0.0,
    capacity_warning_count: int = 0,
    data_quality_warning_count: int = 0,
) -> List[Dict[str, Any]]:
    rows = list(equity_rows)
    strategy_nav = [float(item["strategy_nav"]) for item in rows]
    benchmark_nav = [float(item["benchmark_nav"]) for item in rows if item.get("benchmark_nav") is not None]
    strategy_returns = [float(item["strategy_return"]) for item in rows if item.get("strategy_return") is not None]
    benchmark_returns = [float(item["benchmark_return"]) for item in rows if item.get("benchmark_return") is not None]
    paired_count = min(len(strategy_returns), len(benchmark_returns))
    paired_strategy = strategy_returns[-paired_count:] if paired_count else []
    paired_benchmark = benchmark_returns[-paired_count:] if paired_count else []
    excess_returns = [left - right for left, right in zip(paired_strategy, paired_benchmark)]
    excess_nav = [float(item["excess_nav"]) for item in rows if item.get("excess_nav") is not None]
    drawdowns, maximum_drawdown, peak_index, trough_index = drawdown_series(strategy_nav)
    _, excess_maximum_drawdown, excess_peak, excess_trough = drawdown_series(excess_nav)
    periods = max(len(rows) - 1, 0)
    total_return = strategy_nav[-1] - 1.0 if strategy_nav else None
    benchmark_return = benchmark_nav[-1] - 1.0 if benchmark_nav else None
    annualized_return = (strategy_nav[-1] ** (TRADING_DAYS / periods) - 1.0) if strategy_nav and periods > 0 and strategy_nav[-1] >= 0 else None
    volatility_daily = _stdev(strategy_returns)
    benchmark_vol_daily = _stdev(benchmark_returns)
    excess_vol_daily = _stdev(excess_returns)
    negative_returns = [item for item in strategy_returns if item < 0]
    downside_daily = math.sqrt(sum(item * item for item in negative_returns) / len(negative_returns)) if negative_returns else None
    mean_return = _mean(strategy_returns)
    mean_excess = _mean(excess_returns)
    sharpe = _safe_div(float(mean_return or 0.0), float(volatility_daily or 0.0))
    sortino = _safe_div(float(mean_return or 0.0), float(downside_daily or 0.0))
    information_ratio = _safe_div(float(mean_excess or 0.0), float(excess_vol_daily or 0.0))
    excess_sharpe = information_ratio
    if sharpe is not None:
        sharpe *= math.sqrt(TRADING_DAYS)
    if sortino is not None:
        sortino *= math.sqrt(TRADING_DAYS)
    if information_ratio is not None:
        information_ratio *= math.sqrt(TRADING_DAYS)
        excess_sharpe = information_ratio

    beta = None
    alpha = None
    if paired_count >= 2:
        benchmark_mean = statistics.fmean(paired_benchmark)
        strategy_mean = statistics.fmean(paired_strategy)
        benchmark_variance = sum((item - benchmark_mean) ** 2 for item in paired_benchmark) / (paired_count - 1)
        covariance = sum(
            (left - strategy_mean) * (right - benchmark_mean)
            for left, right in zip(paired_strategy, paired_benchmark)
        ) / (paired_count - 1)
        beta = _safe_div(covariance, benchmark_variance)
        if beta is not None:
            alpha = (strategy_mean - beta * benchmark_mean) * TRADING_DAYS

    sell_trades = [item for item in trades if str(item.get("side")) == "sell"]
    realized = [float(item.get("realized_pnl") or 0.0) for item in sell_trades]
    wins = [item for item in realized if item > 0]
    losses = [item for item in realized if item < 0]
    daily_returns = strategy_returns
    completed_orders = [item for item in orders if item.get("status") == "filled"]
    rejected_orders = [item for item in orders if item.get("status") in {"rejected", "expired"}]
    average_equity = _mean([float(item["equity"]) for item in rows]) or float(initial_cash)
    average_exposure = _mean([float(item.get("gross_exposure") or 0.0) for item in rows])
    holding_days = [float(item["holding_days"]) for item in sell_trades if item.get("holding_days") is not None]

    def metric(code: str, value: Optional[float], unit: str, reason: Optional[str] = None, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "metric_code": code,
            "metric_value": float(value) if value is not None and math.isfinite(float(value)) else None,
            "unit": unit,
            "calculation_version": CALCULATION_VERSION,
            "input_frequency": "1d",
            "null_reason": reason if value is None else None,
            "metric_payload": payload or {},
        }

    interval_payload = {}
    if peak_index is not None and trough_index is not None and rows:
        interval_payload = {"peak_date": str(rows[peak_index]["trade_date"]), "trough_date": str(rows[trough_index]["trade_date"])}
    excess_interval = {}
    if excess_peak is not None and excess_trough is not None and rows:
        excess_interval = {"peak_date": str(rows[excess_peak]["trade_date"]), "trough_date": str(rows[excess_trough]["trade_date"])}

    rejection_counts = defaultdict(int)
    for item in orders:
        if item.get("rejection_code"):
            rejection_counts[str(item["rejection_code"])] += 1

    values = [
        metric("strategy_return", total_return, "ratio", "没有权益序列"),
        metric("annualized_return", annualized_return, "ratio", "至少需要两个交易日"),
        metric("benchmark_return", benchmark_return, "ratio", "缺少基准序列"),
        metric("excess_return", total_return - benchmark_return if total_return is not None and benchmark_return is not None else None, "ratio", "缺少策略或基准收益"),
        metric("daily_average_excess_return", mean_excess, "ratio", "缺少配对日收益"),
        metric("maximum_drawdown", maximum_drawdown, "ratio", "没有权益序列", interval_payload),
        metric("annualized_volatility", volatility_daily * math.sqrt(TRADING_DAYS) if volatility_daily is not None else None, "ratio", "日收益样本不足"),
        metric("downside_volatility", downside_daily * math.sqrt(TRADING_DAYS) if downside_daily is not None else None, "ratio", "没有负收益样本"),
        metric("sharpe", sharpe, "number", "日收益波动率为零或样本不足"),
        metric("sortino", sortino, "number", "下行波动率为零或没有负收益"),
        metric("alpha", alpha, "ratio_per_year", "策略与基准配对样本不足或基准方差为零"),
        metric("beta", beta, "number", "策略与基准配对样本不足或基准方差为零"),
        metric("information_ratio", information_ratio, "number", "超额收益波动率为零或样本不足"),
        metric("benchmark_volatility", benchmark_vol_daily * math.sqrt(TRADING_DAYS) if benchmark_vol_daily is not None else None, "ratio", "基准日收益样本不足"),
        metric("excess_maximum_drawdown", excess_maximum_drawdown, "ratio", "缺少超额净值序列", excess_interval),
        metric("excess_sharpe", excess_sharpe, "number", "超额收益波动率为零或样本不足"),
        metric("win_rate", len(wins) / len(realized) if realized else None, "ratio", "没有已平仓交易"),
        metric("profit_loss_ratio", (statistics.fmean(wins) / abs(statistics.fmean(losses))) if wins and losses else None, "number", "盈利或亏损交易样本缺失"),
        metric("daily_win_rate", sum(item > 0 for item in daily_returns) / len(daily_returns) if daily_returns else None, "ratio", "没有日收益"),
        metric("profitable_trades", float(len(wins)), "count"),
        metric("losing_trades", float(len(losses)), "count"),
        metric("total_orders", float(len(orders)), "count"),
        metric("completed_trades", float(len(trades)), "count"),
        metric("fill_rate", len(completed_orders) / len(orders) if orders else None, "ratio", "没有订单"),
        metric("rejection_rate", len(rejected_orders) / len(orders) if orders else None, "ratio", "没有订单"),
        metric("turnover", turnover_amount / average_equity if average_equity else None, "ratio", "平均权益为零"),
        metric("total_commission", total_commission, "CNY"),
        metric("total_tax", total_tax, "CNY"),
        metric("total_transfer_fee", total_transfer_fee, "CNY"),
        metric("total_slippage_cost", total_slippage_cost, "CNY"),
        metric("total_cost", total_commission + total_tax + total_transfer_fee + total_slippage_cost, "CNY"),
        metric("average_holding_days", _mean(holding_days), "days", "没有已平仓持有期"),
        metric("average_exposure", average_exposure, "ratio", "没有权益序列"),
        metric("peak_single_symbol_weight", peak_single_symbol_weight, "ratio"),
        metric("t1_rejections", float(rejection_counts["T1_NOT_AVAILABLE"]), "count"),
        metric("lot_size_rejections", float(rejection_counts["INVALID_LOT_SIZE"]), "count"),
        metric("suspension_rejections", float(rejection_counts["SUSPENDED"]), "count"),
        metric("limit_up_rejections", float(rejection_counts["LIMIT_UP"]), "count"),
        metric("limit_down_rejections", float(rejection_counts["LIMIT_DOWN"]), "count"),
        metric("capacity_warnings", float(capacity_warning_count), "count"),
        metric("data_quality_warnings", float(data_quality_warning_count), "count"),
    ]
    return values
