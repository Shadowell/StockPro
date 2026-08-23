import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SCRIPT_PATH = SCRIPTS / "research_high_frequency_vwap_reversion.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def module():
    assert SCRIPT_PATH.exists(), "VWAP回归真实研究脚本尚未创建"
    import research_high_frequency_vwap_reversion as value

    return value


def passing(**overrides):
    metrics = {
        "total_return_pct": 3.0,
        "profit_factor": 1.25,
        "max_drawdown_pct": 8.0,
        "round_trips_per_day": 24.0,
        "avg_holding_minutes": 60.0,
        "first_half_return_pct": 1.0,
        "second_half_return_pct": 1.5,
        "positive_rolling_15d_share": 0.75,
        "single_symbol_profit_share": 0.25,
        "stress_total_return_pct": 0.5,
        "stress_profit_factor": 1.10,
        "data_complete": True,
        "parameter_hash_match": True,
    }
    metrics.update(overrides)
    return metrics


def test_research_script_exists():
    assert SCRIPT_PATH.exists(), "VWAP回归真实研究脚本尚未创建"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"total_return_pct": 0}, "盲测总收益不为正"),
        ({"profit_factor": 1.19}, "盲测利润因子低于1.20"),
        ({"max_drawdown_pct": 12.01}, "盲测最大回撤超过12%"),
        ({"round_trips_per_day": 19.9}, "盲测日均闭环少于20"),
        ({"round_trips_per_day": 35.1}, "盲测日均闭环超过35"),
        ({"avg_holding_minutes": 29.9}, "平均持有少于30分钟"),
        ({"avg_holding_minutes": 120.1}, "平均持有超过120分钟"),
        ({"first_half_return_pct": 0}, "盲测前半段不盈利"),
        ({"second_half_return_pct": -0.1}, "盲测后半段不盈利"),
        ({"positive_rolling_15d_share": 0.69}, "滚动15日正收益比例低于70%"),
        ({"single_symbol_profit_share": 0.301}, "单一标的正利润贡献超过30%"),
        ({"stress_total_return_pct": 0}, "压力成本收益不为正"),
        ({"stress_profit_factor": 1.049}, "压力成本利润因子低于1.05"),
        ({"data_complete": False}, "真实数据覆盖不完整"),
        ({"parameter_hash_match": False}, "验证与盲测参数hash不一致"),
    ],
)
def test_vwap_gate_requires_holding_frequency_stability_and_cost(overrides, reason):
    value = module()

    assert value.evaluate_gate(passing())["passed"] is True
    failed = value.evaluate_gate(passing(**overrides))

    assert failed["passed"] is False
    assert reason in failed["reasons"]


def test_parameters_are_frozen_between_validation_and_oos():
    value = module()

    metadata = value.freeze_parameter_metadata(value.VWAP_PARAMETERS)

    assert metadata["validation_parameter_hash"] == metadata["oos_parameter_hash"]
    assert metadata["selected_parameters"]["z_entry"] == 2.0


def test_missing_real_data_reuses_fail_closed_loader(tmp_path):
    value = module()

    with pytest.raises(value.ResearchDataError, match="真实5M K线不足"):
        value.discover_symbol_files(tmp_path, start_ms=1_000, end_ms=2_000, minimum_symbols=20)
