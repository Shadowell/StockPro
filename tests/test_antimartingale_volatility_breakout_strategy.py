import asyncio
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SOURCE_PATH = ROOT / "scripts/strategy_sources/antimartingale_volatility_breakout.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, StrategyState  # noqa: E402
from app.services.agent.code_sandbox import load_base_strategy_class  # noqa: E402


SYMBOL = "BTC/USDT:USDT"


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
        return {
            "status": "filled",
            "symbol": symbol,
            "side": side,
            "notional_usdt": float(notional_usdt),
            "price": price,
        }

    async def close_contract(self, symbol, side, ratio=1.0, contracts=None, price=None):
        self.orders.append(
            {"action": "close", "symbol": symbol, "side": side, "ratio": ratio, "price": price}
        )
        self.positions.pop((symbol, side), None)
        return {"status": "filled", "symbol": symbol, "side": side, "price": price, "realized_pnl": 0.0}

    async def get_contract_position(self, symbol, side):
        return self.positions.get((symbol, side))

    async def get_available_balance(self, currency="USDT"):
        return self.balance


@pytest.fixture(scope="module")
def strategy_class():
    if not SOURCE_PATH.exists():
        pytest.skip("唯一动态策略源码尚未创建")
    return load_base_strategy_class(SOURCE_PATH.read_text(encoding="utf-8"))


def make_bar(index, close=100.0, *, high=None, low=None, volume=1_000.0, symbol=SYMBOL):
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="15m",
        timestamp=1_800_000_000_000 + index * 900_000,
        open=close,
        high=close if high is None else high,
        low=close if low is None else low,
        close=close,
        volume=volume,
    )


