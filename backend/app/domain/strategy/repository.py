"""Read-only PostgreSQL repository for the BitPro strategy workbench port."""
from __future__ import annotations

from typing import Callable

import psycopg2
import psycopg2.extras

from app.core.config import settings


class StrategyRepository:
    def __init__(self, database_url: str | None = None, *, connection_factory: Callable[..., object] = psycopg2.connect) -> None:
        self.database_url = database_url or settings.DATABASE_URL
        self.connection_factory = connection_factory

    def _connect(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for the A-share strategy port")
        connection = self.connection_factory(self.database_url)
        connection.set_session(readonly=True, autocommit=False)
        return connection

    def list_strategies(self) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT ON (name)
                           id,legacy_strategy_id,name,version,description,script_content,
                           parameter_schema,data_dependencies,output_contract,status,
                           validation_status,created_at,updated_at
                    FROM strategy_versions
                    ORDER BY name,version DESC,created_at DESC
                    """
                )
                return [dict(row) for row in cursor.fetchall()]

    def get_strategy(self, strategy_id: int | str) -> dict | None:
        raw = str(strategy_id)
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id,legacy_strategy_id,name,version,description,script_content,
                           parameter_schema,data_dependencies,output_contract,status,
                           validation_status,created_at,updated_at
                    FROM strategy_versions
                    WHERE id::text=%s OR legacy_strategy_id::text=%s
                    ORDER BY version DESC,created_at DESC LIMIT 1
                    """,
                    (raw, raw),
                )
                row = cursor.fetchone()
        return dict(row) if row else None
