import json
from datetime import date, datetime, time
from typing import Dict, List, Optional

import psycopg2
import psycopg2.extras

from app.core.config import settings


class PostgresDatabase:
    KLINE_TIMEFRAME_TABLES = {
        "1m": "kline_1m",
        "5m": "kline_5m",
        "15m": "kline_15m",
        "30m": "kline_30m",
        "1h": "kline_1h",
        "4h": "kline_4h",
        "1d": "kline_1d",
    }

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or settings.DATABASE_URL

    def get_connection(self):
        return psycopg2.connect(self.database_url)

    def init_db(self):
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(self._schema_sql())

    def clear_core_data(self):
        tables = [
            "paper_events",
            "paper_equity_curve",
            "paper_positions",
            "paper_orders",
            "paper_accounts",
            "strategy_backtest_results",
            "strategy_results",
            "strategy_scripts",
            "sync_job_items",
            "sync_jobs",
            "sync_metadata",
            "kline_history",
            "kline_1d",
            "kline_4h",
            "kline_1h",
            "kline_30m",
            "kline_15m",
            "kline_5m",
            "kline_1m",
            "stock_history",
            "stock_fundamentals",
            "market_indices_realtime",
            "all_stocks_realtime",
            "hot_concepts_realtime",
            "ths_hot_realtime",
            "short_line_indices_realtime",
            "concept_leaders_cache",
        ]
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")

    def insert_stock_history_batch(self, records: List[Dict]):
        if not records:
            return
        values = [
            (
                record["symbol"],
                record.get("name") or "",
                record["date"],
                record.get("open"),
                record.get("high"),
                record.get("low"),
                record.get("close"),
                record.get("volume"),
                record.get("turnover"),
            )
            for record in records
        ]
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO stock_history
                    (symbol, name, date, open, high, low, close, volume, turnover)
                    VALUES %s
                    ON CONFLICT (symbol, date) DO UPDATE SET
                        name = EXCLUDED.name,
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        turnover = EXCLUDED.turnover
                    """,
                    values,
                )
        self.insert_klines(records, timeframe="1d")

    def insert_klines(self, records: List[Dict], timeframe: str = "1d", exchange: str = "cn") -> int:
        if not records:
            return 0

        timeframe = self._normalize_timeframe(timeframe)
        table = self._kline_table(timeframe)
        values = [self._kline_record_tuple(record, timeframe, exchange) for record in records]
        values = [value for value in values if value is not None]
        if not values:
            return 0

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO kline_history
                    (exchange, symbol, name, timeframe, timestamp_ms, trade_date,
                     open, high, low, close, volume, turnover, source, updated_at)
                    VALUES %s
                    ON CONFLICT (exchange, symbol, timeframe, timestamp_ms) DO UPDATE SET
                        name = EXCLUDED.name,
                        trade_date = EXCLUDED.trade_date,
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        turnover = EXCLUDED.turnover,
                        source = EXCLUDED.source,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    values,
                )
                split_values = [
                    (
                        item[0],
                        item[1],
                        item[2],
                        item[4],
                        item[5],
                        item[6],
                        item[7],
                        item[8],
                        item[9],
                        item[10],
                        item[11],
                        item[12],
                        item[13],
                    )
                    for item in values
                ]
                psycopg2.extras.execute_values(
                    cursor,
                    f"""
                    INSERT INTO {table}
                    (exchange, symbol, name, timestamp_ms, trade_date,
                     open, high, low, close, volume, turnover, source, updated_at)
                    VALUES %s
                    ON CONFLICT (exchange, symbol, timestamp_ms) DO UPDATE SET
                        name = EXCLUDED.name,
                        trade_date = EXCLUDED.trade_date,
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        turnover = EXCLUDED.turnover,
                        source = EXCLUDED.source,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    split_values,
                )
                for item_exchange, symbol in sorted({(item[0], item[1]) for item in values}):
                    self._refresh_sync_metadata_cursor(cursor, item_exchange, symbol, timeframe)
        return len(values)

    def get_kline_history(
        self,
        symbol: str,
        timeframe: str = "1d",
        start_date: str = None,
        end_date: str = None,
        limit: int = None,
        exchange: str = "cn",
    ) -> List[Dict]:
        timeframe = self._normalize_timeframe(timeframe)
        table = self._kline_table(timeframe)
        params: List = [exchange, symbol]
        where = "WHERE exchange = %s AND symbol = %s"
        if start_date:
            where += " AND trade_date >= %s"
            params.append(start_date)
        if end_date:
            where += " AND trade_date <= %s"
            params.append(end_date)
        limit_sql = ""
        if limit:
            limit_sql = " LIMIT %s"
            params.append(int(limit))

        query = f"""
            SELECT exchange, symbol, name, timestamp_ms AS timestamp, trade_date AS date,
                   open, high, low, close, volume, turnover, source, updated_at
            FROM {table}
            {where}
            ORDER BY trade_date ASC, timestamp_ms ASC
            {limit_sql}
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()

        if not rows:
            rows = self._get_kline_history_unified(symbol, timeframe, start_date, end_date, limit, exchange)
        if not rows and timeframe == "1d":
            return list(reversed(self.get_stock_history(symbol, start_date=start_date, end_date=end_date)))
        return [self._kline_row(row) for row in rows]

    def get_sync_metadata(
        self,
        symbol: str,
        timeframe: str = "1d",
        exchange: str = "cn",
        data_type: str = "kline",
    ) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT exchange, symbol, timeframe, data_type, first_timestamp,
                           last_timestamp, total_records, status, last_sync_at,
                           error_message, updated_at
                    FROM sync_metadata
                    WHERE exchange = %s AND symbol = %s AND timeframe = %s AND data_type = %s
                    """,
                    (exchange, symbol, self._normalize_timeframe(timeframe), data_type),
                )
                row = cursor.fetchone()
        return self._metadata_row(row) if row else None

    def update_sync_metadata(
        self,
        symbol: str,
        timeframe: str = "1d",
        exchange: str = "cn",
        data_type: str = "kline",
        first_timestamp: str = None,
        last_timestamp: str = None,
        total_records: int = 0,
        status: str = "success",
        error_message: str = None,
    ) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO sync_metadata
                    (exchange, symbol, timeframe, data_type, first_timestamp,
                     last_timestamp, total_records, status, last_sync_at, error_message)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
                    ON CONFLICT (exchange, symbol, timeframe, data_type) DO UPDATE SET
                        first_timestamp = EXCLUDED.first_timestamp,
                        last_timestamp = EXCLUDED.last_timestamp,
                        total_records = EXCLUDED.total_records,
                        status = EXCLUDED.status,
                        last_sync_at = CURRENT_TIMESTAMP,
                        error_message = EXCLUDED.error_message,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        exchange,
                        symbol,
                        self._normalize_timeframe(timeframe),
                        data_type,
                        first_timestamp,
                        last_timestamp,
                        int(total_records or 0),
                        status,
                        error_message,
                    ),
                )

    def kline_coverage(self, limit: int = 200) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT h.exchange, h.symbol, COALESCE(NULLIF(MAX(h.name), ''), h.symbol) AS name,
                           h.timeframe, COUNT(*) AS rows, MIN(h.trade_date) AS first_date,
                           MAX(h.trade_date) AS last_date, m.status, m.last_sync_at,
                           m.error_message, m.total_records
                    FROM kline_history h
                    LEFT JOIN sync_metadata m
                      ON m.exchange = h.exchange
                     AND m.symbol = h.symbol
                     AND m.timeframe = h.timeframe
                     AND m.data_type = 'kline'
                    GROUP BY h.exchange, h.symbol, h.timeframe, m.status, m.last_sync_at,
                             m.error_message, m.total_records
                    ORDER BY MAX(h.updated_at) DESC, h.symbol ASC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [
            {
                "exchange": row["exchange"],
                "symbol": row["symbol"],
                "name": row["name"],
                "timeframe": row["timeframe"],
                "rows": int(row["rows"] or 0),
                "first_date": row["first_date"].isoformat() if row["first_date"] else None,
                "last_date": row["last_date"].isoformat() if row["last_date"] else None,
                "status": row["status"],
                "last_sync_at": row["last_sync_at"].isoformat() if row["last_sync_at"] else None,
                "error_message": row["error_message"],
                "total_records": int(row["total_records"] or 0),
            }
            for row in rows
        ]

    def create_sync_job(
        self,
        job_name: str,
        symbols: List[str],
        timeframes: List[str],
        start_date: str,
        end_date: str,
        source: str = "akshare",
    ) -> int:
        symbols = [symbol for symbol in symbols if symbol]
        timeframes = [self._normalize_timeframe(timeframe) for timeframe in timeframes if timeframe]
        total_items = len(symbols) * len(timeframes)
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO sync_jobs
                    (job_name, source, start_date, end_date, status, total_items)
                    VALUES (%s, %s, %s, %s, 'pending', %s)
                    RETURNING id
                    """,
                    (job_name, source, start_date, end_date, total_items),
                )
                job_id = cursor.fetchone()[0]
                items = [
                    (job_id, "cn", symbol, timeframe, "kline", start_date, end_date, "pending")
                    for symbol in symbols
                    for timeframe in timeframes
                ]
                if items:
                    psycopg2.extras.execute_values(
                        cursor,
                        """
                        INSERT INTO sync_job_items
                        (job_id, exchange, symbol, timeframe, data_type, start_date, end_date, status)
                        VALUES %s
                        """,
                        items,
                    )
        return job_id

    def get_sync_job(self, job_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, job_name, source, start_date, end_date, status,
                           total_items, completed_items, failed_items, message,
                           created_at, started_at, finished_at, updated_at
                    FROM sync_jobs
                    WHERE id = %s
                    """,
                    (job_id,),
                )
                row = cursor.fetchone()
        return self._sync_job_row(row) if row else None

    def list_sync_jobs(self, limit: int = 20) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, job_name, source, start_date, end_date, status,
                           total_items, completed_items, failed_items, message,
                           created_at, started_at, finished_at, updated_at
                    FROM sync_jobs
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [self._sync_job_row(row) for row in rows]

    def get_sync_job_items(self, job_id: int, status: str = None) -> List[Dict]:
        query = """
            SELECT id, job_id, exchange, symbol, timeframe, data_type, start_date,
                   end_date, status, records_count, error_message, started_at,
                   finished_at, updated_at
            FROM sync_job_items
            WHERE job_id = %s
        """
        params: List = [job_id]
        if status:
            query += " AND status = %s"
            params.append(status)
        query += " ORDER BY id ASC"
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
        return [self._sync_job_item_row(row) for row in rows]

    def update_sync_job_item(
        self,
        item_id: int,
        status: str,
        records_count: int = 0,
        error_message: str = None,
    ) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE sync_job_items
                    SET status = %s,
                        records_count = %s,
                        error_message = %s,
                        started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                        finished_at = CASE WHEN %s IN ('success', 'failed') THEN CURRENT_TIMESTAMP ELSE finished_at END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (status, int(records_count or 0), error_message, status, item_id),
                )

    def update_sync_job_status(self, job_id: int, status: str, message: str = None) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE sync_jobs
                    SET status = %s,
                        message = COALESCE(%s, message),
                        started_at = CASE WHEN started_at IS NULL AND %s = 'running' THEN CURRENT_TIMESTAMP ELSE started_at END,
                        finished_at = CASE WHEN %s IN ('success', 'partial', 'failed') THEN CURRENT_TIMESTAMP ELSE finished_at END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (status, message, status, status, job_id),
                )

    def refresh_sync_job_progress(self, job_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE status = 'success') AS completed,
                        COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                        COUNT(*) FILTER (WHERE status IN ('pending', 'running')) AS active
                    FROM sync_job_items
                    WHERE job_id = %s
                    """,
                    (job_id,),
                )
                total, completed, failed, active = cursor.fetchone()
                total = int(total or 0)
                completed = int(completed or 0)
                failed = int(failed or 0)
                active = int(active or 0)
                if total == 0:
                    status = "success"
                elif active > 0 and completed + failed > 0:
                    status = "running"
                elif active > 0:
                    status = "pending"
                elif failed > 0 and completed > 0:
                    status = "partial"
                elif failed > 0:
                    status = "failed"
                else:
                    status = "success"
                cursor.execute(
                    """
                    UPDATE sync_jobs
                    SET status = %s,
                        total_items = %s,
                        completed_items = %s,
                        failed_items = %s,
                        started_at = CASE WHEN started_at IS NULL AND %s IN ('running', 'success', 'partial', 'failed') THEN CURRENT_TIMESTAMP ELSE started_at END,
                        finished_at = CASE WHEN %s IN ('success', 'partial', 'failed') THEN CURRENT_TIMESTAMP ELSE finished_at END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (status, total, completed, failed, status, status, job_id),
                )
        return self.get_sync_job(job_id)

    def get_stock_history(self, symbol: str, start_date: str = None, end_date: str = None) -> List[Dict]:
        query = """
            SELECT id, symbol, name, date, open, high, low, close, volume, turnover
            FROM stock_history
            WHERE symbol = %s
        """
        params: List = [symbol]
        if start_date:
            query += " AND date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND date <= %s"
            params.append(end_date)
        query += " ORDER BY date DESC"
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def save_strategy(
        self,
        name: str,
        script_content: str,
        description: str = "",
        interval_seconds: int = 60,
        enabled: bool = True,
    ) -> int:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO strategy_scripts
                    (name, script_content, description, interval_seconds, enabled)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (name) DO UPDATE SET
                        script_content = EXCLUDED.script_content,
                        description = EXCLUDED.description,
                        interval_seconds = EXCLUDED.interval_seconds,
                        enabled = EXCLUDED.enabled,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    (name, script_content, description, interval_seconds, enabled),
                )
                return cursor.fetchone()[0]

    def get_strategies(self) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, name, description, script_content, interval_seconds,
                           enabled, is_running, created_at, updated_at
                    FROM strategy_scripts
                    ORDER BY updated_at DESC, id DESC
                    """
                )
                rows = cursor.fetchall()
        return [self._strategy_row(row) for row in rows]

    def get_strategy_by_id(self, strategy_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, name, description, script_content, interval_seconds,
                           enabled, is_running, created_at, updated_at
                    FROM strategy_scripts
                    WHERE id = %s
                    """,
                    (strategy_id,),
                )
                row = cursor.fetchone()
        return self._strategy_row(row) if row else None

    def delete_strategy(self, strategy_id: int) -> bool:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM strategy_scripts WHERE id = %s", (strategy_id,))
                return cursor.rowcount > 0

    def save_strategy_result(
        self,
        strategy_id: int,
        status: str,
        result_data: str = None,
        error_message: str = None,
        execution_duration_ms: int = None,
    ) -> int:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO strategy_results
                    (strategy_id, status, result_data, error_message, execution_duration_ms)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (strategy_id, status, result_data, error_message, execution_duration_ms),
                )
                return cursor.fetchone()[0]

    def get_latest_strategy_result(self, strategy_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, strategy_id, execution_time, status, result_data,
                           error_message, execution_duration_ms
                    FROM strategy_results
                    WHERE strategy_id = %s
                    ORDER BY execution_time DESC, id DESC
                    LIMIT 1
                    """,
                    (strategy_id,),
                )
                row = cursor.fetchone()
        return dict(row) if row else None

    def get_running_strategies(self) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, name, description, interval_seconds, is_running
                    FROM strategy_scripts
                    WHERE is_running = TRUE
                    ORDER BY id DESC
                    """
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def update_strategy_running_status(self, strategy_id: int, is_running: bool):
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE strategy_scripts
                    SET is_running = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (is_running, strategy_id),
                )

    def init_preset_strategies(self):
        if self.get_strategies():
            return
        self.save_strategy(
            name="A股多股动量模板",
            description="Backtrader 注册策略：多股组合、100股一手、T+1、只做多。",
            script_content=self._preset_strategy_code(),
            interval_seconds=60,
        )

    def table_counts(self) -> List[Dict]:
        table_names = [
            "kline_history",
            "kline_1d",
            "kline_1m",
            "kline_5m",
            "kline_15m",
            "kline_30m",
            "kline_1h",
            "kline_4h",
            "sync_metadata",
            "sync_jobs",
            "sync_job_items",
            "market_indices_realtime",
            "all_stocks_realtime",
            "hot_concepts_realtime",
            "concept_leaders_cache",
            "strategy_scripts",
            "strategy_backtest_results",
            "paper_accounts",
            "paper_orders",
            "paper_positions",
            "paper_equity_curve",
            "paper_events",
        ]
        output = []
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                for name in table_names:
                    cursor.execute(f"SELECT COUNT(*) FROM {name}")
                    output.append({"name": name, "rows": cursor.fetchone()[0]})
        return output

    def delete_klines(self, symbol: str, timeframe: str = "1d", exchange: str = "cn") -> int:
        timeframe = self._normalize_timeframe(timeframe)
        table = self._kline_table(timeframe)
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {table} WHERE exchange = %s AND symbol = %s",
                    (exchange, symbol),
                )
                split_deleted = int(cursor.rowcount or 0)
                cursor.execute(
                    """
                    DELETE FROM kline_history
                    WHERE exchange = %s AND symbol = %s AND timeframe = %s
                    """,
                    (exchange, symbol, timeframe),
                )
                unified_deleted = int(cursor.rowcount or 0)
                cursor.execute(
                    """
                    DELETE FROM sync_metadata
                    WHERE exchange = %s AND symbol = %s AND timeframe = %s AND data_type = 'kline'
                    """,
                    (exchange, symbol, timeframe),
                )
        return max(split_deleted, unified_deleted)

    def _normalize_timeframe(self, timeframe: str) -> str:
        cleaned = str(timeframe or "1d").strip().lower()
        if cleaned in {"daily", "day", "d"}:
            cleaned = "1d"
        if cleaned in {"60m", "1hour"}:
            cleaned = "1h"
        if cleaned not in self.KLINE_TIMEFRAME_TABLES:
            raise ValueError(f"Unsupported kline timeframe: {timeframe}")
        return cleaned

    def _kline_table(self, timeframe: str) -> str:
        return self.KLINE_TIMEFRAME_TABLES[self._normalize_timeframe(timeframe)]

    def _kline_record_tuple(self, record: Dict, timeframe: str, exchange: str):
        symbol = str(record.get("symbol") or record.get("code") or "").strip()
        if not symbol:
            return None
        trade_date = self._coerce_date(record.get("trade_date") or record.get("date"))
        timestamp_ms = record.get("timestamp_ms") or record.get("timestamp")
        if timestamp_ms is None:
            timestamp_ms = self._date_to_timestamp_ms(trade_date)
        return (
            str(record.get("exchange") or exchange or "cn"),
            symbol,
            str(record.get("name") or ""),
            timeframe,
            int(timestamp_ms),
            trade_date,
            self._coerce_float(record.get("open")),
            self._coerce_float(record.get("high")),
            self._coerce_float(record.get("low")),
            self._coerce_float(record.get("close")),
            self._coerce_int(record.get("volume")),
            self._coerce_float(record.get("turnover") or record.get("amount")),
            str(record.get("source") or "akshare"),
            datetime.now(),
        )

    def _get_kline_history_unified(
        self,
        symbol: str,
        timeframe: str,
        start_date: str = None,
        end_date: str = None,
        limit: int = None,
        exchange: str = "cn",
    ) -> List[Dict]:
        params: List = [exchange, symbol, timeframe]
        where = "WHERE exchange = %s AND symbol = %s AND timeframe = %s"
        if start_date:
            where += " AND trade_date >= %s"
            params.append(start_date)
        if end_date:
            where += " AND trade_date <= %s"
            params.append(end_date)
        limit_sql = ""
        if limit:
            limit_sql = " LIMIT %s"
            params.append(int(limit))
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT exchange, symbol, name, timeframe, timestamp_ms AS timestamp,
                           trade_date AS date, open, high, low, close, volume,
                           turnover, source, updated_at
                    FROM kline_history
                    {where}
                    ORDER BY trade_date ASC, timestamp_ms ASC
                    {limit_sql}
                    """,
                    params,
                )
                return cursor.fetchall()

    def _refresh_sync_metadata_cursor(self, cursor, exchange: str, symbol: str, timeframe: str) -> None:
        cursor.execute(
            """
            SELECT MIN(trade_date), MAX(trade_date), COUNT(*)
            FROM kline_history
            WHERE exchange = %s AND symbol = %s AND timeframe = %s
            """,
            (exchange, symbol, timeframe),
        )
        first_date, last_date, total_records = cursor.fetchone()
        cursor.execute(
            """
            INSERT INTO sync_metadata
            (exchange, symbol, timeframe, data_type, first_timestamp,
             last_timestamp, total_records, status, last_sync_at, error_message)
            VALUES (%s, %s, %s, 'kline', %s, %s, %s, 'success', CURRENT_TIMESTAMP, NULL)
            ON CONFLICT (exchange, symbol, timeframe, data_type) DO UPDATE SET
                first_timestamp = EXCLUDED.first_timestamp,
                last_timestamp = EXCLUDED.last_timestamp,
                total_records = EXCLUDED.total_records,
                status = 'success',
                last_sync_at = CURRENT_TIMESTAMP,
                error_message = NULL,
                updated_at = CURRENT_TIMESTAMP
            """,
            (exchange, symbol, timeframe, first_date, last_date, int(total_records or 0)),
        )

    def _coerce_date(self, value):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value or "").strip()
        if not text:
            raise ValueError("Kline record requires trade_date/date")
        return datetime.fromisoformat(text[:10]).date()

    def _date_to_timestamp_ms(self, value: date) -> int:
        return int(datetime.combine(value, time.min).timestamp() * 1000)

    def _coerce_float(self, value, default: float = 0.0):
        try:
            if value is None:
                return default
            return float(value)
        except Exception:
            return default

    def _coerce_int(self, value, default: int = 0):
        try:
            if value is None:
                return default
            return int(float(value))
        except Exception:
            return default

    def _kline_row(self, row) -> Dict:
        date_value = row.get("date")
        updated_at = row.get("updated_at")
        return {
            "exchange": row.get("exchange") or "cn",
            "symbol": row.get("symbol"),
            "name": row.get("name") or "",
            "timestamp": int(row.get("timestamp") or 0),
            "date": date_value.isoformat() if hasattr(date_value, "isoformat") else str(date_value),
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "volume": row.get("volume") or 0,
            "turnover": row.get("turnover") or 0,
            "source": row.get("source") or "",
            "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at),
        }

    def _metadata_row(self, row) -> Dict:
        return {
            "exchange": row["exchange"],
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "data_type": row["data_type"],
            "first_timestamp": row["first_timestamp"].isoformat() if row["first_timestamp"] else None,
            "last_timestamp": row["last_timestamp"].isoformat() if row["last_timestamp"] else None,
            "total_records": int(row["total_records"] or 0),
            "status": row["status"],
            "last_sync_at": row["last_sync_at"].isoformat() if row["last_sync_at"] else None,
            "error_message": row["error_message"],
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    def _sync_job_row(self, row) -> Dict:
        return {
            "id": row["id"],
            "job_name": row["job_name"],
            "source": row["source"],
            "start_date": row["start_date"].isoformat() if row["start_date"] else None,
            "end_date": row["end_date"].isoformat() if row["end_date"] else None,
            "status": row["status"],
            "total_items": int(row["total_items"] or 0),
            "completed_items": int(row["completed_items"] or 0),
            "failed_items": int(row["failed_items"] or 0),
            "message": row["message"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    def _sync_job_item_row(self, row) -> Dict:
        return {
            "id": row["id"],
            "job_id": row["job_id"],
            "exchange": row["exchange"],
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "data_type": row["data_type"],
            "start_date": row["start_date"].isoformat() if row["start_date"] else None,
            "end_date": row["end_date"].isoformat() if row["end_date"] else None,
            "status": row["status"],
            "records_count": int(row["records_count"] or 0),
            "error_message": row["error_message"],
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    def _strategy_row(self, row) -> Dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"] or "",
            "script_content": row["script_content"],
            "interval_seconds": row["interval_seconds"],
            "enabled": bool(row["enabled"]),
            "is_running": bool(row["is_running"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    def _preset_strategy_code(self) -> str:
        return """import backtrader as bt


