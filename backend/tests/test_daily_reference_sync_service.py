import unittest
from unittest.mock import MagicMock

from app.services.daily_reference_sync_service import (
    DailyReferenceSyncService,
    compact_trade_date,
    normalise_trade_date,
    trade_calendar_is_open,
)


class DailyReferenceCalendarGateTests(unittest.TestCase):
    def test_calendar_gate_uses_tushare_open_flag_not_weekday_guess(self):
        records = [
            {"cal_date": "20250103", "is_open": "1"},
            {"cal_date": "20250104", "is_open": 0},
        ]

        self.assertTrue(trade_calendar_is_open(records, "2025-01-03"))
        self.assertFalse(trade_calendar_is_open(records, "20250104"))

    def test_calendar_gate_rejects_missing_target_date(self):
        with self.assertRaisesRegex(ValueError, "未返回"):
            trade_calendar_is_open([{"cal_date": "20250103", "is_open": 1}], "20250104")

    def test_trade_date_normalisation_is_explicit(self):
        self.assertEqual(normalise_trade_date("20250103"), "2025-01-03")
        self.assertEqual(compact_trade_date("2025-01-03"), "20250103")
        with self.assertRaises(ValueError):
            normalise_trade_date("2025/01/03")


class DailyReferenceOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.database = MagicMock()
        self.connection = MagicMock()
        self.cursor = MagicMock()
        self.database.get_connection.return_value.__enter__.return_value = self.connection
        self.connection.cursor.return_value.__enter__.return_value = self.cursor
        self.cursor.fetchone.return_value = {"acquired": True}
        self.service = DailyReferenceSyncService.__new__(DailyReferenceSyncService)
        self.service.database = self.database
        self.service.catalog_service = MagicMock()
        self.service.reference_service = MagicMock()
        self.service.kline_service = MagicMock()
        self.service.snapshot_service = MagicMock()
        self.service.factor_service = MagicMock()
        self.service._schedule_row = MagicMock(return_value={"enabled": True})
        self.service._run_row = MagicMock(return_value=None)
        self.service._start_run = MagicMock(return_value={"id": 41})
        self.service._finish_run = MagicMock(side_effect=lambda _, __, status, result, **kwargs: {"status": status, **result})

    def _event(self, name, result):
        def callback(*args, **kwargs):
            self.events.append(name)
            return result
        return callback

    def _configure_open_day(self):
        self.service.catalog_service.sync_endpoint.side_effect = self._event(
            "calendar_fetch",
            {"run_id": 1, "response_hash": "calendar-hash", "records": [{"cal_date": "20250102", "is_open": 1}]},
        )
        self.service.reference_service.sync_trade_calendar_records.side_effect = self._event(
            "calendar_publish", {"status": "published", "actual_source": "tushare"}
        )
        self.service.reference_service.security_master_is_due.return_value = True
        self.service.reference_service.sync_security_master.side_effect = self._event(
            "security_master", {"status": "published", "actual_source": "tushare"}
        )
        self.service.reference_service.sync_daily_auxiliary_datasets.side_effect = self._event(
            "auxiliary",
            {
                code: {"status": "published", "actual_source": "tushare", "response_hash": f"{code}-hash"}
                for code in (
                    "adjustment_factors", "daily_valuation", "suspensions", "price_limits",
                    "corporate_actions", "benchmark_bars",
                )
            },
        )
        self.service.reference_service.publish_universe_snapshot.side_effect = self._event(
            "universe",
            {"status": "sealed", "universe_snapshot_id": 7, "dataset_partition": {"status": "published"}},
        )
        self.service.kline_service.create_market_daily_sync_job.side_effect = self._event(
            "kline_job", {"job_id": 9, "jobId": 9}
        )
        self.service.kline_service.run_job.side_effect = self._event("kline_sync", {"status": "success"})
        self.service.snapshot_service.publish_daily_bars.side_effect = self._event(
            "dataset_seal",
            {"status": "sealed", "actual_source": "tushare", "snapshot": {"id": 11}},
        )
        self.service.catalog_service.sync_market_evidence.side_effect = self._event(
            "market_evidence", {"status": "restricted", "snapshot_id": None}
        )
        self.service.factor_service.run_daily_schedule.side_effect = self._event(
            "factor_schedule", {"status": "sealed", "factor_snapshot": {"id": 13}}
        )

    def test_open_day_seals_complete_snapshot_before_factor_schedule(self):
        self._configure_open_day()

        result = self.service.run("2025-01-02", ["SH_600000"])

        self.assertEqual(result["status"], "sealed")
        self.assertLess(self.events.index("dataset_seal"), self.events.index("factor_schedule"))
        self.assertEqual(
            self.events,
            ["calendar_fetch", "calendar_publish", "security_master", "auxiliary", "universe", "kline_job", "kline_sync", "dataset_seal", "market_evidence", "factor_schedule"],
        )
        reference_codes = self.service.snapshot_service.publish_daily_bars.call_args.kwargs["reference_dataset_codes"]
        self.assertEqual(len(reference_codes), 9)
        self.service.factor_service.run_daily_schedule.assert_called_once_with("2025-01-02", 11, 7)

    def test_failed_required_calendar_partition_cannot_reach_kline_or_factor(self):
        self._configure_open_day()
        self.service.reference_service.sync_trade_calendar_records.side_effect = self._event(
            "calendar_publish", {"status": "failed"}
        )

        result = self.service.run("2025-01-02", ["SH_600000"])

        self.assertEqual(result["status"], "failed")
        self.service.kline_service.create_market_daily_sync_job.assert_not_called()
        self.service.snapshot_service.publish_daily_bars.assert_not_called()
        self.service.factor_service.run_daily_schedule.assert_not_called()

    def test_failed_auxiliary_partition_cannot_seal_or_trigger_factor(self):
        self._configure_open_day()
        self.service.reference_service.sync_daily_auxiliary_datasets.side_effect = self._event(
            "auxiliary", {"daily_valuation": {"status": "failed"}}
        )

        result = self.service.run("2025-01-02", ["SH_600000"])

        self.assertEqual(result["status"], "failed")
        self.service.snapshot_service.publish_daily_bars.assert_not_called()
        self.service.factor_service.run_daily_schedule.assert_not_called()

    def test_closed_day_never_calls_reference_or_price_sync(self):
        self.service.catalog_service.sync_endpoint.return_value = {
            "run_id": 1, "response_hash": "closed", "records": [{"cal_date": "20250102", "is_open": 0}]
        }

        result = self.service.run("2025-01-02", ["SH_600000"])

        self.assertEqual(result["status"], "not_trading_day")
        self.service.reference_service.sync_trade_calendar_records.assert_not_called()
        self.service.kline_service.create_market_daily_sync_job.assert_not_called()

    def test_locked_day_never_calls_provider(self):
        self.cursor.fetchone.return_value = {"acquired": False}

        self.assertEqual(self.service.run("2025-01-02", ["SH_600000"])["status"], "locked")
        self.service.catalog_service.sync_endpoint.assert_not_called()

    def test_already_sealed_day_is_idempotent(self):
        self.service._run_row.return_value = {
            "id": 41, "trade_date": "2025-01-02", "status": "sealed", "attempt_count": 1,
        }

        result = self.service.run("2025-01-02", ["SH_600000"])

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "already_sealed")
        self.service.catalog_service.sync_endpoint.assert_not_called()

    def test_disabled_schedule_never_calls_provider(self):
        self.service._schedule_row.return_value = {"enabled": False}

        self.assertEqual(self.service.run("2025-01-02", ["SH_600000"])["status"], "disabled")
        self.service.catalog_service.sync_endpoint.assert_not_called()

    def test_force_bypasses_disabled_schedule(self):
        self.service._schedule_row.return_value = {"enabled": False}
        self._configure_open_day()

        result = self.service.run("2025-01-02", ["SH_600000"], force=True)

        self.assertEqual(result["status"], "sealed")
        self.service.kline_service.create_market_daily_sync_job.assert_called_once()


if __name__ == "__main__":
    unittest.main()
