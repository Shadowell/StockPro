import unittest

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.api import create_api_router
from app.core import admin_auth
from app.core.config import settings


class AdminAuthTests(unittest.TestCase):
    def setUp(self):
        self.original_username = settings.ADMIN_USERNAME
        self.original_password = settings.ADMIN_PASSWORD
        self.original_secret = settings.ADMIN_TOKEN_SECRET
        self.original_ttl = settings.ADMIN_TOKEN_TTL_SECONDS
        settings.ADMIN_USERNAME = "admin"
        settings.ADMIN_PASSWORD = "secret-password"
        settings.ADMIN_TOKEN_SECRET = "test-token-secret"
        settings.ADMIN_TOKEN_TTL_SECONDS = 3600

    def tearDown(self):
        settings.ADMIN_USERNAME = self.original_username
        settings.ADMIN_PASSWORD = self.original_password
        settings.ADMIN_TOKEN_SECRET = self.original_secret
        settings.ADMIN_TOKEN_TTL_SECONDS = self.original_ttl

    def test_admin_login_issues_token_and_me_accepts_it(self):
        app = FastAPI()
        app.include_router(create_api_router(include_legacy_sqlite_routes=False), prefix="/api/v1")
        client = TestClient(app)

        login_response = client.post(
            "/api/v1/auth/admin/login",
            json={"username": "admin", "password": "secret-password"},
        )

        self.assertEqual(200, login_response.status_code)
        payload = login_response.json()
        self.assertEqual("bearer", payload["token_type"])
        self.assertEqual("admin", payload["username"])
        self.assertIsInstance(payload["access_token"], str)

        me_response = client.get(
            "/api/v1/auth/admin/me",
            headers={"Authorization": f"Bearer {payload['access_token']}"},
        )

        self.assertEqual(200, me_response.status_code)
        self.assertEqual({"username": "admin"}, me_response.json())

    def test_admin_login_rejects_wrong_password(self):
        app = FastAPI()
        app.include_router(create_api_router(include_legacy_sqlite_routes=False), prefix="/api/v1")
        client = TestClient(app)

        response = client.post(
            "/api/v1/auth/admin/login",
            json={"username": "admin", "password": "wrong"},
        )

        self.assertEqual(401, response.status_code)

    def test_admin_login_rejects_when_password_is_not_configured(self):
        settings.ADMIN_PASSWORD = ""
        app = FastAPI()
        app.include_router(create_api_router(include_legacy_sqlite_routes=False), prefix="/api/v1")
        client = TestClient(app)

        response = client.post(
            "/api/v1/auth/admin/login",
            json={"username": "admin", "password": "secret-password"},
        )

        self.assertEqual(503, response.status_code)

    def test_require_admin_rejects_missing_and_accepts_valid_bearer_token(self):
        app = FastAPI()

        @app.get("/private")
        def private_route(_username: str = Depends(admin_auth.require_admin)):
            return {"ok": True}

        client = TestClient(app)

        missing_response = client.get("/private")
        self.assertEqual(401, missing_response.status_code)

        invalid_response = client.get("/private", headers={"Authorization": "Bearer not-a-token"})
        self.assertEqual(401, invalid_response.status_code)

        token = admin_auth.create_admin_token("admin")
        valid_response = client.get("/private", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(200, valid_response.status_code)
        self.assertEqual({"ok": True}, valid_response.json())


if __name__ == "__main__":
    unittest.main()
