import unittest

from app.services.reference_dataset_sync_service import (
    normalise_adjustment_factor_rows,
    normalise_benchmark_bar_rows,
    normalise_corporate_action_rows,
    normalise_daily_valuation_rows,
    normalise_price_limit_rows,
    normalise_security_master_rows,
    normalise_suspension_rows,
    normalise_trade_calendar_rows,
    provider_ts_code,
)


class ReferenceDatasetNormalisationTests(unittest.TestCase):
    def test_provider_ts_code_accepts_internal_and_tushare_symbols(self):
        self.assertEqual(provider_ts_code("SH_600000"), "600000.SH")
        self.assertEqual(provider_ts_code("000001.SZ"), "000001.SZ")
        self.assertEqual(provider_ts_code("BJ_920116"), "920116.BJ")

    def test_provider_ts_code_rejects_ambiguous_symbol(self):
        with self.assertRaisesRegex(ValueError, "无法规范化证券代码"):
            provider_ts_code("INVALID")

    def test_security_master_preserves_listing_state_and_normalises_symbols(self):
        rows, issues = normalise_security_master_rows(
            [
                {
                    "ts_code": "600000.SH",
                    "name": "浦发银行",
                    "list_status": "L",
                    "list_date": "19991110",
                    "industry": "银行",
                },
                {
                    "ts_code": "430047.BJ",
                    "name": "诺思兰德",
                    "list_status": "L",
                    "list_date": "20201116",
                },
                {
                    "ts_code": "T600018.SH",
                    "name": "历史退市证券",
                    "list_status": "D",
                },
                {
                    "ts_code": "920116.BJ",
                    "name": "北交所证券",
                    "list_status": "L",
                },
            ],
            "2025-01-02",
        )

        self.assertEqual(issues, [])
        self.assertEqual(rows[0]["symbol"], "SH_600000")
        self.assertEqual(rows[0]["list_date"], "1999-11-10")
        self.assertEqual(rows[1]["symbol"], "BJ_430047")
        self.assertEqual(rows[1]["as_of_date"], "2025-01-02")
        self.assertEqual(rows[2]["symbol"], "SH_T600018")
        self.assertEqual(rows[3]["symbol"], "BJ_920116")

    def test_security_master_blocks_unknown_code_and_duplicate(self):
        _, issues = normalise_security_master_rows(
            [
                {"ts_code": "UNKNOWN", "list_status": "L"},
                {"ts_code": "000001.SZ", "list_status": "L"},
                {"ts_code": "000001.SZ", "list_status": "L"},
            ],
            "2025-01-02",
        )

        self.assertEqual({issue["check_code"] for issue in issues}, {"invalid_security_symbol", "duplicate_security_master"})
        self.assertTrue(all(issue["severity"] == "blocking" for issue in issues))

    def test_trade_calendar_uses_explicit_open_flag_and_requested_date(self):
        rows, issues = normalise_trade_calendar_rows(
            [{"exchange": "SSE", "cal_date": "20250102", "is_open": "1", "pretrade_date": "20241231"}],
            "2025-01-02",
        )

        self.assertEqual(issues, [])
        self.assertEqual(rows[0]["trade_date"], "2025-01-02")
        self.assertTrue(rows[0]["is_open"])
        self.assertEqual(rows[0]["pretrade_date"], "2024-12-31")

    def test_trade_calendar_blocks_missing_requested_day(self):
        _, issues = normalise_trade_calendar_rows(
            [{"exchange": "SSE", "cal_date": "20250103", "is_open": "1"}],
            "2025-01-02",
        )

        self.assertTrue(any(issue["check_code"] == "missing_requested_calendar_day" for issue in issues))

    def test_adjustment_factor_requires_positive_finite_value(self):
        rows, issues = normalise_adjustment_factor_rows(
            [
                {"ts_code": "600000.SH", "trade_date": "20250102", "adj_factor": 12.5},
                {"ts_code": "000001.SZ", "trade_date": "20250102", "adj_factor": "nan"},
            ],
            "2025-01-02",
        )

        self.assertEqual(rows[0]["adj_factor"], 12.5)
        self.assertTrue(any(issue["check_code"] == "invalid_adj_factor" for issue in issues))

    def test_daily_valuation_preserves_optional_nulls(self):
        rows, issues = normalise_daily_valuation_rows(
            [{
                "ts_code": "600000.SH",
                "trade_date": "20250102",
                "close": 10.2,
                "turnover_rate": 0.8,
                "pe": None,
                "limit_status": 1,
            }],
            "2025-01-02",
        )

        self.assertEqual(issues, [])
        self.assertIsNone(rows[0]["pe"])
        self.assertEqual(rows[0]["limit_status"], 1)

    def test_suspension_accepts_known_empty_day_and_rejects_unknown_type(self):
        empty_rows, empty_issues = normalise_suspension_rows([], "2025-01-02")
        _, invalid_issues = normalise_suspension_rows(
            [{"ts_code": "000001.SZ", "trade_date": "20250102", "suspend_type": "X"}],
            "2025-01-02",
        )

        self.assertEqual((empty_rows, empty_issues), ([], []))
        self.assertTrue(any(issue["check_code"] == "invalid_suspend_type" for issue in invalid_issues))

    def test_price_limit_checks_order_and_duplicates(self):
        rows, issues = normalise_price_limit_rows(
            [
                {"ts_code": "000001.SZ", "trade_date": "20250102", "pre_close": 10, "up_limit": 9, "down_limit": 11},
                {"ts_code": "000001.SZ", "trade_date": "20250102", "pre_close": 10, "up_limit": 11, "down_limit": 9},
            ],
            "2025-01-02",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual({issue["check_code"] for issue in issues}, {"inverted_price_limits", "duplicate_price_limit"})

    def test_price_limit_maps_no_limit_sentinel_to_explicit_state(self):
        rows, issues = normalise_price_limit_rows(
            [{"ts_code": "920116.BJ", "trade_date": "20250102", "pre_close": 6.92, "up_limit": 99999.99, "down_limit": 0}],
            "2025-01-02",
        )

        self.assertEqual(issues, [])
        self.assertEqual(rows[0]["symbol"], "BJ_920116")
        self.assertFalse(rows[0]["has_price_limit"])
        self.assertIsNone(rows[0]["up_limit"])
        self.assertEqual(rows[0]["source_up_limit"], 99999.99)

    def test_benchmark_bar_enforces_ohlc_and_requested_day(self):
        rows, issues = normalise_benchmark_bar_rows(
            [{
                "ts_code": "000300.SH",
                "trade_date": "20250102",
                "open": 3900,
                "high": 3890,
                "low": 3880,
                "close": 3895,
                "pre_close": 3910,
                "vol": 100,
                "amount": 1000,
            }],
            "2025-01-02",
        )

        self.assertEqual(rows[0]["symbol"], "SH_000300")
        self.assertTrue(any(issue["check_code"] == "illegal_benchmark_ohlc" for issue in issues))

    def test_corporate_action_uses_announcement_availability_and_nulls(self):
        rows, issues = normalise_corporate_action_rows(
            [{
                "ts_code": "600000.SH",
                "end_date": "20241231",
                "ann_date": "20241220",
                "imp_ann_date": "20241227",
                "div_proc": "实施",
                "stk_div": 0.1,
                "cash_div": None,
                "cash_div_tax": 0.2,
                "ex_date": "20250102",
            }],
            "2025-01-02",
        )

        self.assertEqual(issues, [])
        self.assertEqual(rows[0]["symbol"], "SH_600000")
        self.assertEqual(rows[0]["announcement_available_at"], "2024-12-27T09:00:00+08:00")
        self.assertIsNone(rows[0]["cash_div"])

    def test_corporate_action_blocks_missing_availability(self):
        _, issues = normalise_corporate_action_rows(
            [{"ts_code": "000001.SZ", "ex_date": "20250102", "stk_div": 0}],
            "2025-01-02",
        )

        self.assertTrue(any(issue["check_code"] == "missing_corporate_action_availability" for issue in issues))


if __name__ == "__main__":
    unittest.main()
