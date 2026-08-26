import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.strategies.profit_protection import ProfitProtectionConfig, evaluate_exit


def test_profit_floor_exits_after_winning_trade_retraces_to_floor():
    decision = evaluate_exit(
        price=100.25,
        entry_price=100.0,
        peak_price=101.0,
        hold_bars=8,
        config=ProfitProtectionConfig(profit_floor_start_bps=50.0, profit_floor_bps=30.0),
    )

    assert decision.decision == "exit_profit_floor"
    assert round(decision.pnl_bps, 2) == 25.0
    assert round(decision.peak_pnl_bps, 2) == 100.0


def test_profit_floor_waits_until_peak_profit_threshold_was_reached():
    decision = evaluate_exit(
        price=100.10,
        entry_price=100.0,
        peak_price=100.30,
        hold_bars=8,
        config=ProfitProtectionConfig(profit_floor_start_bps=50.0, profit_floor_bps=30.0),
    )

    assert decision.decision is None


def test_trailing_stop_uses_peak_profit_and_pullback():
    decision = evaluate_exit(
        price=100.60,
        entry_price=100.0,
        peak_price=101.0,
        hold_bars=8,
        config=ProfitProtectionConfig(trailing_start_bps=50.0, trailing_pullback_bps=30.0),
    )

    assert decision.decision == "exit_trailing_stop"
    assert round(decision.pnl_bps, 2) == 60.0
    assert decision.pullback_bps > 30.0
