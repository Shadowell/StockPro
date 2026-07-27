import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import backtest


RUN_REQUEST = {
    "strategy_version_id": "11111111-1111-1111-1111-111111111111",
    "dataset_snapshot_id": 10,
    "universe_snapshot_id": 1,
    "symbols": ["SH_600519"],
    "start_date": "2023-01-03",
    "end_date": "2025-01-02",
    "initial_cash": 1_000_000,
    "benchmark_code": "000300.SH",
    "parameters": {},
}


class BacktestApiContractTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(backtest.router, prefix="/backtest")
        self.client = TestClient(app)
        self.service_patch = patch.object(backtest, "service")
        self.service = self.service_patch.start()
        self.addCleanup(self.service_patch.stop)

    def test_configuration_returns_all_immutable_input_selectors(self):
        payload = {"strategy_versions": [], "dataset_snapshots": [], "universe_snapshots": [], "factor_snapshots": [], "cost_models": [], "protocols": []}
        self.service.configuration.return_value = payload
        self.assertEqual(self.client.get("/backtest/configuration").json(), payload)

    def test_full_run_uses_full_mode(self):
        self.service.run.return_value = {"id": "run-1", "status": "success", "run_mode": "full"}
        response = self.client.post("/backtest/runs", json=RUN_REQUEST)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["run_mode"], "full")
        self.assertEqual(self.service.run.call_args.kwargs["mode"], "full")

    def test_quick_run_is_distinct_from_full_run(self):
        self.service.run.return_value = {"id": "run-2", "status": "success", "run_mode": "quick"}
        response = self.client.post("/backtest/quick-runs", json=RUN_REQUEST)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.service.run.call_args.kwargs["mode"], "quick")

    def test_run_detail_returns_persisted_manifest(self):
        self.service.get_run.return_value = {"id": "run-1", "result_manifest": {"manifest_hash": "sealed"}}
        response = self.client.get("/backtest/runs/run-1")
        self.assertEqual(response.json()["result_manifest"]["manifest_hash"], "sealed")

    def test_metrics_preserve_null_reason(self):
        self.service.metrics.return_value = [{"metric_code": "alpha", "metric_value": None, "null_reason": "样本不足"}]
        response = self.client.get("/backtest/runs/run-1/metrics")
        self.assertIsNone(response.json()["items"][0]["metric_value"])
        self.assertEqual(response.json()["items"][0]["null_reason"], "样本不足")

    def test_series_returns_daily_custom_and_monthly_evidence(self):
        self.service.series.return_value = {"daily": [{"trade_date": "2025-01-02"}], "custom_records": [], "monthly_returns": []}
        response = self.client.get("/backtest/runs/run-1/series")
        self.assertEqual(response.json()["daily"][0]["trade_date"], "2025-01-02")

    def test_all_five_detail_ledgers_are_exposed(self):
        for path, method_name in (("positions", "positions"), ("orders", "orders"), ("trades", "trades"), ("logs", "logs"), ("attribution", "attribution")):
            with self.subTest(path=path):
                getattr(self.service, method_name).return_value = [{"kind": path}]
                response = self.client.get(f"/backtest/runs/run-1/{path}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["items"][0]["kind"], path)

    def test_compare_forwards_two_to_eight_run_ids(self):
        self.service.compare.return_value = {"runs": [{"id": "a"}, {"id": "b"}], "series": {}}
        response = self.client.post("/backtest/compare", json={"run_ids": ["a", "b"]})
        self.assertEqual(len(response.json()["runs"]), 2)
        self.service.compare.assert_called_once_with(["a", "b"])

    def test_promotion_returns_explicit_checks(self):
        self.service.evaluate_promotion.return_value = {"run_id": "run-1", "promotion_status": "paper_eligible", "checks": [{"status": "passed"}]}
        response = self.client.post("/backtest/runs/run-1/evaluate-promotion")
        self.assertEqual(response.json()["promotion_status"], "paper_eligible")

    def test_protocol_creation_accepts_oos_windows(self):
        self.service.create_protocol.return_value = {"id": "protocol-1", "status": "sealed"}
        payload = {
            "name": "协议", "hypothesis": "趋势溢价", "train_start": "2023-01-03", "train_end": "2023-12-29",
            "out_of_sample_start": "2024-01-02", "out_of_sample_end": "2025-01-02",
        }
        response = self.client.post("/backtest/protocols", json=payload)
        self.assertEqual(response.json()["status"], "sealed")

    def test_matrix_endpoint_preserves_parameter_grid(self):
        self.service.run_matrix.return_value = {"experiment_id": "experiment-1", "total": 6, "status": "completed"}
        response = self.client.post("/backtest/experiments/experiment-1/matrix", json={
            "parameter_grid": {"lookback": [5, 10, 20], "target": [0.3, 0.6]},
            "start_date": "2023-01-03", "end_date": "2025-01-02", "symbols": ["SH_600519"],
        })
        self.assertEqual(response.json()["total"], 6)
        self.assertEqual(len(self.service.run_matrix.call_args.args[1]["lookback"]), 3)

    def test_historical_reference_endpoint_calls_explicit_data_builder(self):
        reference_service = MagicMock()
        reference_service.sync_historical_backtest_references.return_value = {"status": "sealed", "snapshot": {"id": 10}}
        self.service.reference_service = reference_service
        response = self.client.post("/backtest/datasets/historical-references", json={
            "base_snapshot_id": 8, "start_date": "2023-01-03", "end_date": "2025-01-02",
            "symbols": ["SH_600519"], "benchmarks": ["000300.SH"],
        })
        self.assertEqual(response.json()["snapshot"]["id"], 10)

    def test_value_errors_become_client_errors(self):
        self.service.compare.side_effect = ValueError("只能比较完整回测")
        response = self.client.post("/backtest/compare", json={"run_ids": ["quick", "full"]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "只能比较完整回测")


if __name__ == "__main__":
    unittest.main()
