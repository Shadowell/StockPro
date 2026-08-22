import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SCRIPT_PATH = SCRIPTS / "research_antimartingale_volatility_breakout.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

if SCRIPT_PATH.exists():
    import research_antimartingale_volatility_breakout as research_module  # noqa: E402
    from research_antimartingale_volatility_breakout import (  # noqa: E402
        ResearchDataError,
        classify_path,
        evaluate_gate,
        summarize_paths,
    )
    is_contract_storage_symbol = getattr(research_module, "is_contract_storage_symbol", None)
else:
    ResearchDataError = RuntimeError
    classify_path = evaluate_gate = summarize_paths = None
    is_contract_storage_symbol = None


def test_research_script_exists():
    assert SCRIPT_PATH.exists(), "真实历史研究脚本尚未创建"


@pytest.mark.skipif(not SCRIPT_PATH.exists(), reason="研究脚本尚未创建")
def test_first_passage_uses_first_timestamp_instead_of_final_equity():
    assert classify_path([100, 205, 55], target=200, floor=60) == "target_200"
    assert classify_path([100, 59, 220], target=200, floor=60) == "floor_60"
    assert classify_path([100, 120, 110], target=200, floor=60) == "expired"


@pytest.mark.skipif(not SCRIPT_PATH.exists(), reason="研究脚本尚未创建")
def test_research_universe_accepts_only_usdt_perpetual_storage_symbols():
    assert callable(is_contract_storage_symbol)
    assert is_contract_storage_symbol("BTC-USDT_USDT") is True
    assert is_contract_storage_symbol("BTC-USDT") is False


@pytest.mark.skipif(not SCRIPT_PATH.exists(), reason="研究脚本尚未创建")
def test_summary_reports_target_floor_and_terminal_distribution():
    summary = summarize_paths(
        [
            {"equity": [100, 205], "gross_profit": 110, "gross_loss": 10, "symbol_pnl": {"A": 105, "B": 5}},
            {"equity": [100, 59], "gross_profit": 5, "gross_loss": 46, "symbol_pnl": {"A": -41}},
            {"equity": [100, 120], "gross_profit": 25, "gross_loss": 5, "symbol_pnl": {"B": 20}},
        ],
        target=200,
        floor=60,
    )

    assert summary["target_before_floor_probability"] == pytest.approx(1 / 3)
    assert summary["floor_before_target_probability"] == pytest.approx(1 / 3)
    assert summary["median_terminal_equity"] == pytest.approx(120)
    assert summary["profit_factor"] == pytest.approx(140 / 61)
    assert summary["single_symbol_profit_share"] == pytest.approx(105 / 130)


@pytest.mark.skipif(not SCRIPT_PATH.exists(), reason="研究脚本尚未创建")
def test_gate_requires_all_four_out_of_sample_conditions():
    passing = {
        "target_before_floor_probability": 0.20,
        "floor_before_target_probability": 0.10,
        "median_terminal_equity": 101.0,
        "profit_factor": 1.2,
        "single_symbol_profit_share": 0.45,
    }

    assert evaluate_gate(passing)["passed"] is True
    failing = dict(passing, floor_before_target_probability=0.25)
    result = evaluate_gate(failing)
    assert result["passed"] is False
    assert "翻倍首达概率没有高于60U首达概率" in result["reasons"]


@pytest.mark.skipif(not SCRIPT_PATH.exists(), reason="研究脚本尚未创建")
def test_missing_real_bars_fails_closed(tmp_path):
    from research_antimartingale_volatility_breakout import discover_symbol_files

    with pytest.raises(ResearchDataError, match="真实15M K线不足"):
        discover_symbol_files(tmp_path, start_ms=1_000, end_ms=2_000, minimum_symbols=2)
