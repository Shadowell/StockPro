#!/usr/bin/env python3
"""Real-data research for the Top20 high-frequency micro-breakout strategy."""

from __future__ import annotations

import argparse
import asyncio
import heapq
import hashlib
import json
import math
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


class ResearchDataError(RuntimeError):
    pass


def run_async(awaitable):
    return asyncio.run(awaitable)


class ResearchPaperBroker:
    def __init__(self, *, initial_equity=100.0, cost_rate_per_side=0.001):
        self.initial_capital = float(initial_equity)
        self.cash = float(initial_equity)
        self.cost_rate_per_side = max(0.0, float(cost_rate_per_side))
        self.positions = {}
        self.last_prices = {}
        self.orders = []
        self.trades = []
        self.current_timestamp = 0
        self.warmup_mode = True

    @property
    def equity(self):
        value = self.cash
        for (symbol, side), position in self.positions.items():
            price = float(self.last_prices.get(symbol, position["entry_price"]))
            direction = 1.0 if side == "long" else -1.0
            value += (price - float(position["entry_price"])) * direction * float(
                position["quantity"]
            )
        return float(value)

    @property
    def balance(self):
        return self.equity

    def update_price(self, symbol, price):
        self.last_prices[str(symbol)] = float(price)

    async def open_contract(self, symbol, side, notional_usdt, leverage=None, price=None):
        symbol = str(symbol)
        side = str(side)
        price = float(price)
        notional = float(notional_usdt)
        if price <= 0 or notional <= 0 or (symbol, side) in self.positions:
            return {"status": "rejected"}
        quantity = notional / price
        open_cost = notional * self.cost_rate_per_side
        self.cash -= open_cost
        self.positions[(symbol, side)] = {
            "symbol": symbol,
            "side": side,
            "entry_price": price,
            "quantity": quantity,
            "notional_value": notional,
            "leverage": leverage,
            "opened_at": int(self.current_timestamp),
            "open_cost": open_cost,
        }
        self.orders.append(
            {
                "action": "open",
                "symbol": symbol,
                "side": side,
                "price": price,
                "notional_usdt": notional,
                "timestamp": int(self.current_timestamp),
            }
        )
        return {
            "status": "filled",
            "symbol": symbol,
            "side": side,
            "price": price,
            "notional_usdt": notional,
        }

    async def close_contract(self, symbol, side, ratio=1.0, contracts=None, price=None):
        symbol = str(symbol)
        side = str(side)
        key = (symbol, side)
        position = self.positions.get(key)
        if not position:
            return {"status": "rejected"}
        close_ratio = min(1.0, max(0.0, float(ratio)))
        if close_ratio <= 0:
            return {"status": "rejected"}
        price = float(price)
        quantity = float(position["quantity"]) * close_ratio
        direction = 1.0 if side == "long" else -1.0
        raw_pnl = (price - float(position["entry_price"])) * direction * quantity
        exit_notional = abs(price * quantity)
        exit_cost = exit_notional * self.cost_rate_per_side
        allocated_open_cost = float(position["open_cost"]) * close_ratio
        net_pnl = raw_pnl - exit_cost - allocated_open_cost
        self.cash += raw_pnl - exit_cost
        trade = {
            "symbol": symbol,
            "side": side,
            "opened_at": int(position["opened_at"]),
            "closed_at": int(self.current_timestamp),
            "entry_price": float(position["entry_price"]),
            "exit_price": price,
            "pnl": float(net_pnl),
            "open_cost": float(allocated_open_cost),
            "close_cost": float(exit_cost),
        }
        self.trades.append(trade)
        self.orders.append(
            {
                "action": "close",
                "symbol": symbol,
                "side": side,
                "price": price,
                "timestamp": int(self.current_timestamp),
            }
        )
        if close_ratio >= 1.0:
            self.positions.pop(key, None)
        else:
            position["quantity"] = float(position["quantity"]) - quantity
            position["notional_value"] = float(position["entry_price"]) * float(
                position["quantity"]
            )
            position["open_cost"] = float(position["open_cost"]) - allocated_open_cost
        return {
            "status": "filled",
            "symbol": symbol,
            "side": side,
            "price": price,
            "realized_pnl": float(net_pnl),
        }

    async def get_contract_position(self, symbol, side):
        return self.positions.get((str(symbol), str(side)))

    async def get_available_balance(self, currency="USDT"):
        return self.equity


