import inspect
import unittest
from unittest.mock import patch

from app.api.endpoints import health


class HealthEndpointSafetyTests(unittest.TestCase):
    def test_storage_health_is_sync_and_bounds_database_connect_time(self):
        self.assertFalse(inspect.iscoroutinefunction(health.storage_health_check))

        database_url = "postgresql://stockpro@example.invalid/stockpro"
        with (
            patch.object(health.settings, "DATABASE_URL", database_url),
            patch.object(health.psycopg, "connect", side_effect=RuntimeError("offline")) as connect,
        ):
            payload = health.storage_health_check()

        self.assertEqual(payload["status"], "error")
        self.assertIn("offline", payload["message"])
        connect.assert_called_once_with(database_url, connect_timeout=3)


if __name__ == "__main__":
    unittest.main()
