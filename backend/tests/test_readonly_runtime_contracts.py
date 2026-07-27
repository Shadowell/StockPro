import unittest
from unittest.mock import MagicMock, patch

from app.api.endpoints import data
from app.core.config import Settings
from app.services.daily_reference_sync_service import DailyReferenceSyncService
from app.services.dataset_snapshot_service import DatasetSnapshotService


def database_with_cursor(*, fetchone=None, fetchall=None):
    database = MagicMock()
    connection = MagicMock()
    cursor = MagicMock()
    database.get_connection.return_value.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    if fetchone is not None:
        cursor.fetchone.side_effect = fetchone
    if fetchall is not None:
        cursor.fetchall.return_value = fetchall
    return database, cursor


class DatasetReadBoundaryTests(unittest.TestCase):
    def test_dataset_list_endpoints_never_install_the_registry(self):
        for method_name, args in (
            ("list_datasets", ()),
            ("list_quality_issues", ()),
            ("list_snapshots", ()),
            ("list_source_entitlements", ()),
        ):
            with self.subTest(method=method_name):
                database, cursor = database_with_cursor(fetchall=[])
                service = DatasetSnapshotService(database)
                service.install_registry = MagicMock(side_effect=AssertionError("read path attempted bootstrap"))

                self.assertEqual(getattr(service, method_name)(*args), [])
                service.install_registry.assert_not_called()
                for call in cursor.execute.call_args_list:
                    statement = str(call.args[0]).strip().upper()
                    self.assertTrue(statement.startswith("SELECT"), statement)


class DailyScheduleReadBoundaryTests(unittest.TestCase):
    def test_missing_schedule_returns_disabled_unconfigured_defaults_without_insert(self):
        database, cursor = database_with_cursor(fetchone=[None, None, None])
        service = DailyReferenceSyncService.__new__(DailyReferenceSyncService)
        service.database = database

        payload = service.get_schedule()

        self.assertFalse(payload["configured"])
        self.assertFalse(payload["enabled"])
        self.assertIsNone(payload["updatedAt"])
        for call in cursor.execute.call_args_list:
            statement = str(call.args[0]).strip().upper()
            self.assertTrue(statement.startswith("SELECT"), statement)


class DailyScheduleRuntimePresentationTests(unittest.IsolatedAsyncioTestCase):
    async def test_enabled_pg_schedule_reports_offline_when_runtime_flag_is_disabled(self):
        configured = {
            "code": "daily_reference_publication",
            "configured": True,
            "enabled": True,
            "nextRunAt": "2026-07-28T17:30:00+08:00",
        }
        with patch.object(data.daily_reference_sync_service, "get_schedule", return_value=configured), patch.object(
            data.settings,
            "ENABLE_SCHEDULER",
            False,
        ):
            payload = await data.daily_reference_schedule()

        self.assertEqual("runner_offline", payload["runtimeStatus"])
        self.assertFalse(payload["runnerOnline"])
        self.assertFalse(payload["jobRegistered"])
        self.assertIsNone(payload["effectiveNextRunAt"])
        self.assertEqual(configured["nextRunAt"], payload["configuredNextRunAt"])


class TushareCatalogueReadBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalogue_get_does_not_install_catalogue(self):
        with patch.object(data.tushare_catalog_service, "install_catalog") as install, patch.object(
            data.tushare_catalog_service,
            "catalogue",
            return_value=[{"endpoint_code": "daily"}],
        ) as catalogue:
            payload = await data.list_tushare_endpoints(module="行情数据")

        install.assert_not_called()
        catalogue.assert_called_once_with(module="行情数据")
        self.assertEqual(payload["total"], 1)


class StartupSafetyTests(unittest.IsolatedAsyncioTestCase):
    def test_background_and_bootstrap_defaults_are_safe(self):
        for field in (
            "RUN_MIGRATIONS_ON_STARTUP",
            "RUN_BOOTSTRAP_ON_STARTUP",
            "RUN_PAPER_RECOVERY_ON_STARTUP",
            "ENABLE_SCHEDULER",
            "ENABLE_REALTIME_SYNC",
            "ENABLE_STRATEGY_EXECUTION",
            "ENABLE_EXTERNAL_MARKET_FETCH",
        ):
            with self.subTest(field=field):
                self.assertIs(Settings.model_fields[field].default, False)

    async def test_startup_with_all_runtime_flags_disabled_does_not_mutate_or_start_workers(self):
        from app import main

        runtime = MagicMock()
        runtime.RUN_MIGRATIONS_ON_STARTUP = False
        runtime.RUN_BOOTSTRAP_ON_STARTUP = False
        runtime.RUN_PAPER_RECOVERY_ON_STARTUP = False
        runtime.ENABLE_SCHEDULER = False
        runtime.ENABLE_REALTIME_SYNC = False
        runtime.ENABLE_STRATEGY_EXECUTION = False
        with patch.object(main, "settings", runtime), patch.object(main, "apply_migrations") as migrations:
            await main.startup_event()

        migrations.assert_not_called()


if __name__ == "__main__":
    unittest.main()
