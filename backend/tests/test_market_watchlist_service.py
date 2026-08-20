import unittest

from app.services.market_watchlist_service import MarketWatchlistService


class MarketWatchlistServiceTests(unittest.TestCase):
    def test_symbol_key_accepts_public_and_internal_a_share_formats(self):
        self.assertEqual("600519", MarketWatchlistService.symbol_key("600519.SH"))
        self.assertEqual("600519", MarketWatchlistService.symbol_key("SH_600519"))

    def test_invalid_symbol_is_rejected_before_database_write(self):
        with self.assertRaisesRegex(ValueError, "证券代码"):
            MarketWatchlistService.validate_symbol("not-a-stock")

    def test_note_length_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "备注"):
            MarketWatchlistService.validate_note("x" * 201)


if __name__ == "__main__":
    unittest.main()
