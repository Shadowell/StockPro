import asyncio
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.api.endpoints import data
from app.services.scheduler_service import SchedulerService


class FakeDataModuleDb:
    def table_counts(self):
        return [
            {"name": "kline_history", "rows": 8},
            {"name": "kline_1d", "rows": 8},
        ]

    def kline_coverage(self, limit=200):
        return [
            {
                "exchange": "cn",
                "symbol": "SH_600000",
                "name": "浦发银行",
                "timeframe": "1d",
                "rows": 5,
                "first_date": "2026-01-01",
                "last_date": "2026-01-05",
                "status": "success",
                "last_sync_at": "2026-06-04T10:00:00",
                "error_message": None,
            },
            {
                "exchange": "cn",
                "symbol": "SZ_000001",
                "name": "平安银行",
                "timeframe": "1d",
                "rows": 3,
                "first_date": "2026-01-02",
                "last_date": "2026-01-04",
                "status": "success",
                "last_sync_at": "2026-06-04T10:02:00",
                "error_message": None,
            },
        ]

    def list_sync_jobs(self, limit=20):
        return [
            {
                "id": 7,
                "job_name": "contract-sync",
                "source": "tushare",
                "start_date": "2026-01-01",
                "end_date": "2026-01-05",
                "status": "success",
                "total_items": 2,
                "completed_items": 2,
                "failed_items": 0,
                "message": "done",
                "created_at": "2026-06-04T09:58:00",
                "started_at": "2026-06-04T10:00:00",
                "finished_at": "2026-06-04T10:03:00",
                "updated_at": "2026-06-04T10:03:00",
            }
        ]

    def get_sync_job_items(self, job_id):
        return [
            {
                "id": 1,
                "exchange": "cn",
                "symbol": "SH_600000",
                "timeframe": "1d",
                "status": "success",
                "records_count": 5,
                "started_at": "2026-06-04T10:00:00",
                "finished_at": "2026-06-04T10:01:00",
                "error_message": None,
            }
        ]


class DataModuleContractTest(unittest.TestCase):
    def setUp(self):
        self.fake_db = FakeDataModuleDb()

    def test_status_payload_matches_bitpro_data_manager_contract(self):
        payload = data.build_data_manager_status(
            self.fake_db,
            {"is_running": False, "message": "空闲"},
        )

        self.assertFalse(payload["isRunning"])
        self.assertEqual(payload["summary"]["totalRecords"], 8)
        self.assertEqual(payload["summary"]["symbolsCount"], 2)
        self.assertEqual(payload["summary"]["pairs"], 2)
        self.assertEqual(payload["details"][0]["dataType"], "kline")
        self.assertEqual(payload["details"][0]["totalRecords"], 5)
        self.assertIsInstance(payload["details"][0]["firstTimestamp"], int)

    def test_table_stats_and_jobs_use_bitpro_camel_case(self):
        stats = data.build_data_manager_table_stats(self.fake_db)
        jobs = data.build_data_manager_jobs(self.fake_db, limit=20, include_items=True)

        self.assertEqual(stats["totalRecords"], 8)
        self.assertEqual(stats["totalPairs"], 2)
        self.assertEqual(stats["marketStats"]["stock"]["totalSymbols"], 2)
        self.assertEqual(stats["tables"][0]["tableName"], "kline_1d")
        self.assertEqual(stats["tables"][0]["recordCount"], 5)
        self.assertEqual(jobs["jobs"][0]["jobId"], "7")
        self.assertEqual(jobs["jobs"][0]["status"], "completed")
        self.assertEqual(jobs["jobs"][0]["items"][0]["totalInserted"], 5)


class DataRuntimeConfigPersistenceTest(unittest.TestCase):
    def test_symbol_and_schedule_config_survive_reload(self):
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "data-runtime.json"
            data.reset_data_runtime_config(config_path)

            data.persist_data_symbol("SZ_000002", remove=False, config_path=config_path)
            data.persist_data_symbol("SH_600000", remove=True, config_path=config_path)
            data.persist_data_schedule(
                {
                    "enabled": True,
                    "intervalMinutes": 120,
                    "historyDays": 30,
                    "symbols": ["SZ_000002"],
                    "timeframes": ["1d"],
                },
                config_path=config_path,
            )

            data.reset_data_runtime_config(config_path)
            payload = data.load_data_runtime_config(config_path)

            self.assertIn("SZ_000002", payload["customSymbols"])
            self.assertIn("SH_600000", payload["removedSymbols"])
            self.assertTrue(payload["schedule"]["enabled"])
            self.assertEqual(payload["schedule"]["intervalMinutes"], 120)
            self.assertEqual(payload["schedule"]["historyDays"], 30)
            self.assertEqual(data._schedule_payload()["symbols"], ["SZ_000002"])


class FakeAllAshareDb:
    def get_all_stocks_realtime(self):
        return [
            {"code": "600000", "name": "浦发银行"},
            {"code": "SZ_000001", "name": "平安银行"},
            {"code": "300750", "name": "宁德时代"},
            {"code": "SH_600000", "name": "重复项"},
            {"code": "", "name": "无效行"},
        ]


class FakeAllAshareSyncService:
    def __init__(self):
        self.created = None

    def create_history_sync_job(self, symbols, timeframes, start_date, end_date, job_name=None):
        self.created = {
            "symbols": symbols,
            "timeframes": timeframes,
            "start_date": start_date,
            "end_date": end_date,
            "job_name": job_name,
        }
        return 42


class AllAshareDailySyncTest(unittest.TestCase):
    def test_daily_all_ashare_job_uses_full_market_symbol_universe(self):
        service = FakeAllAshareSyncService()

        job = data.create_all_ashare_daily_sync_job(
            database=FakeAllAshareDb(),
            service=service,
            now=datetime(2026, 6, 4, 18, 10, 0),
            history_days=7,
        )

        self.assertEqual(job["jobId"], "42")
        self.assertEqual(job["symbolsCount"], 3)
        self.assertEqual(service.created["symbols"], ["SH_600000", "SZ_000001", "SZ_300750"])
        self.assertEqual(service.created["timeframes"], ["1d"])
        self.assertEqual(service.created["start_date"], "2026-05-28")
        self.assertEqual(service.created["end_date"], "2026-06-04")
        self.assertIn("all-ashare-daily", service.created["job_name"])

    def test_scheduler_registers_daily_all_ashare_sync_job(self):
        service = SchedulerService()
        asyncio.run(service.initialize())

        self.assertIn("sync_all_ashare_klines", {job.id for job in service.scheduler.get_jobs()})
        job = service.scheduler.get_job("sync_all_ashare_klines")
        self.assertEqual(str(job.trigger.fields[5]), "18")
        self.assertEqual(str(job.trigger.fields[6]), "10")

    def test_scheduled_all_ashare_sync_respects_disabled_schedule(self):
        service = FakeAllAshareSyncService()
        previous_schedule = data._schedule_payload()
        previous_sync_status = dict(data.sync_status)
        data._schedule_config = {**data._default_schedule_config(), "enabled": False}
        try:
            with patch.object(data, "save_data_runtime_config", return_value={}):
                result = asyncio.run(
                    data.run_scheduled_all_ashare_sync(
                        database=FakeAllAshareDb(),
                        service=service,
                        now=datetime(2026, 6, 4, 18, 10, 0),
                    )
                )
        finally:
            data._schedule_config = previous_schedule
            data.sync_status.clear()
            data.sync_status.update(previous_sync_status)

        self.assertFalse(result["success"])
        self.assertIn("未启用", result["message"])
        self.assertIsNone(service.created)


if __name__ == "__main__":
    unittest.main()
