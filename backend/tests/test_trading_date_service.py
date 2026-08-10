import unittest
from unittest.mock import MagicMock

from app.services.trading_date_service import TradingDateService


class TradingDateServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = TradingDateService(MagicMock())
        self.service._row = MagicMock()

    def test_weekend_is_closed_without_guessing_from_missing_calendar(self):
        self.service._row.return_value = None

        self.assertEqual(self.service.status("2026-08-09"), "closed")

    def test_missing_weekday_calendar_is_unknown(self):
        self.service._row.return_value = None

        self.assertEqual(self.service.status("2026-08-10"), "unknown")

    def test_explicit_closed_day_is_rejected_for_market_data(self):
        self.service._row.return_value = {"is_open": False}

        with self.assertRaisesRegex(ValueError, "非交易日"):
            self.service.resolve_market_data_date("2026-08-09")

    def test_default_uses_latest_published_open_day(self):
        self.service._row.return_value = {"trade_date": "2026-08-07"}

        self.assertEqual(
            self.service.resolve_market_data_date(None, on_or_before="2026-08-09"),
            "2026-08-07",
        )

    def test_unknown_weekday_is_blocked_instead_of_assumed_open(self):
        self.service._row.return_value = None

        with self.assertRaisesRegex(ValueError, "交易日历未覆盖"):
            self.service.resolve_market_data_date("2026-08-10")


if __name__ == "__main__":
    unittest.main()