def summarize_simulation(trades, equity_samples, *, start_ms, end_ms):
    initial_equity = float(equity_samples[0][1]) if equity_samples else 100.0
    final_equity = float(equity_samples[-1][1]) if equity_samples else initial_equity
    peak = initial_equity
    max_drawdown_pct = 0.0
    for _, value in equity_samples:
        equity = float(value)
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown_pct = max(max_drawdown_pct, 100.0 * (peak - equity) / peak)
    positive = [float(item["pnl"]) for item in trades if float(item["pnl"]) > 0]
    negative = [abs(float(item["pnl"])) for item in trades if float(item["pnl"]) < 0]
    gross_profit = sum(positive)
    gross_loss = sum(negative)
    holding_minutes = [
        max(0.0, (int(item["closed_at"]) - int(item["opened_at"])) / 60_000.0)
        for item in trades
    ]
    pnl_by_symbol = {}
    for item in trades:
        symbol = str(item["symbol"])
        pnl_by_symbol[symbol] = pnl_by_symbol.get(symbol, 0.0) + float(item["pnl"])
    positive_symbols = {symbol: pnl for symbol, pnl in pnl_by_symbol.items() if pnl > 0}
    total_symbol_profit = sum(positive_symbols.values())
    duration_days = max(1e-9, (int(end_ms) - int(start_ms)) / 86_400_000.0)
    return {
        "initial_equity": initial_equity,
        "final_equity": final_equity,
        "total_return_pct": (
            100.0 * (final_equity / initial_equity - 1.0) if initial_equity > 0 else 0.0
        ),
        "max_drawdown_pct": max_drawdown_pct,
        "profit_factor": (
            gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
        ),
        "closed_round_trips": len(trades),
        "round_trips_per_day": len(trades) / duration_days,
        "avg_holding_minutes": (
            sum(holding_minutes) / len(holding_minutes) if holding_minutes else 0.0
        ),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "single_symbol_profit_share": (
            max(positive_symbols.values()) / total_symbol_profit
            if positive_symbols and total_symbol_profit > 0
            else 0.0
        ),
        "symbol_pnl": pnl_by_symbol,
    }


def classify_path(values, *, target=200.0, floor=85.0):
    for value in values:
        equity = float(value)
        if equity >= float(target):
            return "target_200"
        if equity <= float(floor):
            return "floor_85"
    return "expired"


def evaluate_gate(metrics):
    reasons = []
    if float(metrics.get("total_return_pct", 0.0)) <= 0:
        reasons.append("盲测总收益不为正")
    if float(metrics.get("profit_factor", 0.0)) < 1.20:
        reasons.append("盲测利润因子低于1.20")
    if float(metrics.get("max_drawdown_pct", 999.0)) > 15.0:
        reasons.append("盲测最大回撤超过15%")
    frequency = float(metrics.get("round_trips_per_day", 0.0))
    if frequency < 20.0:
        reasons.append("盲测日均闭环少于20")
    if frequency > 35.0:
        reasons.append("盲测日均闭环超过35")
    if float(metrics.get("avg_holding_minutes", 999.0)) > 120.0:
        reasons.append("平均持有超过120分钟")
    if float(metrics.get("first_half_return_pct", 0.0)) <= 0:
        reasons.append("盲测前半段不盈利")
    if float(metrics.get("second_half_return_pct", 0.0)) <= 0:
        reasons.append("盲测后半段不盈利")
    if float(metrics.get("positive_rolling_15d_share", 0.0)) < 0.70:
        reasons.append("滚动15日正收益比例低于70%")
    if float(metrics.get("single_symbol_profit_share", 1.0)) > 0.30:
        reasons.append("单一标的正利润贡献超过30%")
    if float(metrics.get("stress_total_return_pct", 0.0)) <= 0:
        reasons.append("压力成本收益不为正")
    if float(metrics.get("stress_profit_factor", 0.0)) < 1.05:
        reasons.append("压力成本利润因子低于1.05")
    if not bool(metrics.get("data_complete", False)):
        reasons.append("真实数据覆盖不完整")
    return {"passed": not reasons, "reasons": reasons, **dict(metrics)}


