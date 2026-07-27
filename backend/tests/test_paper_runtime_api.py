import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import monitor_runtime, paper, watch


class PaperRuntimeApiContractTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(paper.router, prefix="/paper")
        app.include_router(watch.router, prefix="/watch")
        app.include_router(monitor_runtime.router, prefix="/monitor")
        self.client = TestClient(app)
        self.paper_patch = patch.object(paper, "runtime_service")
        self.watch_patch = patch.object(watch, "service")
        self.monitor_patch = patch.object(monitor_runtime, "service")
        self.paper = self.paper_patch.start()
        self.watch = self.watch_patch.start()
        self.monitor = self.monitor_patch.start()
        self.addCleanup(self.paper_patch.stop)
        self.addCleanup(self.watch_patch.stop)
        self.addCleanup(self.monitor_patch.stop)

    def test_list_instances_returns_total(self):
        self.paper.list_instances.return_value = [{"id": "paper-1"}]
        self.assertEqual(self.client.get("/paper/instances").json()["total"], 1)

    def test_create_instance_forwards_all_pinned_inputs(self):
        self.paper.create_instance.return_value = {"id": "paper-1", "status": "draft"}
        payload = {"strategy_version_id": "v1", "dataset_snapshot_id": 1, "factor_snapshot_id": 2,
                   "universe_snapshot_id": 3, "pool_snapshot_id": 4, "research_protocol_id": "protocol",
                   "qualifying_backtest_run_id": "run", "initial_cash": 1000000}
        self.assertEqual(self.client.post("/paper/instances", json=payload).json()["status"], "draft")
        self.assertEqual(self.paper.create_instance.call_args.args[0]["pool_snapshot_id"], 4)

    def test_start_is_idempotent_service_contract(self):
        self.paper.start.return_value = {"id": "paper-1", "status": "running", "reused": True}
        self.assertTrue(self.client.post("/paper/instances/paper-1/start").json()["reused"])

    def test_pause_endpoint(self):
        self.paper.pause.return_value = {"id": "paper-1", "status": "paused"}
        self.assertEqual(self.client.post("/paper/instances/paper-1/pause").json()["status"], "paused")

    def test_resume_endpoint(self):
        self.paper.resume.return_value = {"id": "paper-1", "status": "running"}
        self.assertEqual(self.client.post("/paper/instances/paper-1/resume").json()["status"], "running")

    def test_stop_endpoint(self):
        self.paper.stop.return_value = {"id": "paper-1", "status": "stopped"}
        self.assertEqual(self.client.post("/paper/instances/paper-1/stop").json()["status"], "stopped")

    def test_cycle_endpoint_preserves_injected_time(self):
        self.paper.process_cycle.return_value = {"id": "cycle-1", "status": "success"}
        payload = {"trade_date": "2025-01-02", "observed_at": "2025-01-02T15:01:00+08:00"}
        self.client.post("/paper/instances/paper-1/cycles", json=payload)
        self.assertEqual(self.paper.process_cycle.call_args.args[1]["observed_at"], payload["observed_at"])

    def test_events_endpoint_returns_total(self):
        self.paper.events.return_value = [{"id": 1}]
        self.assertEqual(self.client.get("/paper/instances/paper-1/events").json()["total"], 1)

    def test_value_error_is_400(self):
        self.paper.start.side_effect = ValueError("门禁失败")
        self.assertEqual(self.client.post("/paper/instances/paper-1/start").status_code, 400)

    def test_watch_context_endpoint(self):
        self.watch.watch_context.return_value = {"alerts": [], "signals": [], "pool_moves": [], "instances": []}
        self.assertIn("signals", self.client.get("/watch/context").json())

    def test_alert_list_endpoint(self):
        self.watch.list_alerts.return_value = [{"id": "alert-1"}]
        self.assertEqual(self.client.get("/watch/alerts").json()["total"], 1)

    def test_alert_acknowledgement_endpoint(self):
        self.watch.acknowledge_alert.return_value = {"id": "alert-1", "status": "acknowledged"}
        self.assertEqual(self.client.post("/watch/alerts/alert-1/acknowledge").json()["status"], "acknowledged")

    def test_health_endpoint(self):
        self.monitor.health.return_value = {"status": "healthy", "services": []}
        self.assertEqual(self.client.get("/monitor/health").json()["status"], "healthy")


if __name__ == "__main__":
    unittest.main()
