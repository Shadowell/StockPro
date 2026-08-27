from __future__ import annotations

import asyncio
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.backtest.service import BacktestDomainService  # noqa: E402


class FakeBacktestRepository:
    def list_runs(self, **kwargs):
        return [{"id": 7, "strategy_id": 224, "strategy_name": "A股均值回归", "status": "success", "metrics": {"strategy_return": 0.25, "maximum_drawdown": 0.1, "sharpe": 1.5, "win_rate": 0.6, "completed_trades": 12, "total_cost": 88}, "initial_cash": 1_000_000, "frequency": "1d", "start_date": "2025-01-01", "end_date": "2025-12-31", "created_at": "2026-08-25T12:00:00+08:00"}]

    def get_run(self, run_id):
        return self.list_runs()[0] if int(run_id) == 7 else None

    def list_trades(self, run_id):
        return [{"trade_date": "2025-02-01", "symbol": "600519.SH", "side": "buy", "price": 1500, "quantity": 100, "commission": 5, "realized_pnl": 1000}]

    def equity_curve(self, run_id):
        return [{"trade_date": "2025-01-01", "equity": 1_000_000}, {"trade_date": "2025-12-31", "equity": 1_250_000}]


def test_bitpro_backtest_history_maps_a_share_run_metrics_and_detail():
    service = BacktestDomainService(FakeBacktestRepository())
    rows = asyncio.run(service.list_results(limit=20, offset=0, query="", sort_by="created", sort_dir="desc"))
    detail = asyncio.run(service.get_result(7))

    assert rows[0]["total_return"] == 25.0
    assert rows[0]["max_drawdown"] == 10.0
    assert rows[0]["final_capital"] == 1_250_000
    assert detail["strategy_id"] == 224
    assert detail["trades"][0]["symbol"] == "600519.SH"
    assert len(detail["equity_curve"]) == 2
    assert detail["total_fees"] == 5.0


class SingleDayOpenFillRepository(FakeBacktestRepository):
    def list_runs(self, **kwargs):
        return [{
            "id": 8,
            "strategy_id": 0,
            "strategy_name": "单日最小链路",
            "status": "success",
            "metrics": {
                "strategy_return": 0,
                "maximum_drawdown": 0,
                "sharpe": 0,
                "win_rate": 0,
                "completed_trades": 0,
                "total_cost": 0,
            },
            "initial_cash": 1_000_000,
            "final_equity": 999_970.2379,
            "fill_count": 1,
            "order_count": 0,
            "fill_total_cost": 29.7621,
            "equity_point_count": 1,
            "frequency": "1d",
            "start_date": "2026-08-26",
            "end_date": "2026-08-26",
            "created_at": "2026-08-27T10:29:29+08:00",
        }]

    def get_run(self, run_id):
        return self.list_runs()[0] if int(run_id) == 8 else None

    def list_trades(self, run_id):
        return [{
            "trade_date": "2026-08-26",
            "symbol": "BJ_920000",
            "side": "buy",
            "price": 13.59,
            "quantity": 7300,
            "commission": 29.7621,
            "tax": 0,
            "transfer_fee": 0,
            "realized_pnl": None,
        }]

    def equity_curve(self, run_id):
        return [{"trade_date": "2026-08-26", "equity": 999_970.2379}]


def test_single_day_open_fill_separates_counts_and_fail_closes_metrics():
    service = BacktestDomainService(SingleDayOpenFillRepository())
    row = asyncio.run(service.list_results(limit=20, offset=0, query="", sort_by="created", sort_dir="desc"))[0]
    detail = asyncio.run(service.get_result(8))

    assert row["fill_count"] == row["total_trades"] == 1
    assert row["closed_trade_count"] == 0
    assert row["order_count"] == 0
    assert row["final_capital"] == 999_970.2379
    assert row["total_fees"] == 29.7621
    assert row["metric_status"] == "insufficient_sample"
    assert row["total_return"] is None
    assert row["max_drawdown"] is None
    assert row["sharpe_ratio"] is None
    assert row["win_rate"] is None
    assert detail["trades"][0]["symbol"] == "920000.BJ"
    assert detail["fill_count"] == detail["total_trades"] == 1
    assert detail["closed_trade_count"] == 0
