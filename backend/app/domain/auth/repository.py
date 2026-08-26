"""PostgreSQL authentication facts for the active StockPro runtime."""
from __future__ import annotations

from datetime import datetime
from typing import Callable

import psycopg2
import psycopg2.extras

from app.core.config import settings


class PostgresAuthRepository:
    def __init__(self, database_url: str | None = None, *, connection_factory: Callable[..., object] = psycopg2.connect) -> None:
        self.database_url = database_url or settings.DATABASE_URL
        self.connection_factory = connection_factory

    def _connect(self, *, readonly: bool):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for authentication")
        connection = self.connection_factory(self.database_url)
        connection.set_session(readonly=readonly, autocommit=False)
        return connection

    def active_guest_code(self, *, code_hash: str | None = None, code_id: int | None = None, now: datetime) -> dict | None:
        if (code_hash is None) == (code_id is None):
            raise ValueError("exactly one guest-code selector is required")
        selector = "code_hash=%s" if code_hash is not None else "id=%s"
        value = code_hash if code_hash is not None else int(code_id or 0)
        with self._connect(readonly=True) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"""SELECT id,note,expires_at,max_backtests_per_day,max_concurrent_backtests,
                               max_backtest_days,created_by,created_at,last_used_at,revoked_at
                        FROM guest_access_codes
                        WHERE {selector} AND revoked_at IS NULL AND expires_at>%s""",
                    (value, now),
                )
                row = cursor.fetchone()
        return dict(row) if row else None

    def create_guest_code(self, *, code_hash: str, note: str, expires_at: datetime, max_backtests_per_day: int, max_concurrent_backtests: int, max_backtest_days: int, created_by: str) -> dict:
        with self._connect(readonly=False) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """INSERT INTO guest_access_codes
                       (code_hash,note,expires_at,max_backtests_per_day,max_concurrent_backtests,
                        max_backtest_days,created_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (code_hash, note, expires_at, max_backtests_per_day, max_concurrent_backtests, max_backtest_days, created_by),
                )
                return dict(cursor.fetchone())

    def list_guest_codes(self) -> list[dict]:
        with self._connect(readonly=True) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """SELECT id,note,expires_at,max_backtests_per_day,max_concurrent_backtests,
                              max_backtest_days,created_by,created_at,last_used_at,revoked_at
                       FROM guest_access_codes WHERE revoked_at IS NULL
                       ORDER BY created_at DESC,id DESC"""
                )
                return [dict(row) for row in cursor.fetchall()]

    def touch_guest_code(self, code_id: int, now: datetime) -> None:
        with self._connect(readonly=False) as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE guest_access_codes SET last_used_at=%s WHERE id=%s", (now, int(code_id)))

    def revoke_guest_code(self, code_id: int, now: datetime) -> dict:
        with self._connect(readonly=False) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "UPDATE guest_access_codes SET revoked_at=%s WHERE id=%s AND revoked_at IS NULL RETURNING id,revoked_at",
                    (now, int(code_id)),
                )
                row = cursor.fetchone()
        return dict(row) if row else {"id": int(code_id), "revoked_at": now}

    def record_event(self, *, event_type: str, role: str, subject_id: str | None, guest_code_id: int | None, success: bool, reason: str | None, metadata: dict) -> None:
        with self._connect(readonly=False) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO auth_audit_events
                       (event_type,role,subject_id,guest_code_id,success,reason,metadata)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (event_type, role, subject_id, guest_code_id, success, reason, psycopg2.extras.Json(metadata)),
                )

    def session_revoked(self, session_id: str) -> bool:
        with self._connect(readonly=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT EXISTS(SELECT 1 FROM auth_audit_events WHERE event_type='session_revoked' AND subject_id=%s AND success)",
                    (session_id,),
                )
                return bool(cursor.fetchone()[0])
