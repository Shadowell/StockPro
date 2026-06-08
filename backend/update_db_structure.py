#!/usr/bin/env python3
"""
Compatibility wrapper for updating the StockPro Postgres schema.

The runtime is Postgres-only; schema changes are defined in
`backend/postgres/migrations` and applied by the shared migration runner.
"""

from app.core.config import settings
from app.db.postgres_migrations import apply_migrations


def update_database_structure() -> None:
    applied = apply_migrations(settings.DATABASE_URL)
    if applied:
        print("Applied migrations:")
        for migration in applied:
            print(f"- {migration}")
    else:
        print("Postgres schema is already up to date.")


if __name__ == "__main__":
    update_database_structure()
