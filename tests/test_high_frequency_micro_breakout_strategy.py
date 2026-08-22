import asyncio
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SOURCE_PATH = ROOT / "scripts/strategy_sources/high_frequency_micro_breakout.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, StrategyState  # noqa: E402
from app.services.agent.code_sandbox import load_base_strategy_class  # noqa: E402


SYMBOL = "BTC/USDT:USDT"
BASE_TS = 1_800_000_000_000 // 3_600_000 * 3_600_000
FUTURE_VOLUME_SYMBOL = "FUTURE/USDT:USDT"


class FakeBroker:
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
        return {"status": "filled", "symbol": symbol, "side": side, "price": price}

    async def get_contract_position(self, symbol, side):
        return self.positions.get((symbol, side))

    async def get_available_balance(self, currency="USDT"):
        return self.balance


def strategy_class():
    assert SOURCE_PATH.exists(), "唯一动态策略源码尚未创建"
    return load_base_strategy_class(SOURCE_PATH.read_text(encoding="utf-8"))


def make_bar(
    index,
    close=100.0,
    *,
    high=None,
    low=None,
    volume=1_000.0,
    symbol=SYMBOL,
    timeframe="5m",
):
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe=timeframe,
        timestamp=BASE_TS + index * 300_000,
        open=close,
        high=close if high is None else high,
        low=close if low is None else low,
        close=close,
        volume=volume,
    )


def init_strategy(*, symbols=None, config=None, state_positions=None):
    cls = strategy_class()
    state = StrategyState(
        strategy_id=9_101,
        name="[合约][5M][CTA] Top20 · 1H状态微突破锁利 · 100U",
        exchange="okx",
        symbols=list(symbols or [SYMBOL]),
        created_at=datetime.now(timezone.utc),
        status="running",
        positions={"_capital": 100.0, **(state_positions or {})},
    )
    broker = FakeBroker()
    strategy = cls(state, broker)
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


def test_strategy_source_loads_and_initializes_runtime_keys():
    strategy, _ = init_strategy()

    assert strategy.__class__.__name__ == "HighFrequencyMicroBreakoutStrategy"
    assert strategy.runtime_key == "_micro_breakout_runtime"
    assert strategy.pool_view_key == "_dynamic_pool_view"


def test_pure_calculation_helpers_are_deterministic():
    strategy, _ = init_strategy()
    bars = [
        {
            "open": 100 + index,
            "high": 101 + index,
            "low": 99 + index,
            "close": 100 + index,
            "volume": 1_000,
        }
        for index in range(20)
    ]

    assert strategy._ema([1, 2, 3], 2) == pytest.approx([1.0, 1.6666667, 2.5555556])
    assert strategy._atr(bars, 14) > 0
    assert strategy._efficiency([1, 2, 1, 3], 3) == pytest.approx(0.5)
    assert strategy._median([5, 1, 3, 2]) == pytest.approx(2.5)
    assert strategy._adx(bars, 14) >= 0
    assert math.isfinite(strategy._adx(bars, 14))


def test_one_hour_state_uses_only_twelve_completed_five_minute_bars():
    strategy, _ = init_strategy()

    for index in range(12):
        assert strategy._aggregate_5m_bar(make_bar(index, close=100 + index)) is None

    completed = strategy._aggregate_5m_bar(make_bar(12, close=112))

    assert completed["timestamp"] == BASE_TS
    assert completed["open"] == pytest.approx(100)
    assert completed["close"] == pytest.approx(111)
    assert completed["volume"] == pytest.approx(12_000)
    assert len(strategy.h1_bars[SYMBOL]) == 1


def test_aggregation_rejects_out_of_order_or_non_five_minute_bars():
    strategy, _ = init_strategy()
    strategy._aggregate_5m_bar(make_bar(0))

    with pytest.raises(ValueError, match="5M时间戳必须严格递增"):
        strategy._aggregate_5m_bar(make_bar(0))

    malformed = make_bar(1, timeframe="15m")
    with pytest.raises(ValueError, match="仅接受5M已确认K线"):
        strategy._aggregate_5m_bar(malformed)


def h1_row(index, close, *, volume=1_000.0, high=None, low=None):
    return {
        "bucket": 500 + index,
        "timestamp": (500 + index) * 3_600_000,
        "open": float(close),
        "high": float(close + 0.5 if high is None else high),
        "low": float(close - 0.5 if low is None else low),
        "close": float(close),
        "volume": float(volume),
    }


def trend_history(*, direction=1, count=48, step=0.18, volume=1_000.0):
    start = 100.0 if direction > 0 else 120.0
    return [h1_row(index, start + direction * step * index, volume=volume) for index in range(count)]


