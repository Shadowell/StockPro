import unittest
from unittest.mock import Mock, patch

from app.core.config import settings
from app.services.market_service import MarketService


class CacheOnlyDb:
    def __init__(self):
        self.hot_concepts = [
            {"rank": 1, "name": "人工智能", "change_percent": 2.5, "net_inflow": 1200.0}
        ]
        self.ths_hot = [
            {"rank": 1, "code": "600000", "name": "浦发银行", "hot": 99.0, "change_percent": 1.2}
        ]

    def get_hot_concepts_realtime(self, limit):
        return self.hot_concepts[:limit]

    def get_hot_concepts_history(self, trade_date):
        return []

    def get_ths_hot_realtime(self, limit):
        return self.ths_hot[:limit]

    def get_ths_hot_history(self, trade_date):
        return []


def test_hot_concepts_page_path_reads_pg_cache_without_external_fetch():
    fake_db = CacheOnlyDb()

    with (
        patch("app.services.market_service.db", fake_db),
        patch.object(MarketService, "_get_cached_hot_concepts", side_effect=AssertionError("external fetch")),
    ):
        result = MarketService.get_hot_concepts(limit=10)

    assert result == fake_db.hot_concepts


def test_ths_hot_page_path_reads_pg_cache_without_external_fetch():
    fake_db = CacheOnlyDb()

    with (
        patch("app.services.market_service.db", fake_db),
        patch("app.services.market_service.ak.stock_hot_rank_em", side_effect=AssertionError("external fetch")),
    ):
        result = MarketService.get_ths_hot(limit=10)

    assert result == fake_db.ths_hot


def test_news_page_path_returns_db_rows_without_triggering_sync():
    fake_db = Mock()
    fake_db.get_news_stream.return_value = [
        {
            "source": "cls",
            "publish_time": "2026-06-08T10:00:00",
            "title": "市场快讯",
            "content": "市场快讯内容",
        }
    ]

    with (
        patch("app.db.db_instance", fake_db),
        patch("app.services.data_sync_service.data_sync_service.sync_news", side_effect=AssertionError("external sync")),
    ):
        result = MarketService._get_news_from_db_or_api("cls", 50)

    assert len(result) == 1
    assert result[0]["title"] == "市场快讯"


class HotConceptFallbackTests(unittest.TestCase):
    def tearDown(self):
        MarketService._get_cached_hot_concepts.clear_cache()

    def test_hot_concepts_fetches_and_persists_external_rows_when_pg_cache_is_empty(self):
        fake_db = Mock()
        fake_db.get_hot_concepts_realtime.return_value = []
        fake_db.get_hot_concepts_history.return_value = []
        external_rows = [
            {"rank": 1, "name": "存储芯片", "change_percent": 3.12, "inflow": 10.0, "outflow": 3.0, "net_inflow": 7.0},
            {"rank": 2, "name": "中芯国际概念", "change_percent": 2.8, "inflow": 8.0, "outflow": 9.0, "net_inflow": -1.0},
        ]

        with (
            patch("app.services.market_service.db", fake_db),
            patch.object(settings, "ENABLE_EXTERNAL_MARKET_FETCH", True),
            patch.object(MarketService, "_get_cached_hot_concepts", return_value=external_rows) as external_fetch,
        ):
            result = MarketService.get_hot_concepts(limit=1)

        self.assertEqual(external_rows[:1], result)
        external_fetch.assert_called_once()
        fake_db.update_hot_concepts_realtime.assert_called_once_with(external_rows)
        fake_db.insert_hot_concepts_history.assert_called_once()

    def test_hot_concepts_returns_empty_when_pg_cache_is_empty_and_external_fetch_is_disabled(self):
        fake_db = Mock()
        fake_db.get_hot_concepts_realtime.return_value = []
        fake_db.get_hot_concepts_history.return_value = []

        with (
            patch("app.services.market_service.db", fake_db),
            patch.object(settings, "ENABLE_EXTERNAL_MARKET_FETCH", False),
            patch.object(MarketService, "_get_cached_hot_concepts", side_effect=AssertionError("external fetch")),
        ):
            result = MarketService.get_hot_concepts(limit=10)

        self.assertEqual([], result)
