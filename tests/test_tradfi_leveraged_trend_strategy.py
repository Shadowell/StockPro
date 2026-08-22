import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, OrderResult, StrategyState  # noqa: E402
from app.strategies.tradfi_leveraged_trend_strategy import (  # noqa: E402
    RUNTIME_STATE_KEY,
    TradfiLeveragedTrendStrategy,
)

ETF_SYMBOL = "SNXX/USDT:USDT"
STOCK_SYMBOL = "SNDK/USDT:USDT"

# 2026-08-14 17:00 UTC（周五，美东 13:00，处于美股常规时段内）
SESSION_OPEN_TS = 1_786_726_800_000
HOUR_MS = 3_600_000


class _ContractBroker:
    def __init__(self):
        self.equity = 100.0
        self.balance = 100.0
        self.initial_capital = 100.0
        self.positions = {}
        self.orders = []
        self.trades = []
        self.warmup_mode = False

    async def open_contract(self, symbol, side, notional_usdt, leverage=None, price=None):
        self.orders.append(
            {"action": "open", "symbol": symbol, "side": side, "notional_usdt": float(notional_usdt)}
        )
        return OrderResult({"status": "filled", "side": side, "price": price, "notional_usdt": notional_usdt})

    async def close_contract(self, symbol, side, ratio=1.0, contracts=None, price=None):
        self.orders.append({"action": "close", "symbol": symbol, "side": side})
        self.positions.pop((symbol, side), None)
        return OrderResult({"status": "filled", "side": side, "price": price})

    async def get_contract_position(self, symbol, side):
        return self.positions.get((symbol, side))

    async def get_available_balance(self, currency="USDT"):
        return self.balance


def _init_strategy(config=None, positions_state=None):
    broker = _ContractBroker()
    state = StrategyState(
        strategy_id=3101,
        name="[合约][1H][CTA] TradFi7 · 美股杠杆动量趋势锁利版 · 100U",
        exchange="okx",
        symbols=[ETF_SYMBOL, STOCK_SYMBOL],
        created_at=datetime.now(timezone.utc),
        status="running",
        positions={"_capital": 100.0, **(positions_state or {})},
    )
    strategy = TradfiLeveragedTrendStrategy(state, broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": [],
            "trend_filter": "ema_state",
            "timeframe": "1h",
            "fast_window": 2,
            "slow_window": 3,
            "entry_signal_confirm_bars": 1,
            "atr_window": 2,
            "atr_stop_mult": 2.5,
            "min_atr_ratio": 0.0,
            "market_sma_window": 2,
            "entry_min_adx": 0,
            "profit_protection_enabled": False,
            "hard_stop_loss_pct": 0.04,
            "hard_take_profit_pct": 0.2,
            "target_notional_usdt": 30,
            "er_window": 4,
            "er_min": 0.25,
            "etf_symbols": [ETF_SYMBOL],
            "etf_size_mult": 0.5,
            "loss_cooldown_bars": 6,
            "ratchet_step_pct": 25,
            "ratchet_lock_fraction": 0.5,
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy, broker


def _bar(close: float, index: int, symbol: str = STOCK_SYMBOL) -> BarData:
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="1h",
        timestamp=SESSION_OPEN_TS + index * HOUR_MS,
        open=close,
        high=close + 0.5,
        low=close - 0.5,
        close=close,
        volume=1_000.0,
    )


def _trending_bars(count: int = 8, symbol: str = STOCK_SYMBOL):
    return [_bar(100.0 + i * 2.0, i, symbol) for i in range(count)]


def _choppy_bars(count: int = 8, symbol: str = STOCK_SYMBOL):
    # 大幅来回震荡：路径长但净位移接近 0，效率比 << 0.25
    return [_bar(100.0 + (3.0 if i % 2 == 0 else -3.0), i, symbol) for i in range(count)]


# ---------------------------------------------------------------------------
# ER regime 门
# ---------------------------------------------------------------------------


def test_er_gate_allows_trending_market():
    strategy, _ = _init_strategy()
    bars = _trending_bars()
    assert strategy._efficiency_ratio(bars) >= 0.25
    assert strategy._entry_signal(STOCK_SYMBOL, bars, 1) == 1


def test_er_gate_blocks_choppy_market():
    strategy, _ = _init_strategy()
    bars = _choppy_bars()
    assert strategy._efficiency_ratio(bars) < 0.25
    # 原始信号为多头，但 regime 门应拦截
    assert strategy._entry_signal(STOCK_SYMBOL, bars, 1) == 0


def test_er_gate_blocks_when_history_insufficient():
    strategy, _ = _init_strategy(config={"er_window": 30})
    bars = _trending_bars(count=8)
    assert strategy._efficiency_ratio(bars) is None
    assert strategy._entry_signal(STOCK_SYMBOL, bars, 1) == 0


# ---------------------------------------------------------------------------
# 美股时段过滤（基类 session filter + America/New_York 时区配置）
# ---------------------------------------------------------------------------


def _session_config():
    return {
        "session_filter_enabled": True,
        "session_timezone": "America/New_York",
        "signal_sessions": [
            {"name": "us_regular", "start": "09:30", "end": "16:00", "days": ["mon", "tue", "wed", "thu", "fri"]}
        ],
    }


