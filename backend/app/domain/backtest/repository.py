"""Read-only PostgreSQL repository for the original BitPro backtest UI."""
from __future__ import annotations

from typing import Callable

import psycopg2
import psycopg2.extras

from app.core.config import settings


RUN_ID_SQL = "((('x'||substr(replace(r.id::text,'-',''),1,8))::bit(32)::bigint %% 2147483647)::integer)"


class BacktestRepository:
    def __init__(self, database_url: str | None = None, *, connection_factory: Callable[..., object] = psycopg2.connect) -> None:
        self.database_url = database_url or settings.DATABASE_URL
        self.connection_factory = connection_factory

    def _connect(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for the A-share backtest port")
        connection = self.connection_factory(self.database_url)
        connection.set_session(readonly=True, autocommit=False)
        return connection

    def list_runs(self, *, limit: int, offset: int, query: str, sort_by: str, sort_dir: str) -> list[dict]:
        order_map = {
            "created": "r.created_at",
            "return": "COALESCE((r.metrics->>'strategy_return')::numeric,0)",
            "drawdown": "COALESCE((r.metrics->>'maximum_drawdown')::numeric,0)",
            "win_rate": "COALESCE((r.metrics->>'win_rate')::numeric,0)",
        }
        order = order_map.get(sort_by, "r.created_at")
        direction = "ASC" if str(sort_dir).lower() == "asc" else "DESC"
        needle = f"%{query.strip()}%"
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT {RUN_ID_SQL} AS id,r.id AS run_uuid,
                           COALESCE(s.legacy_strategy_id,0) AS strategy_id,
                           COALESCE(s.name,r.name) AS strategy_name,
                           r.status,r.metrics,r.initial_cash,r.frequency,r.start_date,r.end_date,r.created_at
                    FROM backtest_runs r
                    LEFT JOIN strategy_versions s ON s.id=r.strategy_version_id
                    WHERE (%s='' OR COALESCE(s.name,r.name) ILIKE %s OR r.status ILIKE %s)
                    ORDER BY {order} {direction},r.id DESC LIMIT %s OFFSET %s
                    """,
                    (query.strip(), needle, needle, max(1, min(int(limit), 100)), max(0, int(offset))),
                )
                return [dict(row) for row in cursor.fetchall()]

    def get_run(self, run_id: int | str) -> dict | None:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT {RUN_ID_SQL} AS id,r.id AS run_uuid,
                           COALESCE(s.legacy_strategy_id,0) AS strategy_id,
                           COALESCE(s.name,r.name) AS strategy_name,
                           r.status,r.metrics,r.initial_cash,r.frequency,r.start_date,r.end_date,r.created_at
                    FROM backtest_runs r
                    LEFT JOIN strategy_versions s ON s.id=r.strategy_version_id
                    WHERE {RUN_ID_SQL}=%s LIMIT 1
                    """,
                    (int(run_id),),
                )
                row = cursor.fetchone()
        return dict(row) if row else None

    def list_trades(self, run_id: int | str) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT t.trade_date,t.symbol,t.name,t.side,t.price,t.quantity,t.amount,
                           t.commission,t.tax,t.transfer_fee,t.slippage_cost,t.realized_pnl,t.reason
                    FROM backtest_trades t JOIN backtest_runs r ON r.id=t.backtest_run_id
                    WHERE {RUN_ID_SQL}=%s ORDER BY t.trade_date,t.id
                    """,
                    (int(run_id),),
                )
                return [dict(row) for row in cursor.fetchall()]

    def equity_curve(self, run_id: int | str) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT e.trade_date,e.equity
                    FROM backtest_daily_equity e JOIN backtest_runs r ON r.id=e.backtest_run_id
                    WHERE {RUN_ID_SQL}=%s ORDER BY e.trade_date
                    """,
                    (int(run_id),),
                )
                return [dict(row) for row in cursor.fetchall()]
