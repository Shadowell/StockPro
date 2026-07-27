import unittest


class DatasetSnapshotValidationTests(unittest.TestCase):
    def test_valid_daily_bars_have_no_blocking_issue(self):
        from app.services.dataset_snapshot_service import validate_daily_bar_rows

        issues = validate_daily_bar_rows([
            {
                "symbol": "SH_600000",
                "trade_date": "2026-07-15",
                "open": 10.0,
                "high": 10.8,
                "low": 9.9,
                "close": 10.5,
                "volume": 1000,
                "turnover": 10500,
            }
        ])

        self.assertEqual(issues, [])

    def test_illegal_ohlc_and_negative_turnover_block_publication(self):
        from app.services.dataset_snapshot_service import validate_daily_bar_rows

        issues = validate_daily_bar_rows([
            {
                "symbol": "SH_600000",
                "trade_date": "2026-07-15",
                "open": 10.0,
                "high": 9.0,
                "low": 9.5,
                "close": 10.5,
                "volume": 1000,
                "turnover": -1,
            }
        ])

        self.assertTrue(any(item["check_code"] == "illegal_ohlc" for item in issues))
        self.assertTrue(any(item["check_code"] == "negative_volume_or_turnover" for item in issues))
        self.assertTrue(all(item["severity"] == "blocking" for item in issues))

    def test_canonical_hash_is_order_independent_for_mapping_keys(self):
        from app.services.dataset_snapshot_service import canonical_hash

        self.assertEqual(canonical_hash({"b": 2, "a": 1}), canonical_hash({"a": 1, "b": 2}))


if __name__ == "__main__":
    unittest.main()
