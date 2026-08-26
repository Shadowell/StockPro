import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SCRIPT_PATH = SCRIPTS / "research_high_frequency_micro_breakout.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def research_module():
    assert SCRIPT_PATH.exists(), "真实高频研究脚本尚未创建"
    import research_high_frequency_micro_breakout as module

    return module


def passing_metrics(**overrides):
    metrics = {
        "total_return_pct": 4.0,
        "profit_factor": 1.25,
        "max_drawdown_pct": 8.0,
        "round_trips_per_day": 24.0,
        "avg_holding_minutes": 75.0,
        "first_half_return_pct": 1.5,
        "second_half_return_pct": 2.0,
        "positive_rolling_15d_share": 0.75,
        "single_symbol_profit_share": 0.25,
        "stress_total_return_pct": 1.0,
        "stress_profit_factor": 1.10,
        "data_complete": True,
    }
    metrics.update(overrides)
    return metrics


def test_research_script_exists():
    assert SCRIPT_PATH.exists(), "真实高频研究脚本尚未创建"


def test_first_passage_uses_first_timestamp_not_terminal_value():
    module = research_module()

    assert module.classify_path([100, 205, 84], target=200, floor=85) == "target_200"
    assert module.classify_path([100, 84, 210], target=200, floor=85) == "floor_85"
    assert module.classify_path([100, 110, 105], target=200, floor=85) == "expired"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"total_return_pct": 0.0}, "盲测总收益不为正"),
        ({"profit_factor": 1.19}, "盲测利润因子低于1.20"),
        ({"max_drawdown_pct": 15.01}, "盲测最大回撤超过15%"),
        ({"round_trips_per_day": 19.9}, "盲测日均闭环少于20"),
        ({"round_trips_per_day": 35.1}, "盲测日均闭环超过35"),
        ({"avg_holding_minutes": 120.1}, "平均持有超过120分钟"),
        ({"first_half_return_pct": -0.1}, "盲测前半段不盈利"),
        ({"second_half_return_pct": 0.0}, "盲测后半段不盈利"),
        ({"positive_rolling_15d_share": 0.69}, "滚动15日正收益比例低于70%"),
        ({"single_symbol_profit_share": 0.301}, "单一标的正利润贡献超过30%"),
        ({"stress_total_return_pct": 0.0}, "压力成本收益不为正"),
        ({"stress_profit_factor": 1.049}, "压力成本利润因子低于1.05"),
        ({"data_complete": False}, "真实数据覆盖不完整"),
    ],
)
def test_gate_requires_frequency_stability_cost_and_data(overrides, reason):
    module = research_module()

    assert module.evaluate_gate(passing_metrics())["passed"] is True
    failed = module.evaluate_gate(passing_metrics(**overrides))

    assert failed["passed"] is False
    assert reason in failed["reasons"]


def test_parameter_hash_is_stable_and_shared_by_validation_and_oos():
    module = research_module()
    selected = {
        "breakout_window": 12,
        "volume_ratio": 1.35,
        "max_holding_bars": 24,
    }

    metadata = module.freeze_parameter_metadata(selected)

    assert metadata["validation_parameter_hash"] == metadata["oos_parameter_hash"]
    assert metadata["selected_parameters"] == selected
    assert metadata == module.freeze_parameter_metadata(dict(reversed(list(selected.items()))))


def test_rolling_fifteen_day_windows_cover_every_daily_start():
    module = research_module()
    day = 86_400_000

    starts = module.rolling_window_starts(0, 30 * day, window_days=15)

    assert starts[0] == 0
    assert starts[-1] == 15 * day
    assert len(starts) == 16


def test_missing_real_bars_fails_closed(tmp_path):
    module = research_module()

    with pytest.raises(module.ResearchDataError, match="真实5M K线不足"):
        module.discover_symbol_files(
            tmp_path,
            start_ms=1_000,
            end_ms=2_000,
            minimum_symbols=20,
        )


def test_research_broker_deducts_open_and_close_costs():
    module = research_module()
    broker = module.ResearchPaperBroker(initial_equity=100, cost_rate_per_side=0.001)
    broker.update_price("BTC/USDT:USDT", 100)

    opened = module.run_async(
        broker.open_contract(
            "BTC/USDT:USDT",
            "long",
            notional_usdt=100,
            leverage=5,
            price=100,
        )
    )
    broker.current_timestamp = 3_600_000
    broker.update_price("BTC/USDT:USDT", 101)
    closed = module.run_async(
        broker.close_contract("BTC/USDT:USDT", "long", ratio=1.0, price=101)
    )

    assert opened["status"] == "filled"
    assert closed["status"] == "filled"
    assert closed["realized_pnl"] == pytest.approx(0.799)
    assert broker.equity == pytest.approx(100.799)


def test_metrics_use_closed_round_trips_holding_time_drawdown_and_symbol_share():
    module = research_module()
    trades = [
        {"symbol": "A", "opened_at": 0, "closed_at": 3_600_000, "pnl": 2.0},
        {"symbol": "B", "opened_at": 0, "closed_at": 7_200_000, "pnl": -1.0},
        {"symbol": "B", "opened_at": 0, "closed_at": 3_600_000, "pnl": 1.0},
    ]
    equity = [(0, 100.0), (3_600_000, 102.0), (7_200_000, 99.0), (86_400_000, 102.0)]

    metrics = module.summarize_simulation(
        trades,
        equity,
        start_ms=0,
        end_ms=86_400_000,
    )

    assert metrics["closed_round_trips"] == 3
    assert metrics["round_trips_per_day"] == pytest.approx(3.0)
    assert metrics["avg_holding_minutes"] == pytest.approx(80.0)
    assert metrics["profit_factor"] == pytest.approx(3.0)
    assert metrics["max_drawdown_pct"] == pytest.approx(100 * 3 / 102)
    assert metrics["single_symbol_profit_share"] == pytest.approx(1.0)