def init_strategy(strategy_class, *, symbols=None, config=None):
    state = StrategyState(
        strategy_id=9_001,
        name="[合约][15M][CTA] Top60 · 波动爆发反马丁冲刺版 · 100U",
        exchange="okx",
        symbols=list(symbols or [SYMBOL]),
        created_at=datetime.now(timezone.utc),
        status="running",
        positions={"_capital": 100.0},
    )
    broker = FakeBroker()
    strategy = strategy_class(state, broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "timeframe": "15m",
            "primary_signal_timeframe": "1h",
            "leverage": 5,
            "min_h1_bars": 110,
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy, broker


def h1_bar(index, close, *, high=None, low=None, volume=1_000.0):
    return {
        "timestamp": 1_800_000_000_000 + index * 3_600_000,
        "open": close,
        "high": close + 1 if high is None else high,
        "low": close - 1 if low is None else low,
        "close": close,
        "volume": volume,
    }


def test_strategy_source_file_exists():
    assert SOURCE_PATH.exists(), "唯一动态策略源码尚未创建"


def test_strategy_source_loads_as_base_strategy(strategy_class):
    strategy, _ = init_strategy(strategy_class)

    assert strategy.__class__.__name__ == "AntiMartingaleVolatilityBreakoutStrategy"
    assert strategy.runtime_key == "_antimartingale_runtime"
    assert strategy.pool_view_key == "_dynamic_pool_view"


def test_pure_calculation_helpers_are_deterministic(strategy_class):
    strategy, _ = init_strategy(strategy_class)
    bars = [h1_bar(i, 100 + i, high=101 + i, low=99 + i) for i in range(20)]

    assert strategy._ema([1, 2, 3], 2) == pytest.approx([1.0, 1.6666667, 2.5555556])
    assert strategy._atr(bars, 14) > 0
    assert strategy._efficiency([1, 2, 1, 3], 3) == pytest.approx(0.5)
    assert strategy._percentile_rank(2, [1, 2, 3]) == pytest.approx(50.0)
    assert strategy._correlation([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert math.isfinite(strategy._correlation([1, 1, 1], [2, 2, 2]))


def test_symbol_is_not_scored_before_complete_h1_history(strategy_class):
    strategy, _ = init_strategy(strategy_class)
    strategy.h1_bars[SYMBOL] = [h1_bar(i, 100 + i * 0.1) for i in range(109)]

    assert strategy._score_symbol(SYMBOL, completed_hour=500) is None


def qualifying_score(**overrides):
    row = {
        "symbol": SYMBOL,
        "direction": 1,
        "score": 72.0,
        "atr_pct": 3.0,
        "efficiency": 0.25,
        "extension_atr": 1.0,
        "ema_slope": 0.2,
        "confirmed": 2,
        "openable": True,
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    "overrides",
    [
        {"atr_pct": 1.99},
        {"atr_pct": 8.01},
        {"efficiency": 0.119},
        {"extension_atr": 2.51},
        {"score": 64.9},
        {"confirmed": 1},
        {"ema_slope": -0.1},
    ],
)
def test_hard_score_gates_reject_non_qualifying_rows(strategy_class, overrides):
    strategy, _ = init_strategy(strategy_class)

    assert strategy._passes_hard_gates(qualifying_score(**overrides)) is False


def test_breakout_requires_score_volume_and_non_extension(strategy_class):
    strategy, _ = init_strategy(strategy_class)
    strategy.latest_scores[SYMBOL] = qualifying_score()
    strategy.bars_15m[SYMBOL] = [make_bar(i, close=100, high=101, low=99, volume=1_000) for i in range(20)]

    quiet = make_bar(20, close=102, high=102, low=100, volume=1_799)
    breakout = make_bar(20, close=102, high=102, low=100, volume=1_800)

    assert strategy._entry_trigger(SYMBOL, quiet) is None
    assert strategy._entry_trigger(SYMBOL, breakout) == {
        "symbol": SYMBOL,
        "side": "long",
        "score": 72.0,
    }


def test_cross_section_keeps_only_top_sixty_and_requires_two_confirmations(strategy_class):
    symbols = [f"S{i}/USDT:USDT" for i in range(65)]
    strategy, _ = init_strategy(strategy_class, symbols=symbols)
    for index, symbol in enumerate(symbols):
        strategy.latest_scores[symbol] = qualifying_score(symbol=symbol, score=100 - index * 0.5)

    strategy._rank_candidates(completed_hour=500)
    assert len(strategy.candidate_symbols) == 60
    assert strategy.latest_scores[symbols[0]]["confirmed"] == 1
    assert strategy.latest_scores[symbols[0]]["openable"] is False

    strategy._rank_candidates(completed_hour=501)
    assert strategy.latest_scores[symbols[0]]["confirmed"] == 2
    assert strategy.latest_scores[symbols[0]]["openable"] is True
    assert symbols[-1] not in strategy.candidate_symbols


def test_initial_order_plan_risks_four_pct_and_respects_notional_cap(strategy_class):
    strategy, _ = init_strategy(strategy_class)

    plan = strategy._initial_order_plan(equity=100, entry_price=100, atr=2)

    assert plan["risk_usdt"] == pytest.approx(4.0)
    assert plan["risk_price"] == pytest.approx(2.4)
    assert plan["notional_usdt"] == pytest.approx(166.6666667)
    assert plan["leverage"] == 5


def test_open_trigger_creates_auditable_position_state(strategy_class):
    strategy, broker = init_strategy(strategy_class)
    strategy.latest_scores[SYMBOL] = {"atr": 2.0, "score": 72.0}

    asyncio.run(
        strategy._open_trigger(
            {"symbol": SYMBOL, "side": "long", "score": 72.0},
            make_bar(20, close=100, high=101, low=99, volume=2_000),
        )
    )

    assert broker.orders[-1]["action"] == "open"
    state = strategy.entry_state[f"{SYMBOL}|long"]
    assert state["initial_risk_usdt"] == pytest.approx(4.0)
    assert state["initial_risk_price"] == pytest.approx(2.4)
    assert state["adds"] == 0
    assert state["legs"] == [{"price": 100.0, "notional": pytest.approx(166.6666667)}]


def seed_position(strategy, broker, *, side="long", entry=100.0, risk_price=2.0, notional=100.0):
    key = f"{SYMBOL}|{side}"
    broker.positions[(SYMBOL, side)] = {
        "symbol": SYMBOL,
        "side": side,
        "entry_price": entry,
        "notional_usdt": notional,
        "contracts": 1.0,
    }
    strategy.entry_state[key] = {
        "entry_price": entry,
        "initial_risk_price": risk_price,
        "initial_risk_usdt": 4.0,
        "initial_notional": notional,
        "total_notional": notional,
        "adds": 0,
        "highest": entry,
        "lowest": entry,
        "stop_price": entry - risk_price if side == "long" else entry + risk_price,
        "peak_r": 0.0,
        "entry_hour": 0,
    }
    return key


def test_long_adds_half_only_after_one_r_and_moves_stop_to_cost(strategy_class):
    strategy, broker = init_strategy(strategy_class)
    key = seed_position(strategy, broker)

    asyncio.run(strategy._manage_position(SYMBOL, "long", make_bar(1, close=102, high=102.1, low=100.5)))

    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["notional_usdt"] == pytest.approx(50.0)
    assert strategy.entry_state[key]["adds"] == 1
    assert strategy.entry_state[key]["stop_price"] >= 99.99


def test_losing_position_never_adds_and_stop_closes(strategy_class):
    strategy, broker = init_strategy(strategy_class)
    key = seed_position(strategy, broker)

    asyncio.run(strategy._manage_position(SYMBOL, "long", make_bar(1, close=98, high=99, low=97.9)))

    assert [order["action"] for order in broker.orders] == ["close"]
    assert key not in strategy.entry_state


def test_same_bar_stop_has_priority_over_ten_r_take_profit(strategy_class):
    strategy, broker = init_strategy(strategy_class)
    seed_position(strategy, broker)

    asyncio.run(strategy._manage_position(SYMBOL, "long", make_bar(1, close=105, high=121, low=97)))

    assert broker.orders[-1]["action"] == "close"
    assert broker.orders[-1]["price"] == pytest.approx(98.0)


def test_short_position_adds_and_uses_mirrored_stop(strategy_class):
    strategy, broker = init_strategy(strategy_class)
    key = seed_position(strategy, broker, side="short")

    asyncio.run(strategy._manage_position(SYMBOL, "short", make_bar(1, close=98, high=99.5, low=97.9)))

    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["side"] == "short"
    assert strategy.entry_state[key]["adds"] == 1
    assert strategy.entry_state[key]["stop_price"] <= 100.0


def test_second_add_is_quarter_size_and_locks_point_eight_r(strategy_class):
    strategy, broker = init_strategy(strategy_class)
    key = seed_position(strategy, broker)
    strategy.entry_state[key]["adds"] = 1
    strategy.entry_state[key]["total_notional"] = 150.0
    strategy.entry_state[key]["legs"] = [
        {"price": 100.0, "notional": 100.0},
        {"price": 102.0, "notional": 50.0},
    ]

    asyncio.run(strategy._manage_position(SYMBOL, "long", make_bar(2, close=104, high=104.1, low=102.5)))

    assert broker.orders[-1]["notional_usdt"] == pytest.approx(25.0)
    assert strategy.entry_state[key]["adds"] == 2
    assert strategy.entry_state[key]["stop_price"] >= 101.6
    assert strategy._basket_worst_pnl(strategy.entry_state[key], "long") >= -1.0


def test_four_r_tightens_trailing_stop_without_waiting_for_fixed_profit(strategy_class):
    strategy, broker = init_strategy(strategy_class)
    key = seed_position(strategy, broker)
    strategy.latest_scores[SYMBOL] = {"atr": 2.0}

    asyncio.run(strategy._manage_position(SYMBOL, "long", make_bar(4, close=108, high=108.2, low=103)))

    assert not any(order["action"] == "close" for order in broker.orders)
    assert strategy.entry_state[key]["stop_price"] >= 105.7


def test_sixty_floor_closes_all_and_is_permanent(strategy_class):
    strategy, broker = init_strategy(strategy_class)
    seed_position(strategy, broker)
    broker.equity = 59.9

    blocked = asyncio.run(strategy._apply_portfolio_guards(1_800_000_000_000))

    assert blocked is True
    assert broker.orders[-1]["action"] == "close"
    assert strategy.runtime["terminal_reason"] == "equity_floor_60"
    assert asyncio.run(strategy._apply_portfolio_guards(1_800_000_900_000)) is True


def test_two_hundred_target_closes_all_and_marks_success(strategy_class):
    strategy, broker = init_strategy(strategy_class)
    seed_position(strategy, broker)
    broker.equity = 200.1

    assert asyncio.run(strategy._apply_portfolio_guards(1_800_000_000_000)) is True
    assert strategy.runtime["terminal_reason"] == "target_200"


def test_equity_ratchet_floor_terminates_instead_of_restarting(strategy_class):
    strategy, broker = init_strategy(strategy_class)
    broker.equity = 140.0
    assert asyncio.run(strategy._apply_portfolio_guards(1_800_000_000_000)) is False
    assert strategy.runtime["equity_floor"] == pytest.approx(120.0)

    broker.equity = 119.9
    assert asyncio.run(strategy._apply_portfolio_guards(1_800_000_900_000)) is True
    assert strategy.runtime["terminal_reason"] == "ratchet_exit"


def test_daily_eight_pct_loss_pauses_only_until_next_day(strategy_class):
    strategy, broker = init_strategy(strategy_class)
    day = 20_000
    now = day * 86_400_000
    strategy.runtime["day_number"] = day
    strategy.runtime["day_start_equity"] = 100.0
    broker.equity = 91.9

    assert asyncio.run(strategy._apply_portfolio_guards(now)) is True
    assert strategy.runtime["pause_until_day"] == day + 1

    broker.equity = 92.0
    assert asyncio.run(strategy._apply_portfolio_guards((day + 1) * 86_400_000)) is False


def test_runtime_state_restores_terminal_and_entry_state(strategy_class):
    strategy, broker = init_strategy(strategy_class)
    key = seed_position(strategy, broker)
    strategy.runtime["terminal_reason"] = "ratchet_exit"
    strategy._persist_runtime()

    restored, _ = init_strategy(strategy_class)
    restored.state.positions[strategy.runtime_key] = dict(strategy.state.positions[strategy.runtime_key])
    asyncio.run(restored.on_init())

    assert restored.runtime["terminal_reason"] == "ratchet_exit"
    assert key in restored.entry_state
