import unittest

from app.api.api import create_api_router
from app.core.config import settings


class ApiRouterTests(unittest.TestCase):
    def test_single_router_exposes_research_market_data_and_strategy_routes(self):
        router = create_api_router()
        paths = {route.path for route in router.routes}

        self.assertIn("/health/health", paths)
        self.assertIn("/health/storage", paths)
        self.assertIn("/auth/admin/login", paths)
        self.assertIn("/auth/admin/me", paths)
        self.assertIn("/market/overview", paths)
        self.assertIn("/market/hot-concepts", paths)
        self.assertIn("/data-hub/datasets", paths)
        self.assertIn("/admin/task-status", paths)
        self.assertIn("/stocks/search", paths)
        self.assertIn("/strategy", paths)
        self.assertIn("/strategy/{strategy_id}/backtest", paths)
        self.assertIn("/strategy/{strategy_id}/paper-run", paths)
        self.assertIn("/strategy/paper/accounts", paths)
        self.assertIn("/backtest/run", paths)
        self.assertIn("/backtest/results", paths)
        self.assertIn("/paper/run", paths)
        self.assertIn("/paper/accounts", paths)
        self.assertIn("/data/status", paths)

    def test_settings_use_single_api_prefix_and_no_db_mode(self):
        self.assertEqual("/api", settings.API_PREFIX)
        self.assertFalse(hasattr(settings, "API_" + "V1_STR"))
        self.assertFalse(any(name.endswith("_MODE") for name in vars(settings)))


if __name__ == "__main__":
    unittest.main()
