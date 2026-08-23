from __future__ import annotations

from pathlib import Path
from typing import Protocol

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