def test_dynamic_top20_uses_only_trailing_completed_turnover():
    symbols = [f"S{index:02d}/USDT:USDT" for index in range(24)] + [FUTURE_VOLUME_SYMBOL]
    strategy, _ = init_strategy(symbols=symbols, config={"candidate_count": 20})
    completed_hour = 547
    for index, symbol in enumerate(symbols):
        history = trend_history(volume=100 + index)
        if symbol == FUTURE_VOLUME_SYMBOL:
            for row in history:
                row["volume"] = 1.0
            future = h1_row(60, 100, volume=1_000_000_000)
            history.append(future)
        strategy.h1_bars[symbol] = history

    strategy._refresh_universe(completed_hour)

    assert len(strategy.candidate_symbols) == 20
    assert FUTURE_VOLUME_SYMBOL not in strategy.candidate_symbols
    assert "S23/USDT:USDT" in strategy.candidate_symbols


@pytest.mark.parametrize(
    ("config", "history"),
    [
        ({"atr_pct_min": 2.0}, trend_history(step=0.03)),
        ({"atr_pct_max": 0.5}, trend_history(step=0.18)),
        ({"efficiency_min": 0.95}, [h1_row(i, 100 + (i % 2) * 0.4) for i in range(48)]),
        ({"adx_min": 101}, trend_history(step=0.18)),
        ({"extension_atr_max": 0.1}, trend_history(step=0.18)),
    ],
)
def test_state_score_fails_closed_when_a_hard_gate_is_missing(config, history):
    strategy, _ = init_strategy(config=config)
    strategy.candidate_symbols = {SYMBOL}
    strategy.h1_bars[SYMBOL] = history

    assert strategy._score_symbol(SYMBOL, completed_hour=547) is None


def test_state_requires_two_same_direction_confirmations_before_openable():
    strategy, _ = init_strategy(
        config={
            "candidate_count": 20,
            "state_confirmations": 2,
            "score_min": 65,
            "atr_pct_min": 0.5,
            "atr_pct_max": 6.0,
            "efficiency_min": 0.22,
            "adx_min": 18,
            "extension_atr_max": 2.2,
        }
    )
    strategy.candidate_symbols = {SYMBOL}
    strategy.h1_bars[SYMBOL] = trend_history(step=0.18)

    strategy._refresh_scores(completed_hour=547)
    first = strategy.latest_scores[SYMBOL]
    strategy._refresh_scores(completed_hour=548)
    second = strategy.latest_scores[SYMBOL]

    assert first["direction"] == 1
    assert first["confirmed"] == 1
    assert first["openable"] is False
    assert second["confirmed"] == 2
    assert second["openable"] is True
    assert second["score"] >= 65


def test_cross_section_refreshes_once_after_sixty_percent_quorum():
    symbols = [f"Q{index}/USDT:USDT" for index in range(5)]
    strategy, _ = init_strategy(symbols=symbols)
    for symbol in symbols:
        strategy.h1_bars[symbol] = trend_history()

    assert strategy._register_completed_hour(symbols[0], 548) is False
    assert strategy._register_completed_hour(symbols[1], 548) is False
    assert strategy._register_completed_hour(symbols[2], 548) is True
    assert strategy._register_completed_hour(symbols[3], 548) is False
    assert strategy.last_scored_hour == 548


def micro_bar(
    index,
    close=100.0,
    *,
    high=None,
    low=None,
    volume=100.0,
    symbol=SYMBOL,
):
    return make_bar(
        index,
        close=close,
        high=close + 0.4 if high is None else high,
        low=close - 0.4 if low is None else low,
        volume=volume,
        symbol=symbol,
    )


def seeded_entry_strategy(*, config=None, direction=1):
    strategy, broker = init_strategy(
        config={
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
            **(config or {}),
        }
    )
    strategy.latest_scores[SYMBOL] = {
        "symbol": SYMBOL,
        "direction": direction,
        "score": 75.0,
        "openable": True,
    }
    strategy.bars_5m[SYMBOL] = [micro_bar(index) for index in range(20)]
    strategy.five_minute_counts[SYMBOL] = 20
    return strategy, broker


def test_entry_requires_breakout_volume_and_three_times_round_trip_cost():
    low_edge, _ = seeded_entry_strategy(config={"initial_stop_atr_mult": 0.3})
    qualifying_bar = micro_bar(20, close=100.7, high=100.9, low=100.1, volume=140)

    assert low_edge._entry_trigger(SYMBOL, qualifying_bar) is None

    strategy, _ = seeded_entry_strategy()
    trigger = strategy._entry_trigger(SYMBOL, qualifying_bar)

    assert trigger["side"] == "long"
    assert trigger["target_distance_bps"] >= 60
    assert trigger["volume_ratio"] >= 1.35


