"""Read-only PostgreSQL storage health checks."""
from __future__ import annotations

from urllib.parse import urlparse

import psycopg2

from app.core.config import settings
from app.db.postgres_migrations import load_migrations


def _database_name(database_url: str) -> str | None:
    try:
        parsed = urlparse(database_url)
    except Exception:
        return None
    name = parsed.path.lstrip("/")
    return name or None


def check_postgres_storage_health(database_url: str | None = None) -> dict[str, object]:
    """Return a bounded, read-only health payload for the configured Postgres DB."""
    url = database_url if database_url is not None else settings.DATABASE_URL
    expected_migrations = len(load_migrations())
    database = _database_name(url or "")
    if not url:
        return {
            "status": "unavailable",
            "database": database or "postgresql",
            "connected": False,
            "writes_performed": False,
            "expected_migrations": expected_migrations,
            "migration_count": 0,
            "pending_migrations": expected_migrations,
            "error_code": "database_url_missing",
        }

    try:
        connection = psycopg2.connect(url, connect_timeout=3)
        connection.set_session(readonly=True, autocommit=False)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.execute("SELECT to_regclass('public.schema_migrations')")
                migrations_table = cursor.fetchone()[0]
                migration_count = 0
                if migrations_table is not None:
                    cursor.execute("SELECT COUNT(*) FROM schema_migrations")
                    migration_count = int(cursor.fetchone()[0] or 0)
        finally:
            connection.rollback()
            connection.close()
    except Exception as exc:
        return {
            "status": "unavailable",
            "database": database or "postgresql",
            "connected": False,
            "writes_performed": False,
            "expected_migrations": expected_migrations,
            "migration_count": 0,
            "pending_migrations": expected_migrations,
            "error_code": exc.__class__.__name__,
            "error": str(exc)[:240],
        }

    pending = max(0, expected_migrations - migration_count)
    return {
        "status": "healthy" if pending == 0 else "migration_pending",
        "database": database or "postgresql",
        "connected": True,
        "writes_performed": False,
        "expected_migrations": expected_migrations,
        "migration_count": migration_count,
        "pending_migrations": pending,
    }
