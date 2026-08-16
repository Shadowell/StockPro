import json
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional, Sequence

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

    def _fetch_all(self, query: str, params: Sequence[Any] = ()) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, tuple(params))
                return [self._dict_row(row) for row in cursor.fetchall()]

    def _fetch_one(self, query: str, params: Sequence[Any] = ()) -> Optional[Dict]:
        rows = self._fetch_all(query, params)
        return rows[0] if rows else None

    def _dict_row(self, row) -> Dict:
        output = dict(row)
        for key, value in list(output.items()):
            if isinstance(value, (datetime, date)):
                output[key] = value.isoformat()
        return output

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

    def get_market_indices_realtime(self) -> List[Dict]:
        return self._fetch_all(
            """
            SELECT name, code, price, change_amount, change_percent, updated_at
            FROM market_indices_realtime
            ORDER BY id ASC
            """
        )

    def update_market_indices_realtime(self, records: List[Dict]) -> int:
        values = []
        for record in records or []:
            name = str(record.get("name") or "").strip()
            if not name:
                continue
            values.append(
                (
                    name,
                    str(record.get("code") or ""),
                    self._coerce_float(record.get("price")),
                    self._coerce_float(record.get("change_amount")),
                    self._coerce_float(record.get("change_percent")),
                )
            )
        if not values:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO market_indices_realtime
                    (name, code, price, change_amount, change_percent)
                    VALUES %s
                    ON CONFLICT (name) DO UPDATE SET
                        code = EXCLUDED.code,
                        price = EXCLUDED.price,
                        change_amount = EXCLUDED.change_amount,
                        change_percent = EXCLUDED.change_percent,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    values,
                )
        return len(values)

    def get_short_line_indices_realtime(self) -> List[Dict]:
        return self._fetch_all(
            """
            SELECT code, name, price, change_percent, change_amount, updated_at
            FROM short_line_indices_realtime
            ORDER BY id ASC
            """
        )

    def update_short_line_indices_realtime(self, records: List[Dict]) -> int:
        values = []
        for record in records or []:
            code = str(record.get("code") or record.get("name") or "").strip()
            name = str(record.get("name") or code).strip()
            if not code or not name:
                continue
            values.append(
                (
                    code,
                    name,
                    self._coerce_float(record.get("price")),
                    self._coerce_float(record.get("change_percent")),
                    self._coerce_float(record.get("change_amount")),
                )
            )
        if not values:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM short_line_indices_realtime")
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO short_line_indices_realtime
                    (code, name, price, change_percent, change_amount)
                    VALUES %s
                    """,
                    values,
                )
        return len(values)

    def get_all_stocks_realtime(self, include_listing_status: bool = True) -> List[Dict]:
        quote_select = """
            SELECT stocks.code, stocks.name, stocks.price, stocks.change_percent,
                   stocks.volume, stocks.amount, stocks.turnover,
                   stocks.volume_ratio, stocks.pe_dynamic, stocks.pb,
                   stocks.total_market_cap, stocks.float_market_cap,
                   stocks.amplitude, stocks.updated_at
        """
        if not include_listing_status:
            return self._fetch_all(
                f"""
                {quote_select}
                FROM all_stocks_realtime stocks
                ORDER BY stocks.amount DESC NULLS LAST, stocks.code ASC
                """
            )
        return self._fetch_all(
            f"""
            WITH latest_status AS (
                SELECT DISTINCT ON (symbol)
                       symbol, effective_from, listing_status, is_st
                FROM security_status_history
                WHERE effective_from <= CURRENT_DATE
                  AND (effective_to IS NULL OR effective_to >= CURRENT_DATE)
                ORDER BY symbol, effective_from DESC, id DESC
            ), recent_open_days AS (
                SELECT DISTINCT (records.payload->>'trade_date')::DATE AS trade_date
                FROM dataset_partition_records records
                JOIN dataset_partitions partitions ON partitions.id = records.partition_id
                JOIN dataset_definitions datasets ON datasets.id = partitions.dataset_id
                WHERE datasets.code = 'trade_calendar'
                  AND partitions.status = 'published'
                  AND records.payload ? 'trade_date'
                  AND LOWER(COALESCE(records.payload->>'is_open', 'false'))
                      IN ('1', 'true', 't', 'y', 'yes', 'open')
                  AND (records.payload->>'trade_date')::DATE
                      BETWEEN CURRENT_DATE - INTERVAL '90 days' AND CURRENT_DATE
            )
            {quote_select},
                   status.effective_from AS list_date,
                   status.listing_status,
                   status.is_st,
                   CASE
                     WHEN status.effective_from IS NULL THEN NULL
                     WHEN status.effective_from < CURRENT_DATE - INTERVAL '90 days' THEN 6
                     WHEN NOT EXISTS (
                         SELECT 1 FROM recent_open_days open_day
                         WHERE open_day.trade_date >= status.effective_from
                           AND open_day.trade_date <= LEAST(
                               COALESCE(stocks.updated_at::DATE, CURRENT_DATE),
                               CURRENT_DATE
                           )
                     ) THEN NULL
                     ELSE (
                         SELECT COUNT(*)::INTEGER FROM recent_open_days open_day
                         WHERE open_day.trade_date >= status.effective_from
                           AND open_day.trade_date <= LEAST(
                               COALESCE(stocks.updated_at::DATE, CURRENT_DATE),
                               CURRENT_DATE
                           )
                     )
                   END AS listing_trade_days
            FROM all_stocks_realtime stocks
            LEFT JOIN latest_status status
              ON status.symbol = CASE
                   WHEN LEFT(UPPER(stocks.code), 3) IN ('SH_', 'SZ_', 'BJ_')
                     THEN UPPER(stocks.code)
                   WHEN LEFT(RIGHT(REGEXP_REPLACE(stocks.code, '\\D', '', 'g'), 6), 1)
                        IN ('4', '8')
                     OR LEFT(RIGHT(REGEXP_REPLACE(stocks.code, '\\D', '', 'g'), 6), 2) = '92'
                     THEN 'BJ_' || RIGHT(REGEXP_REPLACE(stocks.code, '\\D', '', 'g'), 6)
                   WHEN LEFT(RIGHT(REGEXP_REPLACE(stocks.code, '\\D', '', 'g'), 6), 1)
                        IN ('6', '9')
                     THEN 'SH_' || RIGHT(REGEXP_REPLACE(stocks.code, '\\D', '', 'g'), 6)
                   ELSE 'SZ_' || RIGHT(REGEXP_REPLACE(stocks.code, '\\D', '', 'g'), 6)
                 END
            ORDER BY stocks.amount DESC NULLS LAST, stocks.code ASC
            """
        )

    def update_all_stocks_realtime(self, records: List[Dict]) -> int:
        values = []
        for record in records or []:
            code = self._normalize_stock_code(record.get("code") or record.get("symbol"))
            name = str(record.get("name") or record.get("stock_name") or "").strip()
            if not code or not name:
                continue
            values.append(
                (
                    code,
                    name,
                    self._coerce_float(record.get("price") or record.get("current_price")),
                    self._coerce_float(record.get("change_percent")),
                    self._coerce_float(record.get("volume")),
                    self._coerce_float(record.get("amount")),
                    self._coerce_float(record.get("turnover") or record.get("turnover_rate")),
                    self._coerce_float(record.get("volume_ratio")),
                    self._coerce_float(record.get("pe_dynamic") or record.get("pe_ttm")),
                    self._coerce_float(record.get("pb")),
                    self._coerce_float(record.get("total_market_cap") or record.get("total_mv")),
                    self._coerce_float(record.get("float_market_cap") or record.get("circ_mv")),
                    self._coerce_float(record.get("amplitude")),
                )
            )
        if not values:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO all_stocks_realtime
                    (code, name, price, change_percent, volume, amount, turnover,
                     volume_ratio, pe_dynamic, pb, total_market_cap,
                     float_market_cap, amplitude)
                    VALUES %s
                    ON CONFLICT (code) DO UPDATE SET
                        name = EXCLUDED.name,
                        price = EXCLUDED.price,
                        change_percent = EXCLUDED.change_percent,
                        volume = EXCLUDED.volume,
                        amount = EXCLUDED.amount,
                        turnover = EXCLUDED.turnover,
                        volume_ratio = EXCLUDED.volume_ratio,
                        pe_dynamic = EXCLUDED.pe_dynamic,
                        pb = EXCLUDED.pb,
                        total_market_cap = EXCLUDED.total_market_cap,
                        float_market_cap = EXCLUDED.float_market_cap,
                        amplitude = EXCLUDED.amplitude,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    values,
                )
        return len(values)

    def get_hot_concepts_realtime(self, limit: int = 50) -> List[Dict]:
        return self._fetch_all(
            """
            SELECT rank, name, change_percent, inflow, outflow, net_inflow, updated_at
            FROM hot_concepts_realtime
            ORDER BY rank NULLS LAST, change_percent DESC NULLS LAST
            LIMIT %s
            """,
            (max(1, min(int(limit), 500)),),
        )

    def update_hot_concepts_realtime(self, records: List[Dict]) -> int:
        values = []
        seen = set()
        for idx, record in enumerate(records or [], start=1):
            name = str(record.get("name") or record.get("concept_name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            values.append(
                (
                    self._coerce_int(record.get("rank"), idx),
                    name,
                    self._coerce_float(record.get("change_percent")),
                    self._coerce_float(record.get("inflow")),
                    self._coerce_float(record.get("outflow")),
                    self._coerce_float(record.get("net_inflow") or record.get("net_amount")),
                )
            )
        if not values:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # Full replace so stale concept rows from prior feeds do not linger.
                cursor.execute("DELETE FROM hot_concepts_realtime")
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO hot_concepts_realtime
                    (rank, name, change_percent, inflow, outflow, net_inflow)
                    VALUES %s
                    """,
                    values,
                )
        return len(values)

    def insert_hot_concepts_history(self, trade_date: str, records: List[Dict]) -> int:
        values = []
        seen = set()
        date_text = self._normalize_date_text(trade_date)
        for idx, record in enumerate(records or [], start=1):
            name = str(record.get("name") or record.get("concept_name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            values.append(
                (
                    date_text,
                    self._coerce_int(record.get("rank"), idx),
                    name,
                    self._coerce_float(record.get("change_percent")),
                    self._coerce_float(record.get("inflow")),
                    self._coerce_float(record.get("outflow")),
                    self._coerce_float(record.get("net_inflow") or record.get("net_amount")),
                )
            )
        if not values:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO hot_concepts_history
                    (trade_date, rank, name, change_percent, inflow, outflow, net_inflow)
                    VALUES %s
                    ON CONFLICT (trade_date, name) DO UPDATE SET
                        rank = EXCLUDED.rank,
                        change_percent = EXCLUDED.change_percent,
                        inflow = EXCLUDED.inflow,
                        outflow = EXCLUDED.outflow,
                        net_inflow = EXCLUDED.net_inflow,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    values,
                )
        return len(values)

    def get_hot_concepts_history(self, trade_date: str) -> List[Dict]:
        return self._fetch_all(
            """
            SELECT rank, name, change_percent, inflow, outflow, net_inflow, updated_at
            FROM hot_concepts_history
            WHERE trade_date = %s
            ORDER BY rank NULLS LAST, change_percent DESC NULLS LAST
            """,
            (self._normalize_date_text(trade_date),),
        )

    def get_ths_hot_realtime(self, limit: int = 100) -> List[Dict]:
        return self._fetch_all(
            """
            SELECT rank, code, name, hot_value, change_percent, price, reason, tags, updated_at
            FROM ths_hot_realtime
            ORDER BY rank NULLS LAST, hot_value DESC NULLS LAST
            LIMIT %s
            """,
            (max(1, min(int(limit), 500)),),
        )

    def update_ths_hot_realtime(self, records: List[Dict]) -> int:
        values = []
        for idx, record in enumerate(records or [], start=1):
            code = self._normalize_stock_code(record.get("code") or record.get("symbol") or record.get("stock_code"))
            name = str(record.get("name") or record.get("stock_name") or "").strip()
            if not code or not name:
                continue
            values.append(
                (
                    self._coerce_int(record.get("rank"), idx),
                    code,
                    name,
                    self._coerce_float(record.get("hot_value") or record.get("hot")),
                    self._coerce_float(record.get("change_percent")),
                    self._coerce_float(record.get("price")),
                    str(record.get("reason") or ""),
                    self._json_or_text(record.get("tags")),
                )
            )
        if not values:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO ths_hot_realtime
                    (rank, code, name, hot_value, change_percent, price, reason, tags)
                    VALUES %s
                    ON CONFLICT (code) DO UPDATE SET
                        rank = EXCLUDED.rank,
                        name = EXCLUDED.name,
                        hot_value = EXCLUDED.hot_value,
                        change_percent = EXCLUDED.change_percent,
                        price = EXCLUDED.price,
                        reason = EXCLUDED.reason,
                        tags = EXCLUDED.tags,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    values,
                )
        return len(values)

    def insert_ths_hot_history(self, trade_date: str, records: List[Dict]) -> int:
        values = []
        date_text = self._normalize_date_text(trade_date)
        for idx, record in enumerate(records or [], start=1):
            code = self._normalize_stock_code(record.get("code") or record.get("symbol") or record.get("stock_code"))
            name = str(record.get("name") or record.get("stock_name") or "").strip()
            if not code or not name:
                continue
            values.append(
                (
                    date_text,
                    self._coerce_int(record.get("rank"), idx),
                    code,
                    name,
                    self._coerce_float(record.get("hot_value") or record.get("hot")),
                    self._coerce_float(record.get("change_percent")),
                    self._coerce_float(record.get("price")),
                    str(record.get("reason") or ""),
                    self._json_or_text(record.get("tags")),
                )
            )
        if not values:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO ths_hot_history
                    (trade_date, rank, code, name, hot_value, change_percent, price, reason, tags)
                    VALUES %s
                    ON CONFLICT (trade_date, code) DO UPDATE SET
                        rank = EXCLUDED.rank,
                        name = EXCLUDED.name,
                        hot_value = EXCLUDED.hot_value,
                        change_percent = EXCLUDED.change_percent,
                        price = EXCLUDED.price,
                        reason = EXCLUDED.reason,
                        tags = EXCLUDED.tags,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    values,
                )
        return len(values)

    def get_ths_hot_history(self, trade_date: str) -> List[Dict]:
        return self._fetch_all(
            """
            SELECT rank, code, name, hot_value, change_percent, price, reason, tags, updated_at
            FROM ths_hot_history
            WHERE trade_date = %s
            ORDER BY rank NULLS LAST, hot_value DESC NULLS LAST
            """,
            (self._normalize_date_text(trade_date),),
        )

    def get_concept_leaders_cache(self, concept_name: str, limit: int = 20) -> List[Dict]:
        return self._fetch_all(
            """
            SELECT stock_code AS code, stock_name AS name, price, change_percent,
                   amount, turnover, rank, updated_at
            FROM concept_leaders_cache
            WHERE concept_name = %s
            ORDER BY rank NULLS LAST, change_percent DESC NULLS LAST
            LIMIT %s
            """,
            (concept_name, max(1, min(int(limit), 500))),
        )

    def get_concept_leaders_cache_updated_at(self, concept_name: str) -> Optional[str]:
        row = self._fetch_one(
            """
            SELECT MAX(updated_at) AS updated_at
            FROM concept_leaders_cache
            WHERE concept_name = %s
            """,
            (concept_name,),
        )
        return row.get("updated_at") if row else None

    def update_concept_leaders_cache(self, concept_name: str, records: List[Dict]) -> int:
        values = []
        for idx, record in enumerate(records or [], start=1):
            code = self._normalize_stock_code(record.get("code") or record.get("symbol") or record.get("stock_code"))
            name = str(record.get("name") or record.get("stock_name") or "").strip()
            if not concept_name or not code or not name:
                continue
            values.append(
                (
                    concept_name,
                    code,
                    name,
                    self._coerce_float(record.get("price")),
                    self._coerce_float(record.get("change_percent")),
                    self._coerce_float(record.get("amount")),
                    self._coerce_float(record.get("turnover")),
                    self._coerce_int(record.get("rank"), idx),
                )
            )
        if not values:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM concept_leaders_cache WHERE concept_name = %s", (concept_name,))
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO concept_leaders_cache
                    (concept_name, stock_code, stock_name, price, change_percent,
                     amount, turnover, rank, updated_at)
                    VALUES %s
                    ON CONFLICT (concept_name, stock_code) DO UPDATE SET
                        stock_name = EXCLUDED.stock_name,
                        price = EXCLUDED.price,
                        change_percent = EXCLUDED.change_percent,
                        amount = EXCLUDED.amount,
                        turnover = EXCLUDED.turnover,
                        rank = EXCLUDED.rank,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    values,
                    template="(%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)",
                )
        return len(values)

    def get_stock_fundamentals(self, symbol: str) -> Optional[Dict]:
        code = self._normalize_stock_code(symbol)
        return self._fetch_one(
            """
            SELECT symbol, name, current_price, price, change_amount, change_percent,
                   volume, amount, amplitude, turnover_rate, pe, pe_dynamic, pb,
                   dividend_yield, market_cap, total_market_cap, float_market_cap,
                   updated_at
            FROM stock_fundamentals
            WHERE symbol = %s
            """,
            (code,),
        )

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

    def insert_stock_fundamentals_batch(self, records: List[Dict]) -> int:
        values = []
        for record in records or []:
            code = self._normalize_stock_code(record.get("symbol") or record.get("code"))
            name = str(record.get("name") or "").strip()
            if not code:
                continue
            current_price = self._coerce_float(record.get("current_price") or record.get("price"))
            total_market_cap = self._coerce_float(record.get("total_market_cap") or record.get("market_cap"))
            values.append(
                (
                    code,
                    name,
                    current_price,
                    current_price,
                    self._coerce_float(record.get("change_amount")),
                    self._coerce_float(record.get("change_percent")),
                    self._coerce_float(record.get("volume")),
                    self._coerce_float(record.get("amount")),
                    self._coerce_float(record.get("amplitude")),
                    self._coerce_float(record.get("turnover_rate") or record.get("turnover")),
                    self._coerce_float(record.get("pe") or record.get("pe_ttm")),
                    self._coerce_float(record.get("pe_dynamic")),
                    self._coerce_float(record.get("pb")),
                    self._coerce_float(record.get("dividend_yield")),
                    total_market_cap,
                    total_market_cap,
                    self._coerce_float(record.get("float_market_cap") or record.get("circ_mv")),
                )
            )
        if not values:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO stock_fundamentals
                    (symbol, name, current_price, price, change_amount, change_percent,
                     volume, amount, amplitude, turnover_rate, pe, pe_dynamic, pb,
                     dividend_yield, market_cap, total_market_cap, float_market_cap)
                    VALUES %s
                    ON CONFLICT (symbol) DO UPDATE SET
                        name = EXCLUDED.name,
                        current_price = EXCLUDED.current_price,
                        price = EXCLUDED.price,
                        change_amount = EXCLUDED.change_amount,
                        change_percent = EXCLUDED.change_percent,
                        volume = EXCLUDED.volume,
                        amount = EXCLUDED.amount,
                        amplitude = EXCLUDED.amplitude,
                        turnover_rate = EXCLUDED.turnover_rate,
                        pe = EXCLUDED.pe,
                        pe_dynamic = EXCLUDED.pe_dynamic,
                        pb = EXCLUDED.pb,
                        dividend_yield = EXCLUDED.dividend_yield,
                        market_cap = EXCLUDED.market_cap,
                        total_market_cap = EXCLUDED.total_market_cap,
                        float_market_cap = EXCLUDED.float_market_cap,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    values,
                )
        return len(values)

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
                     open, high, low, close, volume, turnover, source, collected_at, updated_at)
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
                        collected_at = EXCLUDED.collected_at,
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
                        item[14],
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
                    SELECT h.exchange, h.symbol, COALESCE(NULLIF(MAX(h.name), ''), '') AS name,
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
        payload = [
            {
                "exchange": row["exchange"],
                "symbol": row["symbol"],
                "name": row["name"] or "",
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
        missing = [
            item["symbol"]
            for item in payload
            if not item["name"] or item["name"] == item["symbol"]
        ]
        if missing:
            resolved = self.lookup_symbol_names(missing)
            for item in payload:
                symbol = item["symbol"]
                resolved_name = resolved.get(symbol) or ""
                if resolved_name and resolved_name != symbol:
                    item["name"] = resolved_name
                elif not item["name"]:
                    item["name"] = symbol
        return payload

    def create_sync_job(
        self,
        job_name: str,
        symbols: List[str],
        timeframes: List[str],
        start_date: str,
        end_date: str,
        source: str = "tushare",
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

    def create_market_day_sync_job(
        self,
        job_name: str,
        trade_dates: List[str],
        source: str = "tushare",
        market_symbol: str = "__MARKET__",
    ) -> int:
        """One job item per trade date for date-based full-market daily pulls."""
        dates = [str(value).strip()[:10] for value in trade_dates if str(value or "").strip()]
        dates = list(dict.fromkeys(dates))
        if not dates:
            raise ValueError("trade_dates is required")
        start_date = dates[0]
        end_date = dates[-1]
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO sync_jobs
                    (job_name, source, start_date, end_date, status, total_items)
                    VALUES (%s, %s, %s, %s, 'pending', %s)
                    RETURNING id
                    """,
                    (job_name, source, start_date, end_date, len(dates)),
                )
                job_id = cursor.fetchone()[0]
                items = [
                    (job_id, "cn", market_symbol, "1d", "kline", trade_date, trade_date, "pending")
                    for trade_date in dates
                ]
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
                   end_date, status, records_count, actual_source, fallback_reason, error_message, started_at,
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
        actual_source: str = None,
        fallback_reason: str = None,
    ) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE sync_job_items
                    SET status = %s,
                        records_count = %s,
                        actual_source = COALESCE(%s, actual_source),
                        fallback_reason = COALESCE(%s, fallback_reason),
                        error_message = %s,
                        started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                        finished_at = CASE WHEN %s IN ('success', 'failed') THEN CURRENT_TIMESTAMP ELSE finished_at END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (status, int(records_count or 0), actual_source, fallback_reason, error_message, status, item_id),
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

    def get_all_stock_symbols(self, main_board_only: bool = True) -> List[str]:
        rows = self._fetch_all(
            """
            SELECT DISTINCT symbol AS code
            FROM stock_history
            UNION
            SELECT DISTINCT code
            FROM all_stocks_realtime
            ORDER BY code ASC
            """
        )
        symbols: List[str] = []
        for row in rows:
            code = self._normalize_stock_code(row.get("code"))
            if not code:
                continue
            raw_code = code.split("_", 1)[-1]
            if main_board_only and (raw_code.startswith(("30", "68", "8", "43", "9"))):
                continue
            symbols.append(code)
        return symbols

    def get_stock_history_batch(self, symbols: List[str], days: int = 60) -> Dict[str, List[Dict]]:
        if not symbols:
            return {}
        normalized = [self._normalize_stock_code(symbol) for symbol in symbols if symbol]
        query = """
            SELECT symbol, name, date, open, high, low, close, volume, turnover
            FROM (
                SELECT symbol, name, date, open, high, low, close, volume, turnover,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
                FROM stock_history
                WHERE symbol = ANY(%s)
            ) ranked
            WHERE rn <= %s
            ORDER BY symbol ASC, date ASC
        """
        rows = self._fetch_all(query, (normalized, max(1, int(days))))
        grouped: Dict[str, List[Dict]] = {}
        for row in rows:
            grouped.setdefault(row["symbol"], []).append(row)
        return grouped

    def get_strategy_results(self, strategy_id: int, limit: int = 50) -> List[Dict]:
        return self._fetch_all(
            """
            SELECT id, strategy_id, execution_time, status, result_data,
                   error_message, execution_duration_ms
            FROM strategy_results
            WHERE strategy_id = %s
            ORDER BY execution_time DESC, id DESC
            LIMIT %s
            """,
            (strategy_id, max(1, min(int(limit), 500))),
        )

    def insert_ma_data_batch(self, records: List[Dict]) -> int:
        values = []
        for record in records or []:
            symbol = self._normalize_stock_code(record.get("symbol") or record.get("code"))
            if not symbol:
                continue
            values.append(
                (
                    symbol,
                    str(record.get("name") or ""),
                    self._normalize_date_text(record.get("date")),
                    self._coerce_float(record.get("close")),
                    self._coerce_float(record.get("ma5")),
                    self._coerce_float(record.get("ma10")),
                    self._coerce_float(record.get("ma20")),
                    self._coerce_float(record.get("ma30")),
                    self._coerce_float(record.get("ma_diff_max")),
                    self._coerce_float(record.get("ma_diff_pct")),
                )
            )
        if not values:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO stock_ma_data
                    (symbol, name, date, close, ma5, ma10, ma20, ma30,
                     ma_diff_max, ma_diff_pct)
                    VALUES %s
                    ON CONFLICT (symbol, date) DO UPDATE SET
                        name = EXCLUDED.name,
                        close = EXCLUDED.close,
                        ma5 = EXCLUDED.ma5,
                        ma10 = EXCLUDED.ma10,
                        ma20 = EXCLUDED.ma20,
                        ma30 = EXCLUDED.ma30,
                        ma_diff_max = EXCLUDED.ma_diff_max,
                        ma_diff_pct = EXCLUDED.ma_diff_pct,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    values,
                )
        return len(values)

    def get_ma_data_latest_date(self) -> Optional[str]:
        row = self._fetch_one("SELECT MAX(date) AS latest_date FROM stock_ma_data")
        return row.get("latest_date") if row else None

    def get_ma_data_stats(self) -> Dict:
        row = self._fetch_one(
            """
            SELECT COUNT(*) AS total_records,
                   COUNT(DISTINCT symbol) AS symbols_count,
                   MAX(date) AS latest_date
            FROM stock_ma_data
            """
        ) or {}
        return {
            "total_records": int(row.get("total_records") or 0),
            "symbols_count": int(row.get("symbols_count") or 0),
            "latest_date": row.get("latest_date"),
        }

    def save_sync_log(
        self,
        data_type: str,
        trade_date: str,
        status: str,
        count: int = 0,
        error_message: str = None,
        duration_ms: int = None,
    ) -> int:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO sync_logs
                    (data_type, trade_date, status, records_count, error_message, duration_ms)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (data_type, self._normalize_date_text(trade_date), status, int(count or 0), error_message, duration_ms),
                )
                return cursor.fetchone()[0]

    def insert_daily_concept_sectors(self, trade_date: str, records: List[Dict]) -> int:
        values = []
        date_text = self._normalize_date_text(trade_date)
        for idx, record in enumerate(records or [], start=1):
            name = str(record.get("sector_name") or record.get("name") or "").strip()
            if not name:
                continue
            values.append(
                (
                    date_text,
                    str(record.get("code") or ""),
                    name,
                    self._coerce_float(record.get("change_percent")),
                    str(record.get("leader_stock") or ""),
                    self._coerce_float(record.get("leader_change")),
                    self._coerce_float(record.get("total_market_cap")),
                    self._coerce_int(record.get("up_count")),
                    self._coerce_int(record.get("down_count")),
                    idx,
                )
            )
        if not values:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO daily_concept_sectors
                    (date, sector_code, sector_name, change_percent, leader_stock,
                     leader_change, total_market_cap, up_count, down_count, rank)
                    VALUES %s
                    ON CONFLICT (date, sector_name) DO UPDATE SET
                        sector_code = EXCLUDED.sector_code,
                        change_percent = EXCLUDED.change_percent,
                        leader_stock = EXCLUDED.leader_stock,
                        leader_change = EXCLUDED.leader_change,
                        total_market_cap = EXCLUDED.total_market_cap,
                        up_count = EXCLUDED.up_count,
                        down_count = EXCLUDED.down_count,
                        rank = EXCLUDED.rank,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    values,
                )
        return len(values)

    def get_daily_concept_sectors_multi_days(
        self,
        days: int = 30,
        min_change_pct: float = 3.0,
        top_n: int = 15,
    ) -> List[Dict]:
        return self._fetch_all(
            """
            WITH ranked AS (
                SELECT date, sector_code, sector_name, change_percent, leader_stock,
                       leader_change, total_market_cap, up_count, down_count, rank,
                       ROW_NUMBER() OVER (PARTITION BY date ORDER BY change_percent DESC NULLS LAST, rank NULLS LAST) AS rn
                FROM daily_concept_sectors
                WHERE change_percent >= %s
                  AND date IN (
                    SELECT DISTINCT date
                    FROM daily_concept_sectors
                    ORDER BY date DESC
                    LIMIT %s
                  )
            )
            SELECT *
            FROM ranked
            WHERE rn <= %s
            ORDER BY date DESC, rn ASC
            """,
            (float(min_change_pct), max(1, int(days)), max(1, int(top_n))),
        )

    def insert_lianban_ladder_history(self, trade_date: str, prev_date: str, levels: List[Dict]) -> int:
        rows = []
        date_text = self._normalize_date_text(trade_date)
        prev_text = self._normalize_date_text(prev_date) if prev_date else None
        for level in levels or []:
            today_level = self._coerce_int(level.get("today_level") or level.get("level") or level.get("duration_days"), 1)
            items = level.get("today_items") or level.get("items") or []
            if isinstance(items, dict):
                items = list(items.values())
            for item in items:
                code = self._normalize_stock_code(item.get("code") or item.get("symbol"))
                name = str(item.get("name") or "").strip()
                if not code:
                    continue
                rows.append(
                    (
                        date_text,
                        prev_text,
                        today_level,
                        code,
                        name,
                        self._coerce_float(item.get("price")),
                        self._coerce_float(item.get("change_percent")),
                        self._coerce_int(item.get("duration_days") or item.get("lianban"), today_level),
                        str(item.get("reason") or ""),
                        json.dumps(item, ensure_ascii=False, default=str),
                    )
                )
        if not rows:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO lianban_ladder_history
                    (date, prev_date, today_level, code, name, price, change_percent,
                     duration_days, reason, payload_json)
                    VALUES %s
                    ON CONFLICT (date, code) DO UPDATE SET
                        prev_date = EXCLUDED.prev_date,
                        today_level = EXCLUDED.today_level,
                        name = EXCLUDED.name,
                        price = EXCLUDED.price,
                        change_percent = EXCLUDED.change_percent,
                        duration_days = EXCLUDED.duration_days,
                        reason = EXCLUDED.reason,
                        payload_json = EXCLUDED.payload_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    rows,
                )
        return len(rows)

    def get_lianban_ladder_history(self, trade_date: str) -> List[Dict]:
        rows = self._fetch_all(
            """
            SELECT date, prev_date, today_level, code, name, price, change_percent,
                   duration_days, reason, payload_json, updated_at
            FROM lianban_ladder_history
            WHERE date = %s
            ORDER BY today_level DESC, change_percent DESC NULLS LAST
            """,
            (self._normalize_date_text(trade_date),),
        )
        grouped: Dict[int, Dict] = {}
        for row in rows:
            level = int(row.get("today_level") or 1)
            item = {
                "code": row.get("code"),
                "name": row.get("name"),
                "price": row.get("price"),
                "change_percent": row.get("change_percent"),
                "duration_days": row.get("duration_days"),
                "reason": row.get("reason"),
            }
            grouped.setdefault(level, {"today_level": level, "today_items": []})["today_items"].append(item)
        return list(grouped.values())

    def get_lianban_history_multi_days(self, days: int = 30, min_level: int = 2) -> List[Dict]:
        return self._fetch_all(
            """
            SELECT date, today_level, code, name, price, change_percent,
                   duration_days, reason, updated_at
            FROM lianban_ladder_history
            WHERE today_level >= %s
              AND date IN (
                SELECT DISTINCT date
                FROM lianban_ladder_history
                ORDER BY date DESC
                LIMIT %s
              )
            ORDER BY date DESC, today_level DESC, change_percent DESC NULLS LAST
            """,
            (max(1, int(min_level)), max(1, int(days))),
        )

    def list_replay_notes(self, limit: int = 60) -> List[Dict]:
        return self._fetch_all(
            """
            SELECT note_date, title, content, payload_json, updated_at
            FROM replay_notes
            ORDER BY note_date DESC
            LIMIT %s
            """,
            (max(1, min(int(limit), 365)),),
        )

    def get_replay_note(self, note_date: str) -> Optional[Dict]:
        return self._fetch_one(
            """
            SELECT note_date, title, content, payload_json, updated_at
            FROM replay_notes
            WHERE note_date = %s
            """,
            (self._normalize_date_text(note_date),),
        )

    def upsert_replay_note(self, payload: Dict) -> Dict:
        note_date = self._normalize_date_text(payload.get("note_date") or payload.get("date"))
        if not note_date:
            raise ValueError("note_date is required")
        title = str(payload.get("title") or "")
        content = str(payload.get("content") or "")
        payload_json = json.dumps(payload.get("payload") or payload, ensure_ascii=False, default=str)
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO replay_notes (note_date, title, content, payload_json, updated_at)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (note_date) DO UPDATE SET
                        title = EXCLUDED.title,
                        content = EXCLUDED.content,
                        payload_json = EXCLUDED.payload_json,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING note_date, title, content, payload_json, updated_at
                    """,
                    (note_date, title, content, payload_json),
                )
                return self._dict_row(cursor.fetchone())

    def insert_news_batch(self, records: List[Dict]) -> int:
        values = []
        for record in records or []:
            content = str(record.get("content") or record.get("title") or "").strip()
            if not content:
                continue
            values.append(
                (
                    str(record.get("source") or "unknown"),
                    str(record.get("publish_time") or datetime.now().isoformat()),
                    str(record.get("title") or content[:80]),
                    content,
                    self._coerce_int(record.get("importance"), 1),
                    record.get("category"),
                    self._json_or_text(record.get("related_stocks")),
                )
            )
        if not values:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO news_stream
                    (source, publish_time, title, content, importance, category, related_stocks)
                    VALUES %s
                    ON CONFLICT (source, publish_time, title) DO UPDATE SET
                        content = EXCLUDED.content,
                        importance = EXCLUDED.importance,
                        category = EXCLUDED.category,
                        related_stocks = EXCLUDED.related_stocks,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    values,
                )
        return len(values)

    def get_news_stream(self, limit: int = 50, source: str = None) -> List[Dict]:
        query = """
            SELECT source, publish_time, title, content, importance, category,
                   related_stocks, updated_at
            FROM news_stream
            WHERE 1=1
        """
        params: List[Any] = []
        if source:
            query += " AND source = %s"
            params.append(source)
        query += " ORDER BY publish_time DESC, id DESC LIMIT %s"
        params.append(max(1, min(int(limit), 500)))
        return self._fetch_all(query, params)

    def get_market_calendar_events(self, start: str = None, end: str = None) -> List[Dict]:
        query = """
            SELECT event_key, event_date, title, category, market, source,
                   details, updated_at, created_at
            FROM market_calendar_events
            WHERE 1=1
        """
        params: List[Any] = []
        if start:
            query += " AND event_date >= %s"
            params.append(self._normalize_date_text(start))
        if end:
            query += " AND event_date <= %s"
            params.append(self._normalize_date_text(end))
        query += " ORDER BY event_date ASC, id ASC"
        return self._fetch_all(query, params)

    def insert_market_calendar_event(
        self,
        event_date: str,
        title: str = "",
        category: str = "",
        market: str = "A股",
        source: str = "tushare",
        details: str = "",
        event_key: str = None,
        **legacy_fields,
    ) -> int:
        title = title or legacy_fields.get("event_description") or legacy_fields.get("description") or ""
        category = category or legacy_fields.get("event_type") or ""
        date_text = self._normalize_date_text(event_date)
        key = event_key or f"{date_text}:{category}:{title}"
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO market_calendar_events
                    (event_key, event_date, title, category, market, source, details, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (event_key) DO UPDATE SET
                        event_date = EXCLUDED.event_date,
                        title = EXCLUDED.title,
                        category = EXCLUDED.category,
                        market = EXCLUDED.market,
                        source = EXCLUDED.source,
                        details = EXCLUDED.details,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    (key, date_text, title, category, market, source, details),
                )
                return cursor.fetchone()[0]

    def init_factor_definitions(self) -> None:
        defaults = [
            ("PE_DYNAMIC", "动态市盈率", "估值因子", "行情快照", "动态市盈率", "Tushare", "daily", ""),
            ("PB", "市净率", "估值因子", "行情快照", "市净率", "Tushare", "daily", ""),
            ("TOTAL_MV", "总市值", "市值因子", "行情快照", "总市值", "Tushare", "daily", "元"),
            ("CIRC_MV", "流通市值", "市值因子", "行情快照", "流通市值", "Tushare", "daily", "元"),
            ("TURNOVER_RATE", "换手率", "交易因子", "行情快照", "换手率", "Tushare", "daily", "%"),
            ("VOLUME_RATIO", "量比", "交易因子", "行情快照", "量比", "Tushare", "daily", ""),
            ("AMPLITUDE", "振幅", "交易因子", "行情快照", "振幅", "Tushare", "daily", "%"),
            ("CHANGE_PCT_1D", "单日涨跌幅", "动量因子", "行情快照", "当日涨跌幅", "Tushare", "daily", "%"),
            ("MA5", "5日均线", "技术因子", "均线", "5日移动平均", "Tushare", "daily", ""),
            ("MA10", "10日均线", "技术因子", "均线", "10日移动平均", "Tushare", "daily", ""),
            ("MA20", "20日均线", "技术因子", "均线", "20日移动平均", "Tushare", "daily", ""),
            ("MA_DEVIATION", "均线偏离度", "技术因子", "均线", "收盘价相对20日均线偏离", "Tushare", "daily", "%"),
        ]
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO factor_definitions
                    (factor_code, factor_name, category, subcategory, description,
                     data_source, update_frequency, unit)
                    VALUES %s
                    ON CONFLICT (factor_code) DO UPDATE SET
                        factor_name = EXCLUDED.factor_name,
                        category = EXCLUDED.category,
                        subcategory = EXCLUDED.subcategory,
                        description = EXCLUDED.description,
                        data_source = EXCLUDED.data_source,
                        update_frequency = EXCLUDED.update_frequency,
                        unit = EXCLUDED.unit,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    defaults,
                )

    def get_factor_definitions(self, category: str = None) -> List[Dict]:
        query = """
            SELECT factor_code, factor_name, category, subcategory, description,
                   formula, data_source, update_frequency, unit, updated_at
            FROM factor_definitions
            WHERE 1=1
        """
        params: List[Any] = []
        if category:
            query += " AND category = %s"
            params.append(category)
        query += " ORDER BY category ASC, factor_code ASC"
        return self._fetch_all(query, params)

    def get_factor_definition(self, factor_code: str) -> Optional[Dict]:
        return self._fetch_one(
            """
            SELECT factor_code, factor_name, category, subcategory, description,
                   formula, data_source, update_frequency, unit, updated_at
            FROM factor_definitions
            WHERE factor_code = %s
            """,
            (factor_code,),
        )

    def get_factor_categories(self) -> List[Dict]:
        return self._fetch_all(
            """
            SELECT category, COUNT(*) AS count
            FROM factor_definitions
            GROUP BY category
            ORDER BY category ASC
            """
        )

    def insert_factor_data_batch(self, factor_code: str, records: List[Dict]) -> int:
        values = []
        for record in records or []:
            symbol = self._normalize_stock_code(record.get("symbol") or record.get("code"))
            date_text = self._normalize_date_text(record.get("date"))
            if not symbol or not date_text:
                continue
            values.append((factor_code, symbol, date_text, self._coerce_float(record.get("value"))))
        if not values:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO factor_data (factor_code, symbol, date, value)
                    VALUES %s
                    ON CONFLICT (factor_code, symbol, date) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    values,
                )
        return len(values)

    def get_factor_data(
        self,
        factor_code: str,
        date: str = None,
        symbol: str = None,
        limit: int = 100,
    ) -> List[Dict]:
        query = """
            SELECT fd.factor_code, fd.symbol, fd.date, fd.value,
                   d.factor_name, d.category, d.unit
            FROM factor_data fd
            LEFT JOIN factor_definitions d ON d.factor_code = fd.factor_code
            WHERE fd.factor_code = %s
        """
        params: List[Any] = [factor_code]
        if date:
            query += " AND fd.date = %s"
            params.append(self._normalize_date_text(date))
        if symbol:
            query += " AND fd.symbol = %s"
            params.append(self._normalize_stock_code(symbol))
        query += " ORDER BY fd.date DESC, fd.value DESC NULLS LAST LIMIT %s"
        params.append(max(1, min(int(limit), 5000)))
        return self._fetch_all(query, params)

    def get_factor_data_by_date(self, date: str, factor_codes: List[str] = None) -> List[Dict]:
        query = """
            SELECT fd.factor_code, fd.symbol, fd.date, fd.value,
                   d.factor_name, d.category, d.unit
            FROM factor_data fd
            LEFT JOIN factor_definitions d ON d.factor_code = fd.factor_code
            WHERE fd.date = %s
        """
        params: List[Any] = [self._normalize_date_text(date)]
        if factor_codes:
            query += " AND fd.factor_code = ANY(%s)"
            params.append(factor_codes)
        query += " ORDER BY fd.symbol ASC, fd.factor_code ASC"
        return self._fetch_all(query, params)

    def get_factor_data_by_symbol(self, symbol: str, date: str = None) -> List[Dict]:
        query = """
            SELECT fd.factor_code, fd.symbol, fd.date, fd.value,
                   d.factor_name, d.category, d.description, d.unit
            FROM factor_data fd
            LEFT JOIN factor_definitions d ON d.factor_code = fd.factor_code
            WHERE fd.symbol = %s
        """
        params: List[Any] = [self._normalize_stock_code(symbol)]
        if date:
            query += " AND fd.date = %s"
            params.append(self._normalize_date_text(date))
        query += " ORDER BY fd.date DESC, fd.factor_code ASC LIMIT 5000"
        return self._fetch_all(query, params)

    def get_factor_latest_date(self, factor_code: str = None) -> Optional[str]:
        if factor_code:
            row = self._fetch_one("SELECT MAX(date) AS latest_date FROM factor_data WHERE factor_code = %s", (factor_code,))
        else:
            row = self._fetch_one("SELECT MAX(date) AS latest_date FROM factor_data")
        return row.get("latest_date") if row else None

    def get_factor_stats(self) -> Dict:
        row = self._fetch_one(
            """
            SELECT COUNT(*) AS records_count,
                   COUNT(DISTINCT factor_code) AS factors_count,
                   COUNT(DISTINCT symbol) AS symbols_count,
                   MAX(date) AS latest_date
            FROM factor_data
            """
        ) or {}
        return {
            "records_count": int(row.get("records_count") or 0),
            "factors_count": int(row.get("factors_count") or 0),
            "symbols_count": int(row.get("symbols_count") or 0),
            "latest_date": row.get("latest_date"),
            "definitions_count": len(self.get_factor_definitions()),
        }

    def save_factor_sync_log(
        self,
        factor_code: str,
        date: str,
        status: str,
        records_count: int = 0,
        error_message: str = None,
        sync_duration_ms: int = None,
    ) -> int:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO factor_sync_logs
                    (factor_code, date, status, records_count, error_message, sync_duration_ms)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        factor_code,
                        self._normalize_date_text(date),
                        status,
                        int(records_count or 0),
                        error_message,
                        sync_duration_ms,
                    ),
                )
                return cursor.fetchone()[0]

    def get_factor_sync_logs(self, factor_code: str = None, limit: int = 50) -> List[Dict]:
        query = """
            SELECT factor_code, date, status, records_count, error_message,
                   sync_duration_ms, created_at
            FROM factor_sync_logs
            WHERE 1=1
        """
        params: List[Any] = []
        if factor_code:
            query += " AND factor_code = %s"
            params.append(factor_code)
        query += " ORDER BY created_at DESC, id DESC LIMIT %s"
        params.append(max(1, min(int(limit), 500)))
        return self._fetch_all(query, params)

    def clear_factor_data(self, factor_code: str = None) -> int:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                if factor_code:
                    cursor.execute("DELETE FROM factor_data WHERE factor_code = %s", (factor_code,))
                else:
                    cursor.execute("DELETE FROM factor_data")
                return int(cursor.rowcount or 0)

    def insert_dragon_tiger_board(self, trade_date: str, records: List[Dict]) -> int:
        return self._insert_json_rows("dragon_tiger_board", "date", self._normalize_date_text(trade_date), records)

    def insert_northbound_flow(self, records: List[Dict]) -> int:
        return self._insert_json_rows("northbound_flow", "date", None, records)

    def update_sector_realtime(self, sector_type: str, records: List[Dict]) -> int:
        rows = [{**dict(record), "sector_type": sector_type} for record in records or []]
        return self._insert_json_rows("sector_realtime", "sector_type", sector_type, rows)

    def _insert_json_rows(self, table_name: str, key_name: str, key_value: Any, records: List[Dict]) -> int:
        if not records:
            return 0
        values = []
        for idx, record in enumerate(records, start=1):
            payload = dict(record)
            if key_value is not None:
                payload[key_name] = key_value
            values.append((key_value, idx, json.dumps(payload, ensure_ascii=False, default=str)))
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"DELETE FROM {table_name} WHERE key_value IS NOT DISTINCT FROM %s", (key_value,))
                psycopg2.extras.execute_values(
                    cursor,
                    f"""
                    INSERT INTO {table_name} (key_value, row_rank, payload_json)
                    VALUES %s
                    """,
                    values,
                )
        return len(values)

    def save_strategy(
        self,
        name: str,
        script_content: str,
        description: str = "",
        interval_seconds: int = 60,
        enabled: bool = True,
        data_purpose: str = "user",
    ) -> int:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO strategy_scripts
                    (name, script_content, description, interval_seconds, enabled, data_purpose)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (name) DO UPDATE SET
                        script_content = EXCLUDED.script_content,
                        description = EXCLUDED.description,
                        interval_seconds = EXCLUDED.interval_seconds,
                        enabled = EXCLUDED.enabled,
                        data_purpose = EXCLUDED.data_purpose,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    (name, script_content, description, interval_seconds, enabled, data_purpose),
                )
                return cursor.fetchone()[0]

    def get_strategies(self) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, name, description, NULL::text AS script_content, interval_seconds,
                           enabled, is_running, data_purpose, created_at, updated_at
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
                           enabled, is_running, data_purpose, created_at, updated_at
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

    def update_strategy(
        self,
        strategy_id: int,
        name: str,
        script_content: str,
        description: str = "",
        interval_seconds: int = 60,
        data_purpose: Optional[str] = None,
    ) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE strategy_scripts
                    SET name = %s,
                        script_content = %s,
                        description = %s,
                        interval_seconds = %s,
                        data_purpose = COALESCE(%s, data_purpose),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING id, name, description, script_content, interval_seconds,
                              enabled, is_running, data_purpose, created_at, updated_at
                    """,
                    (name, script_content, description, interval_seconds, data_purpose, strategy_id),
                )
                row = cursor.fetchone()
        return self._strategy_row(row) if row else None

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
            description="A股多标的策略，遵循 100 股整数手、T+1 与只做多约束。",
            script_content=self._preset_strategy_code(),
            interval_seconds=60,
            data_purpose="seed",
        )

    # ================================================================
    # Strategy Backtest Results
    # ================================================================

    def save_backtest_result(
        self,
        strategy_id: int,
        symbols: str,
        start_date: str,
        end_date: str,
        initial_capital: float,
        final_capital: float,
        total_return: float,
        max_drawdown: float,
        win_rate: float,
        total_trades: int,
        equity_curve: str,
        trades: str,
        status: str = "completed",
    ) -> int:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO strategy_backtest_results
                    (strategy_id, symbols, start_date, end_date, initial_capital,
                     final_capital, total_return, max_drawdown, win_rate, total_trades,
                     equity_curve, trades, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        strategy_id, symbols, start_date, end_date,
                        initial_capital, final_capital, total_return,
                        max_drawdown, win_rate, total_trades,
                        equity_curve, trades, status,
                    ),
                )
                return cursor.fetchone()[0]

    def list_backtest_results(self, limit: int = 20) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT b.id, b.strategy_id, COALESCE(s.name, '未命名策略') AS strategy_name,
                           b.symbols, b.start_date, b.end_date, b.initial_capital,
                           b.final_capital, b.total_return, b.max_drawdown, b.win_rate,
                           b.total_trades, b.equity_curve, b.trades, b.status, b.created_at
                    FROM strategy_backtest_results b
                    LEFT JOIN strategy_scripts s ON s.id = b.strategy_id
                    ORDER BY b.created_at DESC, b.id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [self._dict_row(row) for row in cursor.fetchall()]

    # ================================================================
    # Paper Trading - Accounts
    # ================================================================

    def create_paper_account(
        self,
        strategy_id: int,
        name: str,
        initial_capital: float,
    ) -> int:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO paper_accounts
                    (strategy_id, name, initial_capital, cash, equity, status)
                    VALUES (%s, %s, %s, %s, %s, 'running')
                    RETURNING id
                    """,
                    (strategy_id, name, initial_capital, initial_capital, initial_capital),
                )
                return cursor.fetchone()[0]

    def update_paper_account(
        self,
        account_id: int,
        cash: float,
        equity: float,
    ) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE paper_accounts
                    SET cash = %s, equity = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (round(cash, 2), round(equity, 2), account_id),
                )

    def get_paper_account(self, account_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT pa.id, pa.strategy_id, pa.name, pa.initial_capital,
                           pa.cash, pa.equity, pa.status, pa.created_at, pa.updated_at,
                           COALESCE(s.name, '未命名策略') AS strategy_name
                    FROM paper_accounts pa
                    LEFT JOIN strategy_scripts s ON s.id = pa.strategy_id
                    WHERE pa.id = %s
                    """,
                    (account_id,),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    def list_paper_accounts(self) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT pa.id, pa.strategy_id, pa.name, pa.initial_capital,
                           pa.cash, pa.equity, pa.status, pa.created_at, pa.updated_at,
                           COALESCE(s.name, '未命名策略') AS strategy_name
                    FROM paper_accounts pa
                    LEFT JOIN strategy_scripts s ON s.id = pa.strategy_id
                    ORDER BY pa.created_at DESC, pa.id DESC
                    """
                )
                return [self._dict_row(row) for row in cursor.fetchall()]

    def stop_paper_account(self, account_id: int) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE paper_accounts
                    SET status = 'stopped', updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (account_id,),
                )

    # ================================================================
    # Paper Trading - Orders
    # ================================================================

    def insert_paper_order(
        self,
        account_id: int,
        strategy_id: int,
        symbol: str,
        side: str,
        price: float,
        quantity: int,
        amount: float,
        fee: float,
        status: str = "filled",
        name: str = None,
        reason: str = None,
    ) -> int:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO paper_orders
                    (account_id, strategy_id, symbol, name, side, price, quantity,
                     amount, fee, status, reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (account_id, strategy_id, symbol, name, side, price,
                     quantity, amount, fee, status, reason),
                )
                return cursor.fetchone()[0]

    def get_paper_orders(self, account_id: int) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, account_id, strategy_id, symbol, name, side, price,
                           quantity, amount, fee, status, reason, created_at
                    FROM paper_orders
                    WHERE account_id = %s
                    ORDER BY created_at DESC, id DESC
                    """,
                    (account_id,),
                )
                return [self._dict_row(row) for row in cursor.fetchall()]

    # ================================================================
    # Paper Trading - Positions
    # ================================================================

    def upsert_paper_position(
        self,
        account_id: int,
        strategy_id: int,
        symbol: str,
        quantity: int,
        avg_price: float,
        last_price: float,
        market_value: float,
        pnl: float,
        pnl_pct: float,
        name: str = None,
    ) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO paper_positions
                    (account_id, strategy_id, symbol, name, quantity, avg_price,
                     last_price, market_value, pnl, pnl_pct, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (account_id, symbol) DO UPDATE SET
                        name = EXCLUDED.name,
                        quantity = EXCLUDED.quantity,
                        avg_price = EXCLUDED.avg_price,
                        last_price = EXCLUDED.last_price,
                        market_value = EXCLUDED.market_value,
                        pnl = EXCLUDED.pnl,
                        pnl_pct = EXCLUDED.pnl_pct,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (account_id, strategy_id, symbol, name, quantity,
                     avg_price, last_price, market_value, pnl, pnl_pct),
                )

    def get_paper_positions(self, account_id: int) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, account_id, strategy_id, symbol, name, quantity,
                           avg_price, last_price, market_value, pnl, pnl_pct, updated_at
                    FROM paper_positions
                    WHERE account_id = %s
                    ORDER BY symbol ASC
                    """,
                    (account_id,),
                )
                return [self._dict_row(row) for row in cursor.fetchall()]

    # ================================================================
    # Paper Trading - Equity Curve
    # ================================================================

    def insert_paper_equity_point(
        self,
        account_id: int,
        equity: float,
        cash: float,
    ) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO paper_equity_curve (account_id, equity, cash)
                    VALUES (%s, %s, %s)
                    """,
                    (account_id, round(equity, 2), round(cash, 2)),
                )

    def get_paper_equity_curve(self, account_id: int) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, account_id, equity, cash, created_at
                    FROM paper_equity_curve
                    WHERE account_id = %s
                    ORDER BY created_at ASC, id ASC
                    """,
                    (account_id,),
                )
                return [self._dict_row(row) for row in cursor.fetchall()]

    # ================================================================
    # Paper Trading - Events
    # ================================================================

    def insert_paper_event(
        self,
        account_id: int,
        level: str,
        message: str,
        payload: str = None,
    ) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO paper_events (account_id, level, message, payload)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (account_id, level, message, payload),
                )

    def get_paper_events(self, account_id: int) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, account_id, level, message, payload, created_at
                    FROM paper_events
                    WHERE account_id = %s
                    ORDER BY created_at DESC, id DESC
                    """,
                    (account_id,),
                )
                return [self._dict_row(row) for row in cursor.fetchall()]

    # ================================================================
    # Data Hub - Jobs
    # ================================================================

    def create_data_hub_job(
        self,
        job_key: str,
        action: str,
        scope: str = None,
        params_json: str = None,
        parent_job_key: str = None,
    ) -> str:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO data_hub_jobs
                    (job_key, action, scope, params_json, parent_job_key, status)
                    VALUES (%s, %s, %s, %s, %s, 'queued')
                    ON CONFLICT (job_key) DO NOTHING
                    RETURNING job_key
                    """,
                    (job_key, action, scope, params_json, parent_job_key),
                )
                row = cursor.fetchone()
                if row:
                    return row[0]
                return job_key

    def get_data_hub_job(self, job_key: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT job_key, action, scope, params_json, status, progress,
                           current, total, message, error_message, result_json,
                           logs_json, parent_job_key, created_at, started_at, finished_at
                    FROM data_hub_jobs
                    WHERE job_key = %s
                    """,
                    (job_key,),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    def list_data_hub_jobs(
        self,
        action: str = None,
        status: str = None,
        scope: str = None,
        parent_job_key: str = None,
        limit: int = 50,
    ) -> List[Dict]:
        query = """
            SELECT job_key, action, scope, params_json, status, progress,
                   current, total, message, error_message, result_json,
                   logs_json, parent_job_key, created_at, started_at, finished_at
            FROM data_hub_jobs
            WHERE 1=1
        """
        params: List[Any] = []
        if action:
            query += " AND action = %s"
            params.append(action)
        if status:
            query += " AND status = %s"
            params.append(status)
        if scope:
            query += " AND scope = %s"
            params.append(scope)
        if parent_job_key:
            query += " AND parent_job_key = %s"
            params.append(parent_job_key)
        query += " ORDER BY id DESC LIMIT %s"
        params.append(max(1, min(limit, 500)))

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [self._dict_row(row) for row in cursor.fetchall()]

    def update_data_hub_job(
        self,
        job_key: str,
        status: str = None,
        progress: float = None,
        current: int = None,
        total: int = None,
        message: str = None,
        error_message: str = None,
        result_json: str = None,
        logs_json: str = None,
        started_at: str = None,
        finished_at: str = None,
    ) -> None:
        updates: List[str] = []
        values: List[Any] = []
        if status is not None:
            updates.append("status = %s")
            values.append(status)
        if progress is not None:
            updates.append("progress = %s")
            values.append(progress)
        if current is not None:
            updates.append("current = %s")
            values.append(current)
        if total is not None:
            updates.append("total = %s")
            values.append(total)
        if message is not None:
            updates.append("message = %s")
            values.append(message)
        if error_message is not None:
            updates.append("error_message = %s")
            values.append(error_message)
        if result_json is not None:
            updates.append("result_json = %s")
            values.append(result_json)
        if logs_json is not None:
            updates.append("logs_json = %s")
            values.append(logs_json)
        if started_at is not None:
            updates.append("started_at = %s")
            values.append(started_at)
        if finished_at is not None:
            updates.append("finished_at = %s")
            values.append(finished_at)
        if not updates:
            return
        values.append(job_key)
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"UPDATE data_hub_jobs SET {', '.join(updates)} WHERE job_key = %s",
                    values,
                )

    # ================================================================
    # Data Hub - Quality Reports
    # ================================================================

    def save_data_hub_quality_report(
        self,
        report_key: str,
        scope: str,
        status: str,
        summary_json: str,
        checks_json: str,
    ) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO data_hub_quality_reports
                    (report_key, scope, status, summary_json, checks_json)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (report_key, scope, status, summary_json, checks_json),
                )

    def get_latest_quality_report(self) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT report_key, scope, status, summary_json, checks_json, created_at
                    FROM data_hub_quality_reports
                    ORDER BY id DESC
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    # ================================================================
    # Data Dev - Tasks
    # ================================================================

    def list_data_dev_tasks(self) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        t.id,
                        t.name,
                        t.description,
                        t.sql_content,
                        t.cron_expression,
                        t.enabled,
                        t.created_at,
                        t.updated_at,
                        l.status AS last_status,
                        l.execution_start AS last_run,
                        l.error_message AS last_error
                    FROM data_dev_tasks t
                    LEFT JOIN data_dev_logs l
                        ON l.id = (
                            SELECT id
                            FROM data_dev_logs
                            WHERE task_id = t.id
                            ORDER BY execution_start DESC, id DESC
                            LIMIT 1
                        )
                    ORDER BY t.updated_at DESC, t.id DESC
                    """
                )
                return [self._dict_row(row) for row in cursor.fetchall()]

    def create_data_dev_task(
        self,
        name: str,
        description: str,
        sql_content: str,
        cron_expression: str,
        enabled: bool = True,
    ) -> int:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO data_dev_tasks
                    (name, description, sql_content, cron_expression, enabled, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    RETURNING id
                    """,
                    (name, description, sql_content, cron_expression, enabled),
                )
                return cursor.fetchone()[0]

    def get_data_dev_task(self, task_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, name, description, sql_content, cron_expression,
                           enabled, created_at, updated_at
                    FROM data_dev_tasks
                    WHERE id = %s
                    """,
                    (task_id,),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    def update_data_dev_task_fields(
        self,
        task_id: int,
        name: str = None,
        description: str = None,
        sql_content: str = None,
        cron_expression: str = None,
        enabled: bool = None,
    ) -> Optional[Dict]:
        updates: List[str] = []
        values: List[Any] = []
        if name is not None:
            updates.append("name = %s")
            values.append(name)
        if description is not None:
            updates.append("description = %s")
            values.append(description)
        if sql_content is not None:
            updates.append("sql_content = %s")
            values.append(sql_content)
        if cron_expression is not None:
            updates.append("cron_expression = %s")
            values.append(cron_expression)
        if enabled is not None:
            updates.append("enabled = %s")
            values.append(enabled)
        if not updates:
            return None
        updates.append("updated_at = CURRENT_TIMESTAMP")
        values.append(task_id)
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"UPDATE data_dev_tasks SET {', '.join(updates)} WHERE id = %s",
                    values,
                )
                cursor.execute(
                    """
                    SELECT id, name, description, sql_content, cron_expression,
                           enabled, created_at, updated_at
                    FROM data_dev_tasks
                    WHERE id = %s
                    """,
                    (task_id,),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    def delete_data_dev_task_and_logs(self, task_id: int) -> bool:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM data_dev_logs WHERE task_id = %s", (task_id,))
                cursor.execute("DELETE FROM data_dev_tasks WHERE id = %s", (task_id,))
                return cursor.rowcount > 0

    # ================================================================
    # Data Dev - Logs
    # ================================================================

    def create_data_dev_log(self, task_id: int, status: str = "running") -> int:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO data_dev_logs (task_id, execution_start, status)
                    VALUES (%s, CURRENT_TIMESTAMP, %s)
                    RETURNING id
                    """,
                    (task_id, status),
                )
                return cursor.fetchone()[0]

    def complete_data_dev_log(
        self,
        log_id: int,
        status: str,
        affected_rows: int = 0,
        error_message: str = None,
    ) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE data_dev_logs
                    SET execution_end = CURRENT_TIMESTAMP,
                        status = %s,
                        affected_rows = %s,
                        error_message = %s
                    WHERE id = %s
                    """,
                    (status, affected_rows, error_message, log_id),
                )

    def get_data_dev_task_logs(self, task_id: int, limit: int = 50) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, execution_start, execution_end, status,
                           error_message, affected_rows
                    FROM data_dev_logs
                    WHERE task_id = %s
                    ORDER BY execution_start DESC, id DESC
                    LIMIT %s
                    """,
                    (task_id, max(1, min(int(limit), 500))),
                )
                return [self._dict_row(row) for row in cursor.fetchall()]

    # ================================================================
    # Stock Sentiment
    # ================================================================

    def insert_sentiment_batch(self, records: List[Dict]) -> int:
        if not records:
            return 0
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                written = 0
                for record in records:
                    cursor.execute(
                        """
                        INSERT INTO stock_sentiment (code, name, date, score, level, components)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (code, date) DO UPDATE SET
                            name = EXCLUDED.name,
                            score = EXCLUDED.score,
                            level = EXCLUDED.level,
                            components = EXCLUDED.components,
                            created_at = CURRENT_TIMESTAMP
                        """,
                        (
                            record["code"],
                            record.get("name"),
                            record["date"],
                            record["score"],
                            record["level"],
                            json.dumps(record.get("components", {}), ensure_ascii=False),
                        ),
                    )
                    written += 1
        return written

    def get_sentiment_for_date(
        self,
        date: str,
        limit: int = 200,
        order: str = "desc",
    ) -> List[Dict]:
        direction = "DESC" if order == "desc" else "ASC"
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT code, name, date, score, level, components, created_at
                    FROM stock_sentiment
                    WHERE date = %s
                    ORDER BY score {direction}
                    LIMIT %s
                    """,
                    (date, limit),
                )
                rows = cursor.fetchall()
        return [self._dict_row(row) for row in rows]

    def get_sentiment_stats(self) -> Dict:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) AS total_records,
                        COUNT(DISTINCT code) AS total_stocks,
                        COUNT(DISTINCT date) AS total_dates,
                        MAX(date) AS latest_date
                    FROM stock_sentiment
                    """
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else {}

    # ================================================================
    # V2 Strategy Workbench - Strategy Versions
    # ================================================================

    def create_strategy_version(
        self,
        name: str,
        script_content: str,
        legacy_strategy_id: int = None,
        description: str = "",
        parameter_schema: Dict = None,
        data_dependencies: List = None,
        output_contract: Dict = None,
        status: str = "draft",
    ) -> Dict:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM strategy_versions WHERE name = %s", (name,))
                next_version = cursor.fetchone()["next_version"]
                cursor.execute(
                    """
                    INSERT INTO strategy_versions
                    (legacy_strategy_id, name, version, description, script_content,
                     parameter_schema, data_dependencies, output_contract, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, name, version, description, script_content,
                              parameter_schema, data_dependencies, output_contract,
                              status, created_at, updated_at
                    """,
                    (
                        legacy_strategy_id, name, next_version, description,
                        script_content,
                        json.dumps(parameter_schema or {}, ensure_ascii=False),
                        json.dumps(data_dependencies or [], ensure_ascii=False),
                        json.dumps(output_contract or {}, ensure_ascii=False),
                        status,
                    ),
                )
                return self._dict_row(cursor.fetchone())

    def get_strategy_version(self, version_id: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, legacy_strategy_id, name, version, description,
                           script_content, parameter_schema, data_dependencies,
                           output_contract, status, created_at, updated_at
                    FROM strategy_versions
                    WHERE id = %s
                    """,
                    (version_id,),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    def list_strategy_versions(self, name: str = None, status: str = None) -> List[Dict]:
        query = """
            SELECT id, legacy_strategy_id, name, version, description,
                   script_content, parameter_schema, data_dependencies,
                   output_contract, status, created_at, updated_at
            FROM strategy_versions
            WHERE 1=1
        """
        params: List[Any] = []
        if name:
            query += " AND name = %s"
            params.append(name)
        if status:
            query += " AND status = %s"
            params.append(status)
        query += " ORDER BY name ASC, version DESC"
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [self._dict_row(row) for row in cursor.fetchall()]

    def update_strategy_version_status(self, version_id: str, status: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE strategy_versions
                    SET status = %s, updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, name, version, status, updated_at
                    """,
                    (status, version_id),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    # ================================================================
    # V2 Strategy Workbench - Strategy Parameters
    # ================================================================

    def save_strategy_parameters(self, version_id: str, params: Dict[str, Any]) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                for name, value in params.items():
                    cursor.execute(
                        """
                        INSERT INTO strategy_parameters (strategy_version_id, name, value)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (strategy_version_id, name) DO UPDATE SET
                            value = EXCLUDED.value
                        """,
                        (version_id, name, json.dumps(value, ensure_ascii=False)),
                    )

    def get_strategy_parameters(self, version_id: str) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, strategy_version_id, name, value, created_at
                    FROM strategy_parameters
                    WHERE strategy_version_id = %s
                    ORDER BY name ASC
                    """,
                    (version_id,),
                )
                return [self._dict_row(row) for row in cursor.fetchall()]

    # ================================================================
    # V2 Strategy Workbench - Strategy Signals
    # ================================================================

    def insert_strategy_signal(
        self,
        strategy_version_id: str = None,
        legacy_strategy_id: int = None,
        symbol: str = None,
        name: str = None,
        signal_type: str = "candidate",
        status: str = "new",
        price: float = None,
        strength: float = None,
        reason: str = None,
        payload: Dict = None,
    ) -> Dict:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO strategy_signals
                    (strategy_version_id, legacy_strategy_id, symbol, name,
                     signal_type, status, price, strength, reason, payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, strategy_version_id, legacy_strategy_id, symbol, name,
                              signal_type, status, signal_time, price, strength, reason,
                              payload, created_at, updated_at
                    """,
                    (
                        strategy_version_id, legacy_strategy_id, symbol, name,
                        signal_type, status, price, strength, reason,
                        json.dumps(payload or {}, ensure_ascii=False),
                    ),
                )
                return self._dict_row(cursor.fetchone())

    def list_strategy_signals(
        self,
        strategy_version_id: str = None,
        legacy_strategy_id: int = None,
        status: str = None,
        signal_type: str = None,
        limit: int = 100,
    ) -> List[Dict]:
        query = """
            SELECT id, strategy_version_id, legacy_strategy_id, symbol, name,
                   signal_type, status, signal_time, price, strength, reason,
                   payload, created_at, updated_at
            FROM strategy_signals
            WHERE 1=1
        """
        params: List[Any] = []
        if strategy_version_id:
            query += " AND strategy_version_id = %s"
            params.append(strategy_version_id)
        if legacy_strategy_id:
            query += " AND legacy_strategy_id = %s"
            params.append(legacy_strategy_id)
        if status:
            query += " AND status = %s"
            params.append(status)
        if signal_type:
            query += " AND signal_type = %s"
            params.append(signal_type)
        query += " ORDER BY signal_time DESC LIMIT %s"
        params.append(max(1, min(limit, 500)))
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [self._dict_row(row) for row in cursor.fetchall()]

    def update_signal_status(self, signal_id: str, status: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE strategy_signals
                    SET status = %s, updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, status, updated_at
                    """,
                    (status, signal_id),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    # ================================================================
    # V2 Strategy Workbench - Backtest Runs
    # ================================================================

    def create_backtest_run(
        self,
        strategy_version_id: str = None,
        name: str = "",
        universe: Dict = None,
        parameters: Dict = None,
        start_date: str = None,
        end_date: str = None,
        status: str = "queued",
    ) -> Dict:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO backtest_runs
                    (strategy_version_id, name, universe, parameters,
                     start_date, end_date, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, strategy_version_id, name, universe, parameters,
                              start_date, end_date, status, metrics, error_message,
                              created_at, started_at, finished_at
                    """,
                    (
                        strategy_version_id, name,
                        json.dumps(universe or {}, ensure_ascii=False),
                        json.dumps(parameters or {}, ensure_ascii=False),
                        start_date, end_date, status,
                    ),
                )
                return self._dict_row(cursor.fetchone())

    def update_backtest_run(
        self,
        run_id: str,
        status: str = None,
        metrics: Dict = None,
        error_message: str = None,
        started_at: str = None,
        finished_at: str = None,
    ) -> Optional[Dict]:
        updates: List[str] = []
        values: List[Any] = []
        if status is not None:
            updates.append("status = %s")
            values.append(status)
        if metrics is not None:
            updates.append("metrics = %s")
            values.append(json.dumps(metrics, ensure_ascii=False))
        if error_message is not None:
            updates.append("error_message = %s")
            values.append(error_message)
        if started_at is not None:
            updates.append("started_at = %s")
            values.append(started_at)
        if finished_at is not None:
            updates.append("finished_at = %s")
            values.append(finished_at)
        if not updates:
            return None
        values.append(run_id)
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"UPDATE backtest_runs SET {', '.join(updates)} WHERE id = %s",
                    values,
                )
                cursor.execute(
                    """
                    SELECT id, strategy_version_id, name, universe, parameters,
                           start_date, end_date, status, metrics, error_message,
                           created_at, started_at, finished_at
                    FROM backtest_runs WHERE id = %s
                    """,
                    (run_id,),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    def list_backtest_runs(self, strategy_version_id: str = None, limit: int = 20) -> List[Dict]:
        query = """
            SELECT id, strategy_version_id, name, universe, parameters,
                   start_date, end_date, status, metrics, error_message,
                   created_at, started_at, finished_at
            FROM backtest_runs
        """
        params: List[Any] = []
        if strategy_version_id:
            query += " WHERE strategy_version_id = %s"
            params.append(strategy_version_id)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(max(1, min(limit, 100)))
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [self._dict_row(row) for row in cursor.fetchall()]

    def get_backtest_run(self, run_id: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, strategy_version_id, name, universe, parameters,
                           start_date, end_date, status, metrics, error_message,
                           created_at, started_at, finished_at
                    FROM backtest_runs
                    WHERE id = %s
                    """,
                    (run_id,),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    # ================================================================
    # V2 Strategy Workbench - Backtest Trades
    # ================================================================

    def insert_backtest_trades(self, run_id: str, trades: List[Dict]) -> int:
        written = 0
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                for trade in trades:
                    cursor.execute(
                        """
                        INSERT INTO backtest_trades
                        (backtest_run_id, trade_date, symbol, name, side, price,
                         quantity, amount, commission, reason)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            run_id,
                            trade.get("date"),
                            trade["symbol"],
                            trade.get("name"),
                            trade.get("side"),
                            float(trade.get("price", 0)),
                            int(trade.get("quantity", 0)),
                            float(trade.get("amount", 0)),
                            float(trade.get("commission", 0)),
                            trade.get("reason"),
                        ),
                    )
                    written += 1
        return written

    def list_backtest_trades(self, run_id: str) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, backtest_run_id, trade_date, symbol, name, side,
                           price, quantity, amount, commission, reason, created_at
                    FROM backtest_trades
                    WHERE backtest_run_id = %s
                    ORDER BY trade_date ASC, id ASC
                    """,
                    (run_id,),
                )
                return [self._dict_row(row) for row in cursor.fetchall()]

    # ================================================================
    # V2 Trading Infrastructure - Portfolios
    # ================================================================

    def create_portfolio(
        self,
        name: str,
        mode: str = "paper",
        base_currency: str = "CNY",
        initial_cash: float = 1000000.0,
        cash_balance: float = None,
        status: str = "active",
    ) -> Dict:
        if cash_balance is None:
            cash_balance = initial_cash
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO portfolios
                    (name, mode, base_currency, initial_cash, cash_balance, status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, name, mode, base_currency, initial_cash,
                              cash_balance, status, created_at, updated_at
                    """,
                    (name, mode, base_currency, initial_cash, cash_balance, status),
                )
                return self._dict_row(cursor.fetchone())

    def get_portfolio(self, portfolio_id: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, name, mode, base_currency, initial_cash,
                           cash_balance, status, created_at, updated_at
                    FROM portfolios
                    WHERE id = %s
                    """,
                    (portfolio_id,),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    def list_portfolios(self, mode: str = None, status: str = None) -> List[Dict]:
        query = """
            SELECT id, name, mode, base_currency, initial_cash,
                   cash_balance, status, created_at, updated_at
            FROM portfolios
            WHERE 1=1
        """
        params: List[Any] = []
        if mode:
            query += " AND mode = %s"
            params.append(mode)
        if status:
            query += " AND status = %s"
            params.append(status)
        query += " ORDER BY created_at DESC"
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [self._dict_row(row) for row in cursor.fetchall()]

    def update_portfolio(self, portfolio_id: str, **kwargs) -> Optional[Dict]:
        allowed = {"name", "mode", "cash_balance", "status"}
        updates: List[str] = []
        values: List[Any] = []
        for key, val in kwargs.items():
            if key in allowed:
                updates.append(f"{key} = %s")
                values.append(val)
        if not updates:
            return None
        updates.append("updated_at = NOW()")
        values.append(portfolio_id)
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"UPDATE portfolios SET {', '.join(updates)} WHERE id = %s",
                    values,
                )
                cursor.execute(
                    "SELECT id, name, mode, base_currency, initial_cash, "
                    "cash_balance, status, created_at, updated_at "
                    "FROM portfolios WHERE id = %s",
                    (portfolio_id,),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    # ================================================================
    # V2 Trading Infrastructure - Positions
    # ================================================================

    def upsert_position(
        self,
        portfolio_id: str,
        symbol: str,
        name: str = None,
        quantity: int = 0,
        available_quantity: int = None,
        avg_cost: float = 0,
        last_price: float = None,
        market_value: float = None,
    ) -> Dict:
        if available_quantity is None:
            available_quantity = quantity
        if market_value is None:
            market_value = quantity * (last_price or avg_cost)
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO positions
                    (portfolio_id, symbol, name, quantity, available_quantity,
                     avg_cost, last_price, market_value)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (portfolio_id, symbol) DO UPDATE SET
                        quantity = EXCLUDED.quantity,
                        available_quantity = EXCLUDED.available_quantity,
                        avg_cost = EXCLUDED.avg_cost,
                        last_price = EXCLUDED.last_price,
                        market_value = EXCLUDED.market_value,
                        updated_at = NOW()
                    RETURNING id, portfolio_id, symbol, name, quantity,
                              available_quantity, avg_cost, last_price,
                              market_value, updated_at
                    """,
                    (portfolio_id, symbol, name, quantity, available_quantity,
                     avg_cost, last_price, market_value),
                )
                return self._dict_row(cursor.fetchone())

    def get_positions(self, portfolio_id: str) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, portfolio_id, symbol, name, quantity,
                           available_quantity, avg_cost, last_price,
                           market_value, updated_at
                    FROM positions
                    WHERE portfolio_id = %s
                    ORDER BY market_value DESC
                    """,
                    (portfolio_id,),
                )
                return [self._dict_row(row) for row in cursor.fetchall()]

    def get_position(self, portfolio_id: str, symbol: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, portfolio_id, symbol, name, quantity,
                           available_quantity, avg_cost, last_price,
                           market_value, updated_at
                    FROM positions
                    WHERE portfolio_id = %s AND symbol = %s
                    """,
                    (portfolio_id, symbol),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    # ================================================================
    # V2 Trading Infrastructure - Orders
    # ================================================================

    def create_order(
        self,
        portfolio_id: str,
        symbol: str,
        side: str,
        order_type: str = "limit",
        price: float = None,
        quantity: int = None,
        name: str = None,
        signal_id: str = None,
        status: str = "pending",
        message: str = None,
    ) -> Dict:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO orders
                    (portfolio_id, signal_id, symbol, name, side, order_type,
                     price, quantity, status, message)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, portfolio_id, signal_id, broker_order_id,
                              symbol, name, side, order_type, price, quantity,
                              filled_quantity, status, message, created_at, updated_at
                    """,
                    (portfolio_id, signal_id, symbol, name, side, order_type,
                     price, quantity, status, message),
                )
                return self._dict_row(cursor.fetchone())

    def get_order(self, order_id: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, portfolio_id, signal_id, broker_order_id,
                           symbol, name, side, order_type, price, quantity,
                           filled_quantity, status, message, created_at, updated_at
                    FROM orders
                    WHERE id = %s
                    """,
                    (order_id,),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    def list_orders(
        self,
        portfolio_id: str = None,
        status: str = None,
        symbol: str = None,
        side: str = None,
        limit: int = 50,
    ) -> List[Dict]:
        query = """
            SELECT id, portfolio_id, signal_id, broker_order_id,
                   symbol, name, side, order_type, price, quantity,
                   filled_quantity, status, message, created_at, updated_at
            FROM orders
            WHERE 1=1
        """
        params: List[Any] = []
        if portfolio_id:
            query += " AND portfolio_id = %s"
            params.append(portfolio_id)
        if status:
            query += " AND status = %s"
            params.append(status)
        if symbol:
            query += " AND symbol = %s"
            params.append(symbol)
        if side:
            query += " AND side = %s"
            params.append(side)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(max(1, min(limit, 500)))
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [self._dict_row(row) for row in cursor.fetchall()]

    def update_order(
        self,
        order_id: str,
        status: str = None,
        filled_quantity: int = None,
        broker_order_id: str = None,
        message: str = None,
    ) -> Optional[Dict]:
        updates: List[str] = []
        values: List[Any] = []
        if status is not None:
            updates.append("status = %s")
            values.append(status)
        if filled_quantity is not None:
            updates.append("filled_quantity = %s")
            values.append(filled_quantity)
        if broker_order_id is not None:
            updates.append("broker_order_id = %s")
            values.append(broker_order_id)
        if message is not None:
            updates.append("message = %s")
            values.append(message)
        if not updates:
            return None
        updates.append("updated_at = NOW()")
        values.append(order_id)
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"UPDATE orders SET {', '.join(updates)} WHERE id = %s",
                    values,
                )
                cursor.execute(
                    "SELECT id, portfolio_id, signal_id, broker_order_id, "
                    "symbol, name, side, order_type, price, quantity, "
                    "filled_quantity, status, message, created_at, updated_at "
                    "FROM orders WHERE id = %s",
                    (order_id,),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    # ================================================================
    # V2 Trading Infrastructure - Trades
    # ================================================================

    def insert_trade(
        self,
        portfolio_id: str,
        symbol: str,
        side: str,
        price: float,
        quantity: int,
        amount: float,
        name: str = None,
        order_id: str = None,
        broker_trade_id: str = None,
        commission: float = 0,
    ) -> Dict:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO trades
                    (portfolio_id, order_id, broker_trade_id, symbol, name,
                     side, price, quantity, amount, commission)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, portfolio_id, order_id, broker_trade_id,
                              symbol, name, side, price, quantity, amount,
                              commission, traded_at
                    """,
                    (portfolio_id, order_id, broker_trade_id, symbol, name,
                     side, price, quantity, amount, commission),
                )
                return self._dict_row(cursor.fetchone())

    def list_trades(
        self,
        portfolio_id: str = None,
        symbol: str = None,
        side: str = None,
        limit: int = 100,
    ) -> List[Dict]:
        query = """
            SELECT id, portfolio_id, order_id, broker_trade_id,
                   symbol, name, side, price, quantity, amount,
                   commission, traded_at
            FROM trades
            WHERE 1=1
        """
        params: List[Any] = []
        if portfolio_id:
            query += " AND portfolio_id = %s"
            params.append(portfolio_id)
        if symbol:
            query += " AND symbol = %s"
            params.append(symbol)
        if side:
            query += " AND side = %s"
            params.append(side)
        query += " ORDER BY traded_at DESC LIMIT %s"
        params.append(max(1, min(limit, 500)))
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [self._dict_row(row) for row in cursor.fetchall()]

    # ================================================================
    # V2 Trading Infrastructure - Cash Ledger
    # ================================================================

    def insert_cash_ledger_entry(
        self,
        portfolio_id: str,
        event_type: str,
        amount: float,
        balance_after: float,
        ref_type: str = None,
        ref_id: str = None,
        note: str = None,
    ) -> Dict:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO cash_ledger
                    (portfolio_id, event_type, amount, balance_after,
                     ref_type, ref_id, note)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, portfolio_id, event_type, amount,
                              balance_after, ref_type, ref_id, note, created_at
                    """,
                    (portfolio_id, event_type, amount, balance_after,
                     ref_type, ref_id, note),
                )
                return self._dict_row(cursor.fetchone())

    def list_cash_ledger(
        self,
        portfolio_id: str,
        event_type: str = None,
        limit: int = 100,
    ) -> List[Dict]:
        query = """
            SELECT id, portfolio_id, event_type, amount, balance_after,
                   ref_type, ref_id, note, created_at
            FROM cash_ledger
            WHERE portfolio_id = %s
        """
        params: List[Any] = [portfolio_id]
        if event_type:
            query += " AND event_type = %s"
            params.append(event_type)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(max(1, min(limit, 500)))
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [self._dict_row(row) for row in cursor.fetchall()]

    # ================================================================
    # V2 Trading Infrastructure - Risk Rules
    # ================================================================

    def create_risk_rule(
        self,
        name: str,
        rule_type: str,
        severity: str = "block",
        enabled: bool = True,
        config: Dict = None,
    ) -> Dict:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO risk_rules (name, rule_type, severity, enabled, config)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, name, rule_type, severity, enabled,
                              config, created_at, updated_at
                    """,
                    (name, rule_type, severity, enabled,
                     json.dumps(config or {}, ensure_ascii=False)),
                )
                return self._dict_row(cursor.fetchone())

    def get_risk_rule(self, rule_id: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT id, name, rule_type, severity, enabled, "
                    "config, created_at, updated_at FROM risk_rules WHERE id = %s",
                    (rule_id,),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    def list_risk_rules(self, enabled: bool = None) -> List[Dict]:
        query = """
            SELECT id, name, rule_type, severity, enabled,
                   config, created_at, updated_at
            FROM risk_rules
            WHERE 1=1
        """
        params: List[Any] = []
        if enabled is not None:
            query += " AND enabled = %s"
            params.append(enabled)
        query += " ORDER BY name ASC"
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [self._dict_row(row) for row in cursor.fetchall()]

    def update_risk_rule(
        self,
        rule_id: str,
        enabled: bool = None,
        severity: str = None,
        config: Dict = None,
    ) -> Optional[Dict]:
        updates: List[str] = []
        values: List[Any] = []
        if enabled is not None:
            updates.append("enabled = %s")
            values.append(enabled)
        if severity is not None:
            updates.append("severity = %s")
            values.append(severity)
        if config is not None:
            updates.append("config = %s")
            values.append(json.dumps(config, ensure_ascii=False))
        if not updates:
            return None
        updates.append("updated_at = NOW()")
        values.append(rule_id)
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"UPDATE risk_rules SET {', '.join(updates)} WHERE id = %s",
                    values,
                )
                cursor.execute(
                    "SELECT id, name, rule_type, severity, enabled, "
                    "config, created_at, updated_at FROM risk_rules WHERE id = %s",
                    (rule_id,),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    # ================================================================
    # V2 Trading Infrastructure - Risk Events
    # ================================================================

    def insert_risk_event(
        self,
        severity: str,
        message: str,
        portfolio_id: str = None,
        order_id: str = None,
        signal_id: str = None,
        rule_id: str = None,
        payload: Dict = None,
    ) -> Dict:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO risk_events
                    (portfolio_id, order_id, signal_id, rule_id,
                     severity, message, payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, portfolio_id, order_id, signal_id,
                              rule_id, severity, message, payload, created_at
                    """,
                    (portfolio_id, order_id, signal_id, rule_id,
                     severity, message,
                     json.dumps(payload or {}, ensure_ascii=False)),
                )
                return self._dict_row(cursor.fetchone())

    def list_risk_events(
        self,
        portfolio_id: str = None,
        severity: str = None,
        limit: int = 100,
    ) -> List[Dict]:
        query = """
            SELECT id, portfolio_id, order_id, signal_id, rule_id,
                   severity, message, payload, created_at
            FROM risk_events
            WHERE 1=1
        """
        params: List[Any] = []
        if portfolio_id:
            query += " AND portfolio_id = %s"
            params.append(portfolio_id)
        if severity:
            query += " AND severity = %s"
            params.append(severity)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(max(1, min(limit, 500)))
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [self._dict_row(row) for row in cursor.fetchall()]

    # ================================================================
    # V2 Trading Infrastructure - Broker Connections
    # ================================================================

    def create_broker_connection(
        self,
        name: str,
        adapter_type: str,
        enabled: bool = False,
        config: Dict = None,
    ) -> Dict:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO broker_connections (name, adapter_type, enabled, config)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, name, adapter_type, enabled, config,
                              last_status, last_checked_at, created_at, updated_at
                    """,
                    (name, adapter_type, enabled,
                     json.dumps(config or {}, ensure_ascii=False)),
                )
                return self._dict_row(cursor.fetchone())

    def get_broker_connection(self, connection_id: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT id, name, adapter_type, enabled, config, "
                    "last_status, last_checked_at, created_at, updated_at "
                    "FROM broker_connections WHERE id = %s",
                    (connection_id,),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    def list_broker_connections(self, adapter_type: str = None) -> List[Dict]:
        query = """
            SELECT id, name, adapter_type, enabled, config,
                   last_status, last_checked_at, created_at, updated_at
            FROM broker_connections
            WHERE 1=1
        """
        params: List[Any] = []
        if adapter_type:
            query += " AND adapter_type = %s"
            params.append(adapter_type)
        query += " ORDER BY name ASC"
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [self._dict_row(row) for row in cursor.fetchall()]

    def update_broker_connection(
        self,
        connection_id: str,
        enabled: bool = None,
        config: Dict = None,
        last_status: str = None,
        last_checked_at: str = None,
    ) -> Optional[Dict]:
        updates: List[str] = []
        values: List[Any] = []
        if enabled is not None:
            updates.append("enabled = %s")
            values.append(enabled)
        if config is not None:
            updates.append("config = %s")
            values.append(json.dumps(config, ensure_ascii=False))
        if last_status is not None:
            updates.append("last_status = %s")
            values.append(last_status)
        if last_checked_at is not None:
            updates.append("last_checked_at = %s")
            values.append(last_checked_at)
        if not updates:
            return None
        updates.append("updated_at = NOW()")
        values.append(connection_id)
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"UPDATE broker_connections SET {', '.join(updates)} WHERE id = %s",
                    values,
                )
                cursor.execute(
                    "SELECT id, name, adapter_type, enabled, config, "
                    "last_status, last_checked_at, created_at, updated_at "
                    "FROM broker_connections WHERE id = %s",
                    (connection_id,),
                )
                row = cursor.fetchone()
        return self._dict_row(row) if row else None

    def get_most_frequent_kline_symbol(self) -> Optional[str]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT symbol FROM kline_history
                    WHERE timeframe = '1d'
                    GROUP BY symbol
                    ORDER BY COUNT(*) DESC, symbol ASC
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()
        return str(row[0]) if row else None

    def lookup_symbol_names(self, symbols: List[str]) -> Dict[str, str]:
        normalized_symbols = sorted({str(symbol).strip() for symbol in symbols if str(symbol).strip()})
        if not normalized_symbols:
            return {}
        names: Dict[str, str] = {}
        digit_to_symbols: Dict[str, List[str]] = {}
        for symbol in normalized_symbols:
            digits = "".join(ch for ch in symbol if ch.isdigit())
            if digits:
                digit_to_symbols.setdefault(digits, []).append(symbol)
        table_queries = [
            ("all_stocks_realtime", "code", True),
            ("stock_fundamentals", "symbol", False),
            ("stock_history", "symbol", False),
            ("kline_history", "symbol", False),
        ]
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                for table, symbol_column, include_digits in table_queries:
                    missing = [s for s in normalized_symbols if s not in names]
                    if not missing:
                        break
                    candidates: List[str] = []
                    for symbol in missing:
                        candidates.append(symbol)
                        digits = "".join(ch for ch in symbol if ch.isdigit())
                        if include_digits and digits:
                            candidates.append(digits)
                    candidates = sorted(set(candidates))
                    placeholders = ", ".join(["%s"] * len(candidates))
                    try:
                        cursor.execute(
                            f"""
                            SELECT {symbol_column}, name
                            FROM {table}
                            WHERE {symbol_column} IN ({placeholders})
                              AND COALESCE(name, '') <> ''
                            """,
                            tuple(candidates),
                        )
                        for raw_symbol, name in cursor.fetchall():
                            name_str = str(name).strip()
                            if not name_str:
                                continue
                            raw = str(raw_symbol).strip()
                            if raw in normalized_symbols:
                                names[raw] = name_str
                            digits = "".join(ch for ch in raw if ch.isdigit())
                            for symbol in digit_to_symbols.get(digits, []):
                                names.setdefault(symbol, name_str)
                    except Exception:
                        pass
        return names

    # ================================================================
    # Data Hub Utilities
    # ================================================================

    def table_exists(self, table_name: str) -> bool:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = %s
                    """,
                    (table_name,),
                )
                row = cursor.fetchone()
        return bool(row and row[0] > 0)

    def table_row_count(self, table_name: str) -> int:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                row = cursor.fetchone()
        return int(row[0]) if row else 0

    def table_fields(self, table_name: str) -> List[str]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (table_name,),
                )
                return [str(row[0]) for row in cursor.fetchall()]

    def table_column_max(self, table_name: str, column: str) -> Optional[str]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT MAX({column}) FROM {table_name}")
                row = cursor.fetchone()
        return str(row[0]) if row and row[0] else None

    def append_job_log(
        self,
        job_key: str,
        message: str,
        level: str = "info",
        payload: Dict = None,
    ) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT logs_json FROM data_hub_jobs WHERE job_key = %s", (job_key,))
                row = cursor.fetchone()
                if not row:
                    return
                logs = json.loads(row[0]) if row[0] else []
                if not isinstance(logs, list):
                    logs = []
                logs.append(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "level": level,
                        "message": message,
                        "payload": payload or {},
                    }
                )
                if len(logs) > 300:
                    logs = logs[-300:]
                cursor.execute(
                    "UPDATE data_hub_jobs SET logs_json = %s WHERE job_key = %s",
                    (json.dumps(logs, ensure_ascii=False), job_key),
                )

    def list_data_hub_jobs_by_scope(self, scope: str, limit: int = 10) -> List[Dict]:
        query = """
            SELECT job_key, action, status, progress, message, error_message,
                   created_at, finished_at, logs_json
            FROM data_hub_jobs
            WHERE scope = %s
               OR (
                   action = 'import_daily_data'
                   AND (
                       params_json LIKE %s
                       OR params_json LIKE %s
                   )
               )
            ORDER BY id DESC
            LIMIT %s
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                if scope in ("stock_fundamentals", "stock_history"):
                    cursor.execute(
                        query,
                        (
                            scope,
                            '%"task_type": "' + scope.replace("stock_", "") + '"%',
                            '%"task_type": "all"%',
                            max(1, min(limit, 100)),
                        ),
                    )
                elif scope == "daily_concept_sectors":
                    cursor.execute(
                        """
                        SELECT job_key, action, status, progress, message, error_message,
                               created_at, finished_at, logs_json
                        FROM data_hub_jobs
                        WHERE scope = %s
                           OR action IN ('backfill_concept_history', 'sync_today_concepts')
                        ORDER BY id DESC
                        LIMIT %s
                        """,
                        (scope, max(1, min(limit, 100))),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT job_key, action, status, progress, message, error_message,
                               created_at, finished_at, logs_json
                        FROM data_hub_jobs
                        WHERE scope = %s
                        ORDER BY id DESC
                        LIMIT %s
                        """,
                        (scope, max(1, min(limit, 100))),
                    )
                return [self._dict_row(row) for row in cursor.fetchall()]

    # ================================================================
    # Quality Check Utilities
    # ================================================================

    def check_stock_history_quality(self) -> Dict:
        result: Dict[str, Any] = {"exists": False, "metrics": {}}
        if not self.table_exists("stock_history"):
            result["table"] = "stock_history"
            return result
        result["exists"] = True
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM stock_history")
                total = int(cursor.fetchone()[0] or 0)
                cursor.execute("SELECT COUNT(*) - COUNT(DISTINCT symbol || '|' || date) FROM stock_history")
                duplicates = int(cursor.fetchone()[0] or 0)
                cursor.execute(
                    "SELECT SUM(CASE WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL THEN 1 ELSE 0 END) FROM stock_history"
                )
                null_ohlc = int(cursor.fetchone()[0] or 0)
                cursor.execute(
                    "SELECT SUM(CASE WHEN high < low OR high < open OR high < close OR low > open OR low > close THEN 1 ELSE 0 END) FROM stock_history"
                )
                invalid_ohlc = int(cursor.fetchone()[0] or 0)
                cursor.execute("SELECT SUM(CASE WHEN close IS NULL OR close <= 0 THEN 1 ELSE 0 END) FROM stock_history")
                invalid_close = int(cursor.fetchone()[0] or 0)
                cursor.execute("SELECT MAX(date) FROM stock_history")
                latest_date = cursor.fetchone()[0]
                cursor.execute(
                    "SELECT date FROM stock_history GROUP BY date ORDER BY date DESC LIMIT 40"
                )
                date_rows = [str(r[0]) for r in cursor.fetchall() if r and r[0]]
        result["metrics"] = {
            "table": "stock_history",
            "total": total,
            "duplicates": duplicates,
            "null_ohlc": null_ohlc,
            "invalid_ohlc": invalid_ohlc,
            "invalid_close": invalid_close,
            "latest_date": latest_date,
            "date_rows": date_rows,
        }
        return result

    def check_fundamental_quality(self) -> Dict:
        result: Dict[str, Any] = {"exists": False, "metrics": {}}
        if not self.table_exists("stock_fundamentals"):
            result["table"] = "stock_fundamentals"
            return result
        result["exists"] = True
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM stock_fundamentals")
                total = int(cursor.fetchone()[0] or 0)
                cursor.execute("SELECT COUNT(*) - COUNT(DISTINCT symbol) FROM stock_fundamentals")
                duplicates = int(cursor.fetchone()[0] or 0)
                cursor.execute(
                    "SELECT SUM(CASE WHEN current_price IS NULL OR pe_dynamic IS NULL OR pb IS NULL OR total_market_cap IS NULL THEN 1 ELSE 0 END) FROM stock_fundamentals"
                )
                null_core = int(cursor.fetchone()[0] or 0)
                cursor.execute(
                    "SELECT SUM(CASE WHEN current_price IS NULL OR current_price <= 0 THEN 1 ELSE 0 END) FROM stock_fundamentals"
                )
                invalid_price = int(cursor.fetchone()[0] or 0)
                cursor.execute("SELECT MAX(updated_at) FROM stock_fundamentals")
                latest = cursor.fetchone()[0]
        result["metrics"] = {
            "table": "stock_fundamentals",
            "total": total,
            "duplicates": duplicates,
            "null_core": null_core,
            "invalid_price": invalid_price,
            "latest": latest,
        }
        return result

    def check_concept_quality(self) -> Dict:
        result: Dict[str, Any] = {"exists": False, "metrics": {}}
        if not self.table_exists("daily_concept_sectors"):
            result["table"] = "daily_concept_sectors"
            return result
        result["exists"] = True
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM daily_concept_sectors")
                total = int(cursor.fetchone()[0] or 0)
                cursor.execute("SELECT COUNT(*) - COUNT(DISTINCT date || '|' || sector_name) FROM daily_concept_sectors")
                duplicates = int(cursor.fetchone()[0] or 0)
                cursor.execute(
                    "SELECT SUM(CASE WHEN sector_name IS NULL OR TRIM(sector_name) = '' OR change_percent IS NULL THEN 1 ELSE 0 END) FROM daily_concept_sectors"
                )
                null_core = int(cursor.fetchone()[0] or 0)
                cursor.execute("SELECT MAX(date) FROM daily_concept_sectors")
                latest = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(DISTINCT date) FROM daily_concept_sectors")
                days = int(cursor.fetchone()[0] or 0)
                cursor.execute(
                    "SELECT date FROM daily_concept_sectors GROUP BY date ORDER BY date DESC LIMIT 40"
                )
                date_rows = [str(r[0]) for r in cursor.fetchall() if r and r[0]]
        result["metrics"] = {
            "table": "daily_concept_sectors",
            "total": total,
            "duplicates": duplicates,
            "null_core": null_core,
            "latest_date": latest,
            "days": days,
            "date_rows": date_rows,
        }
        return result

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
            str(record.get("source") or "tushare"),
            datetime.now(),
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

    def _normalize_stock_code(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        if not text:
            return ""
        text = text.replace(".", "_")
        if "_" in text:
            market, raw = text.split("_", 1)
            market = market[:2]
            return f"{market}_{raw.zfill(6)}" if raw.isdigit() else f"{market}_{raw}"
        for market in ("SH", "SZ", "BJ"):
            if text.startswith(market):
                digits = "".join(ch for ch in text[len(market):] if ch.isdigit())
                return f"{market}_{digits.zfill(6)}" if digits else text
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) >= 6:
            raw = digits[-6:]
            if raw.startswith("6"):
                return f"SH_{raw}"
            if raw.startswith(("0", "3")):
                return f"SZ_{raw}"
            if raw.startswith(("9", "4", "8")):
                return f"BJ_{raw}"
            return raw
        return text

    def _normalize_date_text(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        text = str(value or "").strip()
        if len(text) == 8 and text.isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        return text[:10]

    def _json_or_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)

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
            "actual_source": row.get("actual_source"),
            "fallback_reason": row.get("fallback_reason"),
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
            "script_content": row["script_content"] or "",
            "interval_seconds": row["interval_seconds"],
            "enabled": bool(row["enabled"]),
            "is_running": bool(row["is_running"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    def _preset_strategy_code(self) -> str:
        return """POSITION_PERCENT = 0.18
MOMENTUM_THRESHOLD = 0.012


def initialize(context):
    context.lookback = 3
    set_benchmark("000300.SH")
    set_option("avoid_future_data", True)
    set_order_cost(open_tax=0.0, close_tax=0.0005, commission=0.0003, min_commission=5.0)


def handle_data(context, data):
    for security in context.universe:
        closes = history(security, context.lookback, "1d", "close")
        if len(closes) < context.lookback or not closes[-2]:
            continue
        momentum = (closes[-1] - closes[-2]) / closes[-2]
        target = POSITION_PERCENT if momentum > MOMENTUM_THRESHOLD else 0.0
        order_target_percent(security, target)
        record(security=security, momentum=float(momentum), target=float(target))
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
            source TEXT DEFAULT 'tushare',
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
            source TEXT DEFAULT 'tushare',
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
            source TEXT DEFAULT 'tushare',
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
            source TEXT DEFAULT 'tushare',
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
            source TEXT DEFAULT 'tushare',
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
            source TEXT DEFAULT 'tushare',
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
            source TEXT DEFAULT 'tushare',
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
            source TEXT DEFAULT 'tushare',
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
            source TEXT NOT NULL DEFAULT 'tushare',
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
            current_price DOUBLE PRECISION,
            price DOUBLE PRECISION,
            change_amount DOUBLE PRECISION,
            change_percent DOUBLE PRECISION,
            volume DOUBLE PRECISION,
            amount DOUBLE PRECISION,
            amplitude DOUBLE PRECISION,
            turnover_rate DOUBLE PRECISION,
            pe DOUBLE PRECISION,
            pe_dynamic DOUBLE PRECISION,
            pb DOUBLE PRECISION,
            dividend_yield DOUBLE PRECISION,
            market_cap DOUBLE PRECISION,
            total_market_cap DOUBLE PRECISION,
            float_market_cap DOUBLE PRECISION,
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

        CREATE TABLE IF NOT EXISTS hot_concepts_history (
            id BIGSERIAL PRIMARY KEY,
            trade_date DATE NOT NULL,
            rank INTEGER,
            name TEXT NOT NULL,
            change_percent DOUBLE PRECISION,
            inflow DOUBLE PRECISION,
            outflow DOUBLE PRECISION,
            net_inflow DOUBLE PRECISION,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(trade_date, name)
        );

        CREATE TABLE IF NOT EXISTS ths_hot_history (
            id BIGSERIAL PRIMARY KEY,
            trade_date DATE NOT NULL,
            rank INTEGER,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            hot_value DOUBLE PRECISION,
            change_percent DOUBLE PRECISION,
            price DOUBLE PRECISION,
            reason TEXT,
            tags TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(trade_date, code)
        );

        CREATE TABLE IF NOT EXISTS lianban_ladder_history (
            id BIGSERIAL PRIMARY KEY,
            date DATE NOT NULL,
            prev_date DATE,
            today_level INTEGER NOT NULL DEFAULT 1,
            code TEXT NOT NULL,
            name TEXT,
            price DOUBLE PRECISION,
            change_percent DOUBLE PRECISION,
            duration_days INTEGER,
            reason TEXT,
            payload_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, code)
        );

        CREATE TABLE IF NOT EXISTS daily_concept_sectors (
            id BIGSERIAL PRIMARY KEY,
            date DATE NOT NULL,
            sector_code TEXT,
            sector_name TEXT NOT NULL,
            change_percent DOUBLE PRECISION,
            leader_stock TEXT,
            leader_change DOUBLE PRECISION,
            total_market_cap DOUBLE PRECISION,
            up_count INTEGER,
            down_count INTEGER,
            rank INTEGER,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, sector_name)
        );

        CREATE TABLE IF NOT EXISTS replay_notes (
            id BIGSERIAL PRIMARY KEY,
            note_date DATE NOT NULL UNIQUE,
            title TEXT,
            content TEXT,
            payload_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS news_stream (
            id BIGSERIAL PRIMARY KEY,
            source TEXT NOT NULL,
            publish_time TIMESTAMP NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            importance INTEGER DEFAULT 1,
            category TEXT,
            related_stocks TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source, publish_time, title)
        );

        CREATE TABLE IF NOT EXISTS market_calendar_events (
            id BIGSERIAL PRIMARY KEY,
            event_key TEXT NOT NULL UNIQUE,
            event_date DATE NOT NULL,
            title TEXT NOT NULL,
            category TEXT,
            market TEXT DEFAULT 'A股',
            source TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS stock_ma_data (
            id BIGSERIAL PRIMARY KEY,
            symbol TEXT NOT NULL,
            name TEXT,
            date DATE NOT NULL,
            close DOUBLE PRECISION,
            ma5 DOUBLE PRECISION,
            ma10 DOUBLE PRECISION,
            ma20 DOUBLE PRECISION,
            ma30 DOUBLE PRECISION,
            ma_diff_max DOUBLE PRECISION,
            ma_diff_pct DOUBLE PRECISION,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, date)
        );

        CREATE TABLE IF NOT EXISTS factor_definitions (
            id BIGSERIAL PRIMARY KEY,
            factor_code TEXT NOT NULL UNIQUE,
            factor_name TEXT NOT NULL,
            category TEXT NOT NULL,
            subcategory TEXT,
            description TEXT,
            formula TEXT,
            data_source TEXT,
            update_frequency TEXT DEFAULT 'daily',
            unit TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS factor_data (
            id BIGSERIAL PRIMARY KEY,
            factor_code TEXT NOT NULL,
            symbol TEXT NOT NULL,
            date DATE NOT NULL,
            value DOUBLE PRECISION,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(factor_code, symbol, date)
        );

        CREATE TABLE IF NOT EXISTS factor_sync_logs (
            id BIGSERIAL PRIMARY KEY,
            factor_code TEXT NOT NULL,
            date DATE,
            status TEXT NOT NULL,
            records_count INTEGER DEFAULT 0,
            error_message TEXT,
            sync_duration_ms INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sync_logs (
            id BIGSERIAL PRIMARY KEY,
            data_type TEXT NOT NULL,
            trade_date DATE,
            status TEXT NOT NULL,
            records_count INTEGER DEFAULT 0,
            error_message TEXT,
            duration_ms INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS data_hub_jobs (
            id BIGSERIAL PRIMARY KEY,
            job_key TEXT NOT NULL UNIQUE,
            action TEXT NOT NULL,
            scope TEXT,
            params_json TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            progress DOUBLE PRECISION DEFAULT 0,
            current INTEGER DEFAULT 0,
            total INTEGER DEFAULT 0,
            message TEXT,
            error_message TEXT,
            result_json TEXT,
            logs_json TEXT,
            parent_job_key TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            finished_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS data_hub_quality_reports (
            id BIGSERIAL PRIMARY KEY,
            report_key TEXT NOT NULL UNIQUE,
            scope TEXT,
            status TEXT NOT NULL,
            summary_json TEXT,
            checks_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS data_dev_tasks (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            sql_content TEXT NOT NULL,
            cron_expression TEXT NOT NULL,
            enabled BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS data_dev_logs (
            id BIGSERIAL PRIMARY KEY,
            task_id BIGINT NOT NULL REFERENCES data_dev_tasks(id) ON DELETE CASCADE,
            execution_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            execution_end TIMESTAMP,
            status TEXT NOT NULL,
            error_message TEXT,
            affected_rows INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS dragon_tiger_board (
            id BIGSERIAL PRIMARY KEY,
            key_value TEXT,
            row_rank INTEGER,
            payload_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS northbound_flow (
            id BIGSERIAL PRIMARY KEY,
            key_value TEXT,
            row_rank INTEGER,
            payload_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sector_realtime (
            id BIGSERIAL PRIMARY KEY,
            key_value TEXT,
            row_rank INTEGER,
            payload_json TEXT,
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
        CREATE INDEX IF NOT EXISTS idx_hot_concepts_history_date ON hot_concepts_history(trade_date);
        CREATE INDEX IF NOT EXISTS idx_ths_hot_history_date ON ths_hot_history(trade_date);
        CREATE INDEX IF NOT EXISTS idx_lianban_ladder_date_level ON lianban_ladder_history(date, today_level);
        CREATE INDEX IF NOT EXISTS idx_daily_concept_sectors_date ON daily_concept_sectors(date);
        CREATE INDEX IF NOT EXISTS idx_news_stream_source_time ON news_stream(source, publish_time DESC);
        CREATE INDEX IF NOT EXISTS idx_calendar_events_date ON market_calendar_events(event_date);
        CREATE INDEX IF NOT EXISTS idx_stock_ma_data_symbol_date ON stock_ma_data(symbol, date);
        CREATE INDEX IF NOT EXISTS idx_factor_data_code_date ON factor_data(factor_code, date);
        CREATE INDEX IF NOT EXISTS idx_factor_data_symbol_date ON factor_data(symbol, date);
        CREATE INDEX IF NOT EXISTS idx_data_hub_jobs_status ON data_hub_jobs(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_data_dev_logs_task ON data_dev_logs(task_id, execution_start);
        """


def encode_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)
