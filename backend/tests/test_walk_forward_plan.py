import unittest
from unittest.mock import MagicMock

from app.services.backtest_workbench_service import BacktestCancelled
from app.services.walk_forward_plan_service import (
    WalkForwardExecutionService,
    WalkForwardPlanService,
    generate_trading_folds,
)


class TradingFoldGenerationTests(unittest.TestCase):
    def setUp(self):
        self.dates = [f"2025-01-{day:02d}" for day in range(2, 12)]

    def test_generates_non_overlapping_training_and_oos_windows(self):
        folds = generate_trading_folds(self.dates, train_sessions=4, test_sessions=2, step_sessions=2)
        self.assertEqual(len(folds), 3)
        self.assertEqual(folds[0]["train_start"], "2025-01-02")
        self.assertEqual(folds[0]["train_end"], "2025-01-05")
        self.assertEqual(folds[0]["test_start"], "2025-01-06")
        self.assertEqual(folds[0]["test_end"], "2025-01-07")
        self.assertLess(folds[0]["train_end"], folds[0]["test_start"])
        self.assertEqual(folds[1]["train_start"], "2025-01-04")

    def test_rejects_nonpositive_window_lengths(self):
        with self.assertRaisesRegex(ValueError, "必须为正"):
            generate_trading_folds(self.dates, train_sessions=0, test_sessions=2, step_sessions=2)

    def test_rejects_ranges_that_cannot_form_one_fold(self):
        with self.assertRaisesRegex(ValueError, "不足以生成一折"):
            generate_trading_folds(self.dates[:5], train_sessions=4, test_sessions=2, step_sessions=2)


class WalkForwardPreviewTests(unittest.TestCase):
    def test_preview_uses_only_sealed_snapshot_trading_dates(self):
        service = WalkForwardPlanService.__new__(WalkForwardPlanService)
        service._rows = MagicMock(side_effect=[
            [{"id": 10, "status": "sealed", "manifest_hash": "snapshot-hash"}],
            [{"trade_date": f"2025-01-{day:02d}"} for day in range(2, 12)],
        ])
        result = service.preview({
            "dataset_snapshot_id": 10,
            "start_date": "2025-01-02",
            "end_date": "2025-01-11",
            "train_sessions": 4,
            "test_sessions": 2,
            "step_sessions": 2,
        })
        self.assertEqual(result["dataset_snapshot_id"], 10)
        self.assertEqual(result["dataset_manifest_hash"], "snapshot-hash")
        self.assertEqual(result["date_count"], 10)
        self.assertEqual(result["n_folds"], 3)
        self.assertFalse(result["promotion_eligible"])

    def test_preview_rejects_unsealed_snapshot(self):
        service = WalkForwardPlanService.__new__(WalkForwardPlanService)
        service._rows = MagicMock(return_value=[{"id": 10, "status": "draft", "manifest_hash": "x"}])
        with self.assertRaisesRegex(ValueError, "封存"):
            service.preview({
                "dataset_snapshot_id": 10,
                "start_date": "2025-01-02",
                "end_date": "2025-01-11",
                "train_sessions": 4,
                "test_sessions": 2,
                "step_sessions": 2,
            })


class _FakePlanService:
    def preview(self, payload):
        return {
            "planning_version": "walk-forward-plan.v1",
            "dataset_snapshot_id": 10,
            "dataset_manifest_hash": "snapshot-hash",
            "date_count": 10,
            "n_folds": 2,
            "promotion_eligible": False,
            "folds": [
                {"index": 1, "train_start": "2025-01-02", "train_end": "2025-01-05", "test_start": "2025-01-06", "test_end": "2025-01-07"},
                {"index": 2, "train_start": "2025-01-04", "train_end": "2025-01-07", "test_start": "2025-01-08", "test_end": "2025-01-09"},
            ],
        }


class _FakeWorkbench:
    def __init__(self):
        self.calls = []

    def run(self, payload, *, mode, progress_hook=None, cancel_check=None):
        self.calls.append({"payload": dict(payload), "mode": mode})
        if cancel_check and cancel_check():
            raise BacktestCancelled("用户已停止回测")
        parameter = int((payload.get("parameters") or {}).get("lookback") or 0)
        is_oos = "OOS" in str(payload.get("name") or "")
        fold_index = 2 if "第2折" in str(payload.get("name") or "") else 1
        return {
            "id": f"run-{len(self.calls)}",
            "metrics": {
                "sharpe": 1.0 if is_oos else float(parameter),
                "strategy_return": (-0.05 if fold_index == 2 else 0.10) if is_oos else 0.02 * parameter,
            },
        }


class WalkForwardExecutionTests(unittest.TestCase):
    def setUp(self):
        self.workbench = _FakeWorkbench()
        self.service = WalkForwardExecutionService.__new__(WalkForwardExecutionService)
        self.service.plan_service = _FakePlanService()
        self.service.workbench = self.workbench
        self.payload = {
            "name": "滚动验证",
            "dataset_snapshot_id": 10,
            "universe_snapshot_id": 1,
            "strategy_version_id": "strategy-v1",
            "cost_model_id": "cost-v1",
            "symbols": ["SH_600519"],
            "start_date": "2025-01-02",
            "end_date": "2025-01-09",
            "train_sessions": 4,
            "test_sessions": 2,
            "step_sessions": 2,
            "parameter_grid": {"lookback": [1, 2]},
            "objective": "sharpe",
            "parameters": {"target": 0.5},
            "initial_cash": 1_000_000,
            "benchmark_code": "000300.SH",
        }

    def test_executes_training_grid_then_oos_with_selected_parameters(self):
        result = self.service.execute(self.payload)
        self.assertEqual(result["n_folds"], 2)
        self.assertEqual(result["folds"][0]["best_parameters"]["lookback"], 2)
        self.assertEqual(len(self.workbench.calls), 6)
        self.assertTrue(all(call["mode"] == "full" for call in self.workbench.calls))
        self.assertTrue(all(call["payload"]["diagnostic_only"] for call in self.workbench.calls))
        self.assertTrue(all(call["payload"].get("research_protocol_id") is None for call in self.workbench.calls))
        self.assertEqual(self.workbench.calls[2]["payload"]["parameters"], {"target": 0.5, "lookback": 2})

    def test_aggregates_compounded_oos_and_degradation(self):
        result = self.service.execute(self.payload)
        self.assertAlmostEqual(result["summary"]["compounded_oos_return"], 1.10 * 0.95 - 1.0)
        self.assertEqual(result["summary"]["consistency"], 0.5)
        self.assertEqual(result["summary"]["avg_is_objective"], 2.0)
        self.assertEqual(result["summary"]["avg_oos_objective"], 1.0)
        self.assertEqual(result["summary"]["degradation"], 1.0)
        self.assertEqual(len(result["summary"]["oos_equity_curve"]), 2)

    def test_rejects_an_unbounded_parameter_matrix(self):
        payload = {**self.payload, "parameter_grid": {"lookback": list(range(13))}}
        with self.assertRaisesRegex(ValueError, "最多 12"):
            self.service.execute(payload)

    def test_honors_cancellation_before_starting_a_fold(self):
        with self.assertRaises(BacktestCancelled):
            self.service.execute(self.payload, cancel_check=lambda: True)
        self.assertEqual(self.workbench.calls, [])


if __name__ == "__main__":
    unittest.main()
