import unittest
from unittest.mock import MagicMock, patch

from app.services.local_acceptance_service import DRILLS, LocalAcceptanceService


class LocalAcceptanceUnitTests(unittest.TestCase):
    def setUp(self):
        self.service = LocalAcceptanceService.__new__(LocalAcceptanceService)
        self.service.database = MagicMock()
        self.service.backups = MagicMock()

    def test_contract_has_exactly_nine_drills(self):
        self.assertEqual(len(DRILLS), 9)

    def test_provider_fallback_is_source_labelled(self):
        result = self.service._drill_tushare_unavailable_akshare_fallback()
        self.assertTrue(result["passed"])
        self.assertEqual(result["simulation"]["actual_source"], "akshare")

    def test_both_provider_failure_retains_snapshot(self):
        snapshot = {"id": 10, "manifest_hash": "abc"}
        self.service._row = MagicMock(side_effect=[snapshot, snapshot])
        self.assertTrue(self.service._drill_both_providers_unavailable_last_good()["passed"])

    def test_stale_drill_requires_alert_and_valuation(self):
        self.service._row = MagicMock(return_value={"alert_id": "a", "valuation_count": 1})
        self.assertTrue(self.service._drill_stale_feed_with_positions()["passed"])

    def test_notification_failure_without_alert_fails_safely(self):
        self.service._row = MagicMock(return_value=None)
        self.assertFalse(self.service._drill_notification_delivery_failure()["passed"])

    def test_backup_drill_requires_matching_restore(self):
        self.service.backups.latest.return_value = {"latest_success": {"id": "backup"}}
        self.service.backups.restore_latest.return_value = {"id": "restore", "status": "success", "restore_evidence": {"all_match": True, "checks": {"paper": True}}}
        self.assertTrue(self.service._drill_backup_restore_reconciliation()["passed"])

    def test_unknown_drill_is_rejected(self):
        with self.assertRaises(ValueError):
            self.service.run_drill("unknown")

    def test_run_all_reports_failure_if_any_drill_fails(self):
        self.service.run_drill = MagicMock(side_effect=[{"status": "passed"}] * 8 + [{"status": "failed"}])
        self.assertEqual(self.service.run_all()["status"], "failed")

    def test_list_drills_keeps_latest_per_type(self):
        self.service._rows = MagicMock(return_value=[{"id": 2, "drill_type": "a"}, {"id": 1, "drill_type": "a"}, {"id": 3, "drill_type": "b"}])
        latest = self.service.list_drills()["latest"]
        self.assertEqual([item["id"] for item in latest], [2, 3])


if __name__ == "__main__":
    unittest.main()
