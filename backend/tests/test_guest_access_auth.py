import unittest
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core import admin_auth
from app.core.config import settings


class GuestAccessAuthTests(unittest.TestCase):
    def setUp(self):
        self.original_password = settings.ADMIN_PASSWORD
        self.original_secret = settings.ADMIN_TOKEN_SECRET
        settings.ADMIN_PASSWORD = "secret-password"
        settings.ADMIN_TOKEN_SECRET = "test-token-secret"
        self.code = {
            "id": 7,
            "expires_at": "2099-01-01T00:00:00+00:00",
            "max_backtests_per_day": 3,
            "max_concurrent_backtests": 1,
            "max_backtest_days": 30,
        }

    def tearDown(self):
        settings.ADMIN_PASSWORD = self.original_password
        settings.ADMIN_TOKEN_SECRET = self.original_secret

    @patch("app.services.guest_access_service.GuestAccessService.get_active_code")
    def test_guest_token_resolves_capabilities(self, get_active_code):
        get_active_code.return_value = self.code
        token, session_id = admin_auth.create_guest_token(self.code, now=1_700_000_000)

        principal = admin_auth.verify_access_token(token, now=1_700_000_100)

        self.assertEqual("guest", principal["role"])
        self.assertEqual(session_id, principal["session_id"])
        self.assertEqual(["read", "backtest:run"], principal["permissions"])
        self.assertEqual(30, principal["max_backtest_days"])

    @patch("app.services.guest_access_service.GuestAccessService.get_active_code")
    def test_guest_reads_and_backtests_but_other_writes_are_denied(self, get_active_code):
        get_active_code.return_value = self.code
        token, _session_id = admin_auth.create_guest_token(self.code, now=1_700_000_000)
        app = FastAPI()

        @app.get("/api/strategy")
        def read_route(_principal=Depends(admin_auth.require_authenticated)):
            return {"ok": True}

        @app.post("/api/strategy")
        def write_route(_principal=Depends(admin_auth.require_authenticated)):
            return {"ok": True}

        @app.post("/api/backtest/runs")
        def backtest_route(_principal=Depends(admin_auth.require_authenticated)):
            return {"ok": True}

        client = TestClient(app)
        headers = {"Authorization": f"Bearer {token}"}

        self.assertEqual(200, client.get("/api/strategy", headers=headers).status_code)
        denied = client.post("/api/strategy", headers=headers)
        self.assertEqual(403, denied.status_code)
        self.assertIn("只读", denied.json()["detail"])
        self.assertEqual(200, client.post("/api/backtest/runs", headers=headers).status_code)


if __name__ == "__main__":
    unittest.main()
