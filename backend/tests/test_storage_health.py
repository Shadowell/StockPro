from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core import storage_health  # noqa: E402


def test_storage_health_reports_missing_database_url(monkeypatch) -> None:
    monkeypatch.setattr(storage_health, "load_migrations", lambda: [object(), object()])

    payload = storage_health.check_postgres_storage_health("")

    assert payload["status"] == "unavailable"
    assert payload["connected"] is False
    assert payload["writes_performed"] is False
    assert payload["error_code"] == "database_url_missing"
    assert payload["pending_migrations"] == 2


def test_storage_health_uses_read_only_postgres_probe(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql):
            calls.append(("execute", sql))

        def fetchone(self):
            if "to_regclass" in calls[-1][1]:
                return ("schema_migrations",)
            return (3,)

    class Connection:
        def set_session(self, **kwargs):
            calls.append(("set_session", kwargs))

        def cursor(self):
            return Cursor()

        def rollback(self):
            calls.append(("rollback", True))

        def close(self):
            calls.append(("close", True))

    def connect(url, **kwargs):
        calls.append(("connect", {"url": url, **kwargs}))
        return Connection()

    monkeypatch.setattr(storage_health, "load_migrations", lambda: [1, 2, 3])
    monkeypatch.setattr(storage_health.psycopg2, "connect", connect)

    payload = storage_health.check_postgres_storage_health(
        "postgresql://stockpro:stockpro@127.0.0.1:55432/stockpro_bitpro_rebase_dev"
    )

    assert payload["status"] == "healthy"
    assert payload["database"] == "stockpro_bitpro_rebase_dev"
    assert payload["connected"] is True
    assert payload["writes_performed"] is False
    assert payload["expected_migrations"] == 3
    assert payload["migration_count"] == 3
    assert ("set_session", {"readonly": True, "autocommit": False}) in calls
    assert ("rollback", True) in calls
