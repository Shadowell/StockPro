import unittest

from app.api.endpoints.workflow import workflow_capabilities
from app.core.config import settings


class WorkflowCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_contract_exposes_truthful_paper_only_lifecycle(self):
        result = await workflow_capabilities()

        self.assertEqual("stockpro-workflow-v1", result["contract_version"])
        self.assertEqual("bitpro", result["behavioral_baseline"])
        self.assertEqual("paper_only", result["execution_scope"])
        self.assertFalse(result["feature_gates"]["real_broker"]["enabled"])
        self.assertEqual("not_implemented", result["feature_gates"]["real_broker"]["status"])
        self.assertEqual(
            ["strategy", "backtest", "paper", "watch", "monitor", "review"],
            [stage["id"] for stage in result["stages"]],
        )

    async def test_runtime_flags_are_reported_without_claiming_configuration_is_running(self):
        previous_scheduler = settings.ENABLE_SCHEDULER
        previous_external_fetch = settings.ENABLE_EXTERNAL_MARKET_FETCH
        settings.ENABLE_SCHEDULER = False
        settings.ENABLE_EXTERNAL_MARKET_FETCH = False
        try:
            result = await workflow_capabilities()
            self.assertEqual("disabled", result["feature_gates"]["scheduler_runtime"]["status"])
            self.assertEqual("disabled", result["feature_gates"]["external_market_fetch"]["status"])
        finally:
            settings.ENABLE_SCHEDULER = previous_scheduler
            settings.ENABLE_EXTERNAL_MARKET_FETCH = previous_external_fetch


if __name__ == "__main__":
    unittest.main()
