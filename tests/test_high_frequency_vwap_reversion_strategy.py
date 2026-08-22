import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SOURCE_PATH = ROOT / "scripts/strategy_sources/high_frequency_vwap_reversion.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, StrategyState  # noqa: E402
from app.services.agent.code_sandbox import load_base_strategy_class  # noqa: E402


SYMBOL = "BTC/USDT:USDT"
FUTURE_SYMBOL = "FUTURE/USDT:USDT"
BASE_TS = 1_800_000_000_000 // 3_600_000 * 3_600_000


class FakeBroker:
    def __init__(self):
        self.equity = 100.0
        self.balance = 100.0
        self.initial_capital = 100.0
        self.positions = {}
        self.orders = []
        self.warmup_mode = False

    async def open_contract(self, symbol, side, notional_usdt, leverage=None, price=None):
        self.orders.append(
            {
                "action": "open",
                "symbol": symbol,
                "side": side,
                "notional_usdt": float(notional_usdt),
                "leverage": leverage,
                "price": price,
            }
        )
        return {"status": "filled", "symbol": symbol, "side": side, "price": price}

    async def close_contract(self, symbol, side, ratio=1.0, contracts=None, price=None):
        self.orders.append(
            {"action": "close", "symbol": symbol, "side": side, "ratio": ratio, "price": price}
        )
        self.positions.pop((symbol, side), None)
        return {
            "status": "filled",
            "symbol": symbol,
            "side": side,
            "price": price,
            "realized_pnl": 0.0,
        }

    async def get_contract_position(self, symbol, side):
        return self.positions.get((symbol, side))

    async def get_available_balance(self, currency="USDT"):
        return self.balance


def strategy_class():
    assert SOURCE_PATH.exists(), "唯一VWAP回归动态源码尚未创建"
    return load_base_strategy_class(SOURCE_PATH.read_text(encoding="utf-8"))


def init_strategy(*, symbols=None, config=None, state_positions=None):
    state = StrategyState(
        strategy_id=9_201,
        name="[合约][5M][均值回归] Top20 · 1H震荡状态VWAP回归锁利 · 100U",
        exchange="okx",
        symbols=list(symbols or [SYMBOL]),
        created_at=datetime.now(timezone.utc),
        status="running",
        positions={"_capital": 100.0, **(state_positions or {})},
    )
    broker = FakeBroker()
    strategy = strategy_class()(state, broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "timeframe": "5m",
            "primary_signal_timeframe": "1h",
            "leverage": 5,
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy, broker


def make_bar(index, close=100.0, *, high=None, low=None, volume=1_000.0, symbol=SYMBOL):
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="5m",
        timestamp=BASE_TS + index * 300_000,
        open=float(close),
        high=float(close + 0.4 if high is None else high),
        low=float(close - 0.4 if low is None else low),
        close=float(close),
        volume=float(volume),
    )


def h1_row(index, close, *, volume=1_000.0):
    return {
        "bucket": 500 + index,
        "timestamp": (500 + index) * 3_600_000,
        "open": float(close),
        "high": float(close + 0.6),
        "low": float(close - 0.6),
        "close": float(close),
        "volume": float(volume),
    }


def oscillating_history(count=48, *, volume=1_000.0):
    pattern = [99.6, 100.4, 99.7, 100.3, 99.8, 100.2]
    return [h1_row(index, pattern[index % len(pattern)], volume=volume) for index in range(count)]


def passing_range_metrics(**overrides):
    metrics = {
        "adx": 14.0,
        "efficiency": 0.15,
        "direction_atr": 0.50,
        "atr_pct": 1.2,
        "vwap_crosses": 5,
        "extension_atr": 0.5,
    }
    metrics.update(overrides)
    return metrics


def test_source_loads_with_vwap_runtime_keys():
    strategy, _ = init_strategy()

    assert strategy.__class__.__name__ == "HighFrequencyVwapReversionStrategy"
    assert strategy.runtime_key == "_vwap_reversion_runtime"
    assert strategy.pool_view_key == "_dynamic_pool_view"


def test_one_hour_aggregation_waits_for_twelve_completed_five_minute_bars():
    strategy, _ = init_strategy()
    for index in range(12):
        assert strategy._aggregate_5m_bar(make_bar(index, close=100 + index * 0.1)) is None

    completed = strategy._aggregate_5m_bar(make_bar(12, close=101.2))

    assert completed["timestamp"] == BASE_TS
    assert completed["open"] == pytest.approx(100)
    assert completed["close"] == pytest.approx(101.1)
    assert len(strategy.h1_bars[SYMBOL]) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"adx": 7.9},
        {"adx": 18.1},
        {"efficiency": 0.181},
        {"direction_atr": 0.801},
        {"atr_pct": 0.49},
        {"atr_pct": 5.01},
        {"vwap_crosses": 3},
        {"extension_atr": 1.21},
    ],
)
def test_range_state_gate_rejects_trend_noise_or_insufficient_reversion(overrides):
    strategy, _ = init_strategy()

    assert strategy._range_state_gate(passing_range_metrics()) is True
    assert strategy._range_state_gate(passing_range_metrics(**overrides)) is False


