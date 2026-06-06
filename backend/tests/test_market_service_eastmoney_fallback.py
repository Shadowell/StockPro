import unittest
from unittest.mock import patch

from app.services.market_service import MarketService


class FakeEastMoneyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class MarketServiceEastMoneyFallbackTests(unittest.TestCase):
    def setUp(self):
        MarketService._get_cached_all_stocks.clear_cache()

    def tearDown(self):
        MarketService._get_cached_all_stocks.clear_cache()

    def test_all_stocks_uses_direct_eastmoney_fallback_when_akshare_spot_fails(self):
        payload = {
            "data": {
                "total": 1,
                "diff": [
                    {
                        "f2": 12.34,
                        "f3": 5.67,
                        "f5": 1000,
                        "f6": 1234000,
                        "f7": 8.9,
                        "f8": 1.23,
                        "f9": 18.5,
                        "f10": 1.1,
                        "f12": "600000",
                        "f14": "浦发银行",
                        "f20": 123000000,
                        "f21": 120000000,
                        "f23": 0.9,
                    }
                ],
            }
        }

        with (
            patch("app.services.market_service.ak.stock_zh_a_spot_em", side_effect=RuntimeError("blocked")),
            patch("app.services.market_service.ak.stock_hot_rank_em", side_effect=RuntimeError("blocked")),
            patch("app.services.market_service.ak.stock_zh_a_spot", side_effect=RuntimeError("blocked")),
            patch("requests.get", return_value=FakeEastMoneyResponse(payload)) as get,
        ):
            stocks = MarketService.get_all_stocks()

        self.assertEqual(1, len(stocks))
        self.assertEqual("600000", stocks[0]["code"])
        self.assertEqual("浦发银行", stocks[0]["name"])
        self.assertEqual(12.34, stocks[0]["price"])
        self.assertEqual(5.67, stocks[0]["change_percent"])
        get.assert_called()

    def test_all_stocks_does_not_call_slow_sina_spot_when_fast_sources_fail(self):
        with (
            patch("app.services.market_service.ak.stock_zh_a_spot_em", side_effect=RuntimeError("blocked")),
            patch("app.services.market_service._fetch_eastmoney_a_spot_direct", side_effect=RuntimeError("blocked")),
            patch("app.services.market_service.ak.stock_hot_rank_em", side_effect=RuntimeError("blocked")),
            patch("app.services.market_service.ak.stock_zh_a_spot") as slow_sina,
        ):
            stocks = MarketService.get_all_stocks()

        self.assertEqual([], stocks)
        slow_sina.assert_not_called()


if __name__ == "__main__":
    unittest.main()
