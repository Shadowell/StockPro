import unittest
from unittest.mock import MagicMock, patch, patch

from app.services.backtest_workbench_service import (
    BacktestWorkbenchService,
    reset_configuration_cache,
)


class BacktestProtocolContractTests(unittest.TestCase):
    def setUp(self):
        self.service = BacktestWorkbenchService.__new__(BacktestWorkbenchService)
        self.service.database = MagicMock()

    @staticmethod
    def protocol(**overrides):
        payload = {
            "name": "趋势研究协议",
            "hypothesis": "趋势因子在成本后仍有样本外超额",
            "benchmark_code": "000300.SH",
            "train_start": "2021-01-04",
            "train_end": "2022-12-30",
            "validation_start": "2023-01-09",
            "validation_end": "2023-12-29",
            "out_of_sample_start": "2024-01-08",
            "out_of_sample_end": "2024-12-31",
            "embargo_days": 7,
            "capacity_rules": {
                "max_participation_ratio": 0.1,
                "max_single_symbol_weight": 0.25,
            },
            "promotion_thresholds": {
                "min_return": 0,
                "min_sharpe": 0.5,
                "max_drawdown": 0.2,
            },
            "status": "sealed",
        }
        payload.update(overrides)
        return payload

    def test_sealed_protocol_requires_validation_window(self):
        with self.assertRaisesRegex(ValueError, "验证区间"):
            self.service.create_protocol(self.protocol(validation_start=None, validation_end=None))
        self.service.database.get_connection.assert_not_called()

    def test_protocol_windows_must_be_ordered_and_respect_embargo(self):
        with self.assertRaisesRegex(ValueError, "训练、验证、样本外"):
            self.service.create_protocol(self.protocol(validation_start="2022-12-30"))
        self.service.database.get_connection.assert_not_called()

    def test_sealed_protocol_requires_cost_capacity_and_threshold_contract(self):
        with self.assertRaisesRegex(ValueError, "容量规则"):
            self.service.create_protocol(self.protocol(capacity_rules={}))
        with self.assertRaisesRegex(ValueError, "晋级阈值"):
            self.service.create_protocol(self.protocol(promotion_thresholds={}))

    def test_full_run_window_must_cover_all_protocol_segments(self):
        with self.assertRaisesRegex(ValueError, "覆盖研究协议"):
            self.service._validate_protocol_run_window(
                "2023-01-09",
                "2024-12-31",
                self.protocol(),
            )

    def test_zero_return_meets_an_explicit_zero_minimum(self):
        self.service._row = MagicMock(return_value={
            **self.protocol(),
            "id": "protocol-1",
            "promotion_thresholds": {"min_return": 0},
        })
        self.service._execute = MagicMock()
        self.service._evaluate_protocol_segments("run-1", "protocol-1", {
            "daily_equity": [
                {"trade_date": "2021-01-04", "equity": 1_000_000, "benchmark_nav": 1.0},
                {"trade_date": "2023-01-09", "equity": 1_000_000, "benchmark_nav": 1.0},
                {"trade_date": "2024-01-08", "equity": 1_000_000, "benchmark_nav": 1.0},
            ],
        })
        statuses = [call.args[1][6] for call in self.service._execute.call_args_list]
        self.assertEqual(statuses, ["passed", "passed", "passed"])