def test_us_session_window_allows_regular_hours():
    strategy, _ = _init_strategy(config=_session_config())
    # 周五 17:00 UTC = 美东 13:00，盘中
    context = strategy._entry_session_context(_bar(100.0, 0))
    assert context["entry_enabled"] is True


def test_us_session_window_blocks_off_hours():
    strategy, _ = _init_strategy(config=_session_config())
    # +12 小时 = 周六 05:00 UTC = 美东周六 01:00，休市
    context = strategy._entry_session_context(_bar(100.0, 12))
    assert context["entry_enabled"] is False


# ---------------------------------------------------------------------------
# ETF 名义折减
# ---------------------------------------------------------------------------


def test_etf_symbol_notional_is_halved():
    strategy, _ = _init_strategy()
    stock = strategy._risk_sized_notional(STOCK_SYMBOL, "long", 100.0, 2.0)
    etf = strategy._risk_sized_notional(ETF_SYMBOL, "long", 100.0, 2.0)
    assert stock > 0
    assert etf == stock * 0.5


# ---------------------------------------------------------------------------
# 亏损冷却
# ---------------------------------------------------------------------------


def test_loss_cooldown_blocks_entry_then_expires():
    strategy, broker = _init_strategy()
    bars = _trending_bars()
    now_ms = int(bars[-1].timestamp)

    broker.trades.append(
        {"action": "close_long", "symbol": STOCK_SYMBOL, "realized_pnl": -1.2}
    )
    strategy._update_cooldowns_from_trades(now_ms)

    assert strategy._entry_signal(STOCK_SYMBOL, bars, 1) == 0

    # 冷却 6 根 1H K 线后恢复
    later = [_bar(100.0 + i * 2.0, i + 7) for i in range(8)]
    assert strategy._entry_signal(STOCK_SYMBOL, later, 1) == 1


def test_profitable_close_does_not_trigger_cooldown():
    strategy, broker = _init_strategy()
    bars = _trending_bars()
    broker.trades.append(
        {"action": "close_long", "symbol": STOCK_SYMBOL, "realized_pnl": 2.5}
    )
    strategy._update_cooldowns_from_trades(int(bars[-1].timestamp))
    assert strategy._entry_signal(STOCK_SYMBOL, bars, 1) == 1


# ---------------------------------------------------------------------------
# 权益棘轮
# ---------------------------------------------------------------------------


def test_ratchet_raises_floor_after_step_gain():
    strategy, broker = _init_strategy()
    strategy._update_ratchet()  # 基准 = 100
    broker.equity = 130.0
    strategy._update_ratchet()
    # 地板 = 100 + 30 * 0.5 = 115，新基准 = 130
    assert strategy._ratchet_floor == 115.0
    assert strategy._ratchet_base == 130.0


def test_ratchet_pauses_entries_below_floor_and_resumes_above():
    strategy, broker = _init_strategy()
    strategy._update_ratchet()
    broker.equity = 130.0
    strategy._update_ratchet()

    bars = _trending_bars()
    broker.equity = 110.0  # 跌破 115 地板
    assert strategy._entry_signal(STOCK_SYMBOL, bars, 1) == 0

    broker.equity = 118.0  # 回到地板上方
    assert strategy._entry_signal(STOCK_SYMBOL, bars, 1) == 1


def test_ratchet_floor_never_decreases():
    strategy, broker = _init_strategy()
    strategy._update_ratchet()
    broker.equity = 130.0
    strategy._update_ratchet()
    floor_after_first = strategy._ratchet_floor

    broker.equity = 163.0  # 130 * 1.25 = 162.5，触发第二级
    strategy._update_ratchet()
    assert strategy._ratchet_floor > floor_after_first


# ---------------------------------------------------------------------------
# 状态持久化与恢复
# ---------------------------------------------------------------------------


def test_runtime_state_persists_and_restores():
    strategy, broker = _init_strategy()
    strategy._update_ratchet()
    broker.equity = 130.0
    strategy._update_ratchet()
    broker.trades.append(
        {"action": "close_long", "symbol": STOCK_SYMBOL, "realized_pnl": -1.0}
    )
    strategy._update_cooldowns_from_trades(SESSION_OPEN_TS)

    payload = strategy.state.positions[RUNTIME_STATE_KEY]
    assert payload["ratchet_floor"] == 115.0
    assert payload["cooldown_until_ms"][STOCK_SYMBOL] == SESSION_OPEN_TS + 6 * HOUR_MS

    restored, _ = _init_strategy(positions_state={RUNTIME_STATE_KEY: dict(payload)})
    assert restored._ratchet_floor == 115.0
    assert restored._ratchet_base == 130.0
    assert restored._cooldown_until_ms[STOCK_SYMBOL] == SESSION_OPEN_TS + 6 * HOUR_MS


def test_corrupted_runtime_state_falls_back_to_fresh():
    restored, _ = _init_strategy(positions_state={RUNTIME_STATE_KEY: {"version": 99, "ratchet_floor": 999}})
    assert restored._ratchet_floor == 0.0
    assert restored._cooldown_until_ms == {}
