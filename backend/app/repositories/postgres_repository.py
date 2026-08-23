from __future__ import annotations

from pathlib import Path
from datetime import datetime
from typing import Any
from typing import Protocol

import psycopg2.extras

from app.db.postgres_migrations import DEFAULT_MIGRATIONS_DIR, load_migrations
from app.repositories.protocols import StorageHealth


class DatabaseConnectionProvider(Protocol):
    def get_connection(self): ...


class PostgresRepository:
    def __init__(
        self,
        database: DatabaseConnectionProvider,
        *,
        migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
    ) -> None:
        self.database = database
        self.migrations_dir = Path(migrations_dir)

    def storage_health(self) -> StorageHealth:
        expected = len(load_migrations(self.migrations_dir))
        try:
            with self.database.get_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*)::integer FROM schema_migrations")
                    row = cursor.fetchone()
            applied = int(row[0]) if row else 0
        except Exception:
            return StorageHealth(
                status="error",
                database="postgresql",
                applied_migrations=0,
                expected_migrations=expected,
            )
        return StorageHealth(
            status="healthy" if applied == expected else "error",
            database="postgresql",
            applied_migrations=applied,
            expected_migrations=expected,
        )

    def get_active_guest_code(
        self,
        code_hash: str,
        now: datetime,
    ) -> dict[str, Any] | None:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id,expires_at,max_backtests_per_day,
                           max_concurrent_backtests,max_backtest_days
                    FROM guest_access_codes
                    WHERE code_hash=%s AND revoked_at IS NULL AND expires_at>%s
                    """,
                    (code_hash, now),
                )
                row = cursor.fetchone()
        return dict(row) if row else None

    def touch_guest_code(self, code_id: int, now: datetime) -> None:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE guest_access_codes SET last_used_at=%s WHERE id=%s",
                    (now, int(code_id)),
                )

    def get_active_guest_code_by_id(
        self,
        code_id: int,
        now: datetime,
    ) -> dict[str, Any] | None:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id,expires_at,max_backtests_per_day,
                           max_concurrent_backtests,max_backtest_days
                    FROM guest_access_codes
                    WHERE id=%s AND revoked_at IS NULL AND expires_at>%s
                    """,
                    (int(code_id), now),
                )
                row = cursor.fetchone()
        return dict(row) if row else None

    def record_auth_event(
        self,
        *,
        event_type: str,
        role: str,
        subject_id: str | None,
        guest_code_id: int | None,
        success: bool,
        reason: str | None,
        metadata: dict[str, object],
    ) -> None:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO auth_audit_events(
                        event_type,role,subject_id,guest_code_id,success,reason,metadata
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        event_type,
                        role,
                        subject_id,
                        guest_code_id,
                        bool(success),
                        reason,
                        psycopg2.extras.Json(dict(metadata)),
                    ),
                )
