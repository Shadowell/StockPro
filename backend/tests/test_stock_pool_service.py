import json
import unittest
from unittest.mock import MagicMock

from app.services.dataset_snapshot_service import canonical_hash
from app.services.stock_pool_service import GENERATOR_VERSION, StockPoolService


class StockPoolNormalisationTests(unittest.TestCase):
    def test_internal_symbol_preserves_stockpro_format(self):
        self.assertEqual(StockPoolService._internal_symbol("SH_600519"), "SH_600519")

    def test_internal_symbol_converts_tushare_shanghai(self):
        self.assertEqual(StockPoolService._internal_symbol("600519.SH"), "SH_600519")

    def test_internal_symbol_converts_tushare_shenzhen(self):
        self.assertEqual(StockPoolService._internal_symbol("000333.SZ"), "SZ_000333")

    def test_internal_symbol_infers_beijing(self):
        self.assertEqual(StockPoolService._internal_symbol("830799"), "BJ_830799")

    def test_internal_symbol_infers_shanghai(self):
        self.assertEqual(StockPoolService._internal_symbol("601398"), "SH_601398")

    def test_board_classifies_main_board(self):
        self.assertEqual(StockPoolService._board("SH_600519"), "main_board")

    def test_board_classifies_chinext(self):
        self.assertEqual(StockPoolService._board("SZ_300750"), "chinext")

    def test_board_classifies_star(self):
        self.assertEqual(StockPoolService._board("SH_688981"), "star")

    def test_board_classifies_beijing(self):
        self.assertEqual(StockPoolService._board("BJ_830799"), "beijing")

    def test_json_dumps_is_deterministic_and_datetime_safe(self):
        value = {"b": 2, "a": object()}
        first = StockPoolService._json_dumps(value)
        second = StockPoolService._json_dumps(value)
        self.assertEqual(first, second)
        self.assertEqual(list(json.loads(first)), ["a", "b"])

    def test_generator_version_is_explicit(self):
        self.assertEqual(GENERATOR_VERSION, "stock-pool-generator.v1")


