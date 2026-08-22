from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.local_db import LocalDatabase  # noqa: E402
from app.services.auth_service import AuthError, AuthService  # noqa: E402


def _service(tmp_path: Path) -> AuthService:
    db = LocalDatabase(str(tmp_path / "auth.db"))
    db.init_db()
    return AuthService(db=db)


def test_admin_password_login_creates_http_only_session_shape(tmp_path: Path) -> None:
    service = _service(tmp_path)
    password_hash = service.hash_password("correct-password")

    session = service.login_admin(
        username="admin",
        password="correct-password",
        expected_username="admin",
        expected_password_hash=password_hash,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    assert session["role"] == "admin"
    assert session["token"]
    loaded = service.get_session(session["token"])
    assert loaded is not None
    assert loaded["role"] == "admin"
    assert loaded["session_id"] == session["session_id"]

    with pytest.raises(AuthError):
        service.login_admin(
            username="admin",
            password="wrong-password",
            expected_username="admin",
            expected_password_hash=password_hash,
            ip_address="127.0.0.1",
            user_agent="pytest",
        )


def test_admin_login_default_session_persists_until_explicit_logout(tmp_path: Path) -> None:
    service = _service(tmp_path)
    password_hash = service.hash_password("correct-password")

    session = service.login_admin(
        username="admin",
        password="correct-password",
        expected_username="admin",
        expected_password_hash=password_hash,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    expires_at = datetime.fromisoformat(session["expires_at"])
    assert expires_at > datetime.now(timezone.utc) + timedelta(days=365)
    assert service.get_session(session["token"]) is not None

    service.revoke_session(session["token"])

    assert service.get_session(session["token"]) is None


def test_guest_code_plaintext_is_returned_once_and_only_hash_is_stored(tmp_path: Path) -> None:
    service = _service(tmp_path)

    created = service.create_guest_code(
        note="临时演示",
        expires_in_minutes=60,
        max_backtests_per_day=3,
        max_concurrent_backtests=1,
        max_backtest_days=365,
        created_by="admin",
    )

    assert created["code"]
    assert created["expires_at"]
    conn = service.db.get_connection()
    row = conn.execute(
        "SELECT code_hash, note, max_backtests_per_day FROM guest_access_codes WHERE id = ?",
        (created["id"],),
    ).fetchone()
    assert row["note"] == "临时演示"
    assert row["max_backtests_per_day"] == 3
    assert row["code_hash"] != created["code"]
    assert created["code"] not in str(dict(row))

    guest = service.login_guest(
        created["code"],
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    assert guest["role"] == "guest"
    assert guest["guest_code_id"] == created["id"]


def test_guest_login_session_expires_with_code_not_click_session_cap(tmp_path: Path) -> None:
    service = _service(tmp_path)

    created = service.create_guest_code(
        note="resume link",
        expires_in_minutes=60 * 24 * 30,
        max_backtests_per_day=10,
        max_concurrent_backtests=1,
        max_backtest_days=365,
        created_by="admin",
    )

    guest = service.login_guest(
        created["code"],
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    code_expires_at = datetime.fromisoformat(created["expires_at"])
    session_expires_at = datetime.fromisoformat(guest["expires_at"])
    assert session_expires_at > datetime.now(timezone.utc) + timedelta(days=29)
    assert abs((session_expires_at - code_expires_at).total_seconds()) < 1


def test_guest_code_list_hides_revoked_codes_from_admin_manager(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.create_guest_code(
        note="first",
        expires_in_minutes=60,
        max_backtests_per_day=3,
        max_concurrent_backtests=1,
        max_backtest_days=365,
        created_by="admin",
    )
    second = service.create_guest_code(
        note="second",
        expires_in_minutes=60,
        max_backtests_per_day=3,
        max_concurrent_backtests=1,
        max_backtest_days=365,
        created_by="admin",
    )

    service.revoke_guest_code(first["id"])

    items = service.list_guest_codes()
    assert [item["id"] for item in items] == [second["id"]]
    assert all(item["revoked_at"] is None for item in items)


def test_guest_code_expiry_and_backtest_quota_are_enforced(tmp_path: Path) -> None:
    service = _service(tmp_path)
    created = service.create_guest_code(
        note="short lived",
        expires_in_minutes=60,
        max_backtests_per_day=1,
        max_concurrent_backtests=1,
        max_backtest_days=30,
        created_by="admin",
    )
    guest = service.login_guest(created["code"], ip_address="127.0.0.1", user_agent="pytest")

    with pytest.raises(AuthError, match="最长回测区间"):
        service.check_guest_backtest_quota(
            guest,
            start_date="2025-01-01",
            end_date="2025-03-15",
        )

    service.check_guest_backtest_quota(
        guest,
        start_date="2025-01-01",
        end_date="2025-01-15",
    )
    conn = service.db.get_connection()
    conn.execute(
        """
        INSERT INTO backtest_jobs (job_id, strategy_id, request_json, status)
        VALUES ('job-1', 1, '{}', 'running')
        """,
    )
    conn.commit()
    service.record_guest_backtest_job(guest, "job-1")

    with pytest.raises(AuthError, match="并发回测"):
        service.check_guest_backtest_quota(
            guest,
            start_date="2025-01-01",
            end_date="2025-01-15",
        )
    audit = conn.execute(
        "SELECT event_type, reason FROM auth_audit_events WHERE event_type = 'guest_backtest_quota_rejected' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert audit["event_type"] == "guest_backtest_quota_rejected"
    assert "并发回测" in audit["reason"]

    expired_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    conn.execute(
        "UPDATE guest_access_codes SET expires_at = ? WHERE id = ?",
        (expired_at, created["id"]),
    )
    conn.commit()
    with pytest.raises(AuthError, match="已过期"):
        service.login_guest(created["code"], ip_address="127.0.0.1", user_agent="pytest")
