#!/usr/bin/env python3
"""Real-data first-passage research for the anti-martingale breakout strategy."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from pathlib import Path


class ResearchDataError(RuntimeError):
    pass


def is_contract_storage_symbol(value):
    return str(value or "").endswith("-USDT_USDT")


def classify_path(values, *, target=200.0, floor=60.0):
    for value in values:
        equity = float(value)
        if equity >= float(target):
            return "target_200"
        if equity <= float(floor):
            return "floor_60"
    return "expired"


def _percentile(values, probability):
    numbers = sorted(float(value) for value in values)
    if not numbers:
        return 0.0
    position = (len(numbers) - 1) * float(probability)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return numbers[lower]
    weight = position - lower
    return numbers[lower] * (1.0 - weight) + numbers[upper] * weight


def summarize_paths(paths, *, target=200.0, floor=60.0):
    if not paths:
        raise ResearchDataError("真实15M K线不足：没有可评估的7日路径")
    outcomes = [classify_path(item["equity"], target=target, floor=floor) for item in paths]
    terminal = [float(item["equity"][-1]) for item in paths]
    gross_profit = sum(max(0.0, float(item.get("gross_profit", 0.0))) for item in paths)
    gross_loss = sum(max(0.0, float(item.get("gross_loss", 0.0))) for item in paths)
    positive_by_symbol = {}
    for item in paths:
        for symbol, pnl in (item.get("symbol_pnl") or {}).items():
            if float(pnl) > 0:
                positive_by_symbol[symbol] = positive_by_symbol.get(symbol, 0.0) + float(pnl)
    total_symbol_profit = sum(positive_by_symbol.values())
    return {
        "window_count": len(paths),
        "target_before_floor_probability": outcomes.count("target_200") / len(paths),
        "floor_before_target_probability": outcomes.count("floor_60") / len(paths),
        "expired_probability": outcomes.count("expired") / len(paths),
        "median_terminal_equity": statistics.median(terminal),
        "p10_terminal_equity": _percentile(terminal, 0.10),
        "p90_terminal_equity": _percentile(terminal, 0.90),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
        "single_symbol_profit_share": (
            max(positive_by_symbol.values()) / total_symbol_profit
            if positive_by_symbol and total_symbol_profit > 0
            else 0.0
        ),
    }


def evaluate_gate(summary):
    reasons = []
    if float(summary["target_before_floor_probability"]) <= float(
        summary["floor_before_target_probability"]
    ):
        reasons.append("翻倍首达概率没有高于60U首达概率")
    if float(summary["median_terminal_equity"]) <= 100.0:
        reasons.append("样本外终值中位数不高于100U")
    if float(summary["profit_factor"]) <= 1.15:
        reasons.append("样本外利润因子不高于1.15")
    if float(summary["single_symbol_profit_share"]) > 0.50:
        reasons.append("单一标的正利润贡献超过50%")
    return {"passed": not reasons, "reasons": reasons, **dict(summary)}


def discover_symbol_files(root, *, start_ms, end_ms, minimum_symbols=2):
    try:
        import pyarrow.parquet as pq
    except Exception as exc:
        raise ResearchDataError(f"真实15M K线不足：pyarrow不可用 ({exc})") from exc
    base = Path(root)
    output = {}
    for timeframe_dir in base.glob("*/15m"):
        if not is_contract_storage_symbol(timeframe_dir.parent.name):
            continue
        paths = sorted(timeframe_dir.glob("*.parquet"))
        if not paths:
            continue
        minimum = None
        maximum = None
        selected = []
        for path in paths:
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
        if selected and minimum is not None and maximum is not None:
            if minimum <= int(start_ms) + 900_000 and maximum >= int(end_ms) - 900_000:
                output[timeframe_dir.parent.name] = selected
    if len(output) < int(minimum_symbols):
        raise ResearchDataError(
            f"真实15M K线不足：需要至少{int(minimum_symbols)}个完整标的，实际{len(output)}个"
        )
    return output


def _load_symbol(paths, start_ms, end_ms):
    import pandas as pd
    import pyarrow.parquet as pq

    frames = []
    columns = ["timestamp", "open", "high", "low", "close", "volume", "quote_volume"]
    for path in paths:
        table = pq.read_table(path, columns=columns)
        frame = table.to_pandas()
        frame = frame[(frame["timestamp"] >= start_ms) & (frame["timestamp"] <= end_ms)]
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=columns)
    result = pd.concat(frames, ignore_index=True)
    return result.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def _ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def _prepare_symbol(frame, symbol):
    import numpy as np
    import pandas as pd

    data = frame.copy()
    data["symbol"] = symbol
    data["donchian_high"] = data["high"].shift(1).rolling(20).max()
    data["donchian_low"] = data["low"].shift(1).rolling(20).min()
    data["volume_median"] = data["volume"].shift(1).rolling(20).median()
    data["hour"] = (data["timestamp"] // 3_600_000) * 3_600_000
    hourly = data.groupby("hour", as_index=False).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"), quote_volume=("quote_volume", "sum"),
    )
    previous = hourly["close"].shift(1)
    tr = pd.concat(
        [(hourly["high"] - hourly["low"]), (hourly["high"] - previous).abs(), (hourly["low"] - previous).abs()],
        axis=1,
    ).max(axis=1)
    hourly["atr14"] = _ema(tr, 14)
    hourly["atr48"] = _ema(tr, 48)
    hourly["ema20"] = _ema(hourly["close"], 20)
    hourly["ema_slope"] = hourly["ema20"].diff()
    hourly["direction"] = np.sign(hourly["ema_slope"])
    hourly["momentum6"] = hourly["close"].pct_change(6) * 100
    hourly["momentum24"] = hourly["close"].pct_change(24) * 100
    hourly["atr_pct"] = hourly["atr14"] / hourly["close"] * 100
    path = hourly["close"].diff().abs().rolling(24).sum()
    hourly["efficiency"] = hourly["close"].diff(24).abs() / path
    hourly["extension_atr"] = (hourly["close"] - hourly["ema20"]).abs() / hourly["atr14"]
    hourly["compression"] = hourly["atr14"] / hourly["atr48"]
    hourly["volume_ratio"] = hourly["volume"] / hourly["volume"].shift(1).rolling(20).median()
    hourly["turnover24"] = hourly["quote_volume"].rolling(24).sum()
    hourly["breakout_high"] = hourly["high"].shift(1).rolling(5).max()
    hourly["breakout_low"] = hourly["low"].shift(1).rolling(5).min()
    hourly["breakout_distance_atr"] = (
        hourly["close"] - hourly["breakout_high"].where(hourly["direction"] > 0, hourly["breakout_low"])
    ).abs() / hourly["atr14"]
    hourly["symbol"] = symbol
    merged = pd.merge_asof(
        data.sort_values("timestamp"), hourly.sort_values("hour"),
        left_on="timestamp", right_on="hour", suffixes=("", "_1h"), direction="backward",
    )
    merged["breakout_distance_atr"] = np.where(
        merged["direction"] > 0,
        (merged["donchian_high"] - merged["close"]).abs() / merged["atr14"],
        (merged["donchian_low"] - merged["close"]).abs() / merged["atr14"],
    )
    return merged, hourly


def build_signals(frames):
    import pandas as pd

    prepared = {}
    hourly_rows = []
    for symbol, frame in frames.items():
        bars, hourly = _prepare_symbol(frame, symbol)
        prepared[symbol] = bars
        hourly_rows.append(hourly)
    cross = pd.concat(hourly_rows, ignore_index=True)
    cross["relative"] = cross["momentum24"] * cross["direction"]
    cross["slope_strength"] = cross["ema_slope"] * cross["direction"]
    rank = lambda column, ascending=True: cross.groupby("hour")[column].rank(pct=True, ascending=ascending) * 100
    cross["score"] = (
        rank("relative") * 0.25 + rank("compression", ascending=False) * 0.20
        + rank("breakout_distance_atr", ascending=False) * 0.15 + rank("efficiency") * 0.15
        + rank("slope_strength") * 0.10 + rank("volume_ratio") * 0.10 + rank("turnover24") * 0.05
    )
    cross["hard_ok"] = (
        cross["atr_pct"].between(2, 8) & (cross["efficiency"] >= 0.12)
        & (cross["extension_atr"] <= 2.5) & (cross["score"] >= 65)
        & (cross["momentum6"] * cross["direction"] > 0)
        & (cross["momentum24"] * cross["direction"] > 0)
    )
    cross["direction_rank"] = cross[cross["hard_ok"]].groupby(["hour", "direction"])["score"].rank(ascending=False)
    cross["selected"] = cross["hard_ok"] & (cross["direction_rank"] <= 5)
    cross = cross.sort_values(["symbol", "hour"])
    cross["confirmed"] = cross["selected"] & cross.groupby("symbol")["selected"].shift(1).fillna(False)
    signal_columns = ["hour", "symbol", "score", "direction", "confirmed", "atr14", "extension_atr"]
    signal_rows = cross[signal_columns]
    for symbol, bars in prepared.items():
        per_symbol = signal_rows[signal_rows["symbol"] == symbol].sort_values("hour")
        bars = pd.merge_asof(
            bars.sort_values("timestamp"), per_symbol, left_on="timestamp", right_on="hour",
            suffixes=("", "_signal"), direction="backward",
        )
        volume_ok = bars["volume"] >= bars["volume_median"] * 1.8
        bars["long_signal"] = bars["confirmed"] & (bars["direction_signal"] > 0) & volume_ok & (bars["close"] > bars["donchian_high"])
        bars["short_signal"] = bars["confirmed"] & (bars["direction_signal"] < 0) & volume_ok & (bars["close"] < bars["donchian_low"])
        prepared[symbol] = bars
    return prepared


def simulate_window(prepared, start_ms, end_ms, *, cost_rate=0.001):
    events = {}
    for symbol, frame in prepared.items():
        sample = frame[(frame["timestamp"] >= start_ms) & (frame["timestamp"] <= end_ms)]
        for row in sample.to_dict("records"):
            events.setdefault(int(row["timestamp"]), []).append((symbol, row))
    cash = 100.0
    positions = {}
    last_close = {}
    equity_path = [100.0]
    symbol_pnl = {}
    gross_profit = gross_loss = 0.0
    day = -1
    day_start = 100.0
    pause_until_day = -1
    equity_floor = 0.0

    def mark_equity():
        value = cash
        for symbol, position in positions.items():
            price = last_close.get(symbol, position["entry"])
            direction = 1.0 if position["side"] == "long" else -1.0
            value += (price - position["entry"]) * direction * position["qty"]
        return value

    def close_position(symbol, price):
        nonlocal cash, gross_profit, gross_loss
        position = positions.pop(symbol)
        direction = 1.0 if position["side"] == "long" else -1.0
        pnl = (price - position["entry"]) * direction * position["qty"]
        pnl -= abs(price * position["qty"]) * cost_rate
        cash += pnl
        symbol_pnl[symbol] = symbol_pnl.get(symbol, 0.0) + pnl
        if pnl >= 0:
            gross_profit += pnl
        else:
            gross_loss += abs(pnl)

    terminal = "expired"
    for timestamp in sorted(events):
        rows = events[timestamp]
        for symbol, row in rows:
            last_close[symbol] = float(row["close"])
        current_day = timestamp // 86_400_000
        if current_day != day:
            day = current_day
            day_start = mark_equity()
            if pause_until_day <= day:
                pause_until_day = -1
        for symbol, row in rows:
            position = positions.get(symbol)
            if position is None:
                continue
            high, low = float(row["high"]), float(row["low"])
            entry, risk = position["entry"], position["risk"]
            previous_stop = position["stop"]
            take_profit = entry + 10 * risk if position["side"] == "long" else entry - 10 * risk
            stop_hit = low <= previous_stop if position["side"] == "long" else high >= previous_stop
            tp_hit = high >= take_profit if position["side"] == "long" else low <= take_profit
            if stop_hit or tp_hit:
                close_position(symbol, previous_stop if stop_hit else take_profit)
                continue
            if position["side"] == "long":
                position["best"] = max(position["best"], high)
                best_r = (position["best"] - entry) / risk
            else:
                position["best"] = min(position["best"], low)
                best_r = (entry - position["best"]) / risk
            if best_r >= 1:
                buffer = entry * 0.001
                position["stop"] = max(position["stop"], entry + buffer) if position["side"] == "long" else min(position["stop"], entry - buffer)
            atr = float(row.get("atr14_signal") or row.get("atr14") or risk / 1.2)
            if best_r >= 2:
                pullback, atr_mult = (0.22, 1.2) if best_r >= 4 else (0.40, 2.0)
                if position["side"] == "long":
                    position["stop"] = max(position["stop"], entry + best_r * (1 - pullback) * risk, position["best"] - atr * atr_mult)
                else:
                    position["stop"] = min(position["stop"], entry - best_r * (1 - pullback) * risk, position["best"] + atr * atr_mult)
            threshold = 1 if position["adds"] == 0 else 2 if position["adds"] == 1 else 999
            if best_r >= threshold and position["adds"] < 2:
                if position["adds"] == 1:
                    position["stop"] = max(position["stop"], entry + 0.8 * risk) if position["side"] == "long" else min(position["stop"], entry - 0.8 * risk)
                mult = 0.5 if position["adds"] == 0 else 0.25
                add_notional = position["initial_notional"] * mult
                add_price = float(row["close"])
                add_qty = add_notional / add_price
                old_notional = position["entry"] * position["qty"]
                position["qty"] += add_qty
                position["entry"] = (old_notional + add_notional) / position["qty"]
                position["adds"] += 1
                cash -= add_notional * cost_rate
        equity = mark_equity()
        for threshold, floor in ((120, 108), (140, 120), (160, 138), (180, 160)):
            if equity >= threshold:
                equity_floor = max(equity_floor, float(floor))
        reason = None
        if equity >= 200:
            reason = "target_200"
        elif equity <= 60:
            reason = "floor_60"
        elif equity_floor and equity < equity_floor:
            reason = "ratchet_exit"
        elif day_start > 0 and equity <= day_start * 0.92:
            reason = "daily_pause"
        if reason:
            for symbol in list(positions):
                close_position(symbol, last_close[symbol])
            equity = mark_equity()
            if reason in {"target_200", "floor_60", "ratchet_exit"}:
                terminal = reason
                equity_path.append(equity)
                break
            pause_until_day = day + 1
        if pause_until_day <= day:
            candidates = []
            for symbol, row in rows:
                if symbol in positions or len(positions) >= 2:
                    continue
                side = "long" if bool(row.get("long_signal")) else "short" if bool(row.get("short_signal")) else None
                if side:
                    candidates.append((float(row.get("score_signal") or row.get("score") or 0), symbol, side, row))
            for score, symbol, side, row in sorted(candidates, reverse=True):
                if len(positions) >= 2:
                    break
                equity = mark_equity()
                risk_usdt = equity * (0.02 if equity < 80 else 0.04)
                price = float(row["close"])
                atr = float(row.get("atr14_signal") or row.get("atr14") or 0)
                risk = min(atr * 1.2, price * 0.03)
                if risk <= 0:
                    continue
                notional = min(risk_usdt / (risk / price), equity * 2.5)
                qty = notional / price
                cash -= notional * cost_rate
                positions[symbol] = {
                    "side": side, "entry": price, "qty": qty, "risk": risk,
                    "stop": price - risk if side == "long" else price + risk,
                    "best": price, "adds": 0, "initial_notional": notional,
                }
        equity_path.append(mark_equity())
    for symbol in list(positions):
        close_position(symbol, last_close[symbol])
    equity_path.append(mark_equity())
    return {
        "equity": equity_path,
        "terminal_reason": terminal,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "symbol_pnl": symbol_pnl,
    }


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="/opt/bitpro/data/klines/okx")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--train-days", type=int, default=60)
    parser.add_argument("--test-days", type=int, default=30)
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--as-of-lag-hours", type=int, default=4)
    parser.add_argument("--minimum-symbols", type=int, default=20)
    parser.add_argument("--top-symbols", type=int, default=60)
    parser.add_argument("--strategy-source", default="scripts/strategy_sources/antimartingale_volatility_breakout.py")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-report", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    as_of_ms = int(time.time() * 1000) - int(args.as_of_lag_hours) * 3_600_000
    start_ms = as_of_ms - int(args.days) * 86_400_000
    files = discover_symbol_files(
        args.data_root,
        start_ms=start_ms,
        end_ms=as_of_ms,
        minimum_symbols=args.minimum_symbols,
    )
    turnover_start = as_of_ms - 86_400_000
    turnover = []
    for symbol, paths in files.items():
        recent = _load_symbol(paths, turnover_start, as_of_ms)
        if not recent.empty:
            turnover.append((float(recent["quote_volume"].fillna(0).sum()), symbol))
    selected = [symbol for _, symbol in sorted(turnover, reverse=True)[: int(args.top_symbols)]]
    if len(selected) < int(args.minimum_symbols):
        raise ResearchDataError(
            f"真实15M K线不足：完整且有成交额的标的只有{len(selected)}个"
        )
    frames = {symbol: _load_symbol(files[symbol], start_ms, as_of_ms) for symbol in selected}
    prepared = build_signals(frames)
    train_end = start_ms + int(args.train_days) * 86_400_000
    oos_start = as_of_ms - int(args.test_days) * 86_400_000
    window_ms = int(args.window_days) * 86_400_000

    def windows(left, right):
        output = []
        cursor = left
        while cursor + window_ms <= right:
            output.append(simulate_window(prepared, cursor, cursor + window_ms))
            cursor += 86_400_000
        return output

    train_paths = windows(start_ms + 7 * 86_400_000, train_end)
    oos_paths = windows(oos_start, as_of_ms)
    train_summary = summarize_paths(train_paths)
    oos_summary = summarize_paths(oos_paths)
    gate = evaluate_gate(oos_summary)
    source = Path(args.strategy_source).read_bytes()
    result = {
        "data_coverage": {
            "root": str(args.data_root), "start_ms": start_ms, "as_of_ms": as_of_ms,
            "complete_symbol_count": len(files), "selected_symbol_count": len(selected),
            "selected_symbols": selected,
        },
        "assumptions": {
            "initial_equity": 100.0, "target_equity": 200.0, "floor_equity": 60.0,
            "fee_plus_slippage_per_side": 0.001, "funding": "not_modeled",
            "universe_bias": "fixed_top60_selected_at_as_of_from_complete_symbols",
        },
        "train": train_summary,
        "out_of_sample": oos_summary,
        "gate": gate,
        "source_hash": "sha256:" + hashlib.sha256(source).hexdigest(),
    }
    output_json = Path(args.output_json)
    output_report = Path(args.output_report)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Top60 波动爆发反马丁冲刺研究结果", "",
        f"- 数据截止：`{as_of_ms}`；完整标的 `{len(files)}`，选取 `{len(selected)}`。",
        f"- 样本外窗口：`{oos_summary['window_count']}`。",
        f"- 先到200U概率：`{oos_summary['target_before_floor_probability']:.2%}`。",
        f"- 先到60U概率：`{oos_summary['floor_before_target_probability']:.2%}`。",
        f"- 终值中位数：`{oos_summary['median_terminal_equity']:.2f}U`。",
        f"- 利润因子：`{oos_summary['profit_factor']:.3f}`。",
        f"- 单一标的正利润贡献：`{oos_summary['single_symbol_profit_share']:.2%}`。",
        f"- Paper门槛：`{'通过' if gate['passed'] else '未通过'}`。",
        f"- 未通过原因：`{'；'.join(gate['reasons']) if gate['reasons'] else '无'}`。",
        "", "限制：使用研究截止时点固定Top60，存在幸存者偏差；资金费率未计入。",
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