class StockPoolFilterTests(unittest.TestCase):
    def setUp(self):
        self.service = StockPoolService.__new__(StockPoolService)
        self.service.datasets = MagicMock()
        self.service._rows = MagicMock(return_value=[])
        self.universe = {
            "id": 1,
            "manifest_hash": "universe-hash",
            "members": [
                {"symbol": "SH_600519", "eligibility_flags": {"listed": True, "is_st": False, "suspended": False}},
                {"symbol": "SZ_300750", "eligibility_flags": {"listed": True, "is_st": False, "suspended": False}},
                {"symbol": "SH_600000", "eligibility_flags": {"listed": True, "is_st": True, "suspended": False}},
                {"symbol": "SZ_000001", "eligibility_flags": {"listed": True, "is_st": False, "suspended": True}},
            ],
        }
        self.dataset = {"id": 10}
        self.candidates = [
            {"symbol": symbol, "score": score, "reason": "fixture", "evidence": {}, "source_object_type": "fixture", "source_object_id": symbol}
            for symbol, score in (("600519.SH", 0.9), ("300750.SZ", 0.8), ("600000.SH", 0.7), ("000001.SZ", 0.6))
        ]

    def test_default_filters_remove_st_and_suspended(self):
        rows = self.service._apply_universe_filters(self.candidates, self.universe, self.dataset, "2025-01-02", {})
        self.assertEqual([item["symbol"] for item in rows], ["SH_600519", "SZ_300750"])

    def test_board_filter_is_enforced(self):
        rows = self.service._apply_universe_filters(self.candidates, self.universe, self.dataset, "2025-01-02", {"boards": ["chinext"]})
        self.assertEqual([item["symbol"] for item in rows], ["SZ_300750"])

    def test_top_n_has_stable_score_then_symbol_order(self):
        rows = self.service._apply_universe_filters(self.candidates, self.universe, self.dataset, "2025-01-02", {"top_n": 1})
        self.assertEqual([item["symbol"] for item in rows], ["SH_600519"])

    def test_filter_attaches_universe_evidence(self):
        rows = self.service._apply_universe_filters(self.candidates, self.universe, self.dataset, "2025-01-02", {"top_n": 1})
        self.assertEqual(rows[0]["evidence"]["universe_snapshot_id"], 1)
        self.assertEqual(rows[0]["evidence"]["universe_manifest_hash"], "universe-hash")

    def test_price_filter_uses_only_selection_date_bar(self):
        self.service.datasets.load_daily_bars.return_value = [
            {"symbol": "SH_600519", "trade_date": "2025-01-01", "close": 1, "amount": 1},
            {"symbol": "SH_600519", "trade_date": "2025-01-02", "close": 1500, "amount": 1000},
            {"symbol": "SZ_300750", "trade_date": "2025-01-02", "close": 200, "amount": 1000},
        ]
        rows = self.service._apply_universe_filters(self.candidates, self.universe, self.dataset, "2025-01-02", {"max_price": 500})
        self.assertEqual([item["symbol"] for item in rows], ["SZ_300750"])

    def test_turnover_filter_records_selection_bar_evidence(self):
        self.service.datasets.load_daily_bars.return_value = [
            {"symbol": "SH_600519", "trade_date": "2025-01-02", "close": 1500, "amount": 2000},
            {"symbol": "SZ_300750", "trade_date": "2025-01-02", "close": 200, "amount": 10},
        ]
        rows = self.service._apply_universe_filters(self.candidates, self.universe, self.dataset, "2025-01-02", {"min_turnover": 100})
        self.assertEqual([item["symbol"] for item in rows], ["SH_600519"])
        self.assertEqual(rows[0]["evidence"]["selection_bar"]["turnover"], 2000)

    def test_member_manifest_hash_is_order_sensitive(self):
        a = [{"ordinal": 1, "symbol": "A"}, {"ordinal": 2, "symbol": "B"}]
        b = list(reversed(a))
        self.assertNotEqual(canonical_hash(a), canonical_hash(b))


