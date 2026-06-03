from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


class _PsycopgProxy:
    def connect(self, *args, **kwargs):
        import psycopg as real_psycopg

        return real_psycopg.connect(*args, **kwargs)


psycopg = _PsycopgProxy()

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "postgres" / "migrations"


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    sql: str


def load_migrations(migrations_dir: Path = DEFAULT_MIGRATIONS_DIR) -> List[Migration]:
    """Load SQL migrations in deterministic filename order."""
    root = Path(migrations_dir)
    if not root.exists():
        return []

    migrations: List[Migration] = []
    for path in sorted(root.glob("*.sql")):
        sql = path.read_text(encoding="utf-8").strip()
        if not sql:
            continue
        migrations.append(Migration(version=path.stem, path=path, sql=sql))
    return migrations


def _ensure_migration_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def _applied_versions(cursor) -> set[str]:
    cursor.execute("SELECT version FROM schema_migrations")
    return {str(row[0]) for row in cursor.fetchall()}


def apply_migrations(
    database_url: str,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
    only: Optional[Iterable[str]] = None,
) -> List[str]:
    if not database_url:
        raise ValueError("DATABASE_URL is required to run Postgres migrations")

    selected_versions = set(only or [])
    migrations = [
        migration
        for migration in load_migrations(migrations_dir)
        if not selected_versions or migration.version in selected_versions
    ]

    applied: List[str] = []
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            _ensure_migration_table(cursor)
            existing_versions = _applied_versions(cursor)
            for migration in migrations:
                if migration.version in existing_versions:
                    continue
                cursor.execute(migration.sql)
                cursor.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (migration.version,),
                )
                applied.append(migration.version)
        connection.commit()
    return applied


def main() -> None:
    parser = argparse.ArgumentParser(description="Run StockPro Postgres migrations")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="Postgres connection URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--migrations-dir",
        default=str(DEFAULT_MIGRATIONS_DIR),
        help="Directory containing .sql migrations.",
    )
    args = parser.parse_args()

    applied = apply_migrations(
        database_url=args.database_url,
        migrations_dir=Path(args.migrations_dir),
    )
    if applied:
        print("Applied migrations:")
        for version in applied:
            print(f"- {version}")
    else:
        print("No pending migrations.")


if __name__ == "__main__":
    main()
