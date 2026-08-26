"""离线逻辑验证：动量龙头追击金字塔策略（高风险探索结构）。

覆盖强制退出保护的最小测试面：突破追击多头入场、金字塔加仓与止损上移、
ATR 结构止损、ROI 硬止盈、BTC 大盘状态过滤开仓门禁、总回撤熔断清仓与停摆。
合成 K 线仅用于内部逻辑单元验证；绩效证据一律以生产真实 K 线回测为准。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in (str(PROJECT_ROOT / "backend"), str(PROJECT_ROOT / "strategies")):
    if p not in sys.path:
        sys.path.insert(0, p)

from momentum_chaser_pyramid import MomentumChaserPyramidStrategy  # noqa: E402

HOUR_MS = 3_600_000


class FakeBroker:
    def __init__(self, equity: float = 1000.0):
        self.equity = equity
        self.orders = []
        self.positions = {}

    async def open_contract(self, symbol, side, notional_usdt, leverage=None, price=None):
        key = (symbol, "long")
        if key in self.positions:
            pos = self.positions[key]
            pos["notional_usdt"] += float(notional_usdt)
        else:
            self.positions[key] = {
                "symbol": symbol, "side": "long", "pos_side": "long",
                "entry_price": float(price), "mark_price": float(price),
                "notional_usdt": float(notional_usdt),
                "base_qty": float(notional_usdt) / float(price),
            }
        self.orders.append(("open", symbol, notional_usdt, price))
        return {"status": "submitted", "side": "long"}

    async def close_contract(self, symbol, side, ratio=1.0, contracts=None, price=None):
        key = (symbol, "long")
        pos = self.positions.pop(key, None)
        self.orders.append(("close", symbol, price))
        return {"status": "submitted" if pos else "no_position"}

    async def get_contract_position(self, symbol, side):
        return self.positions.get((symbol, "long"))


def make_strategy(config_overrides=None):
    from app.core.execution.base_strategy import StrategyState

    pool = ["ME/USDT:USDT", "PEPE/USDT:USDT", "BTC/USDT:USDT"]
    state = StrategyState(strategy_id=0, name="test", exchange="okx", symbols=pool)
    broker = FakeBroker()
    strat = MomentumChaserPyramidStrategy(state=state, broker=broker)
    cfg = {
        "scan_interval_bars": 1,
        "ret_fast_window_bars": 3,
        "ret_slow_window_bars": 6,
        "rank_pct": 0.9,
        "breakout_lookback_bars": 5,
        "trend_ema_window": 8,
        "atr_window": 7,
        "min_ret_fast_abs": 0.01,
        "max_positions": 3,
        "leverage": 10,
        "target_notional_pct": 0.35,
        "max_gross_leverage": 3.0,
        "min_notional_usdt": 10.0,
        "max_position_equity_pct": 0.8,
        "pyramid_adds_max": 2,
        "add_trigger_r": 1.0,
        "add_size_mult": 1.0,
        "stop_atr_mult": 1.5,
        "hard_stop_loss_pct": 0.25,
        "hard_take_profit_pct": 0.60,
        "trail_start_r": 2.0,
        "trail_atr_mult": 3.0,
        "lock_pullback_pct": 0.45,
        "max_holding_bars": 48,
        "daily_pause_drawdown_pct": 0.99,
        "loss_cooldown_count": 3,
        "loss_cooldown_hours": 24,
        "regime_symbol": "",
        "max_total_drawdown_pct": 0.0,
    }
    if config_overrides:
        cfg.update(config_overrides)
    strat.set_config(cfg)
    asyncio.run(strat.on_init())
    return strat, broker


def make_bar(symbol, ts, close, high=None, low=None, volume=1000.0):
    from app.core.execution.base_strategy import BarData

    return BarData(
        symbol=symbol, exchange="okx", timeframe="4h", timestamp=ts,
        open=close, high=high or close * 1.001, low=low or close * 0.999,
        close=close, volume=volume,
    )


def feed_rally(strat, ts, bars=30):
    """标的 ME 强势上涨并不断突破前高；PEPE 横盘；BTC 温和上涨。"""
    for i in range(bars):
        base = 100.0
        me_close = base * (1.03 ** i)  # 3% per bar rally
        pepe_close = 50.0 + (i % 2) * 0.1
        btc_close = 60000.0 * (1.002 ** i)
        asyncio.run(strat.on_bar(make_bar("ME/USDT:USDT", ts, me_close)))
        asyncio.run(strat.on_bar(make_bar("PEPE/USDT:USDT", ts, pepe_close)))
        asyncio.run(strat.on_bar(make_bar("BTC/USDT:USDT", ts, btc_close)))
        ts += HOUR_MS
    return ts


def test_chase_entry_on_breakout():
    strat, broker = make_strategy()
    base_ts = 1_700_000_040_000 - 1_700_000_040_000 % HOUR_MS
    ts = feed_rally(strat, base_ts)
    assert ("ME/USDT:USDT", "long") in broker.positions, "强势突破标的应被追入"
    key = "ME/USDT:USDT|long"
    assert key in strat.entry_state
    es = strat.entry_state[key]
    assert es["stop_dist"] > 0 and es["notional_usdt"] >= 10.0
    assert ("PEPE/USDT:USDT", "long") not in broker.positions, "横盘标的不应入场"


def test_pyramid_add_and_stop_raise():
    strat, broker = make_strategy()
    base_ts = 1_700_000_040_000 - 1_700_000_040_000 % HOUR_MS
    ts = feed_rally(strat, base_ts)
    # v2 快兑现口径（ROI +60% @10x ≈ 价格 +6%）下，趋势中表现为快速落袋后按信号重进；
    # 断言策略保持活跃交易且持仓状态始终带完整保护字段。
    key = "ME/USDT:USDT|long"
    es = strat.entry_state.get(key)
    opens = [o for o in broker.orders if o[0] == "open" and o[1] == "ME/USDT:USDT"]
    assert len(opens) >= 1, "强趋势中应保持追击交易"
    if es is not None:
        assert es["stop_dist"] > 0 and es["stop_price"] > 0, "持仓必须有结构止损保护"

    # 直接驱动 _maybe_pyramid 验证金字塔加仓与止损上移逻辑本身
    strat2, broker2 = make_strategy({"pyramid_adds_max": 2})
    ts2 = feed_rally(strat2, base_ts)
    key2 = "ME/USDT:USDT|long"
    es2 = strat2.entry_state.get(key2) or {
        "first_entry": 200.0, "last_add_price": 210.0, "atr_ref": 5.0,
        "stop_dist": 10.0, "stop_price": 195.0, "notional_usdt": 350.0,
        "adds": 0, "peak": 210.0, "bars_in_trade": 1, "opened_ts": ts2,
    }
    before_notional = float(es2.get("notional_usdt", 350.0))
    before_stop = float(es2["stop_price"])
    bar_row = {"symbol": "ME/USDT:USDT", "ts": ts2, "high": 260.0, "low": 255.0, "close": 258.0}
    asyncio.run(strat2._maybe_pyramid(bar_row, es2, 258.0, 10.0))
    assert es2["adds"] >= 1 or es2["notional_usdt"] > before_notional, "浮盈达阈值应加仓"
    assert es2["last_add_price"] == 258.0 and es2["adds"] >= 1, "加仓应更新基准价与计数"
    assert es2["stop_price"] > before_stop - 1e-9, "加仓后止损不得下移"


def test_fast_profit_taking_in_trend():
    """v2 核心行为：追击后价格 +6%（ROI 60% @10x）即快速兑现。"""
    strat, broker = make_strategy()
    base_ts = 1_700_000_040_000 - 1_700_000_040_000 % HOUR_MS
    feed_rally(strat, base_ts)
    closes = [o for o in broker.orders if o[0] == "close" and o[1] == "ME/USDT:USDT"]
    assert closes, "趋势中应有兑现离场记录"


def test_structure_stop_exits():
    strat, broker = make_strategy({"pyramid_adds_max": 0})
    base_ts = 1_700_000_040_000 - 1_700_000_040_000 % HOUR_MS
    ts = feed_rally(strat, base_ts)
    key = "ME/USDT:USDT|long"
    assert key in strat.entry_state
    es = dict(strat.entry_state[key])
    # 推迟扫描避免同根重进；一根深跌击穿结构止损
    strat.next_scan_ts += 10 * HOUR_MS
    crash = es["first_entry"] - es["stop_dist"] * 1.5
    asyncio.run(strat.on_bar(make_bar("ME/USDT:USDT", ts, crash, low=crash * 0.995)))
    asyncio.run(strat.on_bar(make_bar("PEPE/USDT:USDT", ts, 50.0)))
    asyncio.run(strat.on_bar(make_bar("BTC/USDT:USDT", ts, 70000.0)))
    assert key not in strat.entry_state, "跌破结构止损应平仓清理"
    closes = [o for o in broker.orders if o[0] == "close" and o[1] == "ME/USDT:USDT"]
    assert closes, "应有平仓记录"


def test_hard_take_profit_roi_exit():
    strat, broker = make_strategy({"pyramid_adds_max": 0})
    base_ts = 1_700_000_040_000 - 1_700_000_040_000 % HOUR_MS
    ts = feed_rally(strat, base_ts)
    key = "ME/USDT:USDT|long"
    ref = strat.entry_state[key]["last_add_price"]
    strat.next_scan_ts += 10 * HOUR_MS
    spike = ref * 1.07  # 10x 下 ROI ≈ +70% > hard_tp 60%（价格 +6% 快兑现口径）
    asyncio.run(strat.on_bar(make_bar("ME/USDT:USDT", ts, spike, high=spike * 1.01, low=spike * 0.995)))
    asyncio.run(strat.on_bar(make_bar("PEPE/USDT:USDT", ts, 50.0)))
    asyncio.run(strat.on_bar(make_bar("BTC/USDT:USDT", ts, 70000.0)))
    assert key not in strat.entry_state, "ROI 硬止盈应触发离场"


def test_total_drawdown_halt_liquidates():
    strat, broker = make_strategy({"max_total_drawdown_pct": 0.05, "pyramid_adds_max": 0})
    base_ts = 1_700_000_040_000 - 1_700_000_040_000 % HOUR_MS
    ts = feed_rally(strat, base_ts)
    assert strat.entry_state, "入场后才有熔断对象"
    # 权益暴跌模拟深度回撤
    strat.broker.equity = 500.0
    strat.next_scan_ts += 10 * HOUR_MS
    fired = False
    for i in range(5):
        close = strat.market["ME/USDT:USDT"]["close"][-1] * 0.97
        asyncio.run(strat.on_bar(make_bar("ME/USDT:USDT", ts, close)))
        asyncio.run(strat.on_bar(make_bar("PEPE/USDT:USDT", ts, 50.0)))
        asyncio.run(strat.on_bar(make_bar("BTC/USDT:USDT", ts, 65000.0)))
        ts += HOUR_MS
        if strat.halted:
            fired = True
            break
    assert fired, "总回撤超阈值应触发熔断停摆"
    assert not strat.entry_state, "熔断应清空全部持仓账本"
    assert not broker.positions, "熔断应平掉交易所内全部持仓"


def test_regime_filter_blocks_entry():
    strat, broker = make_strategy({"regime_symbol": "BTC/USDT:USDT", "regime_ema_window": 20})
    base_ts = 1_700_000_040_000 - 1_700_000_040_000 % HOUR_MS
    # BTC 长期下跌（低于自身 EMA），ME 强势也不应开仓
    ts = base_ts
    for i in range(30):
        me_close = 100.0 * (1.05 ** i)
        pepe_close = 50.0
        btc_close = 60000.0 * (0.99 ** i)
        asyncio.run(strat.on_bar(make_bar("ME/USDT:USDT", ts, me_close)))
        asyncio.run(strat.on_bar(make_bar("PEPE/USDT:USDT", ts, pepe_close)))
        asyncio.run(strat.on_bar(make_bar("BTC/USDT:USDT", ts, btc_close)))
        ts += HOUR_MS
    assert not broker.positions, "BTC 大盘低于趋势线时应禁止新开仓"


if __name__ == "__main__":
    test_chase_entry_on_breakout()
    print("PASS chase entry")
    test_pyramid_add_and_stop_raise()
    print("PASS pyramid logic + protection fields")
    test_fast_profit_taking_in_trend()
    print("PASS fast profit taking")
    test_structure_stop_exits()
    print("PASS structure stop")
    test_hard_take_profit_roi_exit()
    print("PASS hard tp")
    test_total_drawdown_halt_liquidates()
    print("PASS total drawdown halt")
    test_regime_filter_blocks_entry()
    print("PASS regime filter")
    print("ALL PASS")
