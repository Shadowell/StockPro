from __future__ import annotations

import json
import importlib
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _settings_class(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://stockpro@127.0.0.1/stockpro")
    backend_root = PROJECT_ROOT / "backend"
    sys.path.insert(0, str(backend_root))
    try:
        module = importlib.import_module("app.core.config")
    finally:
        sys.path.remove(str(backend_root))
    return module.Settings


def test_runtime_dependencies_exclude_private_exchange_and_sqlite() -> None:
    requirements = (PROJECT_ROOT / "backend/requirements.txt").read_text(encoding="utf-8").lower()

    assert "-r requirements-base.txt" not in requirements
    assert "ccxt" not in requirements
    assert "aiosqlite" not in requirements
    assert "kairos" not in requirements
    assert "psycopg" in requirements
    assert "tushare" in requirements
    assert "akshare" in requirements


def test_settings_require_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    Settings = _settings_class(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///crypto.db")

    with pytest.raises(ValueError, match="PostgreSQL"):
        Settings(_env_file=None)


def test_settings_fail_when_database_url_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Settings = _settings_class(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_settings_accept_legacy_comma_separated_cors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Settings = _settings_class(monkeypatch)
    monkeypatch.setenv(
        "BACKEND_CORS_ORIGINS",
        "http://localhost:4444,http://127.0.0.1:4444",
    )

    configured = Settings(_env_file=None)

    assert configured.BACKEND_CORS_ORIGINS == [
        "http://localhost:4444",
        "http://127.0.0.1:4444",
    ]


def test_frontend_has_wave_one_verification_scripts() -> None:
    package = json.loads(
        (PROJECT_ROOT / "frontend/package.json").read_text(encoding="utf-8")
    )
    scripts = package["scripts"]

    assert scripts["check"] == "tsc --noEmit"
    assert scripts["test:e2e"] == "playwright test"
    assert scripts["test:e2e:mock"] == "cross-env MOCK_API=true playwright test"
    assert scripts["test:e2e:real"] == "cross-env MOCK_API=false E2E_REAL_BACKEND=1 playwright test"
    assert scripts["check:bundle-budget"] == "node scripts/check-bundle-budget.mjs"
    assert package["dependencies"].get("@bitpro/ui") == "file:../packages/bitpro-ui"
    assert "@playwright/test" in package["devDependencies"]
    assert "cross-env" in package["devDependencies"]
    lockfile = (PROJECT_ROOT / "frontend/package-lock.json").read_text(encoding="utf-8")
    assert "/Users/" not in lockfile