def test_dynamic_top20_ignores_future_turnover():
    symbols = [f"S{index:02d}/USDT:USDT" for index in range(24)] + [FUTURE_SYMBOL]
    strategy, _ = init_strategy(symbols=symbols, config={"candidate_count": 20})
    for index, symbol in enumerate(symbols):
        history = oscillating_history(volume=100 + index)
        if symbol == FUTURE_SYMBOL:
            history = oscillating_history(volume=1)
            history.append(h1_row(60, 100, volume=1_000_000_000))
        strategy.h1_bars[symbol] = history

    strategy._refresh_universe(completed_hour=547)

    assert len(strategy.candidate_symbols) == 20
    assert FUTURE_SYMBOL not in strategy.candidate_symbols
    assert "S23/USDT:USDT" in strategy.candidate_symbols


def test_range_state_needs_two_confirmations_before_openable():
    strategy, _ = init_strategy(
        config={
            "state_confirmations": 2,
            "adx_min": 0,
            "adx_max": 100,
            "efficiency_max": 1,
            "direction_atr_max": 10,
            "vwap_crosses_min": 1,
            "extension_atr_max": 10,
        }
    )
    strategy.candidate_symbols = {SYMBOL}
    strategy.h1_bars[SYMBOL] = oscillating_history()

    strategy._refresh_range_states(547)
    first = dict(strategy.latest_states[SYMBOL])
    strategy._refresh_range_states(548)
    second = dict(strategy.latest_states[SYMBOL])

    assert first["confirmed"] == 1
    assert first["openable"] is False
    assert second["confirmed"] == 2
    assert second["openable"] is True


def test_cross_section_scores_once_after_sixty_percent_quorum():
    symbols = [f"Q{index}/USDT:USDT" for index in range(5)]
    strategy, _ = init_strategy(symbols=symbols)
    for symbol in symbols:
        strategy.h1_bars[symbol] = oscillating_history()

    assert strategy._register_completed_hour(symbols[0], 548) is False
    assert strategy._register_completed_hour(symbols[1], 548) is False
    assert strategy._register_completed_hour(symbols[2], 548) is True
    assert strategy._register_completed_hour(symbols[3], 548) is False


def seeded_vwap_strategy(*, side="long", config=None):
    strategy, broker = init_strategy(
        config={
            "vwap_5m_window": 48,
            "z_entry": 2.0,
            "z_recovery_min": 0.25,
            "volume_window": 20,
            "volume_ratio_min": 0.8,
            "volume_ratio_max": 2.5,
            "max_bar_range_atr": 1.8,
            "round_trip_cost_bps": 20,
            "cost_edge_multiple": 3,
            "initial_stop_atr_mult": 0.9,
            "extreme_stop_buffer_atr": 0.35,
            "hard_take_profit_r": 1.10,
            **(config or {}),
        }
    )
    strategy.latest_states[SYMBOL] = {"symbol": SYMBOL, "openable": True, "vwap": 100.0}
    base_close = 98.0 if side == "long" else 102.0
    strategy.bars_5m[SYMBOL] = [
        make_bar(index, close=100.0, high=100.5, low=99.5, volume=100)
        for index in range(47)
    ] + [
        make_bar(47, close=base_close, high=base_close + 0.5, low=base_close - 0.5, volume=100)
    ]
    strategy.five_minute_counts[SYMBOL] = 48
    return strategy, broker


def test_vwap_snapshot_uses_previous_completed_bars_only():
    strategy, _ = seeded_vwap_strategy(side="long")

    snapshot = strategy._vwap_snapshot(SYMBOL)

    assert snapshot["sample_count"] == 48
    assert snapshot["vwap"] < 100
    assert snapshot["previous_z"] <= -2.0


@pytest.mark.parametrize(
    ("side", "close", "expected"),
    [
        ("long", 98.6, "long"),
        ("short", 101.4, "short"),
    ],
)
def test_entry_requires_extreme_zscore_and_confirmed_recovery(side, close, expected):
    strategy, _ = seeded_vwap_strategy(side=side)

    trigger = strategy._entry_trigger(
        SYMBOL,
        make_bar(48, close=close, high=close + 0.5, low=close - 0.5, volume=100),
    )

    assert trigger["side"] == expected
    assert trigger["vwap_distance_bps"] >= 60
    assert trigger["take_profit_price"] > close if side == "long" else trigger["take_profit_price"] < close


