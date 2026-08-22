#!/usr/bin/env python3
"""Fast 1H market-structure strategy screen on cached OKX OHLCV CSVs.

The script is intentionally standalone so it can run on the production host
against the read-only research cache without importing the live BitPro app.
It performs a first-pass screen only; promising candidates still need the
official Backtrader path before they can become runnable seeds.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


Event = Tuple[int, int, float]


DEFAULT_LOOKBACKS = (12, 24, 48, 72)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, help="Directory containing ohlcv_*_1h_*.csv files")
    parser.add_argument("--output", required=True, help="JSON output path")
    parser.add_argument("--start", default="2025-05-16T00:00:00Z")
    parser.add_argument("--end", default="2026-05-15T00:00:00Z")
    parser.add_argument("--initial", type=float, default=100.0)
    parser.add_argument("--fee", type=float, default=0.0005)
    parser.add_argument("--slippage", type=float, default=0.0001)
    parser.add_argument("--min-trades", type=int, default=5)
    parser.add_argument(
        "--symbols",
        default="",
        help="Optional comma-separated BitPro symbols, e.g. BTC/USDT:USDT,ETH/USDT:USDT",
    )
    parser.add_argument(
        "--profile",
        choices=("fast", "full"),
        default="fast",
        help="fast uses a narrow discovery grid; full expands every tested dimension.",
    )
    parser.add_argument(
        "--modes",
        default="all",
        help=(
            "Comma-separated modes to run: fvg_ob_retest, liquidity_sweep_reclaim, "
            "bos_breakout, compression_breakout, or all."
        ),
    )
    return parser.parse_args()


def _ts_ms(value: str) -> int:
    return int(pd.Timestamp(value).timestamp() * 1000)


def _symbol_from_path(path: Path) -> str:
    core = path.name.split("ohlcv_", 1)[1].split("_1h_", 1)[0]
    base_quote, settle = core.rsplit("_", 1)
    base, quote = base_quote.split("-", 1)
    return f"{base}/{quote}:{settle}"


def load_frames(cache_dir: Path, start_ms: int, end_ms: int, symbols: Iterable[str]) -> Dict[str, pd.DataFrame]:
    frames: Dict[str, pd.DataFrame] = {}
    warmup_start = start_ms - 400 * 3_600_000
    symbol_filter = {str(symbol).strip() for symbol in symbols if str(symbol).strip()}
    for path in sorted(cache_dir.glob("ohlcv_*_1h_*.csv")):
        symbol = _symbol_from_path(path)
        if symbol_filter and symbol not in symbol_filter:
            continue
        df = pd.read_csv(path)
        df = df.sort_values("timestamp").reset_index(drop=True)
        df = df[(df["timestamp"] >= warmup_start) & (df["timestamp"] <= end_ms)].copy()
        df = df.reset_index(drop=True)
        if len(df) < 1_000:
            continue
        for column in ("open", "high", "low", "close", "volume"):
            df[column] = pd.to_numeric(df[column], errors="coerce")
        prev_close = df["close"].shift(1)
        true_range = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        df["atr14"] = true_range.rolling(14).mean()
        df["atr_pct"] = df["atr14"] / df["close"]
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
        df["ema100"] = df["close"].ewm(span=100, adjust=False).mean()
        df["vol_sma20"] = df["volume"].rolling(20).mean()
        for lookback in sorted(set(DEFAULT_LOOKBACKS + (96,))):
            df[f"roll_high_{lookback}"] = df["high"].shift(1).rolling(lookback).max()
            df[f"roll_low_{lookback}"] = df["low"].shift(1).rolling(lookback).min()
        shifted_atr_pct = df["atr_pct"].shift(1)
        df["atr_q20_200"] = shifted_atr_pct.rolling(200).quantile(0.2)
        df["atr_q30_200"] = shifted_atr_pct.rolling(200).quantile(0.3)
        frames[symbol] = df
    return frames


def _metrics(
    trades: List[Dict[str, float]],
    *,
    final_equity: float,
    max_drawdown: float,
    initial: float,
    years: float,
) -> Dict[str, float]:
    wins = [trade for trade in trades if trade["pnl"] > 0]
    losses = [trade for trade in trades if trade["pnl"] < 0]
    gross_win = sum(trade["pnl"] for trade in wins)
    gross_loss = abs(sum(trade["pnl"] for trade in losses))
    annual = -100.0
    if final_equity > 0 and initial > 0 and years > 0:
        annual = ((final_equity / initial) ** (1.0 / years) - 1.0) * 100.0
    return {
        "annual_return": annual,
        "total_return": (final_equity / initial - 1.0) * 100.0,
        "max_drawdown": max_drawdown * 100.0,
        "trades": len(trades),
        "win_rate": (len(wins) / len(trades) * 100.0) if trades else 0.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 1e-12 else (99.0 if gross_win > 0 else 0.0),
        "avg_pnl": statistics.mean([trade["pnl"] for trade in trades]) if trades else 0.0,
        "final": final_equity,
    }


def simulate_events(
    df: pd.DataFrame,
    events: Iterable[Event],
    *,
    rr: float,
    stop_buffer_atr: float,
    max_hold: int,
    notional_mult: float,
    start_ms: int,
    end_ms: int,
    initial: float,
    fee: float,
    slippage: float,
) -> Optional[Dict[str, float]]:
    events = list(events)
    if not events:
        return None
    timestamps = df["timestamp"].to_numpy(dtype=np.int64)
    opens = df["open"].to_numpy(float)
    closes = df["close"].to_numpy(float)
    atr_values = df["atr14"].to_numpy(float)
    years = (end_ms - start_ms) / (365.0 * 24 * 3_600_000)
    equity = float(initial)
    peak = float(initial)
    max_drawdown = 0.0
    trades: List[Dict[str, float]] = []
    last_exit_idx = -1
    limit_idx = len(df) - 1

    for idx, side, stop_ref in events:
        if idx + 1 >= len(df) or idx <= last_exit_idx:
            continue
        if timestamps[idx] < start_ms or timestamps[idx] > end_ms:
            continue
        if not math.isfinite(stop_ref) or not math.isfinite(atr_values[idx]) or atr_values[idx] <= 0:
            continue
        entry_idx = idx + 1
        if timestamps[entry_idx] > end_ms:
            continue
        raw_entry = opens[entry_idx]
        if raw_entry <= 0 or not math.isfinite(raw_entry):
            continue

        entry = raw_entry * (1.0 + slippage * side)
        if side > 0:
            stop = min(float(stop_ref) - stop_buffer_atr * atr_values[idx], entry - 0.15 * atr_values[idx])
            if stop <= 0 or stop >= entry:
                stop = entry - max(0.5, stop_buffer_atr) * atr_values[idx]
            risk = entry - stop
            take = entry + rr * risk
        else:
            stop = max(float(stop_ref) + stop_buffer_atr * atr_values[idx], entry + 0.15 * atr_values[idx])
            if stop <= entry:
                stop = entry + max(0.5, stop_buffer_atr) * atr_values[idx]
            risk = stop - entry
            take = entry - rr * risk
        if risk <= 0 or not math.isfinite(risk):
            continue

        notional = max(0.0, equity * notional_mult)
        if notional <= 1e-9:
            break
        quantity = notional / entry
        entry_fee = notional * fee
        equity -= entry_fee
        min_equity = equity
        exit_signal_idx = min(limit_idx - 1, entry_idx + max_hold)
        reason = "max_hold"
        for cursor in range(entry_idx, min(limit_idx, entry_idx + max_hold) + 1):
            mark_unrealized = side * quantity * (closes[cursor] - entry)
            min_equity = min(min_equity, equity + mark_unrealized)
            if side > 0:
                if closes[cursor] <= stop:
                    exit_signal_idx = cursor
                    reason = "stop"
                    break
                if closes[cursor] >= take:
                    exit_signal_idx = cursor
                    reason = "take"
                    break
            else:
                if closes[cursor] >= stop:
                    exit_signal_idx = cursor
                    reason = "stop"
                    break
                if closes[cursor] <= take:
                    exit_signal_idx = cursor
                    reason = "take"
                    break

        exit_idx = min(limit_idx, exit_signal_idx + 1)
        if timestamps[exit_idx] > end_ms:
            exit_idx = int(np.searchsorted(timestamps, end_ms, side="right") - 1)
            if exit_idx <= entry_idx:
                continue
        raw_exit = opens[exit_idx]
        if raw_exit <= 0 or not math.isfinite(raw_exit):
            continue
        exit_price = raw_exit * (1.0 - slippage * side)
        gross_pnl = side * quantity * (exit_price - entry)
        exit_fee = abs(quantity * exit_price) * fee
        pnl = gross_pnl - entry_fee - exit_fee

        if peak > 0:
            max_drawdown = max(max_drawdown, max(0.0, (peak - min_equity) / peak))
        equity += gross_pnl - exit_fee
        if equity <= 0:
            max_drawdown = 1.0
            trades.append({"pnl": -initial, "side": float(side), "reason": 0.0})
            break
        if peak > 0:
            max_drawdown = max(max_drawdown, max(0.0, (peak - equity) / peak))
        peak = max(peak, equity)
        trades.append({"pnl": pnl, "side": float(side), "reason": 1.0 if reason == "take" else -1.0})
        last_exit_idx = exit_idx

    if not trades:
        return None
    result = _metrics(trades, final_equity=equity, max_drawdown=max_drawdown, initial=initial, years=years)
    result["take_exits"] = sum(1 for trade in trades if trade["reason"] == 1.0)
    result["stop_exits"] = sum(1 for trade in trades if trade["reason"] == -1.0)
    return result


def _passes_trend(df: pd.DataFrame, idx: int, side: int, trend: str) -> bool:
    if trend == "none":
        return True
    close = float(df.at[idx, "close"])
    ema = float(df.at[idx, "ema50"])
    if not math.isfinite(ema):
        return False
    if trend == "with":
        return close > ema if side > 0 else close < ema
    if trend == "meanrev":
        return close < ema if side > 0 else close > ema
    return True


def fvg_events(
    df: pd.DataFrame,
    *,
    min_gap_atr: float,
    min_gap_pct: float,
    max_age: int,
    reclaim: float,
    trend: str,
) -> List[Event]:
    highs = df["high"].to_numpy(float)
    lows = df["low"].to_numpy(float)
    opens = df["open"].to_numpy(float)
    closes = df["close"].to_numpy(float)
    atr_values = df["atr14"].to_numpy(float)
    long_zone: Optional[Tuple[float, float, int, float]] = None
    short_zone: Optional[Tuple[float, float, int, float]] = None
    events: List[Event] = []

    for idx in range(2, len(df) - 1):
        if long_zone is not None:
            lower, upper, created, stop_ref = long_zone
            if idx - created > max_age or closes[idx] < stop_ref:
                long_zone = None
            elif lows[idx] <= upper and closes[idx] >= lower + reclaim * (upper - lower):
                if _passes_trend(df, idx, 1, trend):
                    events.append((idx, 1, stop_ref))
                    long_zone = None
        if short_zone is not None:
            lower, upper, created, stop_ref = short_zone
            if idx - created > max_age or closes[idx] > stop_ref:
                short_zone = None
            elif highs[idx] >= lower and closes[idx] <= upper - reclaim * (upper - lower):
                if _passes_trend(df, idx, -1, trend):
                    events.append((idx, -1, stop_ref))
                    short_zone = None

        if not math.isfinite(atr_values[idx]) or atr_values[idx] <= 0:
            continue
        min_gap = max(min_gap_pct * closes[idx], min_gap_atr * atr_values[idx])
        bull_gap = lows[idx] - highs[idx - 2]
        bear_gap = lows[idx - 2] - highs[idx]
        if bull_gap > min_gap:
            ob_low = highs[idx - 2]
            for prior in range(idx - 1, max(-1, idx - 9), -1):
                if closes[prior] < opens[prior]:
                    ob_low = min(opens[prior], closes[prior])
                    break
            long_zone = (highs[idx - 2], lows[idx], idx, min(highs[idx - 2], ob_low))
        if bear_gap > min_gap:
            ob_high = lows[idx - 2]
            for prior in range(idx - 1, max(-1, idx - 9), -1):
                if closes[prior] > opens[prior]:
                    ob_high = max(opens[prior], closes[prior])
                    break
            short_zone = (highs[idx], lows[idx - 2], idx, max(lows[idx - 2], ob_high))
    return events


def _run_candidate(
    results: List[Dict[str, object]],
    *,
    df: pd.DataFrame,
    symbol: str,
    mode: str,
    events: List[Event],
    params: Dict[str, object],
    args: argparse.Namespace,
    start_ms: int,
    end_ms: int,
) -> None:
    if len(events) < args.min_trades:
        return
    metrics = simulate_events(
        df,
        events,
        rr=float(params["rr"]),
        stop_buffer_atr=float(params["stop_buf_atr"]),
        max_hold=int(params["max_hold"]),
        notional_mult=float(params["notional_mult"]),
        start_ms=start_ms,
        end_ms=end_ms,
        initial=args.initial,
        fee=args.fee,
        slippage=args.slippage,
    )
    if not metrics or metrics["trades"] < args.min_trades:
        return
    results.append({"symbol": symbol, "mode": mode, "params": params, **metrics})


def run_screen(args: argparse.Namespace) -> Dict[str, object]:
    start_ms = _ts_ms(args.start)
    end_ms = _ts_ms(args.end)
    requested_symbols = [item.strip() for item in str(args.symbols or "").split(",") if item.strip()]
    frames = load_frames(Path(args.cache_dir), start_ms, end_ms, requested_symbols)
    results: List[Dict[str, object]] = []
    requested_modes = {item.strip() for item in str(args.modes or "all").split(",") if item.strip()}
    all_modes = "all" in requested_modes
    if args.profile == "full":
        fvg_min_gap_atr = (0.05, 0.1, 0.2)
        fvg_reclaim = (0.3, 0.5, 0.7)
        fvg_trends = ("none", "with")
        sweep_trends = ("none", "meanrev", "with")
        bos_emas = (0, 50, 100)
        stop_grid = (0.0, 0.5, 1.0)
        stop_grid_positive = (0.25, 0.5, 1.0)
        max_hold_grid = (12, 24, 48)
        compression_columns = ("atr_q20_200", "atr_q30_200")
    else:
        fvg_min_gap_atr = (0.1, 0.2)
        fvg_reclaim = (0.5,)
        fvg_trends = ("none", "with")
        sweep_trends = ("none", "meanrev")
        bos_emas = (0, 50)
        stop_grid = (0.0, 0.5)
        stop_grid_positive = (0.25, 0.5)
        max_hold_grid = (12, 24)
        compression_columns = ("atr_q20_200",)

    for symbol, df in frames.items():
        high = df["high"]
        low = df["low"]
        close = df["close"]
        volume = df["volume"]

        if all_modes or "fvg_ob_retest" in requested_modes:
            for min_gap_atr in fvg_min_gap_atr:
                for min_gap_pct in (0.0, 0.0005):
                    for max_age in (12, 24, 48):
                        for reclaim in fvg_reclaim:
                            for trend in fvg_trends:
                                events = fvg_events(
                                    df,
                                    min_gap_atr=min_gap_atr,
                                    min_gap_pct=min_gap_pct,
                                    max_age=max_age,
                                    reclaim=reclaim,
                                    trend=trend,
                                )
                                for rr in (1.5, 2.5):
                                    for stop_buf in (0.25, 0.5):
                                        for max_hold in (12, 24):
                                            for notional in (1.5, 3.0):
                                                _run_candidate(
                                                    results,
                                                    df=df,
                                                    symbol=symbol,
                                                    mode="fvg_ob_retest",
                                                    events=events,
                                                    params={
                                                        "min_gap_atr": min_gap_atr,
                                                        "min_gap_pct": min_gap_pct,
                                                        "max_age": max_age,
                                                        "reclaim": reclaim,
                                                        "trend": trend,
                                                        "rr": rr,
                                                        "stop_buf_atr": stop_buf,
                                                        "max_hold": max_hold,
                                                        "notional_mult": notional,
                                                    },
                                                    args=args,
                                                    start_ms=start_ms,
                                                    end_ms=end_ms,
                                                )

        if all_modes or "liquidity_sweep_reclaim" in requested_modes:
            for lookback in (12, 24, 48):
                prev_low = df[f"roll_low_{lookback}"]
                prev_high = df[f"roll_high_{lookback}"]
                for sweep_pct in (0.0, 0.001, 0.002):
                    for vol_mult in (0.0, 1.2):
                        vol_ok = pd.Series(True, index=df.index) if vol_mult <= 0 else (volume > df["vol_sma20"] * vol_mult)
                        long_base = (low < prev_low * (1.0 - sweep_pct)) & (close > prev_low) & vol_ok
                        short_base = (high > prev_high * (1.0 + sweep_pct)) & (close < prev_high) & vol_ok
                        for trend in sweep_trends:
                            long_signal = long_base.copy()
                            short_signal = short_base.copy()
                            if trend == "meanrev":
                                long_signal &= close < df["ema50"]
                                short_signal &= close > df["ema50"]
                            elif trend == "with":
                                long_signal &= close > df["ema50"]
                                short_signal &= close < df["ema50"]
                            events = [(int(idx), 1, float(low.iat[idx])) for idx in np.where(long_signal.fillna(False).to_numpy())[0]]
                            events += [(int(idx), -1, float(high.iat[idx])) for idx in np.where(short_signal.fillna(False).to_numpy())[0]]
                            events.sort(key=lambda item: item[0])
                            for rr in (1.2, 1.8, 2.5):
                                for stop_buf in stop_grid_positive:
                                    for max_hold in (6, 12, 24):
                                        for notional in (1.5, 3.0):
                                            _run_candidate(
                                                results,
                                                df=df,
                                                symbol=symbol,
                                                mode="liquidity_sweep_reclaim",
                                                events=events,
                                                params={
                                                    "lookback": lookback,
                                                    "sweep_pct": sweep_pct,
                                                    "vol_mult": vol_mult,
                                                    "trend": trend,
                                                    "rr": rr,
                                                    "stop_buf_atr": stop_buf,
                                                    "max_hold": max_hold,
                                                    "notional_mult": notional,
                                                },
                                                args=args,
                                                start_ms=start_ms,
                                                end_ms=end_ms,
                                            )

        if all_modes or "bos_breakout" in requested_modes:
            for lookback in (12, 24, 48, 72):
                prev_low = df[f"roll_low_{lookback}"]
                prev_high = df[f"roll_high_{lookback}"]
                for breakout_pct in (0.0, 0.001, 0.002):
                    for vol_mult in (0.0, 1.2):
                        vol_ok = pd.Series(True, index=df.index) if vol_mult <= 0 else (volume > df["vol_sma20"] * vol_mult)
                        long_base = (close > prev_high * (1.0 + breakout_pct)) & vol_ok
                        short_base = (close < prev_low * (1.0 - breakout_pct)) & vol_ok
                        for ema_window in bos_emas:
                            long_signal = long_base.copy()
                            short_signal = short_base.copy()
                            if ema_window:
                                ema_column = f"ema{ema_window}"
                                long_signal &= close > df[ema_column]
                                short_signal &= close < df[ema_column]
                            events = [(int(idx), 1, float(prev_low.iat[idx])) for idx in np.where(long_signal.fillna(False).to_numpy())[0]]
                            events += [(int(idx), -1, float(prev_high.iat[idx])) for idx in np.where(short_signal.fillna(False).to_numpy())[0]]
                            events.sort(key=lambda item: item[0])
                            for rr in (1.2, 1.8, 2.5):
                                for stop_buf in stop_grid:
                                    for max_hold in max_hold_grid:
                                        for notional in (1.5, 3.0):
                                            _run_candidate(
                                                results,
                                                df=df,
                                                symbol=symbol,
                                                mode="bos_breakout",
                                                events=events,
                                                params={
                                                    "lookback": lookback,
                                                    "breakout_pct": breakout_pct,
                                                    "vol_mult": vol_mult,
                                                    "ema": ema_window,
                                                    "rr": rr,
                                                    "stop_buf_atr": stop_buf,
                                                    "max_hold": max_hold,
                                                    "notional_mult": notional,
                                                },
                                                args=args,
                                                start_ms=start_ms,
                                                end_ms=end_ms,
                                            )

        if all_modes or "compression_breakout" in requested_modes:
            for lookback in (12, 24):
                prev_low = df[f"roll_low_{lookback}"]
                prev_high = df[f"roll_high_{lookback}"]
                for compression_column in compression_columns:
                    compressed = df["atr_pct"].shift(1) < df[compression_column]
                    for breakout_pct in (0.0, 0.001):
                        for vol_mult in (0.0, 1.2):
                            vol_ok = pd.Series(True, index=df.index) if vol_mult <= 0 else (volume > df["vol_sma20"] * vol_mult)
                            long_signal = compressed & (close > prev_high * (1.0 + breakout_pct)) & vol_ok & (close > df["ema50"])
                            short_signal = compressed & (close < prev_low * (1.0 - breakout_pct)) & vol_ok & (close < df["ema50"])
                            events = [(int(idx), 1, float(prev_low.iat[idx])) for idx in np.where(long_signal.fillna(False).to_numpy())[0]]
                            events += [(int(idx), -1, float(prev_high.iat[idx])) for idx in np.where(short_signal.fillna(False).to_numpy())[0]]
                            events.sort(key=lambda item: item[0])
                            for rr in (1.2, 1.8, 2.5):
                                for stop_buf in stop_grid:
                                    for max_hold in max_hold_grid:
                                        for notional in (1.5, 3.0):
                                            _run_candidate(
                                                results,
                                                df=df,
                                                symbol=symbol,
                                                mode="compression_breakout",
                                                events=events,
                                                params={
                                                    "lookback": lookback,
                                                    "compression": compression_column,
                                                    "breakout_pct": breakout_pct,
                                                    "vol_mult": vol_mult,
                                                    "ema": 50,
                                                    "rr": rr,
                                                    "stop_buf_atr": stop_buf,
                                                    "max_hold": max_hold,
                                                    "notional_mult": notional,
                                                },
                                                args=args,
                                                start_ms=start_ms,
                                                end_ms=end_ms,
                                            )

    for result in results:
        result["target_met"] = bool(result["annual_return"] >= 100.0 and result["max_drawdown"] <= 20.0)
        result["high_risk_over_100"] = bool(result["annual_return"] >= 100.0 and result["max_drawdown"] > 20.0)
        result["score"] = (
            float(result["annual_return"])
            - max(0.0, float(result["max_drawdown"]) - 20.0) * 8.0
            + min(int(result["trades"]), 80) * 0.05
        )

    target = [result for result in results if result["target_met"]]
    high_risk = [result for result in results if result["high_risk_over_100"]]
    best_by_mode: Dict[str, Dict[str, object]] = {}
    for result in results:
        current = best_by_mode.get(str(result["mode"]))
        if current is None or float(result["score"]) > float(current["score"]):
            best_by_mode[str(result["mode"])] = result
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assumptions": {
            "start": pd.Timestamp(args.start).isoformat(),
            "end": pd.Timestamp(args.end).isoformat(),
            "fee": args.fee,
            "slippage": args.slippage,
            "initial": args.initial,
            "execution": "signal on confirmed 1H close, entry/exit on next open, close-based stop/take checks",
            "funding": "not applied in this fast screen",
        },
        "candidate_count": len(results),
        "symbols": sorted(frames.keys()),
        "target_count": len(target),
        "high_risk_over_100_count": len(high_risk),
        "best_by_mode": best_by_mode,
        "top_target": sorted(target, key=lambda item: float(item["annual_return"]), reverse=True)[:50],
        "top_score": sorted(results, key=lambda item: float(item["score"]), reverse=True)[:50],
        "high_risk_over_100": sorted(high_risk, key=lambda item: float(item["annual_return"]), reverse=True)[:50],
    }


def main() -> None:
    args = parse_args()
    payload = run_screen(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    summary = {
        "output": str(output),
        "candidate_count": payload["candidate_count"],
        "target_count": payload["target_count"],
        "high_risk_over_100_count": payload["high_risk_over_100_count"],
        "best_by_mode": {
            mode: {
                "symbol": item["symbol"],
                "annual_return": round(float(item["annual_return"]), 4),
                "max_drawdown": round(float(item["max_drawdown"]), 4),
                "trades": item["trades"],
                "params": item["params"],
            }
            for mode, item in payload["best_by_mode"].items()
        },
        "top_target": [
            {
                "symbol": item["symbol"],
                "mode": item["mode"],
                "annual_return": round(float(item["annual_return"]), 4),
                "max_drawdown": round(float(item["max_drawdown"]), 4),
                "trades": item["trades"],
                "params": item["params"],
            }
            for item in payload["top_target"][:10]
        ],
        "top_score": [
            {
                "symbol": item["symbol"],
                "mode": item["mode"],
                "annual_return": round(float(item["annual_return"]), 4),
                "max_drawdown": round(float(item["max_drawdown"]), 4),
                "trades": item["trades"],
                "target_met": item["target_met"],
                "params": item["params"],
            }
            for item in payload["top_score"][:10]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
