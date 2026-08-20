import inspect
import unittest
from unittest.mock import patch

from app.api.endpoints import market
from app.services.backtest_workbench_service import BacktestWorkbenchService
from app.services.chart_service import ChartService
from app.api.endpoints.factor_research import factor_research_library
from app.api.endpoints.strategy_runtime import get_latest_strategy_version
from app.services.factor_research_service import FactorResearchService
from app.services.market_service import MarketService


class ProviderFreeResearchReadTests(unittest.TestCase):
    def test_factor_library_get_does_not_install_seed_records(self):
        source = inspect.getsource(factor_research_library)
        self.assertNotIn("install_reference_factors", source)

    def test_latest_strategy_version_get_does_not_create_version(self):
        source = inspect.getsource(get_latest_strategy_version)
        self.assertNotIn("ensure_legacy_version", source)

    def test_factor_and_backtest_orchestrators_have_no_provider_fetch_calls(self):
        for service in (FactorResearchService, BacktestWorkbenchService):
            with self.subTest(service=service.__name__):
                source = inspect.getsource(service)
                self.assertNotIn("sync_endpoint(", source)
                self.assertNotIn("sync_market_evidence(", source)
                self.assertNotIn("tushare_provider", source.lower())
                self.assertNotIn("akshare", source.lower())

    def test_chart_page_reads_have_no_provider_or_write_calls(self):
        source = inspect.getsource(ChartService)
        self.assertNotIn("tushare_provider", source.lower())
        self.assertNotIn("akshare", source.lower())
        self.assertNotIn("insert_", source.lower())
        rows = [
            {
                "date": "2026-07-16",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "volume": 100,
                "source": "tushare",
                "updated_at": "2026-07-17T02:40:19",
            }
        ]
        with patch("app.services.chart_service.db_instance.get_kline_history", return_value=rows) as read:
            payload = ChartService.get_daily_data("600000.SH")

        read.assert_called_once_with("SH_600000", timeframe="1d")
        self.assertEqual("tushare", payload[0]["source_label"])
        self.assertEqual("2026-07-16", payload[0]["date"])

    def test_message_stream_uses_stored_stocks_and_does_not_write_abnormal_events(self):
        stale = [{"code": "600000", "change_percent": 10, "updated_at": "2025-01-02T15:00:00"}]
        with (
            patch("app.services.market_service.db.get_all_stocks_realtime", return_value=stale),
            patch.object(MarketService, "get_all_stocks", side_effect=AssertionError("provider path reached")),
            patch.object(MarketService, "_upsert_abnormal_events", side_effect=AssertionError("GET attempted write")),
            patch.object(MarketService, "_get_news_from_db_or_api", return_value=[]),
        ):
            payload = MarketService.get_message_stream(limit=10)

        self.assertEqual([], payload["abnormal"]["triggered"])
        self.assertEqual("stale", payload["data_status"]["stock_snapshot_state"])
        self.assertNotEqual(payload["updated_at"], payload["response_generated_at"])


class OptionalStrategyVersionReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_legacy_strategy_without_version_returns_empty_optional_result(self):
        with (
            patch("app.api.endpoints.strategy_runtime.service.latest_for_legacy", return_value=None),
            patch("app.api.endpoints.strategy_runtime.db_instance.get_strategy_by_id", return_value={"id": 1}),
        ):
            self.assertIsNone(await get_latest_strategy_version(1))


class ProviderFreeMarketEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_fundamentals_get_forces_cache_only_mode(self):
        with patch.object(
            market.MarketService,
            "get_stock_fundamentals",
            return_value={"code": "600000", "data_status": "empty"},
        ) as read:
            payload = await market.get_stock_fundamentals("600000.SH")

        read.assert_called_once_with("600000.SH", cache_only=True)
        self.assertEqual("empty", payload["data_status"])


if __name__ == "__main__":
    unittest.main()