@pytest.mark.parametrize(
    ("bar", "config", "cooldown"),
    [
        (make_bar(48, close=98.01, high=98.51, low=97.51, volume=100), {}, {}),
        (make_bar(48, close=98.6, high=99.1, low=98.1, volume=70), {}, {}),
        (make_bar(48, close=98.6, high=99.1, low=98.1, volume=260), {}, {}),
        (make_bar(48, close=98.6, high=100.6, low=96.6, volume=100), {}, {}),
        (
            make_bar(48, close=98.6, high=99.1, low=98.1, volume=100),
            {"cost_edge_multiple": 10},
            {},
        ),
        (
            make_bar(48, close=98.6, high=99.1, low=98.1, volume=100),
            {},
            {f"{SYMBOL}|long": 54},
        ),
    ],
)
def test_entry_rejects_weak_recovery_volume_impulse_cost_or_cooldown(bar, config, cooldown):
    strategy, _ = seeded_vwap_strategy(side="long", config=config)
    strategy.cooldown_until_bar.update(cooldown)

    assert strategy._entry_trigger(SYMBOL, bar) is None


def test_order_plan_caps_risk_direction_and_total_exposure():
    strategy, _ = seeded_vwap_strategy(
        config={
            "risk_per_trade_pct": 0.0035,
            "max_position_notional_usdt": 40,
            "max_positions": 4,
            "same_direction_cap": 2,
            "max_total_notional_equity_pct": 1.2,
        }
    )

    plan = strategy._order_plan(equity=100, entry=100, stop=99.5, side="long")

    assert plan["risk_usdt"] <= 0.35
    assert plan["notional_usdt"] <= 40

    strategy.entry_state = {
        "A|long": {"side": "long", "notional_usdt": 40},
        "B|long": {"side": "long", "notional_usdt": 40},
    }
    assert strategy._order_plan(equity=100, entry=100, stop=99.5, side="long") is None

    strategy.entry_state = {
        "A|long": {"side": "long", "notional_usdt": 55},
        "B|short": {"side": "short", "notional_usdt": 55},
    }
    remaining = strategy._order_plan(equity=100, entry=100, stop=99.5, side="long")
    assert remaining["notional_usdt"] <= 10


def opened_reversion_strategy(*, side="long", config=None):
    strategy, broker = seeded_vwap_strategy(
        side=side,
        config={
            "break_even_at_r": 0.40,
            "profit_trailing_start_r": 0.70,
            "profit_peak_pullback_pct": 0.25,
            "profit_atr_stop_mult": 0.55,
            "regime_break_adx": 24,
            "regime_break_efficiency": 0.35,
            "regime_break_direction_atr": 1.5,
            "max_holding_bars": 24,
            "cooldown_bars": 6,
            **(config or {}),
        },
    )
    entry = 100.0
    risk = 0.5
    key = f"{SYMBOL}|{side}"
    strategy.entry_state[key] = {
        "symbol": SYMBOL,
        "side": side,
        "entry_price": entry,
        "initial_risk_price": risk,
        "stop_price": entry - risk if side == "long" else entry + risk,
        "take_profit_price": entry + 0.55 if side == "long" else entry - 0.55,
        "target_vwap": entry + 0.8 if side == "long" else entry - 0.8,
        "highest": entry,
        "lowest": entry,
        "entry_bar_count": 48,
        "atr": 0.8,
        "notional_usdt": 40,
    }
    broker.positions[(SYMBOL, side)] = {
        "symbol": SYMBOL,
        "side": side,
        "entry_price": entry,
        "notional_value": 40,
    }
    strategy.latest_states[SYMBOL] = {
        "symbol": SYMBOL,
        "openable": True,
        "adx": 14,
        "efficiency": 0.15,
        "direction_atr": 0.5,
    }
    strategy.five_minute_counts[SYMBOL] = 49
    return strategy, broker, key


@pytest.mark.parametrize(
    ("side", "stop"),
    [("long", 99.5), ("short", 100.5)],
)
def test_same_bar_stop_precedes_fixed_or_vwap_take_profit(side, stop):
    strategy, broker, key = opened_reversion_strategy(side=side)

    result = asyncio.run(
        strategy._manage_position(
            SYMBOL,
            side,
            make_bar(49, close=100, high=101, low=99, volume=100),
        )
    )

    assert result["status"] == "filled"
    assert broker.orders[-1]["price"] == pytest.approx(stop)
    assert key not in strategy.entry_state
    assert strategy.cooldown_until_bar[key] == 55


