import unittest
from unittest.mock import patch

from app.core.config import settings
from app.services.market_service import MarketService


class MarketOverviewFastPathTests(unittest.TestCase):
    def test_market_overview_does_not_fetch_providers_when_realtime_cache_is_empty(self):
        indices = [
            {
                "name": "上证指数",
                "code": "sh000001",
                "price": 3000.0,
                "change_amount": 1.2,
                "change_percent": 0.04,
            }
        ]

        with (
            patch("app.services.market_service.db.get_market_indices_realtime", return_value=[]),
            patch("app.services.market_service.db.get_all_stocks_realtime", return_value=[]),
            patch.object(settings, "ENABLE_EXTERNAL_MARKET_FETCH", True),
            patch.object(MarketService, "_fetch_main_indices", return_value=indices) as fetch_indices,
            patch.object(MarketService, "get_all_stocks") as get_all_stocks,
        ):
            overview = MarketService.get_market_overview()

        get_all_stocks.assert_not_called()
        fetch_indices.assert_not_called()
        self.assertEqual([], overview["indices"])
        self.assertEqual(
            {"score": None, "status": "未同步", "advancing": None, "declining": None, "unchanged": None},
            overview["sentiment"],
        )
        self.assertEqual("unavailable", overview["data_status"]["stock_snapshot_state"])
        self.assertEqual("unavailable", overview["data_status"]["index_snapshot_state"])
        self.assertIn("response_generated_at", overview)
        self.assertIsNone(overview["last_update"])
        self.assertIsNone(overview["market_pulse"]["universe_count"])
        self.assertIsNone(overview["market_pulse"]["rise_fall_ratio"])

    def test_market_overview_splits_volume_for_normalized_exchange_codes(self):
        stocks = [
            {"code": "SH_600000", "name": "浦发银行", "change_percent": 1.0, "amount": 100_000_000},
            {"code": "SZ_000001", "name": "平安银行", "change_percent": -1.0, "amount": 200_000_000},
            {"code": "BJ_920000", "name": "安徽凤凰", "change_percent": 0.0, "amount": 300_000_000},
        ]

        with (
            patch("app.services.market_service.db.get_market_indices_realtime", return_value=[]),
            patch("app.services.market_service.db.get_all_stocks_realtime", return_value=stocks),
            patch.object(MarketService, "_fetch_main_indices", return_value=[]),
        ):
            overview = MarketService.get_market_overview()

        self.assertEqual(6.0, overview["volume"]["amount"])
        self.assertEqual(1.0, overview["volume"]["sh_amount"])
        self.assertEqual(2.0, overview["volume"]["sz_amount"])
        self.assertEqual(3.0, overview["volume"]["bj_amount"])
        self.assertIsNone(overview["volume"]["ratio"])
        pulse = overview["market_pulse"]
        self.assertEqual(3, pulse["universe_count"])
        self.assertEqual(1.0, pulse["rise_fall_ratio"])
        self.assertEqual(1, pulse["advancing"])
        self.assertEqual(1, pulse["declining"])
        self.assertEqual(1, pulse["unchanged"])
        self.assertIn("amount_top10_share", pulse)

    def test_market_overview_does_not_invent_neutral_values_for_missing_changes(self):
        stocks = [{"code": "SH_600000", "change_percent": None, "amount": None, "updated_at": "2026-07-27T10:00:00"}]

        with (
            patch("app.services.market_service.db.get_market_indices_realtime", return_value=[]),
            patch("app.services.market_service.db.get_all_stocks_realtime", return_value=stocks),
            patch.object(MarketService, "_fetch_main_indices", return_value=[]),
        ):
            overview = MarketService.get_market_overview()

        self.assertIsNone(overview["sentiment"]["score"])
        self.assertEqual("不可用", overview["sentiment"]["status"])
        self.assertIsNone(overview["volume"]["amount"])
        self.assertIsNone(overview["volume"]["ratio"])


if __name__ == "__main__":
    unittest.main()
