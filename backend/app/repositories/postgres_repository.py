from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from typing import Protocol

import psycopg2.extras

from app.db.postgres_migrations import DEFAULT_MIGRATIONS_DIR, load_migrations
from app.domain.instruments.models import InstrumentContract
from app.domain.research.models import (
    IndexView,
    InstrumentDetailView,
    LimitEcologyView,
    MarketBreadthView,
    MarketOverviewView,
    SectorFlowView,
    TurnoverView,
)
from app.repositories.protocols import StorageHealth


class DatabaseConnectionProvider(Protocol):
    def get_connection(self): ...


class PostgresRepository:
    def __init__(
        self,
        database: DatabaseConnectionProvider,
        *,
        migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
    ) -> None:
        self.database = database
        self.migrations_dir = Path(migrations_dir)

    def storage_health(self) -> StorageHealth:
        expected = len(load_migrations(self.migrations_dir))
        try:
            with self.database.get_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*)::integer FROM schema_migrations")
                    row = cursor.fetchone()
            applied = int(row[0]) if row else 0
        except Exception:
            return StorageHealth(
                status="error",
                database="postgresql",
                applied_migrations=0,
                expected_migrations=expected,
            )
        return StorageHealth(
            status="healthy" if applied == expected else "error",
            database="postgresql",
            applied_migrations=applied,
            expected_migrations=expected,
        )

    def get_active_guest_code(
        self,
        code_hash: str,
        now: datetime,
    ) -> dict[str, Any] | None:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id,expires_at,max_backtests_per_day,
                           max_concurrent_backtests,max_backtest_days
                    FROM guest_access_codes
                    WHERE code_hash=%s AND revoked_at IS NULL AND expires_at>%s
                    """,
                    (code_hash, now),
                )
                row = cursor.fetchone()
        return dict(row) if row else None

    def touch_guest_code(self, code_id: int, now: datetime) -> None:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE guest_access_codes SET last_used_at=%s WHERE id=%s",
                    (now, int(code_id)),
                )

    def get_active_guest_code_by_id(
        self,
        code_id: int,
        now: datetime,
    ) -> dict[str, Any] | None:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id,expires_at,max_backtests_per_day,
                           max_concurrent_backtests,max_backtest_days
                    FROM guest_access_codes
                    WHERE id=%s AND revoked_at IS NULL AND expires_at>%s
                    """,
                    (int(code_id), now),
                )
                row = cursor.fetchone()
        return dict(row) if row else None

    def record_auth_event(
        self,
        *,
        event_type: str,
        role: str,
        subject_id: str | None,
        guest_code_id: int | None,
        success: bool,
        reason: str | None,
        metadata: dict[str, object],
    ) -> None:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO auth_audit_events(
                        event_type,role,subject_id,guest_code_id,success,reason,metadata
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        event_type,
                        role,
                        subject_id,
                        guest_code_id,
                        bool(success),
                        reason,
                        psycopg2.extras.Json(dict(metadata)),
                    ),
                )

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        return None if value is None else Decimal(str(value))

    @staticmethod
    def _instrument_parts(raw_code: str) -> tuple[str, str, str]:
        raw = str(raw_code or "").strip().upper()
        if raw.startswith(("SH_", "SZ_", "BJ_")):
            exchange, digits = raw.split("_", 1)
        elif "." in raw:
            digits, exchange = raw.rsplit(".", 1)
        elif raw.startswith(("SH", "SZ", "BJ")) and raw[2:].isdigit():
            exchange, digits = raw[:2], raw[2:]
        else:
            digits = raw
            exchange = "SH" if digits.startswith(("5", "6", "9")) else (
                "BJ" if digits.startswith(("4", "8")) else "SZ"
            )
        exchange_name = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(exchange, exchange)
        return digits, exchange, exchange_name

    @classmethod
    def _instrument_from_row(
        cls,
        row: dict[str, Any],
        *,
        force_asset_class: str | None = None,
    ) -> InstrumentContract:
        digits, exchange, exchange_name = cls._instrument_parts(str(row.get("code") or ""))
        asset_class = force_asset_class or (
            "etf"
            if digits.startswith(("15", "16", "18", "50", "51", "52", "53", "56", "58"))
            else "stock"
        )
        return InstrumentContract(
            symbol=f"{digits}.{exchange}",
            name=str(row.get("name") or "") or None,
            asset_class=asset_class,  # type: ignore[arg-type]
            market="CN",
            exchange=exchange_name,
            currency="CNY",
            tick_size=Decimal("0.01"),
            lot_size=1 if asset_class == "index" else 100,
            session_calendar="CN_A_SHARE",
            shortable=False,
        )

    @staticmethod
    def _is_stale(value: datetime | None, *, hours: int = 36) -> bool:
        if value is None:
            return True
        observed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds() > hours * 3600

    def market_overview(self) -> MarketOverviewView:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT code,name,price,change_percent,updated_at FROM market_indices_realtime ORDER BY id"
                )
                index_rows = [dict(row) for row in cursor.fetchall()]
                cursor.execute(
                    """
                    SELECT id,trade_date,captured_at,status
                    FROM market_evidence_snapshots
                    WHERE status='published'
                    ORDER BY trade_date DESC,captured_at DESC,id DESC LIMIT 1
                    """
                )
                snapshot = cursor.fetchone()
                metrics: dict[str, dict[str, Any]] = {}
                sectors: list[dict[str, Any]] = []
                if snapshot:
                    cursor.execute(
                        "SELECT metric_code,value,unit,source_label FROM market_evidence_metrics WHERE snapshot_id=%s",
                        (int(snapshot["id"]),),
                    )
                    metrics = {str(row["metric_code"]): dict(row) for row in cursor.fetchall()}
                    cursor.execute(
                        """
                        SELECT sector_code,sector_name,net_flow,return_1d
                        FROM sector_evidence_rows WHERE snapshot_id=%s
                        ORDER BY ABS(COALESCE(net_flow,0)) DESC,sector_name LIMIT 20
                        """,
                        (int(snapshot["id"]),),
                    )
                    sectors = [dict(row) for row in cursor.fetchall()]
                cursor.execute(
                    "SELECT SUM(amount) AS amount,MAX(updated_at) AS updated_at FROM all_stocks_realtime"
                )
                turnover_row = dict(cursor.fetchone() or {})

        indices = tuple(
            IndexView(
                symbol=self._instrument_from_row(row, force_asset_class="index").symbol,
                name=str(row.get("name") or ""),
                value=self._decimal(row.get("price")),
                change_pct=self._decimal(row.get("change_percent")),
                source_updated_at=row.get("updated_at"),
            )
            for row in index_rows
        )
        breadth = None
        if any(code in metrics for code in ("rise_count", "flat_count", "fall_count")):
            breadth = MarketBreadthView(
                rise_count=int(metrics["rise_count"]["value"]) if metrics.get("rise_count", {}).get("value") is not None else None,
                flat_count=int(metrics["flat_count"]["value"]) if metrics.get("flat_count", {}).get("value") is not None else None,
                fall_count=int(metrics["fall_count"]["value"]) if metrics.get("fall_count", {}).get("value") is not None else None,
            )
        turnover = (
            TurnoverView(amount=self._decimal(turnover_row.get("amount")), unit="CNY")
            if turnover_row.get("amount") is not None
            else None
        )
        limit_ecology = None
        if any(code in metrics for code in ("limit_up_count", "limit_down_count", "highest_board")):
            seal_rate = self._decimal(metrics.get("seal_rate", {}).get("value"))
            limit_ecology = LimitEcologyView(
                limit_up_count=int(metrics["limit_up_count"]["value"]) if metrics.get("limit_up_count", {}).get("value") is not None else None,
                limit_down_count=int(metrics["limit_down_count"]["value"]) if metrics.get("limit_down_count", {}).get("value") is not None else None,
                max_streak=int(metrics["highest_board"]["value"]) if metrics.get("highest_board", {}).get("value") is not None else None,
                broken_board_rate=None if seal_rate is None else Decimal("100") - seal_rate,
            )
        sector_flows = tuple(
            SectorFlowView(
                sector_code=str(row.get("sector_code") or ""),
                sector_name=str(row.get("sector_name") or ""),
                net_inflow=self._decimal(row.get("net_flow")),
                change_pct=self._decimal(row.get("return_1d")),
            )
            for row in sectors
        )
        source_updated_at = snapshot.get("captured_at") if snapshot else turnover_row.get("updated_at")
        has_core = bool(indices or breadth or turnover or limit_ecology)
        data_status = "empty" if not has_core else (
            "stale" if self._is_stale(source_updated_at) else (
                "partial" if not sector_flows else "fresh"
            )
        )
        return MarketOverviewView(
            indices=indices,
            breadth=breadth,
            turnover=turnover,
            limit_ecology=limit_ecology,
            sector_flows=sector_flows,
            source_label="PostgreSQL market cache + sealed evidence",
            source_updated_at=source_updated_at,
            trade_date=snapshot.get("trade_date") if snapshot else None,
            data_status=data_status,  # type: ignore[arg-type]
        )

    def search_instruments(
        self,
        query: str,
        asset_class: str | None,
        limit: int,
    ) -> list[InstrumentContract]:
        needle = str(query or "").strip()
        bounded = max(1, min(int(limit), 100))
        items: list[InstrumentContract] = []
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                if asset_class in (None, "stock", "etf"):
                    cursor.execute(
                        """
                        SELECT code,name FROM all_stocks_realtime
                        WHERE (%s='' OR code ILIKE %s OR name ILIKE %s)
                        ORDER BY CASE WHEN code ILIKE %s THEN 0 ELSE 1 END,code LIMIT %s
                        """,
                        (needle, f"%{needle}%", f"%{needle}%", f"%{needle}%", bounded * 3),
                    )
                    for row in cursor.fetchall():
                        item = self._instrument_from_row(dict(row))
                        if asset_class is None or item.asset_class == asset_class:
                            items.append(item)
                            if len(items) >= bounded:
                                break
                if len(items) < bounded and asset_class in (None, "index"):
                    cursor.execute(
                        """
                        SELECT code,name FROM market_indices_realtime
                        WHERE (%s='' OR code ILIKE %s OR name ILIKE %s)
                        ORDER BY id LIMIT %s
                        """,
                        (needle, f"%{needle}%", f"%{needle}%", bounded - len(items)),
                    )
                    items.extend(
                        self._instrument_from_row(dict(row), force_asset_class="index")
                        for row in cursor.fetchall()
                    )
        return items[:bounded]

    def instrument_detail(self, symbol: str) -> InstrumentDetailView | None:
        digits, exchange, _ = self._instrument_parts(symbol)
        raw_code = f"{exchange}_{digits}"
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT code,name,price,change_percent,amount,updated_at
                    FROM all_stocks_realtime WHERE code IN (%s,%s) LIMIT 1
                    """,
                    (raw_code, digits),
                )
                row = cursor.fetchone()
                force_asset_class = None
                if not row:
                    index_code = f"{exchange.lower()}{digits}"
                    cursor.execute(
                        """
                        SELECT code,name,price,change_percent,NULL::double precision AS amount,updated_at
                        FROM market_indices_realtime WHERE LOWER(code)=LOWER(%s) LIMIT 1
                        """,
                        (index_code,),
                    )
                    row = cursor.fetchone()
                    force_asset_class = "index"
        if not row:
            return None
        payload = dict(row)
        updated_at = payload.get("updated_at")
        return InstrumentDetailView(
            instrument=self._instrument_from_row(payload, force_asset_class=force_asset_class),
            latest_price=self._decimal(payload.get("price")),
            change_pct=self._decimal(payload.get("change_percent")),
            turnover=self._decimal(payload.get("amount")),
            source_updated_at=updated_at,
            trade_date=None,
            data_status="stale" if self._is_stale(updated_at) else "fresh",
        )

    def daily_bars(self, symbol: str, limit: int) -> list[dict[str, Any]]:
        digits, exchange, _ = self._instrument_parts(symbol)
        raw_symbol = f"{exchange}_{digits}"
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT date,open,high,low,close,volume,turnover
                    FROM stock_history WHERE symbol IN (%s,%s)
                    ORDER BY date DESC LIMIT %s
                    """,
                    (raw_symbol, digits, max(1, min(int(limit), 2000))),
                )
                rows = [dict(row) for row in cursor.fetchall()]
        rows.reverse()
        return rows

    def list_watchlist(self, owner: str) -> list[dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT w.id,w.owner,w.symbol,w.note,w.created_at,w.updated_at,
                           r.name,r.price,r.change_percent,r.updated_at AS quote_updated_at
                    FROM market_watchlist_entries w
                    LEFT JOIN all_stocks_realtime r
                      ON r.code IN (
                        SPLIT_PART(w.symbol,'.',1),
                        SPLIT_PART(w.symbol,'.',2) || '_' || SPLIT_PART(w.symbol,'.',1)
                      )
                    WHERE w.owner=%s ORDER BY w.created_at DESC,w.id DESC
                    """,
                    (owner,),
                )
                return [dict(row) for row in cursor.fetchall()]

    def upsert_watchlist(self, owner: str, symbol: str, note: str) -> dict[str, Any]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO market_watchlist_entries(owner,symbol,note)
                    VALUES (%s,%s,%s)
                    ON CONFLICT(owner,symbol) DO UPDATE
                    SET note=EXCLUDED.note,updated_at=NOW()
                    RETURNING id,owner,symbol,note,created_at,updated_at
                    """,
                    (owner, symbol, note),
                )
                return dict(cursor.fetchone())

    def delete_watchlist(self, owner: str, entry_id: int) -> bool:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM market_watchlist_entries WHERE owner=%s AND id=%s",
                    (owner, int(entry_id)),
                )
                return cursor.rowcount > 0
