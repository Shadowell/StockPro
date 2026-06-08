#!/usr/bin/env python3
"""
Apply all StockPro Postgres migrations.

This compatibility entrypoint replaces the old local-file migration helper so
operators can still run `python apply_migration.py` from the backend directory.
"""

from app.core.config import settings
from app.db.postgres_migrations import apply_migrations


def main() -> None:
    applied = apply_migrations(settings.DATABASE_URL)
    if applied:
        print("Applied migrations:")
        for migration in applied:
            print(f"- {migration}")
    else:
        print("No pending Postgres migrations.")


if __name__ == "__main__":
    main()
