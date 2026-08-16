import unittest
from unittest.mock import patch

from app.core.config import settings
from app.services.market_service import MarketService


class MarketOverviewFastPathTests(unittest.TestCase):
    def test_current_board_rules_do_not_apply_legacy_five_percent_st_limit(self):
        main_st = MarketService._price_limit_rule(
            "600001",
            "ST 测试",
            listing_trade_days=100,
            is_st=True,
        )
        chinext_st = MarketService._price_limit_rule(
            "300001",
            "ST 创业板",
            listing_trade_days=100,
            is_st=True,
        )

        self.assertEqual(10.0, main_st["threshold_pct"])
        self.assertEqual("sh_sz_main_10", main_st["rule_id"])
        self.assertEqual(20.0, chinext_st["threshold_pct"])
        self.assertEqual("star_chinext_20", chinext_st["rule_id"])

    def test_ipo_no_limit_windows_follow_board_specific_trading_days(self):
        main_day_five = MarketService._price_limit_rule(
            "001234",
            "主板新股",
            listing_trade_days=5,
            is_st=False,
        )
        main_day_six = MarketService._price_limit_rule(
            "001234",
            "主板新股",
            listing_trade_days=6,
            is_st=False,
        )
        beijing_day_one = MarketService._price_limit_rule(
            "920001",
            "北交新股",
            listing_trade_days=1,
            is_st=False,
        )
        beijing_day_two = MarketService._price_limit_rule(
            "920001",
            "北交新股",
            listing_trade_days=2,
            is_st=False,
        )

        self.assertFalse(main_day_five["has_price_limit"])
        self.assertTrue(main_day_six["has_price_limit"])
        self.assertFalse(beijing_day_one["has_price_limit"])
        self.assertTrue(beijing_day_two["has_price_limit"])
        self.assertEqual(30.0, beijing_day_two["threshold_pct"])

    def test_exchange_new_stock_marker_is_a_safe_no_limit_fallback(self):
        first_day = MarketService._price_limit_rule(
            "301707",
            "N展芯",
            listing_trade_days=None,
            is_st=None,
        )
        day_two_to_five = MarketService._price_limit_rule(
            "603468",
            "C津富",
            listing_trade_days=None,
            is_st=None,
        )

        self.assertIs(first_day["has_price_limit"], False)
        self.assertIs(day_two_to_five["has_price_limit"], False)

    def test_market_pulse_withholds_full_market_limit_estimate_when_rule_coverage_is_incomplete(self):
        stocks = [
            {
                "code": "600001",
                "name": "未知上市阶段",
                "change_percent": 10.1,
                "listing_trade_days": None,
            },
            {
                "code": "001234",
                "name": "主板新股",
                "change_percent": 44.0,
                "listing_trade_days": 3,
                "is_st": False,
            },
        ]

        pulse = MarketService._build_market_pulse(stocks, 2, 0, 0)

        self.assertIsNone(pulse["limit_up_est"])
        self.assertIsNone(pulse["limit_down_est"])
        self.assertEqual(1, pulse["price_limit_rule_unknown"])
        self.assertEqual(1, pulse["price_limit_rule_excluded"])
        self.assertEqual(0, pulse["price_limit_rule_covered"])

    def test_market_pulse_counts_only_securities_with_an_active_price_limit(self):
        stocks = [
            {
                "code": "600001",
                "name": "主板股票",
                "change_percent": 10.1,
                "listing_trade_days": 100,
                "is_st": False,
            },
            {
                "code": "300001",
                "name": "创业板股票",
                "change_percent": -20.1,
                "listing_trade_days": 100,
                "is_st": False,
            },
            {
                "code": "920001",
                "name": "北交新股",
                "change_percent": 65.0,
                "listing_trade_days": 1,
                "is_st": False,
            },
        ]

        pulse = MarketService._build_market_pulse(stocks, 2, 1, 0)

        self.assertEqual(1, pulse["limit_up_est"])
        self.assertEqual(1, pulse["limit_down_est"])
        self.assertEqual(2, pulse["price_limit_rule_covered"])
        self.assertEqual(1, pulse["price_limit_rule_excluded"])
        self.assertEqual(0, pulse["price_limit_rule_unknown"])

    def test_market_overview_reads_quotes_without_listing_status_join(self):
        stocks = [
            {"code": "SH_600000", "name": "浦发银行", "change_percent": 1.0, "amount": 100_000_000},
        ]

        with (
            patch("app.services.market_service.db.get_market_indices_realtime", return_value=[]),
            patch("app.services.market_service.db.get_all_stocks_realtime", return_value=stocks) as fetch_stocks,
        ):
            overview = MarketService.get_market_overview()

        fetch_stocks.assert_called_once_with(include_listing_status=False)
        self.assertEqual(1, overview["data_status"]["stock_snapshot_count"])
        self.assertEqual(1, overview["sentiment"]["advancing"])

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
