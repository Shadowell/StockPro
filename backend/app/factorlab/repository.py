"""FactorLab SQLite repositories for small online control-plane state."""

from __future__ import annotations

from typing import Optional

from app.db.local_db import LocalDatabase
from app.factorlab.engine import FactorValue


class FactorLatestRepository:
    def __init__(self, database: LocalDatabase):
        self.database = database

    def upsert(self, value: FactorValue) -> None:
        if value.computed_at is None:
            raise ValueError("factor_latest requires computed_at")
        self.database.get_connection().execute(
            """
            INSERT INTO factor_latest (
                exchange, market_type, symbol, timeframe, instance_id,
                event_time, available_at, computed_at, value, value_status,
                dataset_revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(exchange, market_type, symbol, timeframe, instance_id)
            DO UPDATE SET
                event_time = excluded.event_time,
                available_at = excluded.available_at,
                computed_at = excluded.computed_at,
                value = excluded.value,
                value_status = excluded.value_status,
                dataset_revision = excluded.dataset_revision
            WHERE excluded.event_time > factor_latest.event_time
               OR (
                    excluded.event_time = factor_latest.event_time
                    AND excluded.computed_at >= factor_latest.computed_at
               )
            """,
            (
                value.exchange,
                value.market_type,
                value.symbol,
                value.timeframe,
                value.instance_id,
                value.event_time,
                value.available_at,
                value.computed_at,
                value.value,
                value.value_status,
                value.dataset_revision,
            ),
        )
        self.database.get_connection().commit()

    def get(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
        instance_id: str,
    ) -> Optional[FactorValue]:
        row = self.database.get_connection().execute(
            """
            SELECT * FROM factor_latest
            WHERE exchange = ? AND market_type = ? AND symbol = ?
              AND timeframe = ? AND instance_id = ?
            """,
            (exchange, market_type, symbol, timeframe, instance_id),
        ).fetchone()
        if row is None:
            return None
        values = dict(row)
        return FactorValue(
            exchange=values["exchange"],
            market_type=values["market_type"],
            symbol=values["symbol"],
            timeframe=values["timeframe"],
            instance_id=values["instance_id"],
            event_time=int(values["event_time"]),
            available_at=int(values["available_at"]),
            computed_at=int(values["computed_at"]),
            value=None if values["value"] is None else float(values["value"]),
            value_status=values["value_status"],
            dataset_revision=values["dataset_revision"],
        )
