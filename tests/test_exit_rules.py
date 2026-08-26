import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.strategies.exit_rules import ExitContext, ExitPolicyConfig, ExitPositionState, evaluate_exit


def test_exit_rules_lift_stop_to_breakeven_and_profit_atr_trail_for_long():
    state = ExitPositionState(
        symbol="ETH/USDT:USDT",
        side="long",
        entry_price=100.0,
        opened_bar=1,
        highest_price=100.0,
        lowest_price=100.0,
        initial_risk=10.0,
        trailing_stop=70.0,
    )
    config = ExitPolicyConfig(
        break_even_at_r=1.0,
        break_even_buffer_bps=10.0,
        profit_atr_trailing_start_r=1.5,
        profit_atr_stop_mult=2.0,
    )

    new_state, decision = evaluate_exit(
        ExitContext(
            symbol="ETH/USDT:USDT",
            side="long",
            price=120.0,
            high=122.0,
            low=118.0,
            volatility=4.0,
            bar_count=5,
        ),
        state,
        config,
    )

    assert decision.decision is None
    assert new_state.highest_price == pytest.approx(122.0)
    assert new_state.trailing_stop == pytest.approx(114.0)
    assert decision.current_profit_r == pytest.approx(2.0)
    assert decision.peak_profit_r == pytest.approx(2.2)


def test_exit_rules_peak_pullback_uses_tightened_threshold_after_large_profit():
    state = ExitPositionState(
        symbol="ETH/USDT:USDT",
        side="short",
        entry_price=100.0,
        opened_bar=1,
        highest_price=100.0,
        lowest_price=60.0,
        initial_risk=10.0,
        trailing_stop=130.0,
    )
    config = ExitPolicyConfig(
        profit_trailing_start_r=2.0,
        profit_peak_pullback_pct=0.35,
        profit_tighten_at_r=3.0,
        profit_tight_pullback_pct=0.22,
    )

    new_state, decision = evaluate_exit(
        ExitContext(
            symbol="ETH/USDT:USDT",
            side="short",
            price=70.0,
            high=72.0,
            low=68.0,
            volatility=5.0,
            bar_count=8,
        ),
        state,
        config,
    )

    assert new_state.lowest_price == pytest.approx(60.0)
    assert decision.decision == "exit_profit_pullback"
    assert decision.current_profit_r == pytest.approx(3.0)
    assert decision.peak_profit_r == pytest.approx(4.0)
    assert "22%" in decision.reason


def test_exit_rules_time_decay_exits_when_old_winning_trade_gives_back_most_profit():
    state = ExitPositionState(
        symbol="ETH/USDT:USDT",
        side="long",
        entry_price=100.0,
        opened_bar=1,
        highest_price=135.0,
        lowest_price=100.0,
        initial_risk=10.0,
    )
    config = ExitPolicyConfig(
        profit_trailing_start_r=1.5,
        max_profit_hold_bars=20,
        profit_decay_exit_pct=0.60,
    )

    _, decision = evaluate_exit(
        ExitContext(
            symbol="ETH/USDT:USDT",
            side="long",
            price=115.0,
            high=116.0,
            low=114.0,
            volatility=3.0,
            bar_count=25,
        ),
        state,
        config,
    )

    assert decision.decision == "exit_profit_decay"
    assert decision.hold_bars == 24
    assert decision.current_profit_r == pytest.approx(1.5)
    assert decision.peak_profit_r == pytest.approx(3.5)
