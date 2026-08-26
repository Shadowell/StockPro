"""TradFi 杠杆 ETF / 高波动美股永续趋势策略研究脚本（切片 1 研究闸门）。

用途：
1. 用 ccxt 直接从 OKX 拉取 TradFi7 标的的 15m/1h 真实 OHLCV（自上市起，不足 200 天则取全量）；
2. 回测对比两个版本：
   - A 基线：裸 15m EMA5/20 状态交叉（连续 2 根确认）+ 1.5 ATR 止损 + 反向平仓；
   - B 完整设计：A + 1H EMA6/24 方向门 + 1H 效率比 regime 门 + 美股时段窗口（UTC 13-21 开仓）
     + 浮盈锁利（0.8R 保本 / 1.2R ATR 跟踪 / 峰值回撤 25%→2R 后 18% / 16 根时间止盈）
     + 账户级利润棘轮（每 +25% 抬地板，跌破地板暂停新开仓）；
3. 输出每标的与组合级对比指标：净收益、最大回撤、胜率、交易数、利润回吐比。

真实数据约束：不使用 mock/synthetic 行情；OKX 拉不到的区间直接缩短样本并在输出标注。
运行（生产服务器）：
    /opt/bitpro/backend/venv/bin/python research_tradfi_leveraged_trend.py --out /tmp/tradfi_research
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

SYMBOLS = [
    "SNXX/USDT:USDT",
    "SOXL/USDT:USDT",
    "SNDK/USDT:USDT",
    "MU/USDT:USDT",
    "SKHYNIX/USDT:USDT",
    "MSTR/USDT:USDT",
    "TSLA/USDT:USDT",
]
ETF_SYMBOLS = {"SNXX/USDT:USDT", "SOXL/USDT:USDT"}

FEE_BPS = 5.0
SLIPPAGE_BPS = 5.0
COST_PCT = (FEE_BPS + SLIPPAGE_BPS) / 10000.0

INITIAL_CAPITAL = 100.0
BASE_NOTIONAL = 30.0
ETF_SIZE_MULT = 0.5

FAST, SLOW = 5, 20
CONFIRM_BARS = 2
ATR_WINDOW = 14
ATR_STOP_MULT = 1.5

H1_FAST, H1_SLOW = 6, 24
ER_WINDOW = 24
ER_MIN = 0.25
SESSION_START_UTC, SESSION_END_UTC = 13, 21

BREAK_EVEN_AT_R = 0.8
TRAIL_START_R = 1.2
TRAIL_ATR_MULT = 1.2
PEAK_PULLBACK = 0.25
TIGHTEN_AT_R = 2.0
TIGHT_PULLBACK = 0.18
MAX_PROFIT_HOLD_BARS = 16
PROFIT_DECAY_EXIT = 0.65

RATCHET_STEP_PCT = 25.0


def fetch_ohlcv_all(exchange, symbol: str, timeframe: str, max_days: int = 200) -> List[List[float]]:
    """向前分页拉取全量历史，直到交易所返回空。"""
    tf_ms = exchange.parse_timeframe(timeframe) * 1000
    since = exchange.milliseconds() - max_days * 86400_000
    out: List[List[float]] = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=300)
        if not batch:
            if not out and since < exchange.milliseconds() - tf_ms * 400:
                since += tf_ms * 300  # 上市时间晚于窗口起点时向后跳
                if since > exchange.milliseconds():
                    break
                continue
            break
        if out and batch[-1][0] <= out[-1][0]:
            break
        out.extend(b for b in batch if not out or b[0] > out[-1][0])
        since = out[-1][0] + tf_ms
        if since > exchange.milliseconds() - tf_ms:
            break
        time.sleep(exchange.rateLimit / 1000.0)
    return out


def ema_series(values: List[float], window: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < window:
        return out
    alpha = 2.0 / (window + 1)
    seed = sum(values[:window]) / window
    out[window - 1] = seed
    prev = seed
    for i in range(window, len(values)):
        prev = values[i] * alpha + prev * (1 - alpha)
        out[i] = prev
    return out


def atr_series(bars: List[List[float]], window: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(bars)
    trs: List[float] = []
    for i, b in enumerate(bars):
        if i == 0:
            trs.append(b[2] - b[3])
        else:
            prev_close = bars[i - 1][4]
            trs.append(max(b[2] - b[3], abs(b[2] - prev_close), abs(b[3] - prev_close)))
        if i >= window:
            out[i] = sum(trs[i - window + 1 : i + 1]) / window
    return out


def efficiency_ratio(closes: List[float], window: int, idx: int) -> Optional[float]:
    if idx < window:
        return None
    segment = closes[idx - window : idx + 1]
    direction = abs(segment[-1] - segment[0])
    path = sum(abs(segment[i + 1] - segment[i]) for i in range(len(segment) - 1))
    return direction / path if path > 0 else 0.0


@dataclass
class Position:
    side: str
    entry: float
    stop: float
    notional: float
    qty: float
    entry_idx: int
    initial_risk: float
    peak_r: float = 0.0
    breakeven_armed: bool = False


@dataclass
class SimResult:
    trades: int = 0
    wins: int = 0
    pnl: float = 0.0
    equity_curve: List[float] = field(default_factory=list)
    chop_losses: int = 0  # regime 门本应关闭时段产生的亏损笔数（A 版诊断用）


def h1_context(bars_1h: List[List[float]]) -> Tuple[List[Optional[int]], List[Optional[float]]]:
    closes = [b[4] for b in bars_1h]
    fast = ema_series(closes, H1_FAST)
    slow = ema_series(closes, H1_SLOW)
    direction: List[Optional[int]] = [None] * len(bars_1h)
    ers: List[Optional[float]] = [None] * len(bars_1h)
    for i in range(len(bars_1h)):
        if fast[i] is not None and slow[i] is not None:
            direction[i] = 1 if fast[i] > slow[i] else -1
        ers[i] = efficiency_ratio(closes, ER_WINDOW, i)
    return direction, ers


def run_sim(
    bars_15m: List[List[float]],
    bars_1h: List[List[float]],
    *,
    full_design: bool,
    size_mult: float,
    reversal_mode: str = "instant",  # instant | confirm2 | off
    atr_stop_mult: float = ATR_STOP_MULT,
    loss_cooldown_bars: int = 0,
    signal_tf_ms: int = 3600_000,
) -> SimResult:
    closes = [b[4] for b in bars_15m]
    fast = ema_series(closes, FAST)
    slow = ema_series(closes, SLOW)
    atr15 = atr_series(bars_15m, ATR_WINDOW)
    h1_dir, h1_er = h1_context(bars_1h)
    h1_ts = [b[0] for b in bars_1h]

    res = SimResult()
    equity = INITIAL_CAPITAL
    ratchet_floor = 0.0
    pos: Optional[Position] = None
    state_streak = 0
    last_state = 0
    cooldown_until_idx = -1

    def h1_index(ts: int) -> int:
        # 最近一根已完成 1H（时间戳 <= ts - 1h）
        lo, hi, ans = 0, len(h1_ts) - 1, -1
        target = ts - signal_tf_ms
        while lo <= hi:
            mid = (lo + hi) // 2
            if h1_ts[mid] <= target:
                ans = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return ans

    for i in range(1, len(bars_15m)):
        ts, o, h, l, c, *_ = bars_15m[i]
        if fast[i] is None or slow[i] is None or atr15[i] is None:
            res.equity_curve.append(equity)
            continue

        state = 1 if fast[i] > slow[i] else -1
        state_streak = state_streak + 1 if state == last_state else 1
        last_state = state

        hi_idx = h1_index(ts)
        h1d = h1_dir[hi_idx] if hi_idx >= 0 else None
        er = h1_er[hi_idx] if hi_idx >= 0 else None
        regime_ok = er is not None and er >= ER_MIN
        hour = (ts // 3600_000) % 24
        in_session = SESSION_START_UTC <= hour < SESSION_END_UTC

        # --- 持仓管理 ---
        if pos is not None:
            exit_price = None
            r_now = ((c - pos.entry) if pos.side == "long" else (pos.entry - c)) / pos.initial_risk
            pos.peak_r = max(pos.peak_r, ((h - pos.entry) if pos.side == "long" else (pos.entry - l)) / pos.initial_risk)

            if full_design:
                if not pos.breakeven_armed and pos.peak_r >= BREAK_EVEN_AT_R:
                    pos.breakeven_armed = True
                    be = pos.entry * (1 + 0.0005) if pos.side == "long" else pos.entry * (1 - 0.0005)
                    pos.stop = max(pos.stop, be) if pos.side == "long" else min(pos.stop, be)
                if pos.peak_r >= TRAIL_START_R:
                    trail = (c - TRAIL_ATR_MULT * atr15[i]) if pos.side == "long" else (c + TRAIL_ATR_MULT * atr15[i])
                    pos.stop = max(pos.stop, trail) if pos.side == "long" else min(pos.stop, trail)
                pullback = TIGHT_PULLBACK if pos.peak_r >= TIGHTEN_AT_R else PEAK_PULLBACK
                if pos.peak_r > 0.5 and r_now < pos.peak_r * (1 - pullback) and r_now > 0:
                    exit_price = c
                if i - pos.entry_idx >= MAX_PROFIT_HOLD_BARS and pos.peak_r > 0 and r_now < pos.peak_r * PROFIT_DECAY_EXIT:
                    exit_price = c

            stop_hit = (l <= pos.stop) if pos.side == "long" else (h >= pos.stop)
            if stop_hit:
                exit_price = pos.stop
            opposite = (pos.side == "long" and state == -1) or (pos.side == "short" and state == 1)
            if reversal_mode == "instant":
                reverse = opposite
            elif reversal_mode == "confirm2":
                reverse = opposite and state_streak >= 2
            else:
                reverse = False
            if exit_price is None and reverse:
                exit_price = c

            if exit_price is not None:
                gross = (exit_price - pos.entry) * pos.qty if pos.side == "long" else (pos.entry - exit_price) * pos.qty
                cost = (pos.notional + abs(exit_price * pos.qty)) * COST_PCT
                pnl = gross - cost
                equity += pnl
                res.trades += 1
                res.pnl += pnl
                if pnl > 0:
                    res.wins += 1
                else:
                    if not regime_ok:
                        res.chop_losses += 1
                    if loss_cooldown_bars > 0:
                        cooldown_until_idx = i + loss_cooldown_bars
                pos = None

        # --- 开仓 ---
        if pos is None and state_streak >= CONFIRM_BARS and atr15[i] > 0 and i >= cooldown_until_idx:
            allowed = True
            if full_design:
                allowed = (
                    in_session
                    and regime_ok
                    and h1d is not None
                    and h1d == state
                    and (ratchet_floor <= 0 or equity > ratchet_floor)
                )
            if allowed:
                side = "long" if state == 1 else "short"
                notional = BASE_NOTIONAL * size_mult
                qty = notional / c
                stop = c - atr_stop_mult * atr15[i] if side == "long" else c + atr_stop_mult * atr15[i]
                risk = abs(c - stop)
                if risk > 0:
                    pos = Position(side, c, stop, notional, qty, i, risk)

        # --- 棘轮 ---
        if full_design:
            base = max(INITIAL_CAPITAL, ratchet_floor if ratchet_floor > 0 else INITIAL_CAPITAL)
            if equity >= base * (1 + RATCHET_STEP_PCT / 100.0):
                gain = equity - base
                ratchet_floor = base + gain / 2.0

        res.equity_curve.append(equity)

    return res


def aggregate_bars(bars: List[List[float]], bucket_ms: int) -> List[List[float]]:
    """把低周期 K 线聚合成高周期（按时间桶，忽略不完整的最后一桶）。"""
    out: List[List[float]] = []
    bucket: List[List[float]] = []
    bucket_start: Optional[int] = None
    for b in bars:
        start = (int(b[0]) // bucket_ms) * bucket_ms
        if bucket_start is None or start != bucket_start:
            if bucket:
                out.append(
                    [
                        bucket_start,
                        bucket[0][1],
                        max(x[2] for x in bucket),
                        min(x[3] for x in bucket),
                        bucket[-1][4],
                        sum(x[5] if len(x) > 5 else 0.0 for x in bucket),
                    ]
                )
            bucket = []
            bucket_start = start
        bucket.append(b)
    return out


def metrics(res: SimResult) -> Dict[str, float]:
    curve = res.equity_curve or [INITIAL_CAPITAL]
    peak = INITIAL_CAPITAL
    max_dd = 0.0
    for v in curve:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak * 100 if peak > 0 else 0)
    final = curve[-1]
    top = max(curve)
    giveback = ((top - final) / (top - INITIAL_CAPITAL) * 100) if top > INITIAL_CAPITAL else 0.0
    return {
        "return_pct": round((final - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        "max_dd_pct": round(max_dd, 2),
        "trades": res.trades,
        "win_rate_pct": round(res.wins / res.trades * 100, 1) if res.trades else 0.0,
        "giveback_pct": round(giveback, 1),
        "chop_losses": res.chop_losses,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/tmp/tradfi_research")
    parser.add_argument("--skip-fetch", action="store_true")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    import ccxt  # noqa: 延迟导入，便于本地静态检查

    ex = ccxt.okx({"enableRateLimit": True})

    data: Dict[str, Dict[str, List[List[float]]]] = {}
    for sym in SYMBOLS:
        key = sym.split("/")[0]
        cache = os.path.join(args.out, f"{key}.json")
        if args.skip_fetch and os.path.exists(cache):
            data[sym] = json.load(open(cache))
            continue
        entry: Dict[str, List[List[float]]] = {}
        for tf in ("15m", "1h"):
            bars = fetch_ohlcv_all(ex, sym, tf)
            entry[tf] = bars
            print(f"fetched {sym} {tf}: {len(bars)} bars", flush=True)
        data[sym] = entry
        json.dump(entry, open(cache, "w"))

    report: Dict[str, Dict[str, Dict[str, float]]] = {}
    combo: Dict[str, Dict[str, float]] = {
        tag: {"trades": 0, "wins": 0, "pnl": 0.0, "chop_losses": 0}
        for tag in ("A", "B", "C", "D", "E_1h_exec", "F_wide_stop", "G_pure_1h", "G2_1h_wide")
    }
    for sym, entry in data.items():
        b15, b1h = entry.get("15m") or [], entry.get("1h") or []
        if len(b15) < 200 or len(b1h) < ER_WINDOW + 2:
            report[sym] = {"error": {"bars_15m": len(b15), "bars_1h": len(b1h)}}
            continue
        mult = ETF_SIZE_MULT if sym in ETF_SYMBOLS else 1.0
        res_a = run_sim(b15, b1h, full_design=False, size_mult=mult)
        res_b = run_sim(b15, b1h, full_design=True, size_mult=mult)
        res_c = run_sim(b15, b1h, full_design=True, size_mult=mult, reversal_mode="off")
        res_d = run_sim(b15, b1h, full_design=True, size_mult=mult, reversal_mode="confirm2")
        b4h = aggregate_bars(b1h, 4 * 3600_000)
        res_e = run_sim(
            b1h, b4h, full_design=True, size_mult=mult, reversal_mode="confirm2", signal_tf_ms=4 * 3600_000
        )
        res_f = run_sim(
            b15, b1h, full_design=True, size_mult=mult, reversal_mode="off", atr_stop_mult=2.5, loss_cooldown_bars=8
        )
        # G：纯 1H —— 信号/执行/风控同为 1H（regime/方向门直接用 1H 自身序列）
        res_g = run_sim(
            b1h, b1h, full_design=True, size_mult=mult, reversal_mode="confirm2", signal_tf_ms=3600_000
        )
        # G2：纯 1H + 宽止损 2.5ATR + 止损冷却 6 根
        res_g2 = run_sim(
            b1h, b1h, full_design=True, size_mult=mult, reversal_mode="confirm2",
            signal_tf_ms=3600_000, atr_stop_mult=2.5, loss_cooldown_bars=6,
        )
        report[sym] = {
            "A": metrics(res_a),
            "B": metrics(res_b),
            "C": metrics(res_c),
            "D": metrics(res_d),
            "E_1h_exec": metrics(res_e),
            "F_wide_stop": metrics(res_f),
            "G_pure_1h": metrics(res_g),
            "G2_1h_wide": metrics(res_g2),
        }
        for tag, r in (
            ("A", res_a),
            ("B", res_b),
            ("C", res_c),
            ("D", res_d),
            ("E_1h_exec", res_e),
            ("F_wide_stop", res_f),
            ("G_pure_1h", res_g),
            ("G2_1h_wide", res_g2),
        ):
            combo[tag]["trades"] += r.trades
            combo[tag]["wins"] += r.wins
            combo[tag]["pnl"] += r.pnl
            combo[tag]["chop_losses"] += r.chop_losses

    report["_combined"] = {
        tag: {
            "trades": int(vals["trades"]),
            "win_rate_pct": round(vals["wins"] / vals["trades"] * 100, 1) if vals["trades"] else 0.0,
            "net_pnl_usdt": round(vals["pnl"], 2),
            "chop_losses": int(vals["chop_losses"]),
        }
        for tag, vals in combo.items()
    }
    out_path = os.path.join(args.out, "report.json")
    json.dump(report, open(out_path, "w"), indent=1, ensure_ascii=False)
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
