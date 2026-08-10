import unittest
from datetime import timezone
from unittest.mock import MagicMock, patch

from app.services.paper_runtime_service import PaperRuntimeService


LIMITS = {
    "cash_floor_ratio": 0.05,
    "max_single_symbol_weight": 1.0,
    "max_participation_ratio": 0.10,
    "max_drawdown": 0.20,
    "max_daily_turnover": 2.0,
}


def decisions(**overrides):
    payload = dict(side="buy", quantity=1000, price=10, volume=100000, cash=100000,
                   initial=100000, equity=100000, drawdown=0.0)
    payload.update(overrides)
    return {code: passed for code, passed, _ in PaperRuntimeService.risk_checks(LIMITS, **payload)}


class PaperRiskRuleTests(unittest.TestCase):
    def test_normal_buy_passes_all_rules(self):
        self.assertTrue(all(decisions().values()))

    def test_single_symbol_weight_blocks_entry(self):
        self.assertFalse(decisions(quantity=11000)["single_symbol_weight"])

    def test_participation_blocks_entry(self):
        self.assertFalse(decisions(quantity=10100)["participation"])

    def test_zero_volume_blocks_entry(self):
        self.assertFalse(decisions(volume=0)["participation"])

    def test_cash_floor_blocks_entry(self):
        self.assertFalse(decisions(quantity=9600)["cash_floor"])

    def test_drawdown_blocks_entry(self):
        self.assertFalse(decisions(drawdown=0.21)["drawdown"])

    def test_turnover_blocks_entry(self):
        self.assertFalse(decisions(quantity=21000, volume=1000000, equity=100000)["daily_turnover"])

    def test_sell_ignores_entry_only_limits(self):
        result = decisions(side="sell", quantity=50000, volume=0, cash=0)
        self.assertTrue(result["single_symbol_weight"])
        self.assertTrue(result["participation"])
        self.assertTrue(result["cash_floor"])

    def test_zero_cash_floor_is_respected(self):
        limits = {**LIMITS, "cash_floor_ratio": 0}
        result = PaperRuntimeService.risk_checks(limits, "buy", 10000, 10, 1000000, 100000, 100000, 100000, 0)
        self.assertTrue(dict((code, passed) for code, passed, _ in result)["cash_floor"])

    def test_exact_participation_boundary_passes(self):
        self.assertTrue(decisions(quantity=10000)["participation"])

    def test_exact_drawdown_boundary_passes(self):
        self.assertTrue(decisions(drawdown=0.20)["drawdown"])

    def test_missing_limits_use_defaults(self):
        result = PaperRuntimeService.risk_checks({}, "buy", 1000, 10, 100000, 100000, 100000, 100000, 0)
        self.assertTrue(all(passed for _, passed, _ in result))

    def test_messages_are_auditable(self):
        result = PaperRuntimeService.risk_checks(LIMITS, "buy", 10100, 10, 100000, 100000, 100000, 100000, 0)
        self.assertEqual(next(message for code, _, message in result if code == "participation"), "参与率超过上限")

    def test_timestamp_z_is_timezone_aware(self):
        parsed = PaperRuntimeService._timestamp("2025-01-02T07:00:00Z")
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)

    def test_timestamp_naive_is_normalized_to_utc(self):
        parsed = PaperRuntimeService._timestamp("2025-01-02T07:00:00")
        self.assertEqual(parsed.tzinfo, timezone.utc)


class PaperCycleAndRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.service = PaperRuntimeService.__new__(PaperRuntimeService)
        self.service.database = MagicMock()

    def _recovery_cursor(self, interrupted):
        connection = MagicMock()
        cursor = MagicMock()
        self.service.database.get_connection.return_value.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchall.return_value = interrupted
        return cursor

    def test_completed_cycle_is_reused(self):
        self.service._row = MagicMock(return_value={"id": "cycle-1", "status": "success", "input_hash": "hash"})
        self.assertEqual(self.service._open_cycle("paper", "day", "2025-01-02", MagicMock(), MagicMock(), "hash"), ("cycle-1", True))

    def test_blocked_cycle_is_reused(self):
        self.service._row = MagicMock(return_value={"id": "cycle-1", "status": "blocked", "input_hash": "hash"})
        self.assertTrue(self.service._open_cycle("paper", "day", "2025-01-02", MagicMock(), MagicMock(), "hash")[1])

    def test_same_key_with_changed_input_is_rejected(self):
        self.service._row = MagicMock(return_value={"id": "cycle-1", "status": "failed", "input_hash": "old"})
        with self.assertRaisesRegex(ValueError, "输入清单发生变化"):
            self.service._open_cycle("paper", "day", "2025-01-02", MagicMock(), MagicMock(), "new")

    def test_failed_cycle_can_restart_with_same_input(self):
        self.service._row = MagicMock(return_value={"id": "cycle-1", "status": "failed", "input_hash": "hash"})
        self.service._execute = MagicMock()
        cycle_id, reused = self.service._open_cycle("paper", "day", "2025-01-02", MagicMock(), MagicMock(), "hash")
        self.assertEqual(cycle_id, "cycle-1")
        self.assertFalse(reused)
        self.service._execute.assert_called_once()

    def test_recovery_marks_only_running_cycles_failed(self):
        self.service._rows = MagicMock(return_value=[{"id": "paper-1", "status": "running"}])
        cursor = self._recovery_cursor([{"id": "cycle-1", "paper_instance_id": "paper-1"}])
        self.service._event_cursor = MagicMock()
        result = self.service.recover_instances()
        self.assertEqual(result["restored"], 1)
        self.assertEqual(result["interrupted_cycles"], 1)
        self.assertIn("WHERE status='running'", cursor.execute.call_args.args[0])
        self.service._event_cursor.assert_called_once()

    def test_recovery_persists_cursor_evidence(self):
        row = {"id": "paper-1", "status": "paused", "last_processed_trade_date": "2025-01-02", "last_cycle_key": "close"}
        self.service._rows = MagicMock(return_value=[row])
        self._recovery_cursor([{"id": "cycle-1", "paper_instance_id": "paper-1"}])
        self.service._event_cursor = MagicMock()
        self.service.recover_instances()
        payload = self.service._event_cursor.call_args.args[-1]
        self.assertEqual(payload["last_cycle_key"], "close")
        self.assertEqual(payload["interrupted_cycle_ids"], ["cycle-1"])

    def test_recovery_with_no_instances_is_safe(self):
        self.service._rows = MagicMock(return_value=[])
        self._recovery_cursor([])
        self.service._event_cursor = MagicMock()
        result = self.service.recover_instances()
        self.assertEqual(result["restored"], 0)
        self.assertEqual(result["interrupted_cycles"], 0)
        self.service._event_cursor.assert_not_called()

    def test_recovery_does_not_emit_event_without_interrupted_cycle(self):
        self.service._rows = MagicMock(return_value=[{"id": "paper-1", "status": "running"}])
        self._recovery_cursor([])
        self.service._event_cursor = MagicMock()
        result = self.service.recover_instances()
        self.assertEqual(result["restored"], 1)
        self.assertEqual(result["interrupted_cycles"], 0)
        self.service._event_cursor.assert_not_called()


class PaperPromotionGateTests(unittest.TestCase):
    def setUp(self):
        self.service = PaperRuntimeService.__new__(PaperRuntimeService)
        self.service.database = MagicMock()

    @staticmethod
    def request():
        return {
            "strategy_version_id": "strategy-1",
            "dataset_snapshot_id": 10,
            "factor_snapshot_id": 20,
            "universe_snapshot_id": 30,
            "pool_snapshot_id": 40,
            "research_protocol_id": "protocol-1",
            "qualifying_backtest_run_id": "run-1",
        }

    @staticmethod
    def qualifying():
        return {
            "id": "run-1",
            "strategy_version_id": "strategy-1",
            "dataset_snapshot_id": 10,
            "factor_snapshot_id": 20,
            "universe_snapshot_id": 30,
            "pool_snapshot_id": 40,
            "research_protocol_id": "protocol-1",
        }

    def test_paper_rejects_incomplete_promotion_check_set(self):
        rows = [
            self.qualifying(),
            {"id": 40, "dataset_snapshot_id": 10, "factor_snapshot_id": 20, "universe_snapshot_id": 30},
            {"id": 20},
            {"id": 30},
            {"id": 10},
            {"id": "protocol-1"},
            {"id": "strategy-1", "name": "策略"},
        ]
        self.service._row = MagicMock(side_effect=rows)
        self.service._rows = MagicMock(return_value=[
            {"check_code": "OUT_OF_SAMPLE_PASS", "status": "passed"},
            {"check_code": "CAPACITY_PASS", "status": "passed"},
        ])
        with self.assertRaisesRegex(ValueError, "完整晋级门禁"):
            self.service.create_instance(self.request())
        self.service.database.get_connection.assert_not_called()

if __name__ == "__main__":
    unittest.main()
