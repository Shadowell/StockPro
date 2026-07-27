import sys
import types
import unittest
from unittest.mock import Mock

import pandas as pd


class TushareProviderTests(unittest.TestCase):
    def test_stock_spot_uses_tushare_realtime_quote_before_akshare(self):
        from app.services.tushare_provider import TushareFirstDataProvider

        tushare = types.SimpleNamespace()
        tushare.set_token = Mock()
        tushare.realtime_quote = Mock(
            return_value=pd.DataFrame(
                [
                    {
                        "TS_CODE": "600000.SH",
                        "NAME": "浦发银行",
                        "PRICE": 10.1,
                        "OPEN": 9.9,
                        "HIGH": 10.3,
                        "LOW": 9.8,
                        "PRE_CLOSE": 9.98,
                        "PCT_CHANGE": 1.2,
                        "VOL": 1000,
                        "AMOUNT": 10100,
                    }
                ]
            )
        )
        akshare = types.SimpleNamespace(stock_zh_a_spot_em=Mock(return_value=pd.DataFrame()))

        provider = TushareFirstDataProvider(tushare_module=tushare, akshare_module=akshare, token="token")
        df = provider.stock_zh_a_spot_em()

        self.assertEqual(df.iloc[0]["代码"], "600000")
        self.assertEqual(df.iloc[0]["名称"], "浦发银行")
        self.assertEqual(df.iloc[0]["最新价"], 10.1)
        self.assertEqual(df.iloc[0]["今开"], 9.9)
        self.assertEqual(df.iloc[0]["最高"], 10.3)
        self.assertEqual(df.iloc[0]["最低"], 9.8)
        self.assertEqual(df.iloc[0]["昨收"], 9.98)
        tushare.realtime_quote.assert_called_once()
        akshare.stock_zh_a_spot_em.assert_not_called()

    def test_stock_history_falls_back_to_akshare_when_tushare_has_no_token(self):
        from app.services.tushare_provider import TushareFirstDataProvider

        akshare = types.SimpleNamespace(
            stock_zh_a_hist=Mock(
                return_value=pd.DataFrame(
                    [{"日期": "2026-06-08", "开盘": 10, "收盘": 11, "最高": 11.2, "最低": 9.8}]
                )
            )
        )
        provider = TushareFirstDataProvider(tushare_module=types.SimpleNamespace(), akshare_module=akshare, token="")

        df = provider.stock_zh_a_hist(symbol="600000", period="daily", start_date="20260601", end_date="20260608")

        self.assertEqual(df.iloc[0]["收盘"], 11)
        akshare.stock_zh_a_hist.assert_called_once()

    def test_missing_tushare_method_delegates_to_akshare(self):
        from app.services.tushare_provider import TushareFirstDataProvider

        akshare = types.SimpleNamespace(stock_board_concept_name_em=Mock(return_value=pd.DataFrame([{"名称": "AI"}])))
        provider = TushareFirstDataProvider(tushare_module=types.SimpleNamespace(), akshare_module=akshare, token="token")

        df = provider.stock_board_concept_name_em()

        self.assertEqual(df.iloc[0]["名称"], "AI")
        akshare.stock_board_concept_name_em.assert_called_once()

    def test_history_with_source_reports_akshare_when_tushare_is_not_ready(self):
        from app.services.tushare_provider import TushareFirstDataProvider

        akshare = types.SimpleNamespace(
            stock_zh_a_hist=Mock(return_value=pd.DataFrame([{"日期": "2026-07-15", "收盘": 10.0}]))
        )
        provider = TushareFirstDataProvider(tushare_module=types.SimpleNamespace(), akshare_module=akshare, token="")

        frame, source, fallback_reason = provider.stock_zh_a_hist_with_source(
            symbol="600000", period="daily", start_date="20260715", end_date="20260715"
        )

        self.assertEqual(len(frame), 1)
        self.assertEqual(source, "akshare")
        self.assertEqual(fallback_reason, "tushare_not_ready")


if __name__ == "__main__":
    unittest.main()
