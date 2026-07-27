import unittest

from fastapi import HTTPException

from app.api.endpoints.ai import _require_ai_configuration, ai_capabilities
from app.core.config import settings
from app.services.data_purpose import infer_data_purpose


class AICapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_qwen_key_is_explicitly_unavailable(self):
        previous = settings.QWEN_API_KEY
        settings.QWEN_API_KEY = ""
        try:
            result = await ai_capabilities()
            self.assertFalse(result["configured"])
            self.assertEqual("not_configured", result["generation_status"])
            self.assertIsNone(result["model"])
            self.assertFalse(result["strategy_auto_develop_uses_ai"])
            with self.assertRaises(HTTPException) as context:
                _require_ai_configuration()
            self.assertEqual(503, context.exception.status_code)
        finally:
            settings.QWEN_API_KEY = previous

    async def test_configured_qwen_reports_model_without_secret(self):
        previous = settings.QWEN_API_KEY
        settings.QWEN_API_KEY = "secret-test-value"
        try:
            result = await ai_capabilities()
            self.assertTrue(result["configured"])
            self.assertEqual(settings.QWEN_STOCK_MODEL, result["model"])
            self.assertNotIn("secret-test-value", str(result))
        finally:
            settings.QWEN_API_KEY = previous


class DataPurposeTests(unittest.TestCase):
    def test_acceptance_and_seed_markers_are_classified(self):
        self.assertEqual("acceptance", infer_data_purpose("Sprint QA 回测"))
        self.assertEqual("seed", infer_data_purpose("demo strategy"))
        self.assertEqual("user", infer_data_purpose("红利低波"))


if __name__ == "__main__":
    unittest.main()
