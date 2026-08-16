import unittest
from unittest.mock import MagicMock, patch

from app.services.live_trading_service import LiveTradingService


def _make_service():
    service = LiveTradingService.__new__(LiveTradingService)
    service.database = MagicMock()
    service._record_event = lambda *a, **k: "event-1"
    return service


class LiveTradingStatusTests(unittest.TestCase):
    def test_status_reports_boundary_and_adapters(self):
        service = _make_service()
        status = service.status()
        self.assertFalse(status["trading_enabled"])
        self.assertIn("审计留痕", status["boundary_note"])
        keys = {item["key"] for item in status["adapters"]}
        self.assertIn("miniqmt", keys)
        self.assertIn("ptrade", keys)
        self.assertIn("max_single_order_value", status["risk_limits"])


class LivePreflightTests(unittest.TestCase):
    def test_preflight_blocks_without_broker_and_switch(self):
        service = _make_service()
        candidate = {
            "kind": "backtest_run", "id": "run-1", "name": "完整回测",
            "strategy_version_id": None, "promotion_status": "paper_eligible",
            "metrics": {}, "detail": {"passed_gate_count": 11, "gate_total": 11},
        }
        service._candidate = MagicMock(return_value=candidate)
        with patch.object(service.__class__, "status", return_value={
            "trading_enabled": False, "boundary_note": "", "adapters": [],
            "risk_limits": {"max_single_order_value": 1, "max_position_weight": 1, "max_daily_loss_ratio": 1},
        }):
            result = service.preflight("backtest_run", "run-1")
        codes = {item["check_code"]: item["status"] for item in result["checks"]}
        self.assertEqual(codes["BROKER_ADAPTER"], "failed")
        self.assertEqual(codes["LIVE_TRADING_ENABLED"], "failed")
        self.assertFalse(result["deployable"])
        self.assertIsNone(result["confirm_token"])

    def test_preflight_fails_incomplete_promotion_gate(self):
        service = _make_service()
        candidate = {
            "kind": "backtest_run", "id": "run-2", "name": "完整回测",
            "strategy_version_id": None, "promotion_status": "paper_eligible",
            "metrics": {}, "detail": {"passed_gate_count": 9, "gate_total": 11},
        }
        service._candidate = MagicMock(return_value=candidate)
        result = service.preflight("backtest_run", "run-2")
        gate = next(item for item in result["checks"] if item["check_code"] == "PROMOTION_GATE")
        self.assertEqual(gate["status"], "failed")

    def test_enable_is_blocked_and_audited_when_not_ready(self):
        service = _make_service()
        recorded = []
        service._record_event = lambda etype, kind, cid, status, detail: recorded.append((etype, status)) or "event-9"
        preflight = {
            "deployable": True,
            "checks": [],
        }
        with patch.object(service.__class__, "preflight", return_value=preflight), \
             patch.object(service.__class__, "status", return_value={
                 "trading_enabled": False, "boundary_note": "", "adapters": [],
             }):
            result = service.request_enable("backtest_run", "run-1", service._confirm_token("backtest_run", "run-1"), True)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(recorded[-1], ("enable_request", "blocked"))

    def test_enable_requires_double_confirm_and_valid_token(self):
        service = _make_service()
        result = service.request_enable("backtest_run", "run-1", "token", False)
        self.assertEqual(result["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