def test_break_even_and_trailing_protect_profit_before_next_bar():
    strategy, broker, key = opened_reversion_strategy(side="long")

    asyncio.run(
        strategy._manage_position(
            SYMBOL,
            "long",
            make_bar(49, close=100.4, high=100.45, low=100.25, volume=100),
        )
    )
    locked_stop = strategy.entry_state[key]["stop_price"]

    assert locked_stop >= 100.2
    assert broker.orders == []

    result = asyncio.run(
        strategy._manage_position(
            SYMBOL,
            "long",
            make_bar(50, close=locked_stop, high=100.4, low=locked_stop - 0.01, volume=100),
        )
    )
    assert result["status"] == "filled"
    assert broker.orders[-1]["price"] == pytest.approx(locked_stop)


def test_range_state_break_closes_before_waiting_for_time_exit():
    strategy, broker, key = opened_reversion_strategy(side="long")
    strategy.latest_states[SYMBOL]["adx"] = 25

    result = asyncio.run(
        strategy._manage_position(
            SYMBOL,
            "long",
            make_bar(49, close=100.05, high=100.1, low=100.0),
        )
    )

    assert result["status"] == "filled"
    assert result["exit_reason"] == "range_state_broken"
    assert key not in strategy.entry_state


def test_vwap_target_and_120_minute_exit_clear_state():
    target_strategy, target_broker, target_key = opened_reversion_strategy(side="long")
    target_result = asyncio.run(
        target_strategy._manage_position(
            SYMBOL,
            "long",
            make_bar(49, close=100.6, high=100.65, low=100.3),
        )
    )
    assert target_result["exit_reason"] == "fixed_or_vwap_take_profit"
    assert target_key not in target_strategy.entry_state

    timed, _, timed_key = opened_reversion_strategy(side="long")
    timed.five_minute_counts[SYMBOL] = 72
    timed_result = asyncio.run(
        timed._manage_position(
            SYMBOL,
            "long",
            make_bar(72, close=100.05, high=100.1, low=100.0),
        )
    )
    assert timed_result["exit_reason"] == "time_exit_120m"
    assert timed_key not in timed.entry_state


def test_daily_profit_floor_daily_loss_and_terminal_floor_are_distinct():
    floor_strategy, floor_broker, _ = opened_reversion_strategy(
        config={"daily_lock_activation_pct": 0.015, "daily_lock_fraction": 0.5}
    )
    day = BASE_TS // 86_400_000
    floor_strategy.runtime["day_number"] = day
    floor_strategy.runtime["day_start_equity"] = 100.0
    floor_broker.equity = 104.0
    assert asyncio.run(floor_strategy._apply_portfolio_guards(BASE_TS)) is False
    assert floor_strategy.runtime["daily_profit_floor"] == pytest.approx(102.0)
    floor_broker.equity = 101.9
    assert asyncio.run(floor_strategy._apply_portfolio_guards(BASE_TS + 300_000)) is True
    assert floor_broker.positions == {}
    assert floor_strategy.runtime["last_guard_reason"] == "daily_profit_floor"

    loss_strategy, loss_broker, loss_key = opened_reversion_strategy(
        config={"daily_loss_pct": 0.025}
    )
    loss_strategy.runtime["day_number"] = day
    loss_strategy.runtime["day_start_equity"] = 100.0
    loss_broker.equity = 97.4
    assert asyncio.run(loss_strategy._apply_portfolio_guards(BASE_TS)) is True
    assert loss_key in loss_strategy.entry_state
    assert loss_broker.positions

    terminal, terminal_broker, terminal_key = opened_reversion_strategy(
        config={"terminal_floor_equity": 88}
    )
    terminal_broker.equity = 87.9
    assert asyncio.run(terminal._apply_portfolio_guards(BASE_TS)) is True
    assert terminal.runtime["terminal_reason"] == "equity_floor_88"
    assert terminal_key not in terminal.entry_state


def test_four_losses_pause_two_hours_and_runtime_restores():
    strategy, _, _ = opened_reversion_strategy(
        config={"loss_cooldown_count": 4, "loss_cooldown_hours": 2}
    )
    for index in range(4):
        strategy._record_closed_result(-0.2, BASE_TS + index * 300_000)

    assert strategy.runtime["loss_streak"] == 0
    assert strategy.runtime["pause_until_ms"] == BASE_TS + 3 * 300_000 + 2 * 3_600_000

    strategy._persist_runtime()
    restored, _ = init_strategy(
        state_positions={"_vwap_reversion_runtime": dict(strategy.runtime)}
    )
    assert restored.runtime["pause_until_ms"] == strategy.runtime["pause_until_ms"]