def freeze_parameter_metadata(parameters):
    selected = dict(parameters)
    payload = json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    parameter_hash = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return {
        "selected_parameters": selected,
        "validation_parameter_hash": parameter_hash,
        "oos_parameter_hash": parameter_hash,
    }


def rolling_window_starts(start_ms, end_ms, *, window_days=15):
    day_ms = 86_400_000
    window_ms = max(1, int(window_days)) * day_ms
    last_start = int(end_ms) - window_ms
    if last_start < int(start_ms):
        return []
    return list(range(int(start_ms), last_start + 1, day_ms))


def is_contract_storage_symbol(value):
    return str(value or "").endswith("-USDT_USDT")


def discover_symbol_files(root, *, start_ms, end_ms, minimum_symbols=20):
    try:
        import pyarrow.parquet as pq
    except Exception as exc:
        raise ResearchDataError(f"真实5M K线不足：pyarrow不可用 ({exc})") from exc
    base = Path(root)
    output = {}
    for timeframe_dir in base.glob("*/5m"):
        if not is_contract_storage_symbol(timeframe_dir.parent.name):
            continue
        selected = []
        minimum = None
        maximum = None
        for path in sorted(timeframe_dir.glob("*.parquet")):
            table = pq.read_table(path, columns=["timestamp"])
            if table.num_rows <= 0:
                continue
            values = table.column("timestamp").to_pylist()
            file_min = int(values[0])
            file_max = int(values[-1])
            minimum = file_min if minimum is None else min(minimum, file_min)
            maximum = file_max if maximum is None else max(maximum, file_max)
            if file_max >= int(start_ms) and file_min <= int(end_ms):
                selected.append(str(path))
        if (
            selected
            and minimum is not None
            and maximum is not None
            and minimum <= int(start_ms) + 300_000
            and maximum >= int(end_ms) - 300_000
        ):
            output[timeframe_dir.parent.name] = selected
    if len(output) < int(minimum_symbols):
        raise ResearchDataError(
            f"真实5M K线不足：需要至少{int(minimum_symbols)}个完整标的，实际{len(output)}个"
        )
    return output


DAY_MS = 86_400_000
FIVE_MINUTES_MS = 300_000

DEFAULT_PARAMETERS = {
    "market_type": "swap",
    "timeframe": "5m",
    "primary_signal_timeframe": "1h",
    "initial_capital": 100,
    "leverage": 5,
    "atr_window": 14,
    "adx_window": 14,
    "min_h1_bars": 36,
    "candidate_count": 20,
    "turnover_window": 24,
    "state_confirmations": 2,
    "score_min": 65,
    "atr_pct_min": 0.6,
    "atr_pct_max": 6.0,
    "efficiency_window": 24,
    "efficiency_min": 0.22,
    "direction_window": 12,
    "direction_atr_min": 0.75,
    "donchian_window": 20,
    "adx_min": 18,
    "extension_atr_max": 2.2,
    "breakout_window": 12,
    "volume_window": 20,
    "breakout_volume_ratio": 1.35,
    "min_bar_range_atr": 0.45,
    "max_breakout_extension_atr": 1.2,
    "round_trip_cost_bps": 20,
    "cost_edge_multiple": 3,
    "initial_stop_atr_mult": 0.9,
    "hard_stop_price_pct": 0.008,
    "hard_take_profit_r": 1.15,
    "risk_per_trade_pct": 0.005,
    "max_position_notional_usdt": 50,
    "max_positions": 3,
    "same_direction_cap": 2,
    "max_total_notional_equity_pct": 1.5,
    "min_order_notional_usdt": 0.5,
    "break_even_at_r": 0.45,
    "profit_trailing_start_r": 0.75,
    "profit_peak_pullback_pct": 0.30,
    "profit_atr_stop_mult": 0.65,
    "failed_breakout_exit_bars": 3,
    "failure_buffer_atr": 0.15,
    "max_holding_bars": 24,
    "cooldown_bars": 6,
    "loss_cooldown_count": 4,
    "loss_cooldown_hours": 2,
    "daily_loss_pct": 0.03,
    "daily_lock_activation_pct": 0.02,
    "daily_lock_fraction": 0.40,
    "terminal_floor_equity": 85,
}


