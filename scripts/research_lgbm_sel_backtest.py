#!/usr/bin/env python3
"""LightGBM 日内选币研究：组合回测引擎。

- 决策：每根 15M 已收盘 bar 的截面分数（来自 walk-forward OOS 分数表）；
- 执行：下一根 15M 开盘价 ± 显式滑点；佣金按名义单边计；
- 退出：5M 已确认 high/low 检查硬止损 / 固定止盈 / 保本 / 跟踪锁利，
  同一根同触保守先止损；另有截面排名失效、超时、单标的缺失保护；
- 组合风控：日内权益回撤暂停新开仓、冷却、名额与总杠杆上限。

窗口纪律（合同 lightgbm-intraday-selection-research.md）：
dev 主窗 2026-01-01~2026-06-30；split_a 02~04；split_b 04~06；
盲测窗 2026-07-01 起，只允许对最终候选打开一次。
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

MS_MIN5 = 300_000
MS_BAR15 = 900_000
MS_DAY = 86_400_000


# ---------------------------------------------------------------- data ----
class SymData:
    __slots__ = ("ts5", "o5", "h5", "l5", "c5")

    def __init__(self, df5: pd.DataFrame):
        self.ts5 = df5["timestamp"].to_numpy(np.int64)
        self.o5 = df5["open"].to_numpy(np.float64)
        self.h5 = df5["high"].to_numpy(np.float64)
        self.l5 = df5["low"].to_numpy(np.float64)
        self.c5 = df5["close"].to_numpy(np.float64)


def load_sym(kroot: Path, symbol: str, tf: str, lo: int, hi: int) -> pd.DataFrame | None:
    d = kroot / symbol / tf
    if not d.is_dir():
        return None
    months = []
    for f in sorted(d.glob("*.parquet")):
        ym = f.stem
        try:
            y, m = int(ym[:4]), int(ym[4:])
        except ValueError:
            continue
        ms = int(pd.Timestamp(f"{y:04d}-{m:02d}-01").value // 10**6)
        nxt = (y * 12 + m) // 12
        nm = (y * 12 + m) % 12 + 1
        end_ms = int(pd.Timestamp(f"{nxt:04d}-{nm:02d}-01").value // 10**6)
        if end_ms < lo or ms > hi:
            continue
        months.append(f)
    if not months:
        return None
    df = pd.concat([pd.read_parquet(f) for f in months], ignore_index=True)
    df["timestamp"] = df["timestamp"].astype("int64")
    df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    return df


# ------------------------------------------------------------- position ---
class Pos:
    __slots__ = ("sym", "side", "entry", "qty", "notional", "stop_dist", "tp_price",
                 "be_done", "peak", "trough", "opened_ts", "bars15", "last_px",
                 "atr_entry", "stale_bars", "fee_open")

    def __init__(self, sym, side, entry, notional, stop_dist, tp_price,
                 opened_ts, atr_entry, fee_open):
        self.sym, self.side, self.entry = sym, side, entry
        self.qty = notional / entry
        self.notional = notional
        self.stop_dist = stop_dist
        self.tp_price = tp_price
        self.be_done = False
        self.peak = entry
        self.trough = entry
        self.opened_ts = opened_ts
        self.bars15 = 0
        self.last_px = entry
        self.atr_entry = atr_entry
        self.stale_bars = 0
        self.fee_open = fee_open


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", required=True)
    ap.add_argument("--panel-aux", required=True, help="panel parquet，读 atr14_pct/vol_480 列")
    ap.add_argument("--kline-root", default="/opt/bitpro/data/klines/okx")
    ap.add_argument("--out", required=True)
    ap.add_argument("--trades-csv", default="")
    ap.add_argument("--window-start", required=True)
    ap.add_argument("--window-end", required=True)
    ap.add_argument("--role", default="dev", choices=["dev", "blind", "diag"])

    # 成本（显式滑点改价 + 名义佣金）
    ap.add_argument("--commission-bps-side", type=float, default=7.5)
    ap.add_argument("--slippage-bps-side", type=float, default=2.5)
    ap.add_argument("--funding-drag-bps-rt", type=float, default=0.0)

    # 组合结构
    ap.add_argument("--initial-equity", type=float, default=100.0)
    ap.add_argument("--rank-pct-long", type=float, default=0.15)
    ap.add_argument("--rank-pct-short", type=float, default=0.15)
    ap.add_argument("--max-long", type=int, default=4)
    ap.add_argument("--max-short", type=int, default=4)
    ap.add_argument("--pos-vol-target", type=float, default=0.12)
    ap.add_argument("--max-pos-pct-equity", type=float, default=0.30)
    ap.add_argument("--gross-leverage-cap", type=float, default=2.0)
    ap.add_argument("--min-notional", type=float, default=20.0)

    # 退出保护（合同强制：配置级正数并被平仓路径消费）
    ap.add_argument("--atr-stop-mult", type=float, default=1.5)
    ap.add_argument("--tp-rr", type=float, default=2.0)
    ap.add_argument("--break-even-at-r", type=float, default=1.0)
    ap.add_argument("--trail-start-r", type=float, default=1.5)
    ap.add_argument("--trail-atr-mult", type=float, default=1.2)
    ap.add_argument("--max-hold-bars15", type=int, default=16)

    # 行为约束
    ap.add_argument("--cooldown-bars15", type=int, default=8)
    ap.add_argument("--daily-pause-dd", type=float, default=0.05)
    ap.add_argument("--exit-rank-long", type=float, default=0.45)
    ap.add_argument("--exit-rank-short", type=float, default=0.45)
    ap.add_argument("--min-xsec", type=int, default=10)
    ap.add_argument("--decide-every-bars15", type=int, default=1,
                    help="每 N 根 15M 做一次排名/超时决策（保护性退出不受影响）")
    ap.add_argument("--min-hold-bars15", type=int, default=0,
                    help="开仓后最少持有根数，期间不做排名失效/超时退出")
    ap.add_argument("--long-side-mode", choices=["always", "btc_trend", "off"],
                    default="always",
                    help="多头侧开关：始终开 / 仅当 BTC 在 EMA192(48h) 上方 / 关闭")
    ap.add_argument("--recent-n-trades", type=int, default=0,
                    help=">0 时启用近期亏损熔断：最近 N 笔已平仓净盈亏 <= 阈值则暂停开仓")
    ap.add_argument("--recent-loss-pause-usdt", type=float, default=-10.0)
    ap.add_argument("--recent-loss-pause-pct", type=float, default=0.0,
                    help=">0 时以初始权益百分比覆盖绝对阈值（负数，如 -0.02 = -2%）")
    ap.add_argument("--pause-hours", type=float, default=12.0)
    args = ap.parse_args()

    w_start_ms = int(pd.Timestamp(args.window_start).value // 10**6)
    w_end_ms = int(pd.Timestamp(args.window_end).value // 10**6)

    scores = pd.read_parquet(args.scores)
    scores = scores.drop_duplicates(subset=["symbol", "timestamp"], keep="first")
    scores = scores[(scores["timestamp"] >= w_start_ms) & (scores["timestamp"] < w_end_ms)]

    aux = pd.read_parquet(args.panel_aux,
                          columns=["symbol", "timestamp", "atr14_pct", "vol_480"])
    dec = scores.merge(aux, on=["symbol", "timestamp"], how="left")
    dec = dec.dropna(subset=["score"])

    # 预构建每个决策时点的截面（按分数降序）
    by_time: dict[int, dict] = {}
    for t, g in dec.groupby("timestamp"):
        g = g.sort_values("score", ascending=False).reset_index(drop=True)
        n = len(g)
        if n < args.min_xsec:
            continue
        pct_rank = (np.arange(1, n + 1) / n)
        by_time[int(t)] = {
            "syms": g["symbol"].tolist(),
            "pct": pct_rank,
            "pos": {s: i for i, s in enumerate(g["symbol"].tolist())},
            "atr": dict(zip(g["symbol"], g["atr14_pct"])),
            "vol": dict(zip(g["symbol"], g["vol_480"])),
        }

    kroot = Path(args.kline_root)
    sym_cache: dict[str, SymData] = {}
    idx_hint: dict[str, int] = {}

    # BTC 15M EMA192（48h）趋势门控序列
    btc_gate: dict[int, bool] = {}
    if args.long_side_mode == "btc_trend":
        dfb = load_sym(kroot, "BTC-USDT_USDT", "15m",
                       w_start_ms - 30 * MS_DAY, w_end_ms + MS_DAY)
        if dfb is None or len(dfb) < 200:
            raise SystemExit("btc_trend 门控需要 BTC 15M 数据")
        c = dfb["close"].to_numpy(np.float64)
        ema = np.empty_like(c)
        k = 2.0 / (193.0)
        ema[0] = c[0]
        for i in range(1, len(c)):
            ema[i] = c[i] * k + ema[i - 1] * (1 - k)
        ts_b = dfb["timestamp"].to_numpy(np.int64)
        gate_ts = ts_b
        gate_val = c > ema
        del dfb

    def get_sym(sym: str) -> SymData | None:
        if sym not in sym_cache:
            df5 = load_sym(kroot, sym, "5m", w_start_ms - MS_DAY, w_end_ms + MS_DAY)
            if df5 is None or len(df5) == 0:
                sym_cache[sym] = None  # type: ignore[assignment]
                return None
            sym_cache[sym] = SymData(df5)
            idx_hint[sym] = 0
        sd = sym_cache[sym]
        return sd if sd is not None else None

    def bar_at(sd: SymData, sym: str, t: int):
        """返回该标的在时刻 t（bar open）的行号，无则 None。"""
        i = idx_hint.get(sym, 0)
        ts = sd.ts5
        n = len(ts)
        while i < n and ts[i] < t:
            i += 1
        idx_hint[sym] = i
        if i < n and ts[i] == t:
            return i
        j = np.searchsorted(ts, t)
        return int(j) if j < n and ts[j] == t else None

    commission = args.commission_bps_side / 1e4
    slip = args.slippage_bps_side / 1e4
    funding_rt = args.funding_drag_bps_rt / 1e4

    equity_realized = args.initial_equity
    fees_paid = 0.0
    positions: dict[tuple[str, str], Pos] = {}
    pending: list[tuple] = []  # ("OPEN"/"CLOSE", sym, side, notional, reason)
    cooldown: dict[str, int] = {}
    recent_pnl: list[float] = []
    pause_until_ms = -1
    breaker_threshold = (
        args.recent_loss_pause_pct * args.initial_equity
        if args.recent_loss_pause_pct < 0
        else args.recent_loss_pause_usdt
    )
    day_key = None
    day_start_eq = args.initial_equity
    trades = []
    eq_curve = []
    decision_times = sorted(t for t in by_time if w_start_ms <= t < w_end_ms)
    dec_set = set(decision_times)

    def equity_mark() -> float:
        unrl = 0.0
        for p in positions.values():
            unrl += (p.last_px - p.entry) * p.qty * (1 if p.side == "long" else -1)
        return equity_realized + unrl

    def close_pos(p: Pos, fill: float, reason: str, ts: int, t_close: int):
        nonlocal equity_realized, fees_paid, pause_until_ms
        fee_close = p.notional * commission
        fees_paid += fee_close
        direction = 1 if p.side == "long" else -1
        gross = (fill - p.entry) * p.qty * direction
        net = gross - p.fee_open - fee_close - p.notional * funding_rt
        equity_realized += net
        trades.append({
            "symbol": p.sym, "side": p.side, "open_ts": p.opened_ts, "close_ts": ts,
            "entry": p.entry, "exit": fill, "notional": p.notional,
            "pnl_net": net, "reason": reason,
            "hold_h": (ts - p.opened_ts) / 3_600_000,
        })
        if args.recent_n_trades > 0:
            recent_pnl.append(net)
            if len(recent_pnl) > args.recent_n_trades:
                recent_pnl.pop(0)
            if (len(recent_pnl) == args.recent_n_trades
                    and sum(recent_pnl) <= breaker_threshold
                    and ts + args.pause_hours * 3_600_000 > pause_until_ms):
                pause_until_ms = int(ts + args.pause_hours * 3_600_000)
        positions.pop((p.sym, p.side), None)
        cooldown[p.sym] = t_close // MS_BAR15 + args.cooldown_bars15

    # ------------------------------------------------------------- loop ----
    t = w_start_ms
    grid_end = w_end_ms
    decide_seq = 0
    while t <= grid_end:
        is_boundary = (t % MS_BAR15 == 0)
        do_decide = False
        if is_boundary and (t - MS_BAR15) in dec_set:
            if decide_seq % args.decide_every_bars15 == 0:
                do_decide = True
            decide_seq += 1

        if do_decide:
            cs = by_time[t - MS_BAR15]
            n_cs = len(cs["syms"])
            k_slot = max(1, int(round(n_cs * args.rank_pct_long)))
            eq = equity_mark()
            day = t // MS_DAY
            if day != day_key:
                day_key = day
                day_start_eq = eq
            paused = (
                day_start_eq > 0
                and (day_start_eq - eq) / day_start_eq >= args.daily_pause_dd
            ) or t < pause_until_ms

            # 失效退出判定（排名失效 / 超时；最短持有期内不触发）
            for (sym, side), p in list(positions.items()):
                if p.bars15 < args.min_hold_bars15:
                    continue
                if side == "long" and args.long_side_mode == "btc_trend":
                    j = np.searchsorted(gate_ts, t - MS_BAR15)
                    j = min(max(j - 1, 0), len(gate_val) - 1)
                    if not bool(gate_val[j]):
                        pending.append(("CLOSE", sym, side, 0.0, "btc_gate_exit"))
                        continue
                idx = cs["pos"].get(sym)
                if idx is None:
                    pending.append(("CLOSE", sym, side, 0.0, "xsec_absent"))
                    continue
                percentile = (idx + 1) / n_cs
                if side == "long" and percentile > args.exit_rank_long:
                    pending.append(("CLOSE", sym, side, 0.0, "rank_exit"))
                elif side == "short" and (1.0 - percentile) > args.exit_rank_short:
                    pending.append(("CLOSE", sym, side, 0.0, "rank_exit"))
                elif p.bars15 >= args.max_hold_bars15:
                    pending.append(("CLOSE", sym, side, 0.0, "time_stop"))

            if not paused:
                long_cnt = sum(1 for (_, s) in positions if s == "long")
                short_cnt = sum(1 for (_, s) in positions if s == "short")
                gross = sum(p.notional for p in positions.values())
                now_bar15 = t // MS_BAR15
                for rank_idx in range(n_cs):
                    sym = cs["syms"][rank_idx]
                    if rank_idx < k_slot:
                        want_side = "long"
                    elif (n_cs - 1 - rank_idx) < k_slot:
                        want_side = "short"
                    else:
                        continue
                    if want_side == "long":
                        if args.long_side_mode == "off":
                            continue
                        if args.long_side_mode == "btc_trend":
                            j = np.searchsorted(gate_ts, t - MS_BAR15)
                            j = min(max(j - 1, 0), len(gate_val) - 1)
                            if not bool(gate_val[j]):
                                continue
                    if want_side == "long" and long_cnt >= args.max_long:
                        continue
                    if want_side == "short" and short_cnt >= args.max_short:
                        continue
                    key = (sym, want_side)
                    if key in positions:
                        continue
                    other = ("short" if want_side == "long" else "long")
                    if (sym, other) in positions:
                        pending.append(("CLOSE", sym, other, 0.0, "flip"))
                        continue
                    if now_bar15 < cooldown.get(sym, -10**18):
                        continue
                    ann_vol = cs["vol"].get(sym)
                    if ann_vol is None or not np.isfinite(ann_vol) or ann_vol <= 0:
                        continue
                    notional = eq * args.pos_vol_target / ann_vol
                    notional = min(notional, eq * args.max_pos_pct_equity,
                                   max(0.0, eq * args.gross_leverage_cap - gross))
                    if notional < args.min_notional:
                        continue
                    pending.append(("OPEN", sym, want_side, notional, "signal"))
                    if want_side == "long":
                        long_cnt += 1
                    else:
                        short_cnt += 1
                    gross += notional

        # --- B) 执行挂单（当根 5M 开盘价 ± 滑点）；无法执行即丢弃，下个边界重评 ---
        dec_cs = by_time.get(t - MS_BAR15) if is_boundary else None
        for order in list(pending):
            kind, sym, side, notional, reason = order
            sd = get_sym(sym)
            if sd is None:
                continue
            bi = bar_at(sd, sym, t)
            if bi is None:
                continue
            op = float(sd.o5[bi])
            if op <= 0:
                continue
            if kind == "OPEN":
                atr_pct = dec_cs.get("atr", {}).get(sym) if dec_cs else None
                if not atr_pct or not np.isfinite(atr_pct) or atr_pct <= 0:
                    continue
                fill = op * (1 + slip) if side == "long" else op * (1 - slip)
                stop_dist = max(atr_pct * fill * args.atr_stop_mult, fill * 5e-4)
                tp = (fill * (1 + args.tp_rr * stop_dist / fill)
                      if side == "long"
                      else fill * (1 - args.tp_rr * stop_dist / fill))
                fee_o = notional * commission
                fees_paid += fee_o
                positions[(sym, side)] = Pos(sym, side, fill, notional, stop_dist,
                                             tp, t, atr_pct, fee_o)
            else:  # CLOSE
                p = positions.get((sym, side))
                if p is None:
                    continue
                fill = op * (1 - slip) if side == "long" else op * (1 + slip)
                close_pos(p, fill, reason, t, t)
        pending = []

        # --- C) 当根 5M high/low 保护性退出（止损优先） ---
        for (sym, side), p in list(positions.items()):
            sd = sym_cache.get(sym)
            if sd is None:
                continue
            bi = bar_at(sd, sym, t)
            if bi is None:
                p.stale_bars += 1
                if p.stale_bars >= 288:  # 24h 无价格，强制按最后已知价退出
                    close_pos(p, p.last_px, "stale_guard", t, t)
                continue
            hi = float(sd.h5[bi])
            lo = float(sd.l5[bi])
            op = float(sd.o5[bi])
            p.last_px = float(sd.c5[bi])
            p.stale_bars = 0
            if side == "long":
                p.peak = max(p.peak, hi)
                prog_r = (hi - p.entry) / p.stop_dist
            else:
                p.trough = min(p.trough, lo)
                prog_r = (p.entry - lo) / p.stop_dist

            stop_price = p.entry - p.stop_dist if side == "long" else p.entry + p.stop_dist
            if prog_r >= args.break_even_at_r and not p.be_done:
                p.be_done = True
            if p.be_done:
                be = p.entry + p.stop_dist * 0.05 if side == "long" else p.entry - p.stop_dist * 0.05
                stop_price = max(stop_price, be) if side == "long" else min(stop_price, be)
            if prog_r >= args.trail_start_r:
                trail = (p.peak - args.trail_atr_mult * p.atr_entry * p.entry
                         if side == "long"
                         else p.trough + args.trail_atr_mult * p.atr_entry * p.entry)
                stop_price = max(stop_price, trail) if side == "long" else min(stop_price, trail)

            hit_stop = (lo <= stop_price) if side == "long" else (hi >= stop_price)
            hit_tp = (hi >= p.tp_price) if side == "long" else (lo <= p.tp_price)
            if hit_stop:  # 同根同触保守先止损
                if side == "long":
                    fill = op if op < stop_price else stop_price
                else:
                    fill = op if op > stop_price else stop_price
                close_pos(p, fill, "stop_or_lock", t, t)
            elif hit_tp:
                close_pos(p, p.tp_price, "take_profit", t, t)

        # --- 推进决策计数 ---
        if is_boundary:
            for p in positions.values():
                p.bars15 += 1
            eq_curve.append({"ts": t, "equity": equity_mark()})

        t += MS_MIN5

    # 收尾：强制平掉所有持仓（按最后已知价）
    for (_s, _side), p in list(positions.items()):
        close_pos(p, p.last_px, "window_end", w_end_ms, w_end_ms)

    tr = pd.DataFrame(trades)
    eqc = pd.DataFrame(eq_curve)
    opens = tr[tr["reason"] != "window_end"]
    days_span = max(1e-9, (w_end_ms - w_start_ms) / MS_DAY)
    metrics = {
        "role": args.role,
        "window": [args.window_start, args.window_end],
        "net_return_pct": round((equity_realized / args.initial_equity - 1) * 100, 3),
        "final_equity": round(equity_realized, 4),
        "fees_paid": round(fees_paid, 3),
        "trades": int(len(opens)),
        "opens_per_day": round(len(opens) / days_span, 2),
        "win_rate": round(float((opens["pnl_net"] > 0).mean()) * 100, 2) if len(opens) else None,
        "profit_factor": None,
        "avg_hold_h": round(float(opens["hold_h"].mean()), 2) if len(opens) else None,
        "max_drawdown_pct": None,
        "avg_pnl_per_trade_usdt": round(float(opens["pnl_net"].mean()), 4) if len(opens) else None,
    }
    if len(opens):
        wins = opens.loc[opens["pnl_net"] > 0, "pnl_net"].sum()
        loss = -opens.loc[opens["pnl_net"] < 0, "pnl_net"].sum()
        metrics["profit_factor"] = round(float(wins / loss), 3) if loss > 0 else None
        metrics["gross_win"] = round(float(wins), 3)
        metrics["gross_loss"] = round(float(loss), 3)
        reason_stats = (
            opens.groupby("reason")
            .agg(n=("pnl_net", "size"), pnl=("pnl_net", "sum"),
                 win_rate=("pnl_net", lambda s: float((s > 0).mean())))
            .round(4)
        )
        metrics["by_reason"] = json.loads(reason_stats.to_json(orient="index"))
        side_stats = (
            opens.groupby("side")
            .agg(n=("pnl_net", "size"), pnl=("pnl_net", "sum"))
            .round(4)
        )
        metrics["by_side"] = json.loads(side_stats.to_json(orient="index"))
        pos_total = float(wins)
        if pos_total > 0:
            contrib = opens.loc[opens["pnl_net"] > 0].groupby("symbol")["pnl_net"].sum()
            metrics["top_symbol_profit_share_pct"] = round(float(contrib.max() / pos_total) * 100, 2)
        else:
            metrics["top_symbol_profit_share_pct"] = None
    if len(eqc):
        eq = eqc["equity"].to_numpy()
        peak = np.maximum.accumulate(eq)
        mdd = float(((peak - eq) / peak).max())
        metrics["max_drawdown_pct"] = round(mdd * 100, 2)
        eqc["day"] = eqc["ts"] // MS_DAY
        daily = eqc.groupby("day")["equity"].last()
        mr = daily.pct_change().dropna()
        monthly = {}
        for d, r in mr.items():
            mo = pd.Timestamp(int(d) * MS_DAY, unit="ms").strftime("%Y-%m")
            monthly[mo] = monthly.get(mo, 1.0) * (1 + r)
        metrics["monthly_return_factor"] = {k: round(v - 1, 4) for k, v in sorted(monthly.items())}
        neg_months = sum(1 for v in monthly.values() if v < 1)
        metrics["negative_months"] = neg_months
        metrics["total_months"] = len(monthly)

    result = {
        "config": vars(args),
        "metrics": metrics,
        "gates_passed": None,
    }
    if args.role == "dev":
        result["gates_passed"] = bool(
            metrics["net_return_pct"] > 0
            and (metrics["profit_factor"] or 0) >= 1.10
            and (metrics["opens_per_day"] or 0) >= 8
            and (metrics["max_drawdown_pct"] or 99) <= 12
        )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(metrics, indent=2))
    print(f"gates_passed={result['gates_passed']} -> {out}")
    if args.trades_csv and len(tr):
        Path(args.trades_csv).parent.mkdir(parents=True, exist_ok=True)
        tr.to_csv(args.trades_csv, index=False)


if __name__ == "__main__":
    main()