class AshareMomentumTemplate(bt.Strategy):
    params = dict(position_pct=0.9, max_positions=5)

    def next(self):
        open_count = sum(1 for data in self.datas if self.getposition(data).size)
        slots = max(int(self.p.max_positions) - open_count, 0)
        if slots <= 0:
            return
        candidates = []
        for data in self.datas:
            if len(data.close) < 3 or self.getposition(data).size:
                continue
            momentum = (data.close[0] - data.close[-2]) / data.close[-2] if data.close[-2] else 0
            if momentum > 0.012:
                candidates.append((momentum, data))
        candidates.sort(key=lambda item: item[0], reverse=True)
        allocation = self.broker.getcash() * self.p.position_pct / max(min(len(candidates), slots), 1)
        for _, data in candidates[:slots]:
            size = int((allocation / data.close[0]) // 100) * 100
            if size > 0:
                self.buy(data=data, size=size)
"""

    def _schema_sql(self) -> str:
        return """
        CREATE TABLE IF NOT EXISTS kline_history (
            id BIGSERIAL PRIMARY KEY,
            exchange TEXT NOT NULL DEFAULT 'cn',
            symbol TEXT NOT NULL,
            name TEXT,
            timeframe TEXT NOT NULL,
            timestamp_ms BIGINT NOT NULL,
            trade_date DATE NOT NULL,
            open DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            close DOUBLE PRECISION,
            volume BIGINT,
            turnover DOUBLE PRECISION,
            source TEXT DEFAULT 'akshare',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(exchange, symbol, timeframe, timestamp_ms)
        );

        CREATE TABLE IF NOT EXISTS kline_1m (
            id BIGSERIAL PRIMARY KEY,
            exchange TEXT NOT NULL DEFAULT 'cn',
            symbol TEXT NOT NULL,
            name TEXT,
            timestamp_ms BIGINT NOT NULL,
            trade_date DATE NOT NULL,
            open DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            close DOUBLE PRECISION,
            volume BIGINT,
            turnover DOUBLE PRECISION,
            source TEXT DEFAULT 'akshare',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(exchange, symbol, timestamp_ms)
        );

        CREATE TABLE IF NOT EXISTS kline_5m (
            id BIGSERIAL PRIMARY KEY,
            exchange TEXT NOT NULL DEFAULT 'cn',
            symbol TEXT NOT NULL,
            name TEXT,
            timestamp_ms BIGINT NOT NULL,
            trade_date DATE NOT NULL,
            open DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            close DOUBLE PRECISION,
            volume BIGINT,
            turnover DOUBLE PRECISION,
            source TEXT DEFAULT 'akshare',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(exchange, symbol, timestamp_ms)
        );

        CREATE TABLE IF NOT EXISTS kline_15m (
            id BIGSERIAL PRIMARY KEY,
            exchange TEXT NOT NULL DEFAULT 'cn',
            symbol TEXT NOT NULL,
            name TEXT,
            timestamp_ms BIGINT NOT NULL,
            trade_date DATE NOT NULL,
            open DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            close DOUBLE PRECISION,
            volume BIGINT,
            turnover DOUBLE PRECISION,
            source TEXT DEFAULT 'akshare',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(exchange, symbol, timestamp_ms)
        );

        CREATE TABLE IF NOT EXISTS kline_30m (
            id BIGSERIAL PRIMARY KEY,
            exchange TEXT NOT NULL DEFAULT 'cn',
            symbol TEXT NOT NULL,
            name TEXT,
            timestamp_ms BIGINT NOT NULL,
            trade_date DATE NOT NULL,
            open DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            close DOUBLE PRECISION,
            volume BIGINT,
            turnover DOUBLE PRECISION,
            source TEXT DEFAULT 'akshare',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(exchange, symbol, timestamp_ms)
        );

        CREATE TABLE IF NOT EXISTS kline_1h (
            id BIGSERIAL PRIMARY KEY,
            exchange TEXT NOT NULL DEFAULT 'cn',
            symbol TEXT NOT NULL,
            name TEXT,
            timestamp_ms BIGINT NOT NULL,
            trade_date DATE NOT NULL,
            open DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            close DOUBLE PRECISION,
            volume BIGINT,
            turnover DOUBLE PRECISION,
            source TEXT DEFAULT 'akshare',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(exchange, symbol, timestamp_ms)
        );

        CREATE TABLE IF NOT EXISTS kline_4h (
            id BIGSERIAL PRIMARY KEY,
            exchange TEXT NOT NULL DEFAULT 'cn',
            symbol TEXT NOT NULL,
            name TEXT,
            timestamp_ms BIGINT NOT NULL,
            trade_date DATE NOT NULL,
            open DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            close DOUBLE PRECISION,
            volume BIGINT,
            turnover DOUBLE PRECISION,
            source TEXT DEFAULT 'akshare',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(exchange, symbol, timestamp_ms)
        );

        CREATE TABLE IF NOT EXISTS kline_1d (
            id BIGSERIAL PRIMARY KEY,
            exchange TEXT NOT NULL DEFAULT 'cn',
            symbol TEXT NOT NULL,
            name TEXT,
            timestamp_ms BIGINT NOT NULL,
            trade_date DATE NOT NULL,
            open DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            close DOUBLE PRECISION,
            volume BIGINT,
            turnover DOUBLE PRECISION,
            source TEXT DEFAULT 'akshare',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(exchange, symbol, timestamp_ms)
        );

        CREATE TABLE IF NOT EXISTS sync_metadata (
            id BIGSERIAL PRIMARY KEY,
            exchange TEXT NOT NULL DEFAULT 'cn',
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            data_type TEXT NOT NULL DEFAULT 'kline',
            first_timestamp DATE,
            last_timestamp DATE,
            total_records BIGINT DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            last_sync_at TIMESTAMP,
            error_message TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(exchange, symbol, timeframe, data_type)
        );

        CREATE TABLE IF NOT EXISTS sync_jobs (
            id BIGSERIAL PRIMARY KEY,
            job_name TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'akshare',
            start_date DATE,
            end_date DATE,
            status TEXT NOT NULL DEFAULT 'pending',
            total_items INTEGER NOT NULL DEFAULT 0,
            completed_items INTEGER NOT NULL DEFAULT 0,
            failed_items INTEGER NOT NULL DEFAULT 0,
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sync_job_items (
            id BIGSERIAL PRIMARY KEY,
            job_id BIGINT NOT NULL REFERENCES sync_jobs(id) ON DELETE CASCADE,
            exchange TEXT NOT NULL DEFAULT 'cn',
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            data_type TEXT NOT NULL DEFAULT 'kline',
            start_date DATE,
            end_date DATE,
            status TEXT NOT NULL DEFAULT 'pending',
            records_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS stock_history (
            id BIGSERIAL PRIMARY KEY,
            symbol TEXT NOT NULL,
            name TEXT NOT NULL,
            date DATE NOT NULL,
            open DOUBLE PRECISION,
            high DOUBLE PRECISION,
            low DOUBLE PRECISION,
            close DOUBLE PRECISION,
            volume BIGINT,
            turnover DOUBLE PRECISION,
            UNIQUE(symbol, date)
        );

        CREATE TABLE IF NOT EXISTS stock_fundamentals (
            id BIGSERIAL PRIMARY KEY,
            symbol TEXT NOT NULL UNIQUE,
            name TEXT,
            pe DOUBLE PRECISION,
            pb DOUBLE PRECISION,
            dividend_yield DOUBLE PRECISION,
            market_cap DOUBLE PRECISION,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS market_indices_realtime (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            code TEXT,
            price DOUBLE PRECISION,
            change_amount DOUBLE PRECISION,
            change_percent DOUBLE PRECISION,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS all_stocks_realtime (
            id BIGSERIAL PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            price DOUBLE PRECISION,
            change_percent DOUBLE PRECISION,
            volume DOUBLE PRECISION,
            amount DOUBLE PRECISION,
            turnover DOUBLE PRECISION,
            volume_ratio DOUBLE PRECISION,
            pe_dynamic DOUBLE PRECISION,
            pb DOUBLE PRECISION,
            total_market_cap DOUBLE PRECISION,
            float_market_cap DOUBLE PRECISION,
            amplitude DOUBLE PRECISION,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS hot_concepts_realtime (
            id BIGSERIAL PRIMARY KEY,
            rank INTEGER,
            name TEXT NOT NULL UNIQUE,
            change_percent DOUBLE PRECISION,
            inflow DOUBLE PRECISION,
            outflow DOUBLE PRECISION,
            net_inflow DOUBLE PRECISION,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS ths_hot_realtime (
            id BIGSERIAL PRIMARY KEY,
            rank INTEGER,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            hot_value DOUBLE PRECISION,
            change_percent DOUBLE PRECISION,
            price DOUBLE PRECISION,
            reason TEXT,
            tags TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS short_line_indices_realtime (
            id BIGSERIAL PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            price DOUBLE PRECISION,
            change_percent DOUBLE PRECISION,
            change_amount DOUBLE PRECISION,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS concept_leaders_cache (
            id BIGSERIAL PRIMARY KEY,
            concept_name TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            price DOUBLE PRECISION,
            change_percent DOUBLE PRECISION,
            amount DOUBLE PRECISION,
            turnover DOUBLE PRECISION,
            rank INTEGER,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(concept_name, stock_code)
        );

        CREATE TABLE IF NOT EXISTS strategy_scripts (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            script_content TEXT NOT NULL,
            interval_seconds INTEGER DEFAULT 60,
            enabled BOOLEAN DEFAULT TRUE,
            is_running BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS strategy_results (
            id BIGSERIAL PRIMARY KEY,
            strategy_id BIGINT NOT NULL REFERENCES strategy_scripts(id) ON DELETE CASCADE,
            execution_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL,
            result_data TEXT,
            error_message TEXT,
            execution_duration_ms INTEGER
        );

        CREATE TABLE IF NOT EXISTS strategy_backtest_results (
            id BIGSERIAL PRIMARY KEY,
            strategy_id BIGINT NOT NULL REFERENCES strategy_scripts(id) ON DELETE CASCADE,
            symbols TEXT NOT NULL,
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            initial_capital DOUBLE PRECISION NOT NULL,
            final_capital DOUBLE PRECISION NOT NULL,
            total_return DOUBLE PRECISION NOT NULL,
            max_drawdown DOUBLE PRECISION NOT NULL,
            win_rate DOUBLE PRECISION NOT NULL,
            total_trades INTEGER NOT NULL,
            equity_curve TEXT,
            trades TEXT,
            status TEXT NOT NULL DEFAULT 'completed',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS paper_accounts (
            id BIGSERIAL PRIMARY KEY,
            strategy_id BIGINT NOT NULL REFERENCES strategy_scripts(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            initial_capital DOUBLE PRECISION NOT NULL,
            cash DOUBLE PRECISION NOT NULL,
            equity DOUBLE PRECISION NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS paper_orders (
            id BIGSERIAL PRIMARY KEY,
            account_id BIGINT NOT NULL REFERENCES paper_accounts(id) ON DELETE CASCADE,
            strategy_id BIGINT NOT NULL REFERENCES strategy_scripts(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            name TEXT,
            side TEXT NOT NULL,
            price DOUBLE PRECISION NOT NULL,
            quantity INTEGER NOT NULL,
            amount DOUBLE PRECISION NOT NULL,
            fee DOUBLE PRECISION NOT NULL,
            status TEXT NOT NULL DEFAULT 'filled',
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS paper_positions (
            id BIGSERIAL PRIMARY KEY,
            account_id BIGINT NOT NULL REFERENCES paper_accounts(id) ON DELETE CASCADE,
            strategy_id BIGINT NOT NULL REFERENCES strategy_scripts(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            name TEXT,
            quantity INTEGER NOT NULL,
            avg_price DOUBLE PRECISION NOT NULL,
            last_price DOUBLE PRECISION NOT NULL,
            market_value DOUBLE PRECISION NOT NULL,
            pnl DOUBLE PRECISION NOT NULL,
            pnl_pct DOUBLE PRECISION NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(account_id, symbol)
        );

        CREATE TABLE IF NOT EXISTS paper_equity_curve (
            id BIGSERIAL PRIMARY KEY,
            account_id BIGINT NOT NULL REFERENCES paper_accounts(id) ON DELETE CASCADE,
            equity DOUBLE PRECISION NOT NULL,
            cash DOUBLE PRECISION NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS paper_events (
            id BIGSERIAL PRIMARY KEY,
            account_id BIGINT NOT NULL REFERENCES paper_accounts(id) ON DELETE CASCADE,
            level TEXT NOT NULL DEFAULT 'info',
            message TEXT NOT NULL,
            payload TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_stock_history_symbol_date ON stock_history(symbol, date);
        CREATE INDEX IF NOT EXISTS idx_kline_history_symbol_tf_date ON kline_history(symbol, timeframe, trade_date);
        CREATE INDEX IF NOT EXISTS idx_kline_history_exchange_symbol_tf_ts ON kline_history(exchange, symbol, timeframe, timestamp_ms);
        CREATE INDEX IF NOT EXISTS idx_kline_1m_symbol_date ON kline_1m(symbol, trade_date);
        CREATE INDEX IF NOT EXISTS idx_kline_5m_symbol_date ON kline_5m(symbol, trade_date);
        CREATE INDEX IF NOT EXISTS idx_kline_15m_symbol_date ON kline_15m(symbol, trade_date);
        CREATE INDEX IF NOT EXISTS idx_kline_30m_symbol_date ON kline_30m(symbol, trade_date);
        CREATE INDEX IF NOT EXISTS idx_kline_1h_symbol_date ON kline_1h(symbol, trade_date);
        CREATE INDEX IF NOT EXISTS idx_kline_4h_symbol_date ON kline_4h(symbol, trade_date);
        CREATE INDEX IF NOT EXISTS idx_kline_1d_symbol_date ON kline_1d(symbol, trade_date);
        CREATE INDEX IF NOT EXISTS idx_sync_metadata_symbol_tf ON sync_metadata(symbol, timeframe);
        CREATE INDEX IF NOT EXISTS idx_sync_jobs_status ON sync_jobs(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_sync_job_items_job_status ON sync_job_items(job_id, status);
        CREATE INDEX IF NOT EXISTS idx_concept_leaders_name ON concept_leaders_cache(concept_name);
        CREATE INDEX IF NOT EXISTS idx_strategy_results_strategy_id ON strategy_results(strategy_id);
        CREATE INDEX IF NOT EXISTS idx_backtest_strategy_id ON strategy_backtest_results(strategy_id);
        CREATE INDEX IF NOT EXISTS idx_paper_accounts_strategy_id ON paper_accounts(strategy_id);
        CREATE INDEX IF NOT EXISTS idx_paper_orders_account_id ON paper_orders(account_id);
        CREATE INDEX IF NOT EXISTS idx_paper_positions_account_id ON paper_positions(account_id);
        CREATE INDEX IF NOT EXISTS idx_paper_equity_account_id ON paper_equity_curve(account_id);
        CREATE INDEX IF NOT EXISTS idx_paper_events_account_id ON paper_events(account_id);
        """


def encode_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)
