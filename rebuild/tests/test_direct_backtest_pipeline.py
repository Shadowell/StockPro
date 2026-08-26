from __future__ import annotations

from pathlib import Path
import sys

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.backtest.execution import BacktestExecutionPipeline  # noqa: E402
from app.domain.backtest.jobs import BacktestCancelled  # noqa: E402
from app.domain.backtest.result_repository import PostgresBacktestResultRepository  # noqa: E402


class Resolver:
    def resolve(self, request):
        return {
            "strategy_version": {"id": "strategy-v1", "legacy_strategy_id": 224, "name": "A 股策略"},
            "dataset_snapshot": {"id": 10, "knowledge_cutoff_at": "2026-08-25T00:00:00+08:00"},
            "pool_snapshot": {"id": 5, "manifest_hash": "pool-hash"},
            "symbols": ["600000.SH"], "start_date": "2025-01-02", "end_date": "2025-01-03", "initial_cash": 100_000, "frequency": "1d",
            "cost_model": {"commission_rate": 0.0003, "minimum_commission": 5, "stamp_duty_rate": 0.0005, "transfer_fee_rate": 0.00001, "slippage_rate": 0.001, "max_participation_rate": 0.1},
            "datasets": {
                "daily_bars": [
                    {"trade_date": "2025-01-02", "symbol": "600000.SH", "name": "浦发银行", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1000, "turnover": 10000},
                    {"trade_date": "2025-01-03", "symbol": "600000.SH", "name": "浦发银行", "open": 11, "high": 12, "low": 10, "close": 11, "volume": 1000, "turnover": 11000},
                ],
                "trade_calendar": [{"trade_date": "2025-01-02", "is_open": True}, {"trade_date": "2025-01-03", "is_open": True}],
                "benchmark_bars": [{"trade_date": "2025-01-02", "symbol": "000300.SH", "close": 4000}, {"trade_date": "2025-01-03", "symbol": "000300.SH", "close": 4040}],
                "price_limits": [
                    {"trade_date": "2025-01-02", "symbol": "600000.SH", "up_limit": 11, "down_limit": 9, "has_price_limit": True},
                    {"trade_date": "2025-01-03", "symbol": "600000.SH", "up_limit": 12, "down_limit": 10, "has_price_limit": True},
                ],
                "suspensions": [], "corporate_actions": [],
            },
        }


class ProcessRunner:
    def run(self, bundle):
        return {
            "success": True,
            "input_hash": "input-hash",
            "event_hash": "event-hash",
            "intents": [{"event_ordinal": 0, "simulated_at": "2025-01-02T15:00:00+08:00", "available_at": "2025-01-02T15:00:00+08:00", "symbol": "600000.SH", "intent_type": "order_target_percent", "value": 0.5}],
            "records": [], "logs": [],
        }


class Persistence:
    def __init__(self): self.saved = None
    def persist(self, request, bundle, replay, result):
        self.saved = (request, bundle, replay, result)
        return {"run_id": "run-uuid", "result_id": 321}


def test_pipeline_runs_resolved_strategy_engine_and_atomic_persistence():
    persistence = Persistence()
    progress = []
    pipeline = BacktestExecutionPipeline(Resolver(), ProcessRunner(), persistence)
    output = pipeline.execute({"strategy_id": 224}, progress_hook=lambda *args: progress.append(args), cancel_check=lambda: False)
    assert output["run_id"] == "run-uuid" and output["result_id"] == 321
    assert persistence.saved[3]["status"] == "success"
    assert len(persistence.saved[3]["trades"]) == 1
    phases = [item[1] for item in progress]
    assert phases[:3] == ["resolving", "strategy", "engine"]
    assert phases[-1] == "persisting"
    assert output["summary"]["status"] == "completed"


def test_pipeline_honors_cancel_before_any_persistence():
    persistence = Persistence()
    with pytest.raises(BacktestCancelled):
        BacktestExecutionPipeline(Resolver(), ProcessRunner(), persistence).execute({}, progress_hook=lambda *_: None, cancel_check=lambda: True)
    assert persistence.saved is None


def test_result_repository_is_postgres_only_and_persists_all_evidence_tables():
    source = (BACKEND_ROOT / "app/domain/backtest/result_repository.py").read_text()
    assert "sqlite" not in source.lower()
    for table in ("backtest_runs", "backtest_orders", "backtest_trades", "backtest_daily_equity", "backtest_daily_positions", "backtest_metrics", "backtest_attribution", "backtest_logs"):
        assert table in source
    assert PostgresBacktestResultRepository.__name__ == "PostgresBacktestResultRepository"
