#!/usr/bin/env python3
"""Create stockpro_bitpro_rebase_dev and optionally apply migrations."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse


ISOLATION_DB = "stockpro_bitpro_rebase_dev"
DEFAULT_ADMIN_URL = "postgresql://stockpro:stockpro@127.0.0.1:55432/postgres"
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def isolation_url(admin_url: str) -> str:
    parsed = urlparse(admin_url)
    if not parsed.netloc:
        return f"{parsed.scheme}:///{ISOLATION_DB}"
    return urlunparse(parsed._replace(path=f"/{ISOLATION_DB}"))


def _connect(url: str, autocommit: bool = False):
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required. Install backend requirements first.") from exc
    return psycopg.connect(url, autocommit=autocommit)


def database_exists(admin_url: str) -> bool:
    with _connect(admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (ISOLATION_DB,))
            return cursor.fetchone() is not None


def create_database(admin_url: str) -> bool:
    if database_exists(admin_url):
        return False
    with _connect(admin_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE "{ISOLATION_DB}" OWNER CURRENT_USER')
    return True


def apply_migrations(database_url: str) -> list[str]:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from app.db.postgres_migrations import apply_migrations as run_migrations

    return run_migrations(database_url)


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision the StockPro isolation database")
    parser.add_argument(
        "--admin-url",
        default=os.environ.get("DATABASE_ADMIN_URL") or os.environ.get("POSTGRES_ADMIN_URL") or DEFAULT_ADMIN_URL,
        help="Maintenance Postgres URL.",
    )
    parser.add_argument("--migrate", action="store_true", help="Apply backend/postgres/migrations after create.")
    parser.add_argument("--print-url", action="store_true", help="Print the isolation DATABASE_URL and exit.")
    args = parser.parse_args()

    target_url = isolation_url(args.admin_url)
    if args.print_url:
        print(target_url)
        return 0

    created = create_database(args.admin_url)
    print(f"[provision] {'created' if created else 'already exists'}: {ISOLATION_DB}")
    print(f"[provision] DATABASE_URL={target_url}")

    if args.migrate:
        applied = apply_migrations(target_url)
        print(f"[provision] applied {len(applied)} migrations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
