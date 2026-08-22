from __future__ import annotations

from pathlib import Path
import sys

import pytest

from rebuild.assert_safety import assert_safe_to_start, scan_rebuild_safety


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_safety_report_blocks_registered_private_exchange_and_sqlite_runtime(
    tmp_path: Path,
) -> None:
    main = tmp_path / "backend/app/main.py"
    main.parent.mkdir(parents=True)
    main.write_text("client.get_account(); sqlite3.connect('crypto.db')", encoding="utf-8")

    report = scan_rebuild_safety(tmp_path)

    assert report.passed is False
    assert report.registered_private_exchange_routes == 1
    assert report.active_sqlite_repository == 1


def test_safety_report_blocks_active_versioned_api_paths(tmp_path: Path) -> None:
    client = tmp_path / "frontend/src/api/client.ts"
    client.parent.mkdir(parents=True)
    client.write_text("axios.get('/api/v2/market')", encoding="utf-8")

    report = scan_rebuild_safety(tmp_path)

    assert report.active_versioned_api_routes == 1
    with pytest.raises(RuntimeError, match="unsafe to start"):
        assert_safe_to_start(tmp_path)


def test_safety_report_treats_unreachable_imported_source_as_quarantined(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "backend/app/services/legacy_crypto.py"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        "from app.exchange import exchange_manager\nsqlite3.connect('legacy.db')",
        encoding="utf-8",
    )

    report = scan_rebuild_safety(tmp_path)

    assert report.passed is True
    assert report.quarantined_source_findings == 1


def test_safety_report_blocks_live_route_and_crypto_job_registration(
    tmp_path: Path,
) -> None:
    app = tmp_path / "frontend/src/App.tsx"
    app.parent.mkdir(parents=True)
    app.write_text('<Route path="live-real" />', encoding="utf-8")
    main = tmp_path / "backend/app/main.py"
    main.parent.mkdir(parents=True)
    main.write_text("await scheduler_service.start()", encoding="utf-8")

    report = scan_rebuild_safety(tmp_path)

    assert report.registered_live_routes == 1
    assert report.registered_crypto_jobs == 1
    assert report.passed is False


def test_imported_repository_has_no_active_unsafe_surface() -> None:
    report = scan_rebuild_safety(PROJECT_ROOT)

    assert report.passed is True
    assert report.registered_private_exchange_routes == 0
    assert report.active_sqlite_repository == 0
    assert report.active_versioned_api_routes == 0
    assert report.registered_live_routes == 0
    assert report.registered_crypto_jobs == 0
    assert report.quarantined_source_findings > 0


def test_current_api_registers_only_unversioned_rebuild_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://stockpro@127.0.0.1/stockpro")
    backend_root = PROJECT_ROOT / "backend"
    sys.path.insert(0, str(backend_root))
    try:
        from app.main import create_app

        paths = {route.path for route in create_app().routes}
    finally:
        sys.path.remove(str(backend_root))

    assert "/api/health" in paths
    assert "/api/auth/me" in paths
    assert not any(path.startswith(("/api/v1", "/api/v2")) for path in paths)


def test_current_health_is_truthful_and_write_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://stockpro@127.0.0.1/stockpro")
    backend_root = PROJECT_ROOT / "backend"
    sys.path.insert(0, str(backend_root))
    try:
        from fastapi.testclient import TestClient
        from app.main import create_app

        response = TestClient(create_app()).get("/api/health")
    finally:
        sys.path.remove(str(backend_root))

    assert response.status_code == 200
    assert response.json() == {
        "status": "rebuild_safe",
        "project": "StockPro",
        "database_backend": "postgresql",
        "services_started": False,
        "writes_performed": False,
    }


def test_frontend_registers_only_stockpro_routes() -> None:
    app_source = (PROJECT_ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    navigation = (PROJECT_ROOT / "frontend/src/components/MainLayout.tsx").read_text(
        encoding="utf-8"
    )

    for forbidden in ("live-real", "onchain", "arbitrage", 'path="arc"'):
        assert forbidden not in app_source
        assert forbidden not in navigation
    for required in ("paper", "watch", "signals", "monitor", "review"):
        assert f'path="{required}"' in app_source
        assert f"path: '/{required}'" in navigation
