from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.core.config import settings


class AshareInstrumentRepository:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or settings.DATABASE_URL

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def begin_run(self, trigger: str) -> int | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE a_share_daily_sync_runs
                    SET status='interrupted', finished_at=NOW(), updated_at=NOW(),
                        error_message=COALESCE(error_message,'进程中断后自动收敛')
                    WHERE status='running' AND started_at < NOW() - INTERVAL '2 hours'
                    """
                )
                try:
                    cursor.execute(
                        """
                        INSERT INTO a_share_daily_sync_runs(trigger,status)
                        VALUES (%s,'running') RETURNING id
                        """,
                        (trigger,),
                    )
                    run_id = int(cursor.fetchone()["id"])
                except psycopg.errors.UniqueViolation:
                    connection.rollback()
                    return None
            connection.commit()
        return run_id

    def complete_run(
        self,
        run_id: int,
        instruments: list[dict[str, Any]],
        daily_rows: list[dict[str, Any]],
        trade_date: str | None,
    ) -> dict[str, Any]:
        instrument_values = [
            (
                "CN", row["exchange"], row["symbol"], row["name"], "stock", "CNY",
                0.01, 100, "CN_A_SHARE", False, "tushare.stock_basic",
                row.get("industry"), row.get("board"), row.get("list_status") or "L",
                row.get("list_date"), row.get("delist_date"), row.get("is_hs"),
            )
            for row in instruments
        ]
        history_values = [
            (
                row["storage_symbol"], row["name"], row["trade_date"], row.get("open"),
                row.get("high"), row.get("low"), row.get("close"), row.get("volume"), row.get("amount"),
            )
            for row in daily_rows
        ]
        realtime_values = []
        for row in daily_rows:
            pre_close = row.get("pre_close")
            amplitude = None
            if pre_close and row.get("high") is not None and row.get("low") is not None:
                amplitude = (float(row["high"]) - float(row["low"])) / float(pre_close) * 100
            realtime_values.append((
                row["storage_symbol"], row["name"], row.get("close"), row.get("change_percent"),
                row.get("volume"), row.get("amount"), row.get("turnover_rate"), row.get("volume_ratio"),
                row.get("pe"), row.get("pb"), row.get("total_market_cap"), row.get("float_market_cap"),
                amplitude,
            ))

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO instrument_definitions(
                        market,exchange,symbol,name,asset_class,currency,tick_size,lot_size,
                        session_calendar,shortable,source_label,industry,board,list_status,
                        list_date,delist_date,is_hs,updated_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                    ON CONFLICT(market,exchange,symbol) DO UPDATE SET
                        name=EXCLUDED.name, asset_class='stock', currency='CNY', tick_size=0.01,
                        lot_size=100, session_calendar='CN_A_SHARE', shortable=FALSE,
                        source_label=EXCLUDED.source_label, industry=EXCLUDED.industry,
                        board=EXCLUDED.board, list_status=EXCLUDED.list_status,
                        list_date=EXCLUDED.list_date, delist_date=EXCLUDED.delist_date,
                        is_hs=EXCLUDED.is_hs, updated_at=NOW()
                    """,
                    instrument_values,
                )
                cursor.executemany(
                    """
                    INSERT INTO stock_history(symbol,name,date,open,high,low,close,volume,turnover)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(symbol,date) DO UPDATE SET
                        name=EXCLUDED.name,open=EXCLUDED.open,high=EXCLUDED.high,low=EXCLUDED.low,
                        close=EXCLUDED.close,volume=EXCLUDED.volume,turnover=EXCLUDED.turnover
                    """,
                    history_values,
                )
                cursor.executemany(
                    """
                    INSERT INTO all_stocks_realtime(
                        code,name,price,change_percent,volume,amount,turnover,volume_ratio,
                        pe_dynamic,pb,total_market_cap,float_market_cap,amplitude,updated_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                    ON CONFLICT(code) DO UPDATE SET
                        name=EXCLUDED.name,price=EXCLUDED.price,change_percent=EXCLUDED.change_percent,
                        volume=EXCLUDED.volume,amount=EXCLUDED.amount,turnover=EXCLUDED.turnover,
                        volume_ratio=EXCLUDED.volume_ratio,pe_dynamic=EXCLUDED.pe_dynamic,pb=EXCLUDED.pb,
                        total_market_cap=EXCLUDED.total_market_cap,float_market_cap=EXCLUDED.float_market_cap,
                        amplitude=EXCLUDED.amplitude,updated_at=NOW()
                    """,
                    realtime_values,
                )
                cursor.execute(
                    """
                    UPDATE a_share_daily_sync_runs
                    SET status='success',trade_date=%s,instrument_count=%s,daily_count=%s,
                        error_message=NULL,finished_at=NOW(),updated_at=NOW()
                    WHERE id=%s
                    """,
                    (trade_date, len(instruments), len(daily_rows), run_id),
                )
            connection.commit()
        return {
            "run_id": run_id,
            "status": "success",
            "instrument_count": len(instruments),
            "daily_count": len(daily_rows),
            "trade_date": trade_date,
        }

    def fail_run(self, run_id: int, error: Exception) -> None:
        message = str(error)
        token = str(settings.TUSHARE_TOKEN or "").strip()
        if token:
            message = message.replace(token, "<redacted>")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE a_share_daily_sync_runs
                SET status='failed',error_message=%s,finished_at=NOW(),updated_at=NOW()
                WHERE id=%s
                """,
                (message[:1000], run_id),
            )
            connection.commit()

    def list_instruments(self, *, active_only: bool = True, limit: int = 10000) -> list[dict[str, Any]]:
        query = """
            SELECT symbol,name,exchange,asset_class,industry,board,list_status,list_date,delist_date,updated_at
            FROM instrument_definitions
            WHERE market='CN' AND asset_class IN ('stock','etf','index')
        """
        params: list[Any] = []
        if active_only:
            query += " AND list_status IN ('L','P')"
        query += " ORDER BY CASE asset_class WHEN 'stock' THEN 0 WHEN 'etf' THEN 1 ELSE 2 END,exchange,symbol LIMIT %s"
        params.append(max(1, min(int(limit), 20000)))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
        return [
            {
                "symbol": str(row["symbol"]),
                "name": str(row["name"] or ""),
                "display_name": f"{str(row['name'] or '').strip()} {row['symbol']}".strip(),
                "exchange": row["exchange"],
                "asset_class": row["asset_class"],
                "industry": row["industry"],
                "board": row["board"],
                "list_status": row["list_status"],
                "list_date": row["list_date"].isoformat() if row["list_date"] else None,
                "delist_date": row["delist_date"].isoformat() if row["delist_date"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
            for row in rows
        ]

    def lookup_names(self, symbols: list[str]) -> dict[str, str]:
        raw_symbols = [str(item or "").strip().upper() for item in symbols if str(item or "").strip()]
        canonical: dict[str, str] = {}
        for raw in raw_symbols:
            if "_" in raw:
                exchange, digits = raw.split("_", 1)
                canonical[raw] = f"{digits}.{exchange}"
            elif "." in raw:
                canonical[raw] = raw
            elif raw.isdigit() and len(raw) == 6:
                suffix = "SH" if raw.startswith(("5", "6", "9")) else ("BJ" if raw.startswith(("4", "8")) else "SZ")
                canonical[raw] = f"{raw}.{suffix}"
        if not canonical:
            return {}
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT symbol,name FROM instrument_definitions WHERE market='CN' AND symbol=ANY(%s)",
                    (sorted(set(canonical.values())),),
                )
                by_symbol = {str(row["symbol"]): str(row["name"] or "") for row in cursor.fetchall() if row["name"]}
        result: dict[str, str] = {}
        for raw, normalized in canonical.items():
            name = by_symbol.get(normalized)
            if name:
                result[raw] = name
                result[normalized] = name
        return result

    def latest_run(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id,trigger,status,provider,trade_date,instrument_count,daily_count,
                           error_message,started_at,finished_at
                    FROM a_share_daily_sync_runs ORDER BY id DESC LIMIT 1
                    """
                )
                row = cursor.fetchone()
        if not row:
            return None
        return {
            "run_id": int(row["id"]), "trigger": row["trigger"], "status": row["status"],
            "provider": row["provider"], "trade_date": row["trade_date"].isoformat() if row["trade_date"] else None,
            "instrument_count": int(row["instrument_count"]), "daily_count": int(row["daily_count"]),
            "error_message": row["error_message"],
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
        }
