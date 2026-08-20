import unittest
from unittest.mock import MagicMock

from app.services.walk_forward_plan_service import WalkForwardPlanService, generate_trading_folds


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


if __name__ == "__main__":
    unittest.main()
