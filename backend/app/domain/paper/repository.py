"""Read-only PostgreSQL Paper repository for the original BitPro live workspace."""
from __future__ import annotations

from typing import Callable

import psycopg2
import psycopg2.extras

from app.core.config import settings


PAPER_ID_SQL = "((('x'||substr(replace(i.id::text,'-',''),1,8))::bit(32)::bigint & 2147483647)::integer)"


class PaperRepository:
    def __init__(self, database_url: str | None = None, *, connection_factory: Callable[..., object] = psycopg2.connect) -> None:
        self.database_url = database_url or settings.DATABASE_URL
        self.connection_factory = connection_factory

    def _connect(self):
        if not self.database_url: raise RuntimeError("DATABASE_URL is required for the A-share Paper port")
        connection = self.connection_factory(self.database_url)
        connection.set_session(readonly=True, autocommit=False)
        return connection

    def list_instances(self) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(f"""
                    SELECT {PAPER_ID_SQL} AS id,i.id AS instance_uuid,i.name,i.status,
                           COALESCE(s.legacy_strategy_id,0) AS strategy_id,s.name AS strategy_name,
                           p.initial_cash,p.cash_balance,i.created_at,i.started_at,i.updated_at,
                           (SELECT e.equity FROM paper_equity_snapshots e WHERE e.paper_instance_id=i.id ORDER BY e.trade_date DESC,e.id DESC LIMIT 1) AS current_equity,
                           (SELECT MAX(e.drawdown) FROM paper_equity_snapshots e WHERE e.paper_instance_id=i.id) AS max_drawdown,
                           (SELECT COUNT(*) FROM trades t WHERE t.paper_instance_id=i.id) AS trade_count,
                           ARRAY(SELECT DISTINCT pos.symbol FROM positions pos WHERE pos.portfolio_id=i.portfolio_id ORDER BY pos.symbol) AS symbols
                    FROM paper_instances i JOIN portfolios p ON p.id=i.portfolio_id
                    LEFT JOIN strategy_versions s ON s.id=i.strategy_version_id
                    ORDER BY i.created_at DESC,i.id
                """)
                return [dict(row) for row in cursor.fetchall()]

    def get_instance(self, instance_id: int | str) -> dict | None:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(f"""
                    SELECT {PAPER_ID_SQL} AS id,i.id AS instance_uuid,i.name,i.status,
                           COALESCE(s.legacy_strategy_id,0) AS strategy_id,s.name AS strategy_name,
                           p.initial_cash,p.cash_balance,i.created_at,i.started_at,i.updated_at,
                           (SELECT e.equity FROM paper_equity_snapshots e WHERE e.paper_instance_id=i.id ORDER BY e.trade_date DESC,e.id DESC LIMIT 1) AS current_equity,
                           (SELECT MAX(e.drawdown) FROM paper_equity_snapshots e WHERE e.paper_instance_id=i.id) AS max_drawdown,
                           (SELECT COUNT(*) FROM trades t WHERE t.paper_instance_id=i.id) AS trade_count,
                           ARRAY(SELECT DISTINCT pos.symbol FROM positions pos WHERE pos.portfolio_id=i.portfolio_id ORDER BY pos.symbol) AS symbols
                    FROM paper_instances i JOIN portfolios p ON p.id=i.portfolio_id
                    LEFT JOIN strategy_versions s ON s.id=i.strategy_version_id
                    WHERE {PAPER_ID_SQL}=%s LIMIT 1
                """, (int(instance_id),))
                row = cursor.fetchone()
        return dict(row) if row else None

    def positions(self, instance_id: int | str) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(f"""SELECT pos.* FROM positions pos JOIN paper_instances i ON i.portfolio_id=pos.portfolio_id WHERE {PAPER_ID_SQL}=%s ORDER BY pos.symbol""", (int(instance_id),))
                return [dict(row) for row in cursor.fetchall()]

    def trades(self, instance_id: int | str, limit: int) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(f"""SELECT t.* FROM trades t JOIN paper_instances i ON i.id=t.paper_instance_id WHERE {PAPER_ID_SQL}=%s ORDER BY t.traded_at DESC,t.id DESC LIMIT %s""", (int(instance_id), max(1, min(int(limit), 500))))
                return [dict(row) for row in cursor.fetchall()]

    def events(self, instance_id: int | str, limit: int) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(f"""SELECT e.event_type,e.level,e.message,e.payload,e.occurred_at FROM paper_instance_events e JOIN paper_instances i ON i.id=e.paper_instance_id WHERE {PAPER_ID_SQL}=%s ORDER BY e.occurred_at DESC,e.id DESC LIMIT %s""", (int(instance_id), max(1, min(int(limit), 500))))
                return [dict(row) for row in cursor.fetchall()]

    def equity_curve(self, instance_id: int | str) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(f"""SELECT e.trade_date,e.equity,e.drawdown,e.cash,e.market_value FROM paper_equity_snapshots e JOIN paper_instances i ON i.id=e.paper_instance_id WHERE {PAPER_ID_SQL}=%s ORDER BY e.trade_date,e.id""", (int(instance_id),))
                return [dict(row) for row in cursor.fetchall()]