@pytest.mark.parametrize(
    ("bar", "runtime_patch"),
    [
        (micro_bar(20, close=100.7, high=100.9, low=100.1, volume=120), {}),
        (micro_bar(20, close=100.7, high=100.72, low=100.68, volume=140), {}),
        (micro_bar(20, close=102.0, high=102.2, low=101.4, volume=140), {}),
        (
            micro_bar(20, close=100.7, high=100.9, low=100.1, volume=140),
            {f"{SYMBOL}|long": 25},
        ),
    ],
)
def test_entry_rejects_weak_volume_range_extension_or_cooldown(bar, runtime_patch):
    strategy, _ = seeded_entry_strategy()
    strategy.cooldown_until_bar.update(runtime_patch)

    assert strategy._entry_trigger(SYMBOL, bar) is None


def test_short_entry_is_a_mirror_of_long_entry():
    strategy, _ = seeded_entry_strategy(direction=-1)
    strategy.bars_5m[SYMBOL] = [
        micro_bar(index, close=100, high=100.4, low=99.6) for index in range(20)
    ]

    trigger = strategy._entry_trigger(
        SYMBOL,
        micro_bar(20, close=99.3, high=99.9, low=99.1, volume=140),
    )

    assert trigger["side"] == "short"
    assert trigger["stop_price"] > trigger["entry_price"]
    assert trigger["take_profit_price"] < trigger["entry_price"]


def test_order_plan_caps_risk_notional_and_total_exposure():
    strategy, _ = seeded_entry_strategy(
        config={
            "risk_per_trade_pct": 0.005,
            "max_position_notional_usdt": 50,
            "max_positions": 3,
            "same_direction_cap": 2,
            "max_total_notional_equity_pct": 1.5,
        }
    )

    plan = strategy._order_plan(equity=100, entry=100, stop=99.5, side="long")

    assert plan["risk_usdt"] <= 0.5
    assert plan["notional_usdt"] <= 50
    assert plan["notional_usdt"] * 0.005 <= 0.5

    strategy.entry_state = {
        "A|long": {"side": "long", "notional_usdt": 50},
        "B|long": {"side": "long", "notional_usdt": 50},
    }
    assert strategy._order_plan(equity=100, entry=100, stop=99.5, side="long") is None

    strategy.entry_state = {
        "A|long": {"side": "long", "notional_usdt": 70},
        "B|short": {"side": "short", "notional_usdt": 70},
    }
    remaining = strategy._order_plan(equity=100, entry=100, stop=99.5, side="long")
    assert remaining["notional_usdt"] <= 10


def opened_position_strategy(*, side="long", entry=100.0, risk=0.5, config=None):
    strategy, broker = seeded_entry_strategy(
        config={
            "break_even_at_r": 0.45,
            "profit_trailing_start_r": 0.75,
            "profit_peak_pullback_pct": 0.30,
            "profit_atr_stop_mult": 0.65,
            "failed_breakout_exit_bars": 3,
            "failure_buffer_atr": 0.15,
            "max_holding_bars": 24,
            "cooldown_bars": 6,
            **(config or {}),
        },
        direction=1 if side == "long" else -1,
    )
    key = f"{SYMBOL}|{side}"
    stop = entry - risk if side == "long" else entry + risk
    take = entry + risk * 1.15 if side == "long" else entry - risk * 1.15
    strategy.entry_state[key] = {
        "symbol": SYMBOL,
        "side": side,
        "entry_price": entry,
        "initial_risk_price": risk,
        "stop_price": stop,
        "take_profit_price": take,
        "highest": entry,
        "lowest": entry,
        "entry_bar_count": 20,
        "breakout_level": entry - 0.2 if side == "long" else entry + 0.2,
        "atr": 0.8,
        "notional_usdt": 50,
    }
    broker.positions[(SYMBOL, side)] = {
        "symbol": SYMBOL,
        "side": side,
        "entry_price": entry,
        "notional_value": 50,
    }
    strategy.five_minute_counts[SYMBOL] = 21
    return strategy, broker, key


@pytest.mark.parametrize(
    ("side", "high", "low", "expected_stop"),
    [
        ("long", 101.0, 99.0, 99.5),
        ("short", 101.0, 99.0, 100.5),
    ],
)
def test_same_bar_stop_has_priority_over_take_profit(side, high, low, expected_stop):
    strategy, broker, key = opened_position_strategy(side=side)

    result = asyncio.run(
        strategy._manage_position(
            SYMBOL,
            side,
            micro_bar(21, close=100.0, high=high, low=low, volume=140),
        )
    )

    assert result["status"] == "filled"
    assert broker.orders[-1]["price"] == pytest.approx(expected_stop)
    assert key not in strategy.entry_state
    assert strategy.cooldown_until_bar[key] == 27


