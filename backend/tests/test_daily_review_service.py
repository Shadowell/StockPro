import unittest
from datetime import datetime
from unittest.mock import MagicMock

from app.services.daily_review_service import DailyReviewService


class DailyReviewUnitTests(unittest.TestCase):
    def setUp(self):
        self.service = DailyReviewService.__new__(DailyReviewService)
        self.service.database = MagicMock()

    def test_date_accepts_iso_day(self):
        self.assertEqual(self.service._date("2025-01-02T15:00:00"), "2025-01-02")

    def test_date_rejects_invalid_value(self):
        with self.assertRaises(ValueError):
            self.service._date("2025-13-99")

    def test_trade_time_uses_asia_shanghai_offset(self):
        value = self.service._trade_time("2025-01-02", "17:30:00")
        self.assertEqual(value.utcoffset().total_seconds(), 8 * 3600)

    def test_counts_groups_timeline_categories(self):
        result = self.service._counts([{"category": "risk"}, {"category": "risk"}, {"category": "trade"}])
        self.assertEqual(result, {"risk": 2, "trade": 1})

    def test_add_builds_deterministic_source_reference(self):
        items = []
        self.service._add(items, datetime.fromisoformat("2025-01-02T15:00:00+08:00"), "market", "市场", "摘要", "market_evidence_snapshot", 3, "/market", {"hash": "abc"})
        self.assertEqual(items[0]["source_object_id"], "3")
        self.assertEqual(len(items[0]["evidence_hash"]), 64)

    def test_add_same_object_has_same_item_key(self):
        first, second = [], []
        args = (datetime.fromisoformat("2025-01-02T15:00:00+08:00"), "pool", "池", None, "stock_pool_snapshot", 4, "/pools", {})
        self.service._add(first, *args)
        self.service._add(second, *args)
        self.assertEqual(first[0]["item_key"], second[0]["item_key"])

    def test_json_dumps_handles_decimal_like_values(self):
        class Value:
            def __str__(self):
                return "1.23"
        self.assertIn("1.23", self.service._json_dumps({"value": Value()}))

    def test_resolve_rejects_unknown_object_type(self):
        result = self.service.resolve("unknown", "1")
        self.assertEqual(result["status"], "unavailable")

    def test_resolve_reports_archived_missing_object(self):
        self.service._row = MagicMock(return_value=None)
        result = self.service.resolve("order", "11111111-1111-1111-1111-111111111111")
        self.assertEqual(result["status"], "archived")

    def test_available_dates_are_normalized(self):
        self.service._rows = MagicMock(return_value=[{"trade_date": "2025-01-02"}, {"trade_date": "2024-12-31"}])
        self.assertEqual(self.service.available_dates(), ["2025-01-02", "2024-12-31"])

    def test_sealed_context_reads_persisted_evidence(self):
        review = {"id": "review-1", "trade_date": "2025-01-02", "status": "sealed"}
        self.service._row = MagicMock(return_value=review)
        self.service._stored = MagicMock(return_value={"status": "sealed"})
        self.assertEqual(self.service.context("2025-01-02")["status"], "sealed")

    def test_save_rejects_sealed_review(self):
        self.service._row = MagicMock(return_value={"id": "review-1", "status": "sealed"})
        with self.assertRaisesRegex(ValueError, "不可修改"):
            self.service.save("2025-01-02", {"summary": "changed"})


if __name__ == "__main__":
    unittest.main()
