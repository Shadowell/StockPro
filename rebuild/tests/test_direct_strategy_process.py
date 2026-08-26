from __future__ import annotations

from pathlib import Path
import sys

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.backtest.strategy_process import StrategyProcessRunner  # noqa: E402


def bundle(code: str):
    return {
        "strategy_version": {"id": "strategy-v1", "script_content": code},
        "dataset_snapshot": {"id": 10, "knowledge_cutoff_at": "2026-08-25T00:00:00+08:00"},
        "pool_snapshot": {"id": 5},
        "symbols": ["600000.SH"],
        "start_date": "2025-01-02",
        "end_date": "2025-01-03",
        "initial_cash": 100_000,
        "datasets": {
            "daily_bars": [
                {"trade_date": "2025-01-02", "symbol": "600000.SH", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1000, "turnover": 10000},
                {"trade_date": "2025-01-03", "symbol": "600000.SH", "open": 11, "high": 12, "low": 10, "close": 11, "volume": 1000, "turnover": 11000},
            ],
            "trade_calendar": [
                {"trade_date": "2025-01-02", "is_open": True},
                {"trade_date": "2025-01-03", "is_open": True},
            ],
            "benchmark_bars": [], "price_limits": [], "suspensions": [], "corporate_actions": [],
        },
    }


VALID_CODE = """
def initialize(context):
    set_benchmark('000300.SH')

def handle_data(context, data):
    closes = history('600000.SH', 2, '1d', 'close')
    if closes[-1] >= 11:
        order_target_percent('600000.SH', 0.5)
    record(close=closes[-1])
"""


def test_parent_process_builds_point_in_time_events_and_isolated_intents():
    result = StrategyProcessRunner().run(bundle(VALID_CODE))
    assert result["success"] is True
    assert [event["trade_date"] for event in result["events"]] == ["2025-01-02", "2025-01-03"]
    assert result["events"][1]["previous_date"] == "2025-01-02"
    assert result["intents"][0]["simulated_at"] == "2025-01-03T15:00:00+08:00"
    assert result["intents"][0]["available_at"] == "2025-01-03T15:00:00+08:00"
    assert result["intents"][0]["symbol"] == "600000.SH"
    assert result["records"][0]["payload"] == {"close": 10.0}


def test_parent_process_rejects_unsafe_code_before_worker_launch():
    unsafe = "import os\n" + VALID_CODE
    with pytest.raises(ValueError, match="策略代码未通过验证"):
        StrategyProcessRunner().run(bundle(unsafe))
