import types
import unittest
from unittest.mock import Mock

import pandas as pd

from app.services.tushare_catalog_service import (
    CATALOG_BY_CODE,
    TushareCatalogService,
    build_limit_ecology,
    build_market_breadth,
    normalise_limit_pool_rows,
)


class TushareCatalogTests(unittest.TestCase):
    def test_short_line_baseline_and_restricted_extensions_are_explicit(self):
        self.assertEqual(CATALOG_BY_CODE["limit_list_d"].required_credits, 5000)
        self.assertEqual(CATALOG_BY_CODE["kpl_list"].required_credits, 5000)
        self.assertEqual(CATALOG_BY_CODE["ths_hot"].required_credits, 6000)
        self.assertEqual(CATALOG_BY_CODE["limit_step"].required_credits, 8000)
        self.assertEqual(CATALOG_BY_CODE["limit_step"].baseline_state, "restricted")

    def test_limit_ecology_uses_tushare_limit_times_for_ladder(self):
        up_rows = normalise_limit_pool_rows(
            [
                {"ts_code": "000001.SZ", "name": "平安银行", "limit_times": 1},
                {"ts_code": "600000.SH", "name": "浦发银行", "limit_times": 2},
                {"ts_code": "300001.SZ", "name": "特锐德", "limit_times": 5},
            ],
            "up",
            "tushare_limit_list_d",
        )
        metrics = {item["metric_code"]: item["value"] for item in build_limit_ecology(up_rows, [], [{"symbol": "x"}])}

        self.assertEqual(metrics["limit_up_count"], 3.0)
        self.assertEqual(metrics["broken_board_count"], 1.0)
        self.assertEqual(metrics["ladder_1_board_count"], 1.0)
        self.assertEqual(metrics["ladder_2_board_count"], 1.0)
        self.assertEqual(metrics["ladder_5_plus_board_count"], 1.0)
        self.assertEqual(metrics["highest_board"], 5.0)
        self.assertEqual(metrics["seal_rate"], 75.0)

    def test_provider_catalog_call_does_not_fall_back_to_akshare(self):
        from app.services.tushare_provider import TushareFirstDataProvider

        pro = types.SimpleNamespace(limit_list_d=Mock(return_value=pd.DataFrame([{"ts_code": "600000.SH"}])))
        tushare = types.SimpleNamespace(set_token=Mock(), pro_api=Mock(return_value=pro))
        akshare = types.SimpleNamespace(stock_zt_pool_em=Mock())
        provider = TushareFirstDataProvider(tushare_module=tushare, akshare_module=akshare, token="token")

        frame = provider.fetch_pro_endpoint("limit_list_d", trade_date="20260716", limit_type="U")

        self.assertEqual(frame.iloc[0]["ts_code"], "600000.SH")
        pro.limit_list_d.assert_called_once_with(trade_date="20260716", limit_type="U")
        akshare.stock_zt_pool_em.assert_not_called()

    def test_market_breadth_excludes_b_shares_and_keeps_missing_changes_unavailable(self):
        metrics = {
            item["metric_code"]: item["value"]
            for item in build_market_breadth(
                [
                    {"ts_code": "600000.SH", "pct_chg": 1.5},
                    {"ts_code": "000001.SZ", "pct_chg": -0.5},
                    {"ts_code": "300001.SZ", "pct_chg": 0},
                    {"ts_code": "200001.SZ", "pct_chg": 3.0},
                    {"ts_code": "601000.SH"},
                ]
            )
        }

        self.assertEqual(metrics["rise_count"], 1.0)
        self.assertEqual(metrics["fall_count"], 1.0)
        self.assertEqual(metrics["flat_count"], 1.0)
        self.assertAlmostEqual(metrics["red_market_ratio"], 100 / 3)
        self.assertEqual(metrics["rise_fall_ratio"], 1.0)

    def test_market_evidence_sync_persists_daily_breadth_metrics(self):
        service = TushareCatalogService.__new__(TushareCatalogService)
        service.provider = Mock()
        service.provider.is_tushare_ready.return_value = True

        def fetch(endpoint_code, **params):
            if endpoint_code == "daily":
                return pd.DataFrame([
                    {"ts_code": "600000.SH", "pct_chg": 1.0},
                    {"ts_code": "000001.SZ", "pct_chg": -1.0},
                ])
            if endpoint_code == "kpl_list":
                return pd.DataFrame()
            if endpoint_code == "limit_list_d":
                return pd.DataFrame()
            raise AssertionError(endpoint_code)

        service.provider.fetch_pro_endpoint.side_effect = fetch
        service._store_market_evidence_snapshot = Mock(return_value=(2, True))

        result = service.sync_market_evidence("2025-01-02")

        metrics = {item["metric_code"]: item for item in result["metrics"]}
        self.assertEqual(metrics["rise_count"]["value"], 1.0)
        self.assertEqual(metrics["fall_count"]["value"], 1.0)
        self.assertEqual(metrics["rise_count"]["source_label"], "tushare_daily")
        self.assertEqual(result["sources"]["market_breadth"], "tushare_daily")
        self.assertNotIn("market_breadth", result["errors"])


if __name__ == "__main__":
    unittest.main()
