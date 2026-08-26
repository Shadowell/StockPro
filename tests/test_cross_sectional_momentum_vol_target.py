"""离线逻辑验证：截面动量波动率目标组合策略。

覆盖策略退出保护强制规则要求的最小测试面：
多头入场、空头入场、ATR 止损、峰值利润回撤锁利、ROI 硬止盈、
截面失效退出与 entry_state 状态清理。

合成 K 线只用于策略内部逻辑单元验证；绩效证据一律以生产真实 K 线
Backtrader 回测为准，本文件不产出任何收益结论。
"""

from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in (str(PROJECT_ROOT / "backend"), str(PROJECT_ROOT / "strategies")):
    if p not in sys.path:
        sys.path.insert(0, p)

from cross_sectional_momentum_vol_target import (  # noqa: E402
    CrossSectionalMomentumVolTargetStrategy,
)

HOUR_MS = 3_600_000


class FakeBroker:
    def __init__(self, equity: float = 1000.0):
        self.equity = equity
        self.orders = []
        # positions: {(symbol, side): {"notional_usdt":..., "entry":...}}
        self.positions = {}

    async def open_contract(self, symbol, side, notional_usdt, leverage=None, price=None):
        key = (symbol, side)
        if key in self.positions:
            return {"status": "rejected", "reason": "already_holding"}
        self.positions[key] = {
            "symbol": symbol,
            "side": side,
            "pos_side": side,
            "entry_price": float(price),
            "mark_price": float(price),
            "notional_usdt": float(notional_usdt),
            "base_qty": float(notional_usdt) / float(price),
        }
        self.orders.append(("open", symbol, side, notional_usdt, price))
        return {"status": "submitted", "side": side}

    async def close_contract(self, symbol, side, ratio=1.0, contracts=None, price=None):
        key = (symbol, side)
        pos = self.positions.pop(key, None)
        self.orders.append(("close", symbol, side, price))
        if pos is None:
            return {"status": "no_position"}
        return {"status": "submitted", "side": side}

    async def get_contract_position(self, symbol, side):
        return self.positions.get((symbol, side))


def make_strategy(pool_symbols):
    from app.core.execution.base_strategy import StrategyState

    state = StrategyState(strategy_id=0, name="test", exchange="okx", symbols=pool_symbols)
    broker = FakeBroker()
    strat = CrossSectionalMomentumVolTargetStrategy(state=state, broker=broker)
    strat.set_config(
        {
            "rebalance_bars": 1,
            "min_cross_section_symbols": 2,
            "mom_fast_window_bars": 24,
            "mom_slow_window_bars": 48,
            "vol_window_bars": 48,
            "trend_ema_window": 20,
            "adx_window": 7,
            "entry_min_adx": 10.0,
            "rank_pct_long": 0.25,
            "rank_pct_short": 0.25,
            "max_long_positions": 1,
            "max_short_positions": 1,
            "max_total_positions": 2,
            "target_portfolio_vol": 0.30,
            "max_position_equity_pct": 0.5,
            "max_gross_leverage": 1.0,
            "min_notional_usdt": 10.0,
            "leverage": 5.0,
            "atr_stop_mult": 2.0,
            "hard_stop_loss_pct": 0.12,
            "hard_take_profit_pct": 0.45,
            "break_even_at_r": 1.0,
            "profit_trailing_start_r": 1.5,
            "trail_atr_mult": 2.5,
            "peak_pullback_pct": 0.35,
            "max_holding_bars": 96,
            "loss_cooldown_count": 3,
            "loss_cooldown_hours": 12,
        }
    )
    asyncio.run(strat.on_init())
    return strat, broker


def make_bar(symbol, ts, close, high=None, low=None, volume=1000.0):
    from app.core.execution.base_strategy import BarData

    return BarData(
        symbol=symbol,
        exchange="okx",
        timeframe="1h",
        timestamp=ts,
        open=close,
        high=high or close * 1.001,
        low=low or close * 0.999,
        close=close,
        volume=volume,
    )


async def feed_warmup(strat, symbols, base_ts, bars=80):
    """标的 A 单调上涨，标的 B 单调下跌，其余横盘。"""
    ts = base_ts
    for i in range(bars):
        for j, sym in enumerate(symbols):
            if j == 0:
                close = 100.0 + i * 0.8
            elif j == 1:
                close = 200.0 - i * 0.8
            else:
                close = 150.0 + (i % 3)
            await strat.on_bar(make_bar(sym, ts, close, volume=5000.0))
        ts += HOUR_MS
    return ts


def test_long_entry_short_entry_and_state():
    pool = ["A/USDT:USDT", "B/USDT:USDT"]
    strat, broker = make_strategy(pool)
    base_ts = 1_700_000_000_000 - 1_700_000_000_000 % HOUR_MS
    ts = asyncio.run(feed_warmup(strat, pool, base_ts))

    assert ("A/USDT:USDT", "long") in broker.positions, "强动量标的应开多"
    assert ("B/USDT:USDT", "short") in broker.positions, "弱动量标的应开空"
    keys = list(strat.entry_state.keys())
    assert len(keys) == 2 and all("|" in k for k in keys), "入场后应登记 entry_state"
    for es in strat.entry_state.values():
        assert es["stop_dist"] > 0 and es["notional_usdt"] >= 10.0


