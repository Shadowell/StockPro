import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import pools


class StockPoolApiContractTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(pools.router)
        self.client = TestClient(app)
        self.patch = patch.object(pools, "service")
        self.service = self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_list_pools_returns_total(self):
        self.service.list_pools.return_value = [{"id": "pool-1"}]
        self.assertEqual(self.client.get("/pools").json()["total"], 1)

    def test_create_pool_preserves_versioned_config(self):
        self.service.create_pool.return_value = {"id": "pool-1", "rule_version": 1}
        response = self.client.post("/pools", json={"name": "动量", "pool_type": "factor", "config": {"top_n": 20}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.service.create_pool.call_args.args[0]["config"]["top_n"], 20)

    def test_generate_requires_snapshot_inputs(self):
        self.service.generate.return_value = {"id": "generation-1", "status": "success"}
        response = self.client.post("/pools/pool-1/generate", json={"dataset_snapshot_id": 9, "universe_snapshot_id": 1, "trade_date": "2025-01-02", "factor_snapshot_id": 3})
        self.assertEqual(response.json()["status"], "success")
        self.assertEqual(self.service.generate.call_args.args[1]["factor_snapshot_id"], 3)

    def test_member_endpoint_returns_ordered_evidence(self):
        self.service.members.return_value = [{"ordinal": 1, "symbol": "SH_600519", "reason": "top rank"}]
        response = self.client.get("/pools/pool-1/members?generation_id=generation-1")
        self.assertEqual(response.json()["items"][0]["reason"], "top rank")
        self.service.members.assert_called_once_with("pool-1", "generation-1")

    def test_snapshot_endpoint_forwards_generation(self):
        self.service.seal_snapshot.return_value = {"id": 11, "status": "sealed"}
        response = self.client.post("/pools/pool-1/snapshots", json={"generation_id": "generation-1"})
        self.assertEqual(response.json()["id"], 11)
        self.service.seal_snapshot.assert_called_once_with("pool-1", "generation-1")

    def test_snapshot_list_supports_pool_filter(self):
        self.service.list_snapshots.return_value = [{"id": 11}]
        response = self.client.get("/pool-snapshots?pool_id=pool-1")
        self.assertEqual(response.json()["total"], 1)
        self.service.list_snapshots.assert_called_once_with("pool-1")

    def test_snapshot_detail_uses_integer_id(self):
        self.service.get_snapshot.return_value = {"id": 11, "members": []}
        self.client.get("/pool-snapshots/11")
        self.service.get_snapshot.assert_called_once_with(11)

    def test_backtest_draft_does_not_accept_symbol_list(self):
        self.service.create_backtest_draft.return_value = {"status": "draft", "experiment": {"id": "experiment-1"}}
        payload = {"strategy_version_id": "11111111-1111-1111-1111-111111111111", "start_date": "2024-01-02", "end_date": "2025-01-02"}
        response = self.client.post("/pool-snapshots/11/backtest-draft", json=payload)
        self.assertEqual(response.json()["status"], "draft")
        self.assertNotIn("symbols", self.service.create_backtest_draft.call_args.args[1])

    def test_value_error_becomes_400(self):
        self.service.generate.side_effect = ValueError("快照不兼容")
        response = self.client.post("/pools/pool-1/generate", json={"dataset_snapshot_id": 9, "universe_snapshot_id": 1, "trade_date": "2025-01-02"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "快照不兼容")


if __name__ == "__main__":
    unittest.main()
