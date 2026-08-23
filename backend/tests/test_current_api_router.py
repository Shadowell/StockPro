from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _create_client(monkeypatch) -> TestClient:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://stockpro@127.0.0.1/stockpro_bitpro_rebase_dev",
    )
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        module = importlib.import_module("app.main")
        return TestClient(module.create_app())
    finally:
        sys.path.remove(str(BACKEND_ROOT))


@dataclass(frozen=True)
class FakeStorageHealth:
    status: str = "healthy"
    database: str = "postgresql"
    applied_migrations: int = 37
    expected_migrations: int = 37


class FakeHealthRepository:
    def storage_health(self) -> FakeStorageHealth:
        return FakeStorageHealth()


def test_only_current_api_is_registered(monkeypatch) -> None:
    client = _create_client(monkeypatch)

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health/storage").status_code == 200
    assert client.get("/api/v2/health").status_code == 404
    assert client.get("/api/v1/health").status_code == 404


def test_openapi_has_no_versioned_paths(monkeypatch) -> None:
    client = _create_client(monkeypatch)

    paths = client.get("/openapi.json").json()["paths"]

    assert all("/api/v" not in path for path in paths)
    assert "/api/health" in paths
    assert "/api/health/storage" in paths


def test_legacy_router_package_is_removed() -> None:
    assert not (BACKEND_ROOT / "app/api/v2").exists()


def test_storage_health_uses_injected_current_context(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://stockpro@127.0.0.1/stockpro_bitpro_rebase_dev",
    )
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        from app.main import create_app

        context = SimpleNamespace(
            settings=SimpleNamespace(
                AUTH_ENABLED=False,
                ADMIN_USERNAME="admin",
                BACKEND_CORS_ORIGINS=["http://localhost:4444"],
            ),
            repositories=SimpleNamespace(
                health=FakeHealthRepository(),
                auth=FakeHealthRepository(),
                market=FakeHealthRepository(),
            ),
            clock=lambda: datetime.now(timezone.utc),
        )
        response = TestClient(create_app(context)).get("/api/health/storage")
    finally:
        sys.path.remove(str(BACKEND_ROOT))

    assert response.json() == {
        "status": "healthy",
        "database": "postgresql",
        "applied_migrations": 37,
        "expected_migrations": 37,
        "writes_performed": False,
    }
