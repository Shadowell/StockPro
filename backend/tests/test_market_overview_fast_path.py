import unittest
from unittest.mock import patch

from app.services.market_service import MarketService


class MarketOverviewFastPathTests(unittest.TestCase):
    def test_market_overview_does_not_fetch_all_stocks_when_realtime_cache_is_empty(self):
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
            patch.object(MarketService, "_fetch_main_indices", return_value=indices),
            patch.object(MarketService, "get_all_stocks") as get_all_stocks,
        ):
            overview = MarketService.get_market_overview()

        get_all_stocks.assert_not_called()
        self.assertEqual(indices, overview["indices"])
        self.assertEqual(
            {"score": 50.0, "status": "中性", "advancing": 0, "declining": 0, "unchanged": 0},
            overview["sentiment"],
        )


if __name__ == "__main__":
    unittest.main()