class BacktestPromotionGateTests(unittest.TestCase):
    def setUp(self):
        self.service = BacktestWorkbenchService.__new__(BacktestWorkbenchService)
        self.service.database = MagicMock()
        connection = self.service.database.get_connection.return_value.__enter__.return_value
        self.cursor = connection.cursor.return_value.__enter__.return_value
        self.service._rows = MagicMock(return_value=[])

    @staticmethod
    def run_payload(**overrides):
        payload = {
            "id": "run-1",
            "status": "success",
            "run_mode": "full",
            "research_protocol_id": "protocol-1",
            "benchmark_code": "000300.SH",
            "cost_model_id": "cost-1",
            "cost_model_hash": "cost-hash",
            "result_manifest": {"manifest_hash": "result-hash"},
            "core_metrics": [
                {"metric_code": "total_cost", "metric_value": 128.5},
                {"metric_code": "benchmark_return", "metric_value": 0.08},
                {"metric_code": "capacity_warnings", "metric_value": 0},
                {"metric_code": "data_quality_warnings", "metric_value": 0},
                {"metric_code": "peak_single_symbol_weight", "metric_value": 0.2},
            ],
        }
        payload.update(overrides)
        return payload

    @staticmethod
    def protocol(**overrides):
        payload = {
            "id": "protocol-1",
            "status": "sealed",
            "content_hash": "protocol-hash",
            "benchmark_code": "000300.SH",
            "capacity_rules": {
                "max_participation_ratio": 0.1,
                "max_single_symbol_weight": 0.25,
            },
            "promotion_thresholds": {
                "min_return": 0,
                "min_sharpe": 0.5,
                "max_drawdown": 0.2,
            },
        }
        payload.update(overrides)
        return payload

    @staticmethod
    def evaluations(validation_status="passed"):
        return [
            {"sample_label": "train", "status": "passed"},
            {"sample_label": "validation", "status": validation_status},
            {"sample_label": "out_of_sample", "status": "passed"},
        ]

    def configure(self, run=None, protocol=None, evaluations=None, peak_capacity_ratio=0.05):
        self.service.get_run = MagicMock(return_value=run or self.run_payload())
        self.service._row = MagicMock(side_effect=[
            protocol or self.protocol(),
            {"peak_capacity_ratio": peak_capacity_ratio},
        ])
        self.service._rows = MagicMock(side_effect=[evaluations or self.evaluations(), []])

    def test_quick_preview_is_never_a_paper_candidate(self):
        self.service.get_run = MagicMock(return_value=self.run_payload(run_mode="quick", promotion_status="not_eligible_quick"))
        result = self.service.evaluate_promotion("run-1")
        self.assertEqual(result["promotion_status"], "not_eligible_quick")
        self.assertEqual(result["checks"][0]["check_code"], "QUICK_PREVIEW_ONLY")
        self.assertEqual(result["checks"][0]["status"], "failed")

    def test_validation_failure_blocks_promotion(self):
        self.configure(evaluations=self.evaluations("rejected"))
        result = self.service.evaluate_promotion("run-1")
        self.assertEqual(result["promotion_status"], "rejected")
        checks = {item["check_code"]: item["status"] for item in result["checks"]}
        self.assertEqual(checks["VALIDATION_PASS"], "failed")

    def test_missing_cost_or_benchmark_evidence_blocks_promotion(self):
        metrics = [
            {"metric_code": "total_cost", "metric_value": None},
            {"metric_code": "benchmark_return", "metric_value": None},
            {"metric_code": "capacity_warnings", "metric_value": 0},
            {"metric_code": "data_quality_warnings", "metric_value": 0},
            {"metric_code": "peak_single_symbol_weight", "metric_value": 0.2},
        ]
        self.configure(run=self.run_payload(core_metrics=metrics))
        result = self.service.evaluate_promotion("run-1")
        checks = {item["check_code"]: item["status"] for item in result["checks"]}
        self.assertEqual(checks["COST_MODEL_PASS"], "failed")
        self.assertEqual(checks["BENCHMARK_PASS"], "failed")

    def test_capacity_limit_is_checked_against_persisted_evidence(self):
        self.configure(peak_capacity_ratio=0.12)
        result = self.service.evaluate_promotion("run-1")
        checks = {item["check_code"]: item["status"] for item in result["checks"]}
        self.assertEqual(checks["CAPACITY_PASS"], "failed")

    def test_complete_protocol_evidence_becomes_paper_eligible(self):
        self.configure()
        result = self.service.evaluate_promotion("run-1")
        self.assertEqual(result["promotion_status"], "paper_eligible")
        self.assertTrue(all(item["status"] == "passed" for item in result["checks"]))


class BacktestPersistBatchTests(unittest.TestCase):
    @patch("app.services.backtest_workbench_service.psycopg2.extras.execute_values")
    def test_insert_values_pages_rows_for_tunnel_writes(self, execute_values):
        from app.services.backtest_workbench_service import _insert_values

        cursor = MagicMock()
        rows = [(index,) for index in range(120)]
        _insert_values(cursor, "INSERT INTO t (id) VALUES %s", rows, page_size=50)
        execute_values.assert_called_once_with(
            cursor, "INSERT INTO t (id) VALUES %s", rows, page_size=50
        )
        _insert_values(cursor, "INSERT INTO t (id) VALUES %s", [])
        execute_values.assert_called_once()


class BacktestDiagnosticRunTests(unittest.TestCase):
    def test_walk_forward_diagnostic_full_runs_never_evaluate_promotion(self):
        self.assertFalse(BacktestWorkbenchService._should_evaluate_promotion("full", {"diagnostic_only": True}))
        self.assertFalse(BacktestWorkbenchService._should_evaluate_promotion("quick", {}))
        self.assertTrue(BacktestWorkbenchService._should_evaluate_promotion("full", {}))


class BacktestReadPathTests(unittest.TestCase):
    def setUp(self):
        reset_configuration_cache()
        self.service = BacktestWorkbenchService.__new__(BacktestWorkbenchService)
        self.service.database = MagicMock()
        self.service._cursor = None
        connection = self.service.database.get_connection.return_value.__enter__.return_value
        connection.cursor.return_value.__enter__.return_value = MagicMock()
        self.queries: list[str] = []

        def fake_rows(query, params=()):
            self.queries.append(query)
            return []

        self.service._rows = fake_rows

    def test_configuration_omits_script_content_and_member_join(self):
        payload = self.service.configuration()
        version_sql = next(item for item in self.queries if "strategy_versions" in item)
        universe_sql = next(item for item in self.queries if "universe_snapshots" in item)
        self.assertNotIn("script_content", version_sql)
        self.assertIn("content_hash", version_sql)
        self.assertNotIn("LEFT JOIN universe_snapshot_members m ON m.snapshot_id=s.id", universe_sql)
        self.assertEqual(payload["strategy_versions"], [])

    def test_list_runs_selects_list_columns_not_full_row(self):
        self.service.list_runs(20)
        sql = self.queries[-1]
        self.assertNotIn("SELECT r.*", sql)
        self.assertIn("r.metrics", sql)
        self.assertIn("promotion_gate_complete", sql)
        self.assertNotIn("universe_manifest", sql)


if __name__ == "__main__":
    unittest.main()
