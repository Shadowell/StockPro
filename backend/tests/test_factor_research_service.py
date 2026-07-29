import unittest

import pandas as pd

from app.services.factor_research_service import (
    FactorContext,
    FactorResearchService,
    REFERENCE_FACTORS,
    SnapshotFactorData,
    _reference_code,
    calculate_forward_return_metrics,
    validate_factor_python,
)


class FactorPythonValidationTests(unittest.TestCase):
    def test_all_reference_factors_use_valid_dynamic_python_contract(self):
        results = [validate_factor_python(_reference_code(item)) for item in REFERENCE_FACTORS]

        self.assertEqual(len(results), 100)
        self.assertTrue(all(item["valid"] for item in results))
        codes = [item["code"] for item in REFERENCE_FACTORS]
        self.assertEqual(len(codes), len(set(codes)))

    def test_validator_rejects_import_network_file_and_top_level_execution(self):
        examples = [
            "import os\nFACTOR_META={}\ndef calculate(context, data):\n    return {}",
            "FACTOR_META={'name':'x','category':'x','frequency':'daily','lookback':1,'direction':1}\nopen('/tmp/x')\ndef calculate(context, data):\n    return {}",
            "FACTOR_META={'name':'x','category':'x','frequency':'daily','lookback':1,'direction':1}\ndef calculate(context, data):\n    return data.__dict__",
        ]

        self.assertTrue(all(not validate_factor_python(code)["valid"] for code in examples))

    def test_validator_requires_exact_calculate_signature_and_metadata(self):
        result = validate_factor_python("FACTOR_META={'name':'x'}\ndef calculate(data):\n    return {}")

        self.assertFalse(result["valid"])
        self.assertTrue(any("(context, data)" in item for item in result["errors"]))
        self.assertTrue(any("lookback" in item for item in result["errors"]))


class SnapshotFactorDataTests(unittest.TestCase):
    def setUp(self):
        self.bars = [
            {"symbol": symbol, "trade_date": trade_date, "open": close, "high": close, "low": close, "close": close, "volume": 100, "turnover": 1000}
            for symbol, closes in (("SH_600000", [10, 11, 12]), ("SZ_000001", [20, 19, 18]))
            for trade_date, close in zip(("2025-01-01", "2025-01-02", "2025-01-03"), closes)
        ]
        self.valuation = [
            {"symbol": "SH_600000", "turnover_rate": 1.2, "total_mv": 1000},
            {"symbol": "SZ_000001", "turnover_rate": None, "total_mv": 2000},
        ]
        self.members = [
            {"symbol": "SH_600000", "industry_code": "银行", "eligibility_flags": {"eligible_for_research": True}},
            {"symbol": "SZ_000001", "industry_code": "银行", "eligibility_flags": {"eligible_for_research": True}},
            {"symbol": "SH_600519", "industry_code": "食品", "eligibility_flags": {"eligible_for_research": True}},
        ]

    def test_history_never_reads_after_context_trade_date(self):
        data = SnapshotFactorData("2025-01-02", self.bars, self.valuation, self.members)

        history = data.history("close", 10)

        self.assertEqual(history.index.max(), pd.Timestamp("2025-01-02"))
        self.assertEqual(history.shape, (2, 2))
        self.assertEqual(data.get_universe(), ["SH_600000", "SZ_000001"])

    def test_current_preserves_missing_valuation_as_nan(self):
        data = SnapshotFactorData("2025-01-02", self.bars, self.valuation, self.members)

        values = data.current("turnover_rate")

        self.assertEqual(values["SH_600000"], 1.2)
        self.assertTrue(pd.isna(values["SZ_000001"]))

    def test_reference_code_executes_to_symbol_series(self):
        data = SnapshotFactorData("2025-01-02", self.bars, self.valuation, self.members)
        service = FactorResearchService.__new__(FactorResearchService)
        context = FactorContext("2025-01-02", "2025-01-02T17:30:00+08:00", 1, 1)

        result = service._execute(_reference_code(REFERENCE_FACTORS[0]), context, data)

        self.assertAlmostEqual(result["SH_600000"], 0.1)
        self.assertAlmostEqual(result["SZ_000001"], -0.05)

    def test_preprocessing_keeps_pending_forward_metrics_null(self):
        data = SnapshotFactorData("2025-01-02", self.bars, self.valuation, self.members)
        service = FactorResearchService.__new__(FactorResearchService)
        raw = pd.Series({"SH_600000": 1.0, "SZ_000001": None})
        version = {"preprocessing": {"winsorize": [0.01, 0.99], "standardize": True}, "direction": 1}

        values, metrics = service._prepare_values_and_metrics(raw, data, version, "2025-01-02")

        self.assertEqual(len(values), 2)
        self.assertIsNone(next(item for item in values if item["symbol"] == "SZ_000001")["processed_value"])
        rank_ic = next(item for item in metrics if item["metric_code"] == "rank_ic" and item["horizon"] == 1)
        self.assertIsNone(rank_ic["metric_value"])
        self.assertTrue(rank_ic["pending_reason"])


