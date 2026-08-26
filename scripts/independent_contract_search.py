#!/usr/bin/env python3
"""Independent OKX USDT perpetual strategy search.

This script deliberately does not read BitPro strategy seeds or prior
backtest_results. It scans stored OHLCV parquet data and ranks simple
single-symbol contract strategy families with conservative execution costs.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def ms(value: str) -> int:
    return int(pd.Timestamp(value).value // 10**6)


def symbol_to_dir(symbol: str) -> str:
    return symbol.replace("/", "-").replace(":", "_")


def finite(value: Any, default: float = 0.0) -> float:
    try:
        num = float(value)
    except Exception:
        return default
    return num if math.isfinite(num) else default


def top_contract_symbols(db_path: Path, data_dir: Path, limit: int) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        """
        select symbol, max(coalesce(quote_volume, 0)) as qv
        from ticker_cache
        where exchange = 'okx' and symbol like '%/USDT:USDT'
        group by symbol
        order by qv desc
        limit ?
        """,
        (max(limit * 3, limit),),
    ).fetchall()
    symbols: list[str] = []
    for symbol, _qv in rows:
        folder = data_dir / symbol_to_dir(str(symbol))
        if folder.exists() and any((folder / tf / "202605.parquet").exists() for tf in ("5m", "15m", "1h")):
            symbols.append(str(symbol))
        if len(symbols) >= limit:
            break
    return symbols


def load_ohlcv(data_dir: Path, symbol: str, timeframe: str, warmup_ms: int, end_ms: int) -> pd.DataFrame | None:
    folder = data_dir / symbol_to_dir(symbol) / timeframe
    files = [folder / "202605.parquet"]
    frames = [pd.read_parquet(path) for path in files if path.exists()]
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates("timestamp").sort_values("timestamp")
    df = df[(df["timestamp"] >= warmup_ms) & (df["timestamp"] <= end_ms + 86_400_000)].copy()
    if len(df) < 120:
        return None
    return df.reset_index(drop=True)


def build_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)

    out: dict[str, Any] = {"atr14": true_range.ewm(alpha=1 / 14, adjust=False).mean()}
    for period in (3, 5, 8, 10, 13, 20, 21, 34, 50, 55, 89):
        out[f"ema{period}"] = close.ewm(span=period, adjust=False).mean()

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr = out["atr14"].replace(0, np.nan)
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / 14, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / 14, adjust=False).mean() / atr
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).fillna(0)
    out["adx14"] = dx.ewm(alpha=1 / 14, adjust=False).mean()
    out["plus_di"] = plus_di.fillna(0)
    out["minus_di"] = minus_di.fillna(0)

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    rs = gain.ewm(alpha=1 / 14, adjust=False).mean() / loss.ewm(alpha=1 / 14, adjust=False).mean().replace(0, np.nan)
    out["rsi14"] = (100 - 100 / (1 + rs)).fillna(50)

    for period in (12, 20, 32, 48):
        out[f"don_hi{period}"] = high.shift(1).rolling(period).max()
        out[f"don_lo{period}"] = low.shift(1).rolling(period).min()

    for period in (20, 32):
        middle = close.rolling(period).mean()
        std = close.rolling(period).std()
        out[f"bb_mid{period}"] = middle
        out[f"bb_up{period}"] = middle + 2 * std
        out[f"bb_lo{period}"] = middle - 2 * std

    return pd.DataFrame(out)


def run_backtest(
    df: pd.DataFrame,
    ind: pd.DataFrame,
    kind: str,
    params: dict[str, Any],
    *,
    start_ms: int,
    split_ms: int,
    end_ms: int,
    initial: float,
    cost_bps: float,
) -> dict[str, Any]:
    equity = initial
    peak = initial
    max_drawdown = 0.0
    position = 0
    entry_price = 0.0
    stop_price: float | None = None
    trail_price: float | None = None
    notional = finite(params.get("notional"), 100.0)
    trades: list[dict[str, Any]] = []
    wins = 0
    losses = 0
    gross_profit = 0.0
    gross_loss = 0.0
    last_exit_index = -999_999

    for index in range(100, len(df)):
        timestamp = int(df["timestamp"].iloc[index])
        previous = index - 1
        if timestamp < start_ms or timestamp > end_ms:
            continue
        open_price = finite(df["open"].iloc[index])
        high_price = finite(df["high"].iloc[index])
        low_price = finite(df["low"].iloc[index])
        previous_close = finite(df["close"].iloc[previous])
        atr = finite(ind["atr14"].iloc[previous])
        if atr <= 0 or open_price <= 0:
            continue

        if position:
            exit_price: float | None = None
            reason: str | None = None
            if position > 0:
                new_trail = high_price - finite(params.get("trail_atr"), 2.0) * atr
                trail_price = max(trail_price if trail_price is not None else -1e100, new_trail)
                guard = max(stop_price if stop_price is not None else -1e100, trail_price)
                if low_price <= guard:
                    exit_price = guard
                    reason = "stop"
                elif kind in {"ema", "don"}:
                    fast = finite(ind[f"ema{int(params.get('fast', 5))}"].iloc[previous])
                    slow = finite(ind[f"ema{int(params.get('slow', 20))}"].iloc[previous])
                    if fast < slow:
                        exit_price = open_price
                        reason = "reverse_state"
                elif kind == "bb":
                    middle = finite(ind[f"bb_mid{int(params.get('bb_n', 20))}"].iloc[previous])
                    if previous_close >= middle:
                        exit_price = open_price
                        reason = "mean"
            else:
                new_trail = low_price + finite(params.get("trail_atr"), 2.0) * atr
                trail_price = min(trail_price if trail_price is not None else 1e100, new_trail)
                guard = min(stop_price if stop_price is not None else 1e100, trail_price)
                if high_price >= guard:
                    exit_price = guard
                    reason = "stop"
                elif kind in {"ema", "don"}:
                    fast = finite(ind[f"ema{int(params.get('fast', 5))}"].iloc[previous])
                    slow = finite(ind[f"ema{int(params.get('slow', 20))}"].iloc[previous])
                    if fast > slow:
                        exit_price = open_price
                        reason = "reverse_state"
                elif kind == "bb":
                    middle = finite(ind[f"bb_mid{int(params.get('bb_n', 20))}"].iloc[previous])
                    if previous_close <= middle:
                        exit_price = open_price
                        reason = "mean"

            max_bars = int(params.get("max_bars", 999_999))
            if exit_price is None and trades and index - int(trades[-1]["entry_i"]) >= max_bars:
                exit_price = open_price
                reason = "time"

            if exit_price is not None and exit_price > 0:
                raw_return = (exit_price / entry_price - 1.0) * position
                pnl = notional * raw_return - notional * cost_bps / 10_000
                equity += pnl
                if pnl >= 0:
                    wins += 1
                    gross_profit += pnl
                else:
                    losses += 1
                    gross_loss += -pnl
                trades[-1].update(
                    {
                        "exit_ts": timestamp,
                        "exit_price": exit_price,
                        "pnl": pnl,
                        "reason": reason,
                    }
                )
                position = 0
                entry_price = 0.0
                stop_price = None
                trail_price = None
                last_exit_index = index

        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak * 100 if peak > 0 else 0)
        if equity <= initial * 0.5:
            break

        if position == 0 and index - last_exit_index >= int(params.get("cooldown", 0)):
            side = entry_side(kind, df, ind, previous, params, previous_close, atr)
            if side:
                position = side
                entry_price = open_price
                notional = finite(params.get("notional"), 100.0)
                equity -= notional * cost_bps / 10_000
                if side > 0:
                    stop_price = entry_price - finite(params.get("stop_atr"), 1.5) * atr
                else:
                    stop_price = entry_price + finite(params.get("stop_atr"), 1.5) * atr
                trail_price = stop_price
                trades.append(
                    {
                        "entry_ts": timestamp,
                        "entry_i": index,
                        "entry_price": entry_price,
                        "side": side,
                    }
                )
                peak = max(peak, equity)
                max_drawdown = max(max_drawdown, (peak - equity) / peak * 100 if peak > 0 else 0)

    if position and trades:
        exit_price = finite(df["close"].iloc[-1])
        timestamp = int(df["timestamp"].iloc[-1])
        raw_return = (exit_price / entry_price - 1.0) * position
        pnl = notional * raw_return - notional * cost_bps / 10_000
        equity += pnl
        if pnl >= 0:
            wins += 1
            gross_profit += pnl
        else:
            losses += 1
            gross_loss += -pnl
        trades[-1].update({"exit_ts": timestamp, "exit_price": exit_price, "pnl": pnl, "reason": "final"})

    closed = [trade for trade in trades if "pnl" in trade]
    profit_factor = gross_profit / gross_loss if gross_loss > 1e-9 else (999.0 if gross_profit > 0 else 0.0)
    pnl = equity - initial
    train_pnl = sum(finite(t["pnl"]) for t in closed if int(t.get("exit_ts", 0)) < split_ms)
    valid_pnl = sum(finite(t["pnl"]) for t in closed if int(t.get("exit_ts", 0)) >= split_ms)
    return {
        "final": equity,
        "pnl": pnl,
        "ret_pct": pnl / initial * 100,
        "max_dd": max_drawdown,
        "trades": len(closed),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(closed) * 100 if closed else 0.0,
        "pf": profit_factor,
        "train_pnl": train_pnl,
        "valid_pnl": valid_pnl,
        "sample_trades": closed[-8:],
    }


def entry_side(kind: str, df: pd.DataFrame, ind: pd.DataFrame, i: int, params: dict[str, Any], close: float, atr: float) -> int:
    if kind == "ema":
        fast = int(params.get("fast", 5))
        mid = int(params.get("mid", 10))
        slow = int(params.get("slow", 20))
        slope_bars = int(params.get("slope_b", 3))
        ema_fast = finite(ind[f"ema{fast}"].iloc[i])
        ema_mid = finite(ind[f"ema{mid}"].iloc[i])
        ema_slow = finite(ind[f"ema{slow}"].iloc[i])
        old_fast = finite(ind[f"ema{fast}"].iloc[max(0, i - slope_bars)])
        slope = (ema_fast - old_fast) / max(1, slope_bars)
        adx = finite(ind["adx14"].iloc[i])
        plus_di = finite(ind["plus_di"].iloc[i])
        minus_di = finite(ind["minus_di"].iloc[i])
        spread = abs(ema_fast - ema_slow) / atr
        min_spread = finite(params.get("min_spread_atr"), 0.15)
        min_slope = finite(params.get("min_slope_atr"), 0.01) * atr
        if ema_fast > ema_mid > ema_slow and slope > min_slope and spread >= min_spread and adx >= finite(params.get("adx"), 15) and plus_di >= minus_di:
            return 1
        if ema_fast < ema_mid < ema_slow and slope < -min_slope and spread >= min_spread and adx >= finite(params.get("adx"), 15) and minus_di >= plus_di:
            return -1
        return 0

    if kind == "don":
        period = int(params.get("n", 20))
        if finite(ind["adx14"].iloc[i]) < finite(params.get("adx"), 15):
            return 0
        high_break = finite(ind[f"don_hi{period}"].iloc[i]) + finite(params.get("buf_atr"), 0.0) * atr
        low_break = finite(ind[f"don_lo{period}"].iloc[i]) - finite(params.get("buf_atr"), 0.0) * atr
        if close > high_break:
            return 1
        if close < low_break:
            return -1
        return 0

    if kind == "bb":
        period = int(params.get("bb_n", 20))
        if finite(ind["adx14"].iloc[i]) > finite(params.get("max_adx"), 25):
            return 0
        rsi = finite(ind["rsi14"].iloc[i])
        lower = finite(ind[f"bb_lo{period}"].iloc[i])
        upper = finite(ind[f"bb_up{period}"].iloc[i])
        if close < lower and rsi <= finite(params.get("rsi_low"), 32):
            return 1
        if close > upper and rsi >= finite(params.get("rsi_high"), 68):
            return -1
    return 0


def parameter_grid(profile: str = "full") -> list[tuple[str, dict[str, Any]]]:
    grid: list[tuple[str, dict[str, Any]]] = []
    if profile == "coarse":
        ema_sets = ((3, 8, 21), (5, 10, 20), (8, 21, 55))
        ema_adx = (12, 18, 24)
        ema_spreads = (0.05, 0.30)
        ema_stops = ((1.0, 1.4), (1.8, 2.8))
        don_periods = (12, 20, 32)
        don_adx = (10, 18, 26)
        don_buffers = (0.0, 0.25)
        don_stops = ((1.2, 1.8), (2.4, 3.8))
        bb_periods = (20, 32)
        bb_adx = (24, 30)
        bb_rsi = ((28, 72), (32, 68))
        bb_stops = ((1.0, 1.2), (1.8, 2.4))
    else:
        ema_sets = ((3, 8, 21), (5, 10, 20), (5, 13, 34), (8, 21, 55))
        ema_adx = (12, 18, 24, 30)
        ema_spreads = (0.05, 0.15, 0.30, 0.50)
        ema_stops = ((1.0, 1.4), (1.4, 2.0), (1.8, 2.8), (2.4, 3.6))
        don_periods = (12, 20, 32, 48)
        don_adx = (10, 16, 22, 28)
        don_buffers = (0.0, 0.1, 0.25, 0.5)
        don_stops = ((1.2, 1.8), (1.8, 2.8), (2.4, 3.8))
        bb_periods = (20, 32)
        bb_adx = (18, 24, 30)
        bb_rsi = ((28, 72), (32, 68), (35, 65))
        bb_stops = ((1.0, 1.2), (1.4, 1.8), (2.0, 2.4))

    for notional in (100.0, 150.0):
        for fast, mid, slow in ema_sets:
            for adx in ema_adx:
                for min_spread in ema_spreads:
                    for stop_atr, trail_atr in ema_stops:
                        grid.append(
                            (
                                "ema",
                                {
                                    "notional": notional,
                                    "fast": fast,
                                    "mid": mid,
                                    "slow": slow,
                                    "adx": adx,
                                    "min_spread_atr": min_spread,
                                    "min_slope_atr": 0.01,
                                    "stop_atr": stop_atr,
                                    "trail_atr": trail_atr,
                                    "cooldown": 2,
                                    "max_bars": 96,
                                },
                            )
                        )
        for period in don_periods:
            for adx in don_adx:
                for buffer_atr in don_buffers:
                    for stop_atr, trail_atr in don_stops:
                        grid.append(
                            (
                                "don",
                                {
                                    "notional": notional,
                                    "n": period,
                                    "fast": 5,
                                    "slow": 20,
                                    "adx": adx,
                                    "buf_atr": buffer_atr,
                                    "stop_atr": stop_atr,
                                    "trail_atr": trail_atr,
                                    "cooldown": 2,
                                    "max_bars": 96,
                                },
                            )
                        )
        for period in bb_periods:
            for max_adx in bb_adx:
                for rsi_low, rsi_high in bb_rsi:
                    for stop_atr, trail_atr in bb_stops:
                        grid.append(
                            (
                                "bb",
                                {
                                    "notional": notional,
                                    "bb_n": period,
                                    "rsi_low": rsi_low,
                                    "rsi_high": rsi_high,
                                    "max_adx": max_adx,
                                    "stop_atr": stop_atr,
                                    "trail_atr": trail_atr,
                                    "cooldown": 1,
                                    "max_bars": 48,
                                },
                            )
                        )
    return grid


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="/opt/bitpro/data/crypto_data.db")
    parser.add_argument("--data-dir", default="/opt/bitpro/data/klines/okx")
    parser.add_argument("--output", default="/opt/bitpro/data/research/independent_contract_search_20260526_round1.json")
    parser.add_argument("--symbol-limit", type=int, default=70)
    parser.add_argument("--start", default="2026-05-16T00:00:00Z")
    parser.add_argument("--split", default="2026-05-21T00:00:00Z")
    parser.add_argument("--end", default="2026-05-26T00:00:00Z")
    parser.add_argument("--warmup", default="2026-05-06T00:00:00Z")
    parser.add_argument("--initial", type=float, default=100.0)
    parser.add_argument("--cost-bps", type=float, default=6.0)
    parser.add_argument("--max-dd", type=float, default=18.0)
    parser.add_argument("--profile", choices=("coarse", "full"), default="full")
    parser.add_argument("--timeframes", default="5m,15m,1h")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    db_path = Path(args.db)
    start_ms = ms(args.start)
    split_ms = ms(args.split)
    end_ms = ms(args.end)
    warmup_ms = ms(args.warmup)

    symbols = top_contract_symbols(db_path, data_dir, args.symbol_limit)
    grid = parameter_grid(args.profile)
    timeframes = tuple(item.strip() for item in args.timeframes.split(",") if item.strip())
    print(f"symbols={len(symbols)} params={len(grid)}")
    print("symbol_sample=", symbols[:20])

    results: list[dict[str, Any]] = []
    started = time.time()
    min_rows = {"5m": 1_000, "15m": 300, "1h": 80}
    for symbol_index, symbol in enumerate(symbols, start=1):
        for timeframe in timeframes:
            df = load_ohlcv(data_dir, symbol, timeframe, warmup_ms, end_ms)
            if df is None:
                continue
            target_rows = int(((df["timestamp"] >= start_ms) & (df["timestamp"] <= end_ms)).sum())
            if target_rows < min_rows[timeframe]:
                continue
            ind = build_indicators(df)
            for kind, params in grid:
                if timeframe == "1h" and kind == "bb":
                    continue
                result = run_backtest(
                    df,
                    ind,
                    kind,
                    params,
                    start_ms=start_ms,
                    split_ms=split_ms,
                    end_ms=end_ms,
                    initial=args.initial,
                    cost_bps=args.cost_bps,
                )
                if (
                    result["trades"] >= 2
                    and result["pnl"] > 0
                    and result["train_pnl"] > 0
                    and result["valid_pnl"] > 0
                    and result["max_dd"] <= args.max_dd
                ):
                    results.append({**result, "symbol": symbol, "timeframe": timeframe, "kind": kind, "params": params})
        if symbol_index % 10 == 0:
            print(f"scanned={symbol_index} results={len(results)} elapsed={time.time() - started:.1f}s", flush=True)

    results.sort(key=lambda item: (item["pnl"], item["pf"], -item["max_dd"]), reverse=True)
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": f"{args.start} ~ {args.end}",
        "split": args.split,
        "initial": args.initial,
        "cost_bps_per_side": args.cost_bps,
        "symbols": symbols,
        "result_count": len(results),
        "top": results[:80],
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"saved={output_path} count={len(results)}")
    for rank, result in enumerate(results[:25], start=1):
        print(
            rank,
            result["symbol"],
            result["timeframe"],
            result["kind"],
            "pnl",
            round(result["pnl"], 4),
            "dd",
            round(result["max_dd"], 2),
            "tr",
            result["trades"],
            "pf",
            round(result["pf"], 2),
            "train",
            round(result["train_pnl"], 2),
            "valid",
            round(result["valid_pnl"], 2),
            "params",
            result["params"],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
