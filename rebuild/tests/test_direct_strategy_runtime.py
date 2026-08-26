from __future__ import annotations

from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.strategy_runtime_worker import Runtime  # noqa: E402


def test_stockpro_v1_runtime_emits_point_in_time_a_share_intents():
    code = """
def initialize(context):
    set_benchmark('000300.SH')

def handle_data(context, data):
    if data['600000.SH'].close > 10:
        order_target_percent('600000.SH', 0.5)
    record(close=data['600000.SH'].close)
"""
    payload = {
        "code": code,
        "symbols": ["600000.SH"],
        "parameters": {"initial_cash": 100000},
        "events": [
            {
                "simulated_at": "2025-01-02T15:00:00+08:00",
                "available_at": "2025-01-02T15:00:00+08:00",
                "previous_date": "2024-12-31",
                "bars": {"600000.SH": {"close": 11}},
            }
        ],
        "series": {"600000.SH": {"close": [11]}},
        "limits": {"max_intents": 100, "max_records": 100, "log_bytes": 65536},
        "knowledge_cutoff_at": "2025-01-02T15:00:00+08:00",
    }
    result = Runtime(payload).execute()
    assert result["success"] is True
    assert result["benchmark"] == "000300.SH"
    assert result["intents"] == [
        {
            "event_ordinal": 0,
            "simulated_at": "2025-01-02T15:00:00+08:00",
            "available_at": "2025-01-02T15:00:00+08:00",
            "symbol": "600000.SH",
            "intent_type": "order_target_percent",
            "value": 0.5,
        }
    ]
    assert result["records"][0]["payload"] == {"close": 11}


def test_runtime_history_cannot_read_future_values():
    runtime = Runtime(
        {
            "symbols": ["600000.SH"],
            "events": [{"simulated_at": "2025-01-02T15:00:00+08:00", "available_at": "2025-01-02T15:00:00+08:00", "bars": {}}],
            "series": {"600000.SH": {"close": [10, 999]}},
            "limits": {"max_intents": 10, "max_records": 10, "log_bytes": 1024},
        }
    )
    runtime.current_ordinal = 0
    assert runtime.history("600000.SH", 10, "1d", "close") == [10]
