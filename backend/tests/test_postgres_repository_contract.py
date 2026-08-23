from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.repositories.postgres_repository import PostgresRepository


class FakeCursor:
    def __init__(self, count: int) -> None:
        self.count = count
        self.queries: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query: str) -> None:
        assert query.strip().lower().startswith("select")
        self.queries.append(query)

    def fetchone(self):
        return (self.count,)


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor


class FakeDatabase:
    def __init__(self, count: int) -> None:
        self.cursor = FakeCursor(count)

    def get_connection(self) -> FakeConnection:
        return FakeConnection(self.cursor)


def test_storage_health_reads_postgres_migrations(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for index in range(37):
        (migrations / f"{index:04d}_migration.sql").write_text("SELECT 1;", encoding="utf-8")
    repository = PostgresRepository(FakeDatabase(37), migrations_dir=migrations)

    health = repository.storage_health()

    assert health.database == "postgresql"
    assert health.applied_migrations == 37
    assert health.expected_migrations == 37
    assert health.status == "healthy"
    assert len(repository.database.cursor.queries) == 1


def test_storage_health_reports_migration_drift(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for index in range(37):
        (migrations / f"{index:04d}_migration.sql").write_text("SELECT 1;", encoding="utf-8")

    health = PostgresRepository(FakeDatabase(36), migrations_dir=migrations).storage_health()

    assert health.status == "error"
    assert health.applied_migrations == 36
    assert health.expected_migrations == 37
