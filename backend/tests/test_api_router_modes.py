import unittest

from app.api.api import create_api_router


class ApiRouterModeTests(unittest.TestCase):
    def test_postgres_mode_exposes_health_without_legacy_sqlite_routes(self):
        router = create_api_router(include_legacy_sqlite_routes=False)
        paths = {route.path for route in router.routes}

        self.assertIn("/health/health", paths)
        self.assertIn("/health/storage", paths)
        self.assertNotIn("/health/health/storage", paths)
        self.assertNotIn("/stocks/search", paths)
        self.assertNotIn("/database/tables", paths)

    def test_legacy_mode_keeps_existing_routers_available(self):
        router = create_api_router(include_legacy_sqlite_routes=True)
        paths = {route.path for route in router.routes}

        self.assertIn("/health/health", paths)
        self.assertIn("/stocks/search", paths)
        self.assertIn("/database/tables", paths)


if __name__ == "__main__":
    unittest.main()