def test_break_even_and_trailing_lock_profit_before_next_bar_exit():
    strategy, broker, key = opened_position_strategy(side="long")

    asyncio.run(
        strategy._manage_position(
            SYMBOL,
            "long",
            micro_bar(21, close=100.45, high=100.5, low=100.3, volume=140),
        )
    )
    locked_stop = strategy.entry_state[key]["stop_price"]

    assert locked_stop >= 100.2
    assert broker.orders == []

    result = asyncio.run(
        strategy._manage_position(
            SYMBOL,
            "long",
            micro_bar(22, close=locked_stop, high=100.4, low=locked_stop - 0.01, volume=100),
        )
    )

    assert result["status"] == "filled"
    assert broker.orders[-1]["price"] == pytest.approx(locked_stop)
    assert key not in strategy.entry_state


@pytest.mark.parametrize(
    ("bars_held", "close", "expected_reason"),
    [
        (2, 99.6, "failed_breakout"),
        (24, 100.1, "time_exit_120m"),
    ],
)
def test_failed_breakout_and_time_exit_clear_state(bars_held, close, expected_reason):
    strategy, broker, key = opened_position_strategy(side="long")
    strategy.five_minute_counts[SYMBOL] = 20 + bars_held

    result = asyncio.run(
        strategy._manage_position(
            SYMBOL,
            "long",
            micro_bar(20 + bars_held, close=close, high=close + 0.05, low=close - 0.05),
        )
    )

    assert result["status"] == "filled"
    assert strategy.runtime["last_exit_reason"] == expected_reason
    assert key not in strategy.entry_state
    assert broker.positions == {}


def test_daily_profit_floor_closes_positions_and_pauses_until_next_day():
    strategy, broker, _ = opened_position_strategy(
        config={
            "daily_loss_pct": 0.03,
            "daily_lock_activation_pct": 0.02,
            "daily_lock_fraction": 0.40,
        }
    )
    day = BASE_TS // 86_400_000
    strategy.runtime["day_number"] = day
    strategy.runtime["day_start_equity"] = 100.0
    broker.equity = 104.0

    assert asyncio.run(strategy._apply_portfolio_guards(BASE_TS)) is False
    assert strategy.runtime["daily_profit_floor"] == pytest.approx(101.6)

    broker.equity = 101.5
    blocked = asyncio.run(strategy._apply_portfolio_guards(BASE_TS + 300_000))

    assert blocked is True
    assert broker.positions == {}
    assert strategy.runtime["pause_until_day"] == day + 1
    assert strategy.runtime["last_guard_reason"] == "daily_profit_floor"


def test_daily_loss_pauses_new_entries_without_forcing_existing_position():
    strategy, broker, key = opened_position_strategy(config={"daily_loss_pct": 0.03})
    day = BASE_TS // 86_400_000
    strategy.runtime["day_number"] = day
    strategy.runtime["day_start_equity"] = 100.0
    broker.equity = 96.9

    blocked = asyncio.run(strategy._apply_portfolio_guards(BASE_TS))

    assert blocked is True
    assert key in strategy.entry_state
    assert broker.positions
    assert strategy.runtime["pause_until_day"] == day + 1


def test_terminal_floor_is_permanent_and_runtime_state_restores():
    strategy, broker, key = opened_position_strategy(config={"terminal_floor_equity": 85})
    broker.equity = 84.9

    assert asyncio.run(strategy._apply_portfolio_guards(BASE_TS)) is True
    assert broker.positions == {}
    assert strategy.runtime["terminal_reason"] == "equity_floor_85"
    assert key not in strategy.entry_state

    restored, _ = init_strategy(
        state_positions={"_micro_breakout_runtime": dict(strategy.runtime)}
    )
    assert restored.runtime["terminal_reason"] == "equity_floor_85"
    assert asyncio.run(restored._apply_portfolio_guards(BASE_TS + 86_400_000)) is True


def test_four_consecutive_losses_pause_new_entries_for_two_hours():
    strategy, _ = seeded_entry_strategy(
        config={"loss_cooldown_count": 4, "loss_cooldown_hours": 2}
    )

    for index in range(4):
        strategy._record_closed_result(-0.25, BASE_TS + index * 300_000)

    assert strategy.runtime["loss_streak"] == 0
    assert strategy.runtime["pause_until_ms"] == BASE_TS + 3 * 300_000 + 2 * 3_600_000
    assert asyncio.run(strategy._apply_portfolio_guards(BASE_TS + 4 * 300_000)) is True
