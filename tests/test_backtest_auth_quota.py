from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.v2.endpoints import backtest  # noqa: E402
from app.api.v2.endpoints import auth as auth_endpoint  # noqa: E402
from app.core.auth_middleware import AuthMiddleware  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.errors import register_exception_handlers  # noqa: E402
from app.db.local_db import LocalDatabase  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402


def build_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, AuthService, LocalDatabase]:
    database = LocalDatabase(str(tmp_path / "auth-backtest.db"))
    database.init_db()
    service = AuthService(db=database)

    monkeypatch.setattr(settings, "BITPRO_AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BITPRO_ADMIN_USERNAME", "admin", raising=False)
    monkeypatch.setattr(settings, "BITPRO_ADMIN_PASSWORD_HASH", service.hash_password("admin-pass"), raising=False)
    monkeypatch.setattr(settings, "BITPRO_AUTH_COOKIE_SECURE", False, raising=False)
    monkeypatch.setattr(auth_endpoint, "auth_service", service)
    monkeypatch.setattr(backtest, "db", database)
    monkeypatch.setattr(
        backtest,
        "get_strategy_for_id",
        lambda strategy_id: {
            "id": strategy_id,
            "name": "[合约][1H][CTA] BTC · 测试策略 · 100U",
            "strategy_key": "demo",
            "config": {"strategy_key": "demo", "timeframe": "1h", "symbols": ["BTC/USDT:USDT"]},
            "symbols": ["BTC/USDT:USDT"],
        },
    )
    monkeypatch.setattr(backtest, "get_base_strategy_registry", lambda: {"demo": object})

    async def fake_run_backtest_job_task(job_id: str, payload: dict):
        return None

    monkeypatch.setattr(backtest, "_run_backtest_job_task", fake_run_backtest_job_task)

    app = FastAPI()
    app.add_middleware(AuthMiddleware, auth_service=service)
    app.include_router(auth_endpoint.router, prefix="/api/v2/auth")
    app.include_router(backtest.router, prefix="/api/v2/backtest")
    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False), service, database


def test_guest_backtest_run_job_records_owner_and_enforces_range_quota(tmp_path: Path, monkeypatch) -> None:
    client, service, database = build_client(tmp_path, monkeypatch)
    guest_code = service.create_guest_code(
        note="demo",
        expires_in_minutes=60,
        max_backtests_per_day=3,
        max_concurrent_backtests=1,
        max_backtest_days=30,
        created_by="admin",
    )["code"]
    assert client.post("/api/v2/auth/guest/login", json={"code": guest_code}).status_code == 200

    too_long = client.post(
        "/api/v2/backtest/run_job",
        json={
            "strategy_id": 1,
            "start_date": "2025-01-01",
            "end_date": "2025-03-15",
            "initial_capital": 100,
        },
    )
    assert too_long.status_code == 403
    assert "最长回测区间" in str(too_long.json())

    ok_response = client.post(
        "/api/v2/backtest/run_job",
        json={
            "strategy_id": 1,
            "start_date": "2025-01-01",
            "end_date": "2025-01-15",
            "initial_capital": 100,
        },
    )
    assert ok_response.status_code == 200
    job_id = ok_response.json()["job_id"]

    row = database.get_connection().execute(
        "SELECT owner_role, owner_session_id, owner_guest_code_id FROM backtest_jobs WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    assert row["owner_role"] == "guest"
    assert row["owner_session_id"]
    assert row["owner_guest_code_id"]

    concurrent = client.post(
        "/api/v2/backtest/run_job",
        json={
            "strategy_id": 1,
            "start_date": "2025-02-01",
            "end_date": "2025-02-15",
            "initial_capital": 100,
        },
    )
    assert concurrent.status_code == 403
    assert "并发回测" in str(concurrent.json())