class ForwardMetricTests(unittest.TestCase):
    def test_forward_metrics_match_cross_sectional_fixture(self):
        symbols = [f"S{index}" for index in range(1, 6)]
        processed = pd.Series([1, 2, 3, 4, 5], index=symbols, dtype=float)
        quantiles = pd.Series([1, 2, 3, 4, 5], index=symbols, dtype=float)
        base = pd.Series([10, 10, 10, 10, 10], index=symbols, dtype=float)
        future = pd.Series([9, 9.5, 10, 10.5, 11], index=symbols, dtype=float)

        metrics = calculate_forward_return_metrics(processed, quantiles, base, future, 5)

        self.assertEqual(len(metrics), 4)
        self.assertAlmostEqual(next(item for item in metrics if item["metric_code"] == "ic")["metric_value"], 1.0)
        self.assertAlmostEqual(next(item for item in metrics if item["metric_code"] == "rank_ic")["metric_value"], 1.0)
        long_short = next(item for item in metrics if item["metric_code"] == "long_short_return")
        self.assertAlmostEqual(long_short["metric_value"], 0.2)
        self.assertEqual(long_short["metric_payload"]["sample_count"], 5)

    def test_forward_metrics_require_three_complete_symbols(self):
        index = ["A", "B"]
        metrics = calculate_forward_return_metrics(
            pd.Series([1, 2], index=index),
            pd.Series([1, 5], index=index),
            pd.Series([10, 10], index=index),
            pd.Series([11, 9], index=index),
            1,
        )

        self.assertEqual(metrics, [])

    def test_preprocessing_marks_only_clipped_symbols_as_winsorized(self):
        bars = [
            {"symbol": symbol, "trade_date": "2025-01-02", "open": 10, "high": 10, "low": 10, "close": 10, "volume": 100, "turnover": 1000}
            for symbol in ("A", "B", "C", "D")
        ]
        members = [{"symbol": symbol, "industry_code": "X", "eligibility_flags": {"eligible_for_research": True}} for symbol in ("A", "B", "C", "D")]
        data = SnapshotFactorData("2025-01-02", bars, [], members)
        service = FactorResearchService.__new__(FactorResearchService)

        values, _ = service._prepare_values_and_metrics(
            pd.Series({"A": 1.0, "B": 2.0, "C": 3.0, "D": 100.0}),
            data,
            {"preprocessing": {"winsorize": [0.25, 0.75], "standardize": True}, "direction": 1},
            "2025-01-02",
        )

        flags = {item["symbol"]: item["quality_flags"]["winsorized"] for item in values}
        self.assertEqual(flags, {"A": True, "B": False, "C": False, "D": True})


class ResearchPromotionGateTests(unittest.TestCase):
    def test_training_sample_cannot_be_passed_as_promotion_evidence(self):
        service = FactorResearchService.__new__(FactorResearchService)

        with self.assertRaisesRegex(ValueError, "非样本外"):
            service.create_evaluation({"sample_label": "train", "status": "passed"})

    def test_oos_pass_requires_snapshot_metrics_rationale_and_rejected_variants(self):
        service = FactorResearchService.__new__(FactorResearchService)

        with self.assertRaisesRegex(ValueError, "样本外通过必须"):
            service.create_evaluation({"sample_label": "out_of_sample", "status": "passed"})


if __name__ == "__main__":
    unittest.main()
