import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.onboarding_readiness_service import OnboardingReadinessService


class OnboardingReadinessServiceTests(unittest.TestCase):
    def test_required_readiness_does_not_treat_optional_paper_as_blocker(self):
        service = OnboardingReadinessService(MagicMock(), SimpleNamespace(ADMIN_PASSWORD="set", ADMIN_TOKEN_SECRET="set", ENABLE_TUSHARE=True, TUSHARE_TOKEN="set"), 37)
        service._counts = MagicMock(return_value={"migrations": 37, "snapshots": 1, "strategies": 0, "paper": 0, "reviews": 0})
        result = service.build()
        self.assertEqual("ready", result["status"])
        self.assertFalse(result["writes_performed"])

    def test_missing_provider_and_snapshot_are_separate_required_steps(self):
        service = OnboardingReadinessService(MagicMock(), SimpleNamespace(ADMIN_PASSWORD="set", ADMIN_TOKEN_SECRET="set", ENABLE_TUSHARE=True, TUSHARE_TOKEN=""), 37)
        service._counts = MagicMock(return_value={"migrations": 37, "snapshots": 0, "strategies": 0, "paper": 0, "reviews": 0})
        result = service.build()
        missing = {item["code"] for item in result["steps"] if item["status"] == "missing" and item["required"]}
        self.assertEqual({"provider", "snapshot"}, missing)
        self.assertEqual("action_required", result["status"])


if __name__ == "__main__":
    unittest.main()