class StockPoolBindingGateTests(unittest.TestCase):
    def setUp(self):
        self.service = StockPoolService.__new__(StockPoolService)
        self.service.database = MagicMock()
        self.service.datasets = MagicMock()
        self.service.references = MagicMock()
        self.service.factors = MagicMock()
        self.service.get_pool = MagicMock(
            return_value={
                "id": "pool-1",
                "pool_type": "factor",
                "rule_id": "rule-1",
                "rule_version": 1,
                "rule_hash": "rule-hash",
                "config": {"factor_code": "momentum_20d"},
            }
        )
        self.service.datasets.get_snapshot.return_value = {
            "id": 10,
            "status": "sealed",
            "manifest_hash": "dataset-hash",
            "knowledge_cutoff_at": "2025-01-02T18:00:00+08:00",
            "items": [
                {
                    "dataset_code": "daily_bars",
                    "start_date": "2024-01-02",
                    "end_date": "2025-01-02",
                }
            ],
        }
        self.service.references.get_universe_snapshot.return_value = {
            "id": 1,
            "status": "sealed",
            "trade_date": "2025-01-02",
            "manifest_hash": "universe-hash",
            "knowledge_cutoff_at": "2025-01-02T18:00:00+08:00",
        }
        self.service.factors.get_factor_snapshot.return_value = {
            "id": 3,
            "status": "sealed",
            "trade_date": "2025-01-02",
            "dataset_snapshot_id": 10,
            "universe_snapshot_id": 1,
            "manifest_hash": "factor-hash",
            "knowledge_cutoff_at": "2025-01-02T18:00:00+08:00",
        }

    @staticmethod
    def _valid_generation():
        return {
            "id": "generation-1",
            "pool_id": "pool-1",
            "status": "success",
            "dataset_snapshot_id": 10,
            "universe_snapshot_id": 1,
            "factor_snapshot_id": 3,
            "market_evidence_snapshot_id": None,
            "trade_date": "2025-01-02",
            "knowledge_cutoff_at": "2025-01-02T18:00:00+08:00",
            "input_hash": "input-hash",
            "input_manifest": {
                "dataset_snapshot_id": 10,
                "dataset_manifest_hash": "dataset-hash",
                "universe_snapshot_id": 1,
                "universe_manifest_hash": "universe-hash",
                "factor_snapshot_id": 3,
                "factor_manifest_hash": "factor-hash",
                "market_evidence_snapshot_id": None,
                "market_evidence_hash": None,
                "trade_date": "2025-01-02",
            },
            "members": [
                {
                    "ordinal": 1,
                    "symbol": "SH_600519",
                    "score": 1.0,
                    "reason": "top rank",
                    "evidence": {},
                    "evidence_hash": "evidence-hash",
                    "valid_from": "2025-01-02",
                    "valid_until": "2025-01-07",
                    "generator_version": GENERATOR_VERSION,
                }
            ],
        }

    def test_generate_rejects_universe_from_a_different_trade_date_before_writing(self):
        self.service.references.get_universe_snapshot.return_value["trade_date"] = "2025-01-03"

        with self.assertRaisesRegex(ValueError, "Universe Snapshot 日期必须与股票池交易日一致"):
            self.service.generate(
                "pool-1",
                {
                    "dataset_snapshot_id": 10,
                    "universe_snapshot_id": 1,
                    "factor_snapshot_id": 3,
                    "trade_date": "2025-01-02",
                },
            )

        self.service.database.get_connection.assert_not_called()

    def test_generate_rejects_dataset_that_does_not_cover_trade_date_before_writing(self):
        self.service.datasets.get_snapshot.return_value["items"][0]["end_date"] = "2025-01-01"

        with self.assertRaisesRegex(ValueError, "数据快照不覆盖股票池交易日"):
            self.service.generate(
                "pool-1",
                {
                    "dataset_snapshot_id": 10,
                    "universe_snapshot_id": 1,
                    "factor_snapshot_id": 3,
                    "trade_date": "2025-01-02",
                },
            )

        self.service.database.get_connection.assert_not_called()

    def test_factor_generation_requires_factor_snapshot_before_writing(self):
        with self.assertRaisesRegex(ValueError, "因子股票池必须绑定封存因子快照"):
            self.service.generate(
                "pool-1",
                {
                    "dataset_snapshot_id": 10,
                    "universe_snapshot_id": 1,
                    "trade_date": "2025-01-02",
                },
            )

        self.service.database.get_connection.assert_not_called()

    def test_seal_revalidates_generation_bindings_before_snapshot_write(self):
        self.service.references.get_universe_snapshot.return_value["trade_date"] = "2025-01-03"
        self.service.get_generation = MagicMock(return_value=self._valid_generation())

        with self.assertRaisesRegex(ValueError, "Universe Snapshot 日期必须与股票池交易日一致"):
            self.service.seal_snapshot("pool-1", "generation-1")

        self.service.database.get_connection.assert_not_called()

    def test_seal_rejects_manifest_that_no_longer_matches_sealed_inputs(self):
        generation = self._valid_generation()
        generation["input_manifest"]["dataset_manifest_hash"] = "tampered-hash"
        self.service.get_generation = MagicMock(return_value=generation)

        with self.assertRaisesRegex(ValueError, "生成批次输入清单与封存证据不一致"):
            self.service.seal_snapshot("pool-1", "generation-1")

        self.service.database.get_connection.assert_not_called()

    def test_seal_rejects_member_without_selection_date_evidence(self):
        generation = self._valid_generation()
        generation["members"][0]["valid_from"] = "2025-01-01"
        self.service.get_generation = MagicMock(return_value=generation)

        with self.assertRaisesRegex(ValueError, "成员有效期或证据哈希与生成交易日不一致"):
            self.service.seal_snapshot("pool-1", "generation-1")

        self.service.database.get_connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
