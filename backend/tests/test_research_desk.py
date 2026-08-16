import unittest
from pathlib import Path

from app.services.research_desk_service import choose_next_action
from app.services.strategy_runtime_service import validate_strategy_python


class ResearchDeskNextActionTests(unittest.TestCase):
    def test_empty_data_stage_is_the_first_action(self):
        action = choose_next_action(
            [
                {"id": "data", "status": "empty", "route": "/data"},
                {"id": "strategy", "status": "empty", "route": "/strategy"},
            ]
        )
        self.assertEqual("/data", action["route"])
        self.assertIn("数据", action["reason"])

    def test_strategy_is_next_when_upstream_is_ready(self):
        action = choose_next_action(
            [
                {"id": "data", "status": "available", "route": "/data"},
                {"id": "market", "status": "available", "route": "/market"},
                {"id": "factors", "status": "available", "route": "/factors"},
                {"id": "pools", "status": "available", "route": "/pools"},
                {"id": "strategy", "status": "empty", "route": "/strategy"},
            ]
        )
        self.assertEqual("/strategy", action["route"])

    def test_complete_pipeline_returns_watch(self):
        stages = [
            {"id": item, "status": "available", "route": f"/{item}"}
            for item in ("data", "market", "factors", "pools", "strategy", "backtest", "paper", "watch", "monitor", "review")
        ]
        action = choose_next_action(stages, {"name": "多因子风险预算"})
        self.assertEqual("/watch", action["route"])
        self.assertIn("多因子风险预算", action["reason"])


class MultiFactorStrategyContractTests(unittest.TestCase):
    def test_reference_strategy_is_valid_strategy_api_v1(self):
        code = Path(__file__).resolve().parents[2].joinpath("strategies", "multi_factor_risk_budget.py").read_text(encoding="utf-8")
        result = validate_strategy_python(code)
        self.assertTrue(result["valid"], result["issues"])
        self.assertEqual("stockpro.v1", result["api_version"])
        for name in ("get_factor_values", "run_weekly", "order_target_percent", "history"):
            self.assertIn(name, result["dependencies"])


if __name__ == "__main__":
    unittest.main()
