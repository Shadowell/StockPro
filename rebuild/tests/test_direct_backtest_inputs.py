from __future__ import annotations

from pathlib import Path
import sys

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.backtest.inputs import BacktestInputResolver  # noqa: E402


class FakeGateway:
    def get_strategy(self, strategy_id):
        assert int(strategy_id) == 224
        return {
            "id": "11111111-1111-1111-1111-111111111111",
            "legacy_strategy_id": 224,
            "name": "A 股日线策略",
            "script_content": "def initialize(context): pass\ndef handle_data(context, data): pass",
            "validation_status": "valid",
            "parameter_schema": {"asset_class": "stock", "symbols": []},
        }

    def resolve_snapshot(self, *, start_date, end_date, snapshot_id, required_datasets):
        assert (start_date, end_date) == ("2025-08-04", "2025-12-31")
        assert snapshot_id is None
        assert {"daily_bars", "trade_calendar", "benchmark_bars", "price_limits"}.issubset(required_datasets)
        return {"id": 34, "name": "sealed-H2", "status": "sealed", "knowledge_cutoff_at": "2026-08-25T00:00:00+08:00"}

    def resolve_pool(self, *, snapshot_id, pool_snapshot_id):
        assert snapshot_id == 34 and pool_snapshot_id is None
        return {"id": 7, "name": "流动性 Top500", "dataset_snapshot_id": 34, "symbols": ["SH_600000", "SZ_000001"]}

    def load_dataset(self, snapshot_id, dataset_code, *, symbols, start_date, end_date):
        rows = {
            "daily_bars": [
                {"trade_date": "2025-08-04", "symbol": "SH_600000", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "turnover": 10000},
                {"trade_date": "2025-08-04", "symbol": "SZ_000001", "open": 12, "high": 13, "low": 11, "close": 12.5, "volume": 1000, "turnover": 12000},
            ],
            "trade_calendar": [{"trade_date": "2025-08-04", "is_open": True}],
            "benchmark_bars": [{"trade_date": "2025-08-04", "symbol": "SH_000300", "close": 4000}],
            "price_limits": [{"trade_date": "2025-08-04", "symbol": "SH_600000", "up_limit": 11, "down_limit": 9, "has_price_limit": True}],
            "suspensions": [],
            "corporate_actions": [],
        }
        return rows[dataset_code]


def request(**overrides):
    return {
        "strategy_id": 224,
        "exchange": "SSE",
        "timeframe": "1d",
        "start_date": "2025-08-04",
        "end_date": "2025-12-31",
        "initial_capital": 1_000_000,
        "maker_fee_bps": 99,
        "taker_fee_bps": 99,
        "slippage_bps": 10,
        **overrides,
    }


def test_resolver_binds_strategy_snapshot_pool_and_all_execution_evidence():
    resolved = BacktestInputResolver(FakeGateway()).resolve(request())
    assert resolved["strategy_version"]["id"] == "11111111-1111-1111-1111-111111111111"
    assert resolved["dataset_snapshot"]["id"] == 34
    assert resolved["pool_snapshot"]["id"] == 7
    assert resolved["symbols"] == ["600000.SH", "000001.SZ"]
    assert resolved["cost_model"] == {
        "commission_rate": 0.0003,
        "minimum_commission": 5.0,
        "stamp_duty_rate": 0.0005,
        "transfer_fee_rate": 0.00001,
        "slippage_rate": 0.001,
        "max_participation_rate": 0.10,
    }
    assert set(resolved["datasets"]) == {"daily_bars", "trade_calendar", "benchmark_bars", "price_limits", "suspensions", "corporate_actions"}
    assert resolved["datasets"]["daily_bars"][0]["symbol"] == "600000.SH"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"timeframe": "1h"}, "仅支持 1d"),
        ({"exchange": "okx"}, "仅支持 A 股"),
        ({"start_date": "2026-01-01", "end_date": "2025-12-31"}, "开始日期"),
        ({"initial_capital": 0}, "初始资金"),
        ({"symbols": ["BTC-USDT"]}, "无效 A 股标的"),
    ],
)
def test_resolver_rejects_non_a_share_or_invalid_requests(overrides, message):
    with pytest.raises(ValueError, match=message):
        BacktestInputResolver(FakeGateway()).resolve(request(**overrides))