def canonical_symbol(storage_symbol):
    value = str(storage_symbol)
    suffix = "-USDT_USDT"
    if not value.endswith(suffix):
        raise ResearchDataError(f"真实5M K线不足：不是USDT永续存储标的 {value}")
    return value[: -len(suffix)] + "/USDT:USDT"


def _load_symbol(paths, start_ms, end_ms):
    import pandas as pd
    import pyarrow.parquet as pq

    frames = []
    columns = ["timestamp", "open", "high", "low", "close", "volume"]
    for path in paths:
        table = pq.read_table(path, columns=columns)
        frame = table.to_pandas()
        frame = frame[(frame["timestamp"] >= int(start_ms)) & (frame["timestamp"] <= int(end_ms))]
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=columns)
    result = pd.concat(frames, ignore_index=True)
    return result.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def load_complete_frames(files, *, start_ms, end_ms, minimum_symbols=20):
    frames = {}
    coverage = {}
    expected = max(1, int((int(end_ms) - int(start_ms)) // FIVE_MINUTES_MS) + 1)
    for storage_symbol, paths in files.items():
        frame = _load_symbol(paths, start_ms, end_ms)
        ratio = len(frame) / float(expected)
        if not frame.empty and ratio >= 0.97:
            symbol = canonical_symbol(storage_symbol)
            frames[symbol] = frame
            coverage[symbol] = ratio
    if len(frames) < int(minimum_symbols):
        raise ResearchDataError(
            f"真实5M K线不足：覆盖率>=97%的标的只有{len(frames)}个"
        )
    return frames, coverage


def _load_strategy_class(repo_root, strategy_source):
    repo = Path(repo_root).resolve()
    backend = repo / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from app.services.agent.code_sandbox import load_base_strategy_class

    source = Path(strategy_source)
    if not source.is_absolute():
        source = repo / source
    if not source.exists():
        raise ResearchDataError(f"策略源码不存在：{source}")
    return load_base_strategy_class(source.read_text(encoding="utf-8")), source


async def _simulate_segment_async(
    frames,
    *,
    start_ms,
    end_ms,
    repo_root,
    strategy_source,
    parameters,
    cost_rate_per_side,
    warmup_hours=48,
):
    repo = Path(repo_root).resolve()
    backend = repo / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from app.core.execution.base_strategy import BarData, StrategyState

    strategy_class, _ = _load_strategy_class(repo, strategy_source)
    symbols = sorted(frames)
    state = StrategyState(
        strategy_id=9_102,
        name="[合约][5M][CTA] Top20 · 1H状态微突破锁利 · 100U",
        exchange="okx",
        symbols=symbols,
        created_at=datetime.now(timezone.utc),
        status="running",
        positions={"_capital": 100.0},
    )
    broker = ResearchPaperBroker(initial_equity=100.0, cost_rate_per_side=cost_rate_per_side)
    strategy = strategy_class(state, broker)
    strategy.set_config(dict(parameters))
    await strategy.on_init()
    warmup_start = int(start_ms) - int(warmup_hours) * 3_600_000
    records = {}
    heap = []
    for symbol, frame in frames.items():
        sample = frame[
            (frame["timestamp"] >= warmup_start) & (frame["timestamp"] <= int(end_ms))
        ]
        rows = sample.to_dict("records")
        if rows:
            records[symbol] = rows
            heapq.heappush(heap, (int(rows[0]["timestamp"]), symbol, 0))
    equity_samples = []
    while heap:
        timestamp = int(heap[0][0])
        batch = []
        while heap and int(heap[0][0]) == timestamp:
            _, symbol, index = heapq.heappop(heap)
            row = records[symbol][index]
            batch.append((symbol, row))
            next_index = index + 1
            if next_index < len(records[symbol]):
                next_row = records[symbol][next_index]
                heapq.heappush(heap, (int(next_row["timestamp"]), symbol, next_index))
        broker.current_timestamp = timestamp
        broker.warmup_mode = timestamp < int(start_ms)
        for symbol, row in batch:
            broker.update_price(symbol, float(row["close"]))
        for symbol, row in batch:
            bar = BarData(
                exchange="okx",
                symbol=symbol,
                timeframe="5m",
                timestamp=timestamp,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            await strategy.on_bar(bar)
        if timestamp >= int(start_ms):
            equity_samples.append((timestamp, broker.equity))
    broker.current_timestamp = int(end_ms)
    for symbol, side in list(broker.positions):
        price = float(broker.last_prices.get(symbol, broker.positions[(symbol, side)]["entry_price"]))
        await broker.close_contract(symbol, side, ratio=1.0, price=price)
    equity_samples.append((int(end_ms), broker.equity))
    return {
        "trades": list(broker.trades),
        "equity": equity_samples,
        "runtime": dict(strategy.runtime),
    }


def simulate_segment(frames, **kwargs):
    return run_async(_simulate_segment_async(frames, **kwargs))


def _equity_at(equity_samples, timestamp):
    value = float(equity_samples[0][1]) if equity_samples else 100.0
    for sample_timestamp, equity in equity_samples:
        if int(sample_timestamp) > int(timestamp):
            break
        value = float(equity)
    return value


def _segment_return(equity_samples, start_ms, end_ms):
    start_equity = _equity_at(equity_samples, start_ms)
    end_equity = _equity_at(equity_samples, end_ms)
    return 100.0 * (end_equity / start_equity - 1.0) if start_equity > 0 else 0.0


def summarize_rolling_fifteen_days(equity_samples, *, start_ms, end_ms):
    starts = rolling_window_starts(start_ms, end_ms, window_days=15)
    rows = []
    outcomes = []
    for window_start in starts:
        window_end = window_start + 15 * DAY_MS
        start_equity = _equity_at(equity_samples, window_start)
        end_equity = _equity_at(equity_samples, window_end)
        values = [
            100.0 * float(value) / start_equity
            for timestamp, value in equity_samples
            if window_start <= int(timestamp) <= window_end and start_equity > 0
        ]
        outcome = classify_path(values, target=200, floor=85)
        outcomes.append(outcome)
        rows.append(
            {
                "start_ms": window_start,
                "end_ms": window_end,
                "return_pct": (
                    100.0 * (end_equity / start_equity - 1.0) if start_equity > 0 else 0.0
                ),
                "outcome": outcome,
            }
        )
    positive = sum(1 for row in rows if float(row["return_pct"]) > 0)
    return {
        "window_count": len(rows),
        "positive_window_share": positive / len(rows) if rows else 0.0,
        "target_before_floor_probability": (
            outcomes.count("target_200") / len(outcomes) if outcomes else 0.0
        ),
        "floor_before_target_probability": (
            outcomes.count("floor_85") / len(outcomes) if outcomes else 0.0
        ),
        "expired_probability": outcomes.count("expired") / len(outcomes) if outcomes else 0.0,
        "windows": rows,
    }


def _run_and_summarize(frames, *, start_ms, end_ms, **kwargs):
    simulation = simulate_segment(frames, start_ms=start_ms, end_ms=end_ms, **kwargs)
    metrics = summarize_simulation(
        simulation["trades"],
        simulation["equity"],
        start_ms=start_ms,
        end_ms=end_ms,
    )
    return simulation, metrics


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="/opt/bitpro/data/klines/okx")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--strategy-source", default="scripts/strategy_sources/high_frequency_micro_breakout.py")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--train-days", type=int, default=60)
    parser.add_argument("--validation-days", type=int, default=30)
    parser.add_argument("--oos-days", type=int, default=30)
    parser.add_argument("--as-of-lag-hours", type=int, default=4)
    parser.add_argument("--minimum-symbols", type=int, default=20)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-report", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    if int(args.train_days) + int(args.validation_days) + int(args.oos_days) != int(args.days):
        raise ResearchDataError("训练、验证和盲测天数之和必须等于总天数")
    as_of_ms = (
        int(time.time() * 1000) - int(args.as_of_lag_hours) * 3_600_000
    ) // FIVE_MINUTES_MS * FIVE_MINUTES_MS
    research_start = as_of_ms - int(args.days) * DAY_MS
    data_start = research_start - 48 * 3_600_000
    files = discover_symbol_files(
        args.data_root,
        start_ms=data_start,
        end_ms=as_of_ms,
        minimum_symbols=args.minimum_symbols,
    )
    frames, coverage = load_complete_frames(
        files,
        start_ms=data_start,
        end_ms=as_of_ms,
        minimum_symbols=args.minimum_symbols,
    )
    train_end = research_start + int(args.train_days) * DAY_MS
    validation_end = train_end + int(args.validation_days) * DAY_MS
    oos_start = validation_end
    parameters = dict(DEFAULT_PARAMETERS)
    parameter_metadata = freeze_parameter_metadata(parameters)
    common = {
        "repo_root": args.repo_root,
        "strategy_source": args.strategy_source,
        "parameters": parameters,
        "cost_rate_per_side": 0.001,
    }
    _, train = _run_and_summarize(
        frames,
        start_ms=research_start,
        end_ms=train_end,
        **common,
    )
    _, validation = _run_and_summarize(
        frames,
        start_ms=train_end,
        end_ms=validation_end,
        **common,
    )
    oos_simulation, oos = _run_and_summarize(
        frames,
        start_ms=oos_start,
        end_ms=as_of_ms,
        **common,
    )
    _, stress = _run_and_summarize(
        frames,
        start_ms=oos_start,
        end_ms=as_of_ms,
        repo_root=args.repo_root,
        strategy_source=args.strategy_source,
        parameters=parameters,
        cost_rate_per_side=0.002,
    )
    midpoint = oos_start + int(args.oos_days) * DAY_MS // 2
    oos["first_half_return_pct"] = _segment_return(
        oos_simulation["equity"], oos_start, midpoint
    )
    oos["second_half_return_pct"] = _segment_return(
        oos_simulation["equity"], midpoint, as_of_ms
    )
    rolling = summarize_rolling_fifteen_days(
        oos_simulation["equity"], start_ms=oos_start, end_ms=as_of_ms
    )
    gate_metrics = {
        **oos,
        "positive_rolling_15d_share": rolling["positive_window_share"],
        "stress_total_return_pct": stress["total_return_pct"],
        "stress_profit_factor": stress["profit_factor"],
        "data_complete": len(frames) >= int(args.minimum_symbols)
        and min(coverage.values()) >= 0.97,
    }
    gate = evaluate_gate(gate_metrics)
    _, source_path = _load_strategy_class(args.repo_root, args.strategy_source)
    result = {
        "data_coverage": {
            "root": str(args.data_root),
            "start_ms": data_start,
            "research_start_ms": research_start,
            "as_of_ms": as_of_ms,
            "complete_symbol_count": len(frames),
            "minimum_coverage_ratio": min(coverage.values()),
            "symbols": sorted(frames),
        },
        "assumptions": {
            "initial_equity": 100.0,
            "baseline_cost_rate_per_side": 0.001,
            "stress_cost_rate_per_side": 0.002,
            "funding": "not_modeled",
            "universe": "dynamic_trailing_24h_top20_from_complete_symbols",
        },
        "parameters": parameter_metadata,
        "train": train,
        "validation": validation,
        "out_of_sample": oos,
        "rolling_15d": rolling,
        "stress": stress,
        "gate": gate,
        "source_hash": "sha256:" + hashlib.sha256(source_path.read_bytes()).hexdigest(),
    }
    output_json = Path(args.output_json)
    output_report = Path(args.output_report)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Top20 高频微突破锁利研究结果",
        "",
        f"- 数据截止：`{as_of_ms}`；完整5M标的 `{len(frames)}`。",
        f"- 盲测收益：`{oos['total_return_pct']:.2f}%`。",
        f"- 盲测PF：`{oos['profit_factor']:.3f}`。",
        f"- 盲测最大回撤：`{oos['max_drawdown_pct']:.2f}%`。",
        f"- 日均闭环：`{oos['round_trips_per_day']:.2f}`。",
        f"- 平均持有：`{oos['avg_holding_minutes']:.1f}分钟`。",
        f"- 滚动15日正收益比例：`{rolling['positive_window_share']:.2%}`。",
        f"- 压力成本收益/PF：`{stress['total_return_pct']:.2f}% / {stress['profit_factor']:.3f}`。",
        f"- Paper门槛：`{'通过' if gate['passed'] else '未通过'}`。",
        f"- 未通过原因：`{'；'.join(gate['reasons']) if gate['reasons'] else '无'}`。",
        "",
        "限制：资金费率未建模；Paper 启动前仍需 MCP 动态源码校验和现有实例连续性回读。",
    ]
    output_report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if not gate["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except ResearchDataError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(2)
