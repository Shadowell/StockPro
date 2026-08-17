import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.services.market_research_service import (
    MarketResearchService,
    SENTIMENT_KPIS,
    reset_research_context_cache,
)


class MarketTemperatureTests(unittest.TestCase):
    def setUp(self):
        self.service = MarketResearchService.__new__(MarketResearchService)

    def test_temperature_has_five_public_components(self):
        components = self.service._temperature_components({})
        self.assertEqual(set(components), {"breadth", "limit_ecology", "momentum_continuity", "loss_risk", "liquidity_participation"})

    def test_missing_component_remains_none(self):
        components = self.service._temperature_components({"seal_rate": {"value": 80}})
        self.assertIsNone(components["breadth"]["value"])
        self.assertIsNone(components["liquidity_participation"]["value"])

    def test_seal_rate_is_clamped_to_one_hundred(self):
        components = self.service._temperature_components({"seal_rate": {"value": 120}})
        self.assertEqual(components["limit_ecology"]["value"], 100)

    def test_highest_board_normalises_against_ten(self):
        components = self.service._temperature_components({"highest_board": {"value": 6}})
        self.assertEqual(components["momentum_continuity"]["value"], 60)

    def test_loss_risk_decreases_with_limit_down_count(self):
        components = self.service._temperature_components({"limit_down_count": {"value": 10}})
        self.assertEqual(components["loss_risk"]["value"], 80)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(self.service.temperature_weights.values()), 1.0)


class MarketEvidenceDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.service = MarketResearchService.__new__(MarketResearchService)

    def test_kpi_contract_has_twelve_metrics(self):
        self.assertEqual(len(SENTIMENT_KPIS), 12)

    def test_seal_rate_numerator_is_limit_up_count(self):
        value = self.service._numerator("seal_rate", {"limit_up_count": {"value": 56}})
        self.assertEqual(value, 56)

    def test_seal_rate_denominator_includes_broken_boards(self):
        value = self.service._denominator("seal_rate", {"limit_up_count": {"value": 56}, "broken_board_count": {"value": 9}})
        self.assertEqual(value, 65)

    def test_mixed_sources_are_labelled_mixed(self):
        self.assertEqual(self.service._single_source([{"source_label": "tushare"}, {"source_label": "akshare"}]), "mixed")

    def test_stale_detection_uses_36_hour_boundary(self):
        self.assertFalse(self.service._is_stale(datetime.now(timezone.utc) - timedelta(hours=2)))
        self.assertTrue(self.service._is_stale(datetime.now(timezone.utc) - timedelta(hours=40)))

    def test_latest_research_context_exposes_snapshot_freshness(self):
        reset_research_context_cache()
        self.service._latest_snapshot = MagicMock(return_value={
            "id": 7,
            "status": "published",
            "snapshot_type": "post_close",
            "captured_at": datetime(2025, 1, 2, tzinfo=timezone.utc),
        })
        self.service.sentiment = MagicMock(return_value={"metrics": []})
        self.service.limit_ecosystem = MagicMock(return_value={})
        self.service.sector_evidence = MagicMock(return_value={})
        self.service._comparisons = MagicMock(return_value=[])
        self.service._evidence_summary = MagicMock(return_value={})
        self.service._rows = MagicMock(return_value=[])

        result = self.service.research_context(market_scope="all_a")

        self.assertEqual("stale", result["snapshot"]["freshness"])
        self.assertEqual("盘后", result["snapshot"]["session_label"])

    def test_evidence_summary_separates_facts_and_inferences(self):
        sentiment = {"metrics": [{"metric_code": "limit_up_count", "value": 56}, {"metric_code": "seal_rate", "value": 80}]}
        result = self.service._evidence_summary({"id": 1}, sentiment, {"highest_board": 6})
        self.assertEqual(result["evidence_snapshot_id"], 1)
        self.assertTrue(all("evidence_ref" in item for item in result["facts"]))
        self.assertTrue(all("basis" in item for item in result["inferences"]))

    def test_cohort_definition_only_promotes_adjacent_or_higher_level(self):
        self.service._rows = MagicMock(return_value=[{"symbol": "A", "limit_times": 1}, {"symbol": "B", "limit_times": 1}])
        rows = self.service._cohorts(1, [{"symbol": "A", "limit_times": 2}, {"symbol": "B", "limit_times": 1}])
        self.assertEqual(rows[0]["cohort_size"], 2)
        self.assertEqual(rows[0]["promoted_count"], 1)
        self.assertEqual(rows[0]["eliminated_count"], 1)

    def test_comparisons_use_only_the_latest_snapshot_for_each_trade_date(self):
        self.service._rows = MagicMock(return_value=[])

        self.service._comparisons(
            {"market_scope": "all_a", "snapshot_type": "post_close", "trade_date": "2025-01-02"},
            {"metrics": []},
        )

        query = self.service._rows.call_args.args[0]
        self.assertIn("DISTINCT ON (trade_date)", query)

    def test_comparisons_batch_metric_reads_for_long_history(self):
        history = [{"id": 300 - index, "trade_date": f"2024-01-{(index % 28) + 1:02d}"} for index in range(242)]

        def fake_rows(query, params=()):
            if "DISTINCT ON" in query:
                return history
            snapshot_ids = list(params[0])
            rows = []
            for snapshot_id in snapshot_ids:
                rows.append({"snapshot_id": snapshot_id, "metric_code": "limit_up_count", "value": 50})
                rows.append({"snapshot_id": snapshot_id, "metric_code": "highest_board", "value": 5})
            return rows

        self.service._rows = MagicMock(side_effect=fake_rows)
        self.service.sentiment = MagicMock(side_effect=AssertionError("must not load sentiment per snapshot"))

        result = self.service._comparisons(
            {"market_scope": "all_a", "snapshot_type": "post_close", "trade_date": "2025-01-02"},
            {"metrics": [
                {"metric_code": "limit_up_count", "value": 56},
                {"metric_code": "highest_board", "value": 6},
            ]},
        )

        self.assertLessEqual(self.service._rows.call_count, 2)
        day_over_day = next(item for item in result if item["comparison_code"] == "day_over_day")
        self.assertEqual(day_over_day["deltas"]["limit_up_count"], 6.0)
        percentile = next(item for item in result if item["comparison_code"] == "one_year_percentile")
        self.assertEqual(percentile["publication_state"], "published")
        self.assertEqual(percentile["value"], 1.0)

    def test_session_reuses_one_connection_for_nested_reads(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [{"id": 1}]
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        connection.cursor.return_value.__exit__.return_value = False
        database = MagicMock()
        database.get_connection.return_value.__enter__.return_value = connection
        database.get_connection.return_value.__exit__.return_value = False
        self.service.database = database

        with self.service._session():
            first = self.service._rows("SELECT 1")
            second = self.service._rows("SELECT 2")

        self.assertEqual(first, [{"id": 1}])
        self.assertEqual(second, [{"id": 1}])
        self.assertEqual(database.get_connection.call_count, 1)
        self.assertEqual(cursor.execute.call_count, 2)


if __name__ == "__main__":
    unittest.main()
