import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import monitor_runtime, paper, watch
from app.services.paper_runtime_service import PaperRuntimeService


class PaperRuntimeApiContractTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(paper.router, prefix="/paper")
        app.include_router(watch.router, prefix="/watch")
        app.include_router(monitor_runtime.router, prefix="/monitor")
        self.client = TestClient(app)
        self.paper_patch = patch.object(paper, "runtime_service")
        self.watch_patch = patch.object(watch, "service")
        self.watch_rule_patch = patch.object(watch, "rule_service")
        self.monitor_patch = patch.object(monitor_runtime, "service")
        watch.reset_watch_cache()
        paper.reset_paper_list_cache()
        self.paper = self.paper_patch.start()
        self.watch = self.watch_patch.start()
        self.watch_rule = self.watch_rule_patch.start()
        self.monitor = self.monitor_patch.start()
        self.addCleanup(self.paper_patch.stop)
        self.addCleanup(self.watch_patch.stop)
        self.addCleanup(self.watch_rule_patch.stop)
        self.addCleanup(self.monitor_patch.stop)
        self.addCleanup(paper.reset_paper_list_cache)

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

    def test_pinned_kline_endpoint_returns_snapshot_evidence(self):
        self.paper.get_instance_klines.return_value = {
            "items": [{"date": "2025-01-02", "close": 10.5}],
            "total": 1,
            "dataset_snapshot_id": 10,
            "source_label": "PostgreSQL 封存数据快照",
            "data_status": "available",
        }
        response = self.client.get("/paper/instances/paper-1/klines/SZ_002415")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["dataset_snapshot_id"], 10)
        self.paper.get_instance_klines.assert_called_once_with("paper-1", "SZ_002415")

    def test_only_explicit_historical_replay_can_bypass_wall_clock_staleness(self):
        self.assertTrue(PaperRuntimeService._feed_allows_stale_entries({
            "mode": "historical_replay",
            "allow_new_entries_when_stale": True,
        }))
        self.assertFalse(PaperRuntimeService._feed_allows_stale_entries({
            "mode": "realtime",
            "allow_new_entries_when_stale": True,
        }))
        self.assertFalse(PaperRuntimeService._feed_allows_stale_entries({
            "mode": "recorded_replay",
            "allow_new_entries_when_stale": False,
        }))

    def test_value_error_is_400(self):
        self.paper.start.side_effect = ValueError("门禁失败")
        self.assertEqual(self.client.post("/paper/instances/paper-1/start").status_code, 400)

    def test_watch_context_endpoint(self):
        self.watch.watch_context.return_value = {"alerts": [], "signals": [], "pool_moves": [], "instances": []}
        self.assertIn("signals", self.client.get("/watch/context").json())
        self.watch.watch_context.assert_called_once_with("business")

    def test_watch_context_explicit_audit_scope_preserves_acceptance_evidence(self):
        self.watch.watch_context.return_value = {"scope": "audit", "alerts": [], "signals": [], "pool_moves": [], "instances": []}
        self.assertEqual(self.client.get("/watch/context?scope=audit").json()["scope"], "audit")
        self.watch.watch_context.assert_called_once_with("audit")

    def test_alert_list_endpoint(self):
        self.watch.list_alerts.return_value = [{"id": "alert-1"}]
        self.assertEqual(self.client.get("/watch/alerts").json()["total"], 1)

    def test_alert_acknowledgement_endpoint(self):
        self.watch.acknowledge_alert.return_value = {"id": "alert-1", "status": "acknowledged"}
        self.assertEqual(self.client.post("/watch/alerts/alert-1/acknowledge").json()["status"], "acknowledged")

    def test_watch_rule_crud_preview_and_explicit_evaluation_contract(self):
        payload = {
            "name": "贵州茅台价格观察",
            "rule_type": "price",
            "severity": "warning",
            "config": {
                "symbols": ["600519.SH"],
                "logic": "all",
                "conditions": [{"field": "price", "operator": "gte", "value": 1500}],
            },
        }
        self.watch_rule.list_watch_rules.return_value = [{"id": "rule-1", **payload}]
        self.watch_rule.create_watch_rule.return_value = {"id": "rule-1", "rule_version": 1, **payload}
        self.watch_rule.preview_watch_rule.return_value = {"matched": 1, "items": [{"symbol": "600519.SH"}]}
        self.watch_rule.evaluate_watch_rule.return_value = {"matched": 1, "alerts_created": 1, "orders_created": 0}

        self.assertEqual(self.client.get("/watch/rules").json()["total"], 1)
        self.assertEqual(self.client.post("/watch/rules", json=payload).json()["rule_version"], 1)
        self.assertEqual(self.client.post("/watch/rules/rule-1/preview").json()["matched"], 1)
        evaluated = self.client.post("/watch/rules/rule-1/evaluate").json()
        self.assertEqual(evaluated["alerts_created"], 1)
        self.assertEqual(evaluated["orders_created"], 0)

    def test_watch_rule_validation_error_is_400(self):
        self.watch_rule.create_watch_rule.side_effect = ValueError("不支持的盯盘字段")
        response = self.client.post("/watch/rules", json={"name": "非法规则"})
        self.assertEqual(response.status_code, 400)

    def test_health_endpoint(self):
        self.monitor.health.return_value = {"status": "healthy", "services": []}
        self.assertEqual(self.client.get("/monitor/health").json()["status"], "healthy")
        self.monitor.health.assert_called_once_with("business")

    def test_health_endpoint_rejects_unknown_scope(self):
        self.assertEqual(self.client.get("/monitor/health?scope=everything").status_code, 422)

    def test_list_instances_reuses_cache_within_ttl(self):
        paper.reset_paper_list_cache()
        self.paper.list_instances.return_value = [{"id": "paper-1"}]
        self.assertEqual(self.client.get("/paper/instances").json()["total"], 1)
        self.assertEqual(self.client.get("/paper/instances").json()["total"], 1)
        self.assertEqual(self.paper.list_instances.call_count, 1)

    def test_list_cache_stamps_after_query(self):
        paper.reset_paper_list_cache()

        def slow_list():
            time.sleep(0.05)
            return [{"id": "paper-1"}]

        self.paper.list_instances.side_effect = slow_list
        with patch.object(paper, "_PAPER_LIST_TTL_SECONDS", 0.04):
            self.assertEqual(self.client.get("/paper/instances").json()["total"], 1)
            self.assertEqual(self.client.get("/paper/instances").json()["total"], 1)
        self.assertEqual(self.paper.list_instances.call_count, 1)

    def test_start_invalidates_instance_list_cache(self):
        paper.reset_paper_list_cache()
        self.paper.list_instances.return_value = [{"id": "paper-1"}]
        self.paper.start.return_value = {"id": "paper-1", "status": "running"}
        self.client.get("/paper/instances")
        self.client.post("/paper/instances/paper-1/start")
        self.client.get("/paper/instances")
        self.assertEqual(self.paper.list_instances.call_count, 2)


if __name__ == "__main__":
    unittest.main()