def test_atr_stop_triggers_and_cleans_state():
    pool = ["A/USDT:USDT", "B/USDT:USDT"]
    strat, broker = make_strategy(pool)
    base_ts = 1_700_000_000_000 - 1_700_000_000_000 % HOUR_MS
    ts = asyncio.run(feed_warmup(strat, pool, base_ts))
    assert ("A/USDT:USDT", "long") in broker.positions
    es_before = strat.entry_state["A/USDT:USDT|long"]

    # 一根深跌 K 线击穿多头初始止损（entry 约 162，stop_dist≈2*ATR）
    # 推迟下一次重平衡，隔离“同根 bar 止损后被重平衡立刻接回”的组合行为
    strat.next_rebalance_ts += 10 * HOUR_MS
    crash_low = es_before["entry_price"] - es_before["stop_dist"] * 1.5
    asyncio.run(
        strat.on_bar(
            make_bar("A/USDT:USDT", ts, crash_low, high=crash_low * 1.002, low=crash_low * 0.99)
        )
    )
    assert ("A/USDT:USDT", "long") not in broker.positions, "跌破止损价应平多"
    assert "A/USDT:USDT|long" not in strat.entry_state, "平仓后应清理 entry_state"


def test_profit_pullback_locks_gain():
    pool = ["A/USDT:USDT", "B/USDT:USDT"]
    strat, broker = make_strategy(pool)
    base_ts = 1_700_000_000_000 - 1_700_000_000_000 % HOUR_MS
    ts = asyncio.run(feed_warmup(strat, pool, base_ts))
    key = "A/USDT:USDT|long"
    assert key in strat.entry_state
    es = strat.entry_state[key]
    dist = es["stop_dist"]
    entry = es["entry_price"]

    # 推到 ~2R 峰值再回撤到 ~1.2R（回撤 40% > peak_pullback_pct=35%）
    strat.next_rebalance_ts += 10 * HOUR_MS
    peak_close = entry + 2.0 * dist
    pullback_close = entry + 1.15 * dist
    asyncio.run(strat.on_bar(make_bar("A/USDT:USDT", ts, peak_close)))
    asyncio.run(strat.on_bar(make_bar("A/USDT:USDT", ts + HOUR_MS, pullback_close)))
    assert ("A/USDT:USDT", "long") not in broker.positions, "峰值利润回撤超阈值应锁利离场"
    assert key not in strat.entry_state


def test_hard_take_profit_roi_exit():
    pool = ["A/USDT:USDT", "B/USDT:USDT"]
    strat, broker = make_strategy(pool)
    strat.leverage = 5.0
    base_ts = 1_700_000_000_000 - 1_700_000_000_000 % HOUR_MS
    ts = asyncio.run(feed_warmup(strat, pool, base_ts))
    key = "A/USDT:USDT|long"
    entry = strat.entry_state[key]["entry_price"]

    # 单根拉升使 ROI 触及 hard_take_profit_pct(45%)/5x => 价格 +9%
    strat.next_rebalance_ts += 10 * HOUR_MS
    spike = entry * 1.10
    asyncio.run(
        strat.on_bar(make_bar("A/USDT:USDT", ts, spike, high=spike * 1.01, low=spike * 0.995))
    )
    assert ("A/USDT:USDT", "long") not in broker.positions, "ROI 硬止盈应触发"
    assert key not in strat.entry_state


def test_cross_section_exit_when_momentum_fades():
    pool = ["A/USDT:USDT", "B/USDT:USDT"]
    strat, broker = make_strategy(pool)
    base_ts = 1_700_000_000_000 - 1_700_000_000_000 % HOUR_MS
    ts = asyncio.run(feed_warmup(strat, pool, base_ts))
    assert ("A/USDT:USDT", "long") in broker.positions

    # A 转为深度下跌而 B 反转上涨：下一轮重平衡后 A 的多头应因截面失效退出
    for i in range(60):
        a_close = 160.0 - i * 1.2
        b_close = 90.0 + i * 1.2
        asyncio.run(strat.on_bar(make_bar("A/USDT:USDT", ts, a_close, low=min(a_close, a_close - 0.5))))
        asyncio.run(strat.on_bar(make_bar("B/USDT:USDT", ts, b_close, high=max(b_close, b_close + 0.5))))
        ts += HOUR_MS

    assert ("A/USDT:USDT", "long") not in broker.positions, "动量跌出后多头应被截面失效退出"
    closes = [o for o in broker.orders if o[0] == "close" and o[1] == "A/USDT:USDT"]
    assert closes, "应有针对 A 的平仓记录"


if __name__ == "__main__":
    test_long_entry_short_entry_and_state()
    print("PASS long/short entry + state")
    test_atr_stop_triggers_and_cleans_state()
    print("PASS atr stop + cleanup")
    test_profit_pullback_locks_gain()
    print("PASS profit pullback lock")
    test_hard_take_profit_roi_exit()
    print("PASS hard tp roi")
    test_cross_section_exit_when_momentum_fades()
    print("PASS cross-section exit")
    print("ALL PASS")
