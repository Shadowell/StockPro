from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

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
        *,
        auxiliary_datasets: dict[str, list[dict[str, Any]]] | None = None,
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
                dataset_snapshot = self._publish_research_datasets(
                    cursor,
                    run_id=run_id,
                    instruments=instruments,
                    daily_rows=daily_rows,
                    trade_date=trade_date,
                    auxiliary_datasets=auxiliary_datasets or {},
                )
            connection.commit()
        result = {
            "run_id": run_id,
            "status": "success",
            "instrument_count": len(instruments),
            "daily_count": len(daily_rows),
            "trade_date": trade_date,
        }
        if dataset_snapshot:
            result["dataset_snapshot"] = dataset_snapshot
        return result

    def update_history_progress(self, run_id: int, **payload: Any) -> None:
        """Persist bounded progress for a long-running full-market history run."""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE a_share_daily_sync_runs
                    SET sync_scope='history',
                        requested_start_date=%s,
                        requested_end_date=%s,
                        trade_date_count=%s,
                        processed_trade_dates=%s,
                        last_processed_trade_date=%s,
                        daily_count=%s,
                        updated_at=NOW()
                    WHERE id=%s AND status='running'
                    """,
                    (
                        payload.get("start_date"),
                        payload.get("end_date"),
                        int(payload.get("total_trade_dates") or 0),
                        int(payload.get("processed_trade_dates") or 0),
                        payload.get("last_processed_trade_date"),
                        int(payload.get("daily_count") or 0),
                        run_id,
                    ),
                )
            connection.commit()

    def complete_history_run(
        self,
        run_id: int,
        instruments: list[dict[str, Any]],
        daily_rows: list[dict[str, Any]],
        start_date: str,
        end_date: str,
        *,
        trade_date_count: int,
    ) -> dict[str, Any]:
        """Atomically upsert the full history after all provider calls succeed."""
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
                cursor.execute(
                    """
                    UPDATE a_share_daily_sync_runs
                    SET status='success', sync_scope='history',
                        trade_date=%s, requested_start_date=%s, requested_end_date=%s,
                        trade_date_count=%s, processed_trade_dates=%s,
                        last_processed_trade_date=%s, instrument_count=%s, daily_count=%s,
                        error_message=NULL, finished_at=NOW(), updated_at=NOW()
                    WHERE id=%s
                    """,
                    (
                        end_date,
                        start_date,
                        end_date,
                        int(trade_date_count),
                        int(trade_date_count),
                        end_date,
                        len(instruments),
                        len(daily_rows),
                        run_id,
                    ),
                )
            connection.commit()
        return {
            "run_id": run_id,
            "status": "success",
            "sync_scope": "history",
            "instrument_count": len(instruments),
            "daily_count": len(daily_rows),
            "start_date": start_date,
            "end_date": end_date,
            "trade_date_count": int(trade_date_count),
        }

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(key): AshareInstrumentRepository._jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [AshareInstrumentRepository._jsonable(item) for item in value]
        return value

    @classmethod
    def _content_hash(cls, value: Any) -> str:
        payload = json.dumps(cls._jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _dataset_id(cursor, code: str) -> int:
        cursor.execute("SELECT id FROM dataset_definitions WHERE code=%s", (code,))
        row = cursor.fetchone()
        if not row:
            raise RuntimeError(f"数据集未注册：{code}")
        return int(row["id"])

    @staticmethod
    def _record_symbol_count(rows: list[dict[str, Any]]) -> int:
        return len({str(row.get("symbol") or "").strip() for row in rows if str(row.get("symbol") or "").strip()})

    def _publish_partition(
        self,
        cursor,
        *,
        dataset_code: str,
        partition_key: str,
        rows: list[dict[str, Any]],
        trade_date: str,
        request_params: dict[str, Any],
        allow_empty: bool = False,
    ) -> dict[str, Any]:
        if not rows and not allow_empty:
            raise RuntimeError(f"{dataset_code} 没有可发布的规范化记录")
        normalized_rows = [self._jsonable(dict(row)) for row in rows]
        normalized_rows.sort(key=self._content_hash)
        content_hash = self._content_hash(normalized_rows)
        dataset_id = self._dataset_id(cursor, dataset_code)
        cursor.execute(
            """
            INSERT INTO source_entitlements(dataset_code,source,permission_state,cache_policy,export_policy,contract_version,checked_at)
            VALUES (%s,'tushare','available','local_pg_research_only','disabled','ashare.dataset.v1',NOW())
            ON CONFLICT(dataset_code,source) DO UPDATE SET
                permission_state='available', cache_policy=EXCLUDED.cache_policy,
                export_policy=EXCLUDED.export_policy, contract_version=EXCLUDED.contract_version,
                checked_at=NOW()
            """,
            (dataset_code,),
        )
        cursor.execute(
            """
            INSERT INTO source_fetch_runs(
                dataset_id,requested_source,actual_source,request_params,schema_version,
                finished_at,status,row_count,response_hash
            ) VALUES (%s,'tushare','tushare',%s,'ashare.dataset.v1',NOW(),'success',%s,%s)
            RETURNING id
            """,
            (dataset_id, Jsonb(self._jsonable(request_params)), len(normalized_rows), content_hash),
        )
        fetch_run_id = int(cursor.fetchone()["id"])
        cursor.execute(
            """
            INSERT INTO dataset_partitions(
                dataset_id,fetch_run_id,partition_key,start_date,end_date,symbol_count,row_count,
                content_hash,available_at,knowledge_cutoff_at,status
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW(),'sealed')
            ON CONFLICT(dataset_id,partition_key,content_hash) DO NOTHING
            RETURNING id
            """,
            (
                dataset_id,
                fetch_run_id,
                partition_key,
                trade_date,
                trade_date,
                self._record_symbol_count(normalized_rows),
                len(normalized_rows),
                content_hash,
            ),
        )
        inserted = cursor.fetchone()
        if inserted:
            partition_id = int(inserted["id"])
            if normalized_rows:
                cursor.executemany(
                    """
                    INSERT INTO dataset_partition_records(partition_id,record_ordinal,record_hash,payload)
                    VALUES (%s,%s,%s,%s)
                    ON CONFLICT(partition_id,record_ordinal) DO NOTHING
                    """,
                    [
                        (partition_id, ordinal, self._content_hash(row), Jsonb(row))
                        for ordinal, row in enumerate(normalized_rows, start=1)
                    ],
                )
        else:
            cursor.execute(
                """
                SELECT id FROM dataset_partitions
                WHERE dataset_id=%s AND partition_key=%s AND content_hash=%s
                """,
                (dataset_id, partition_key, content_hash),
            )
            partition_id = int(cursor.fetchone()["id"])
        cursor.execute(
            """
            INSERT INTO dataset_watermarks(dataset_id,last_published_trade_date,last_fetch_run_id,updated_at)
            VALUES (%s,%s,%s,NOW())
            ON CONFLICT(dataset_id) DO UPDATE SET
                last_published_trade_date=EXCLUDED.last_published_trade_date,
                last_fetch_run_id=EXCLUDED.last_fetch_run_id,
                updated_at=NOW()
            """,
            (dataset_id, trade_date, fetch_run_id),
        )
        return {
            "dataset_code": dataset_code,
            "partition_id": partition_id,
            "content_hash": content_hash,
            "row_count": len(normalized_rows),
            "symbol_count": self._record_symbol_count(normalized_rows),
        }

    def _seal_research_snapshot(self, cursor, trade_date: str, partitions: list[dict[str, Any]]) -> dict[str, Any]:
        ordered = sorted(partitions, key=lambda item: item["dataset_code"])
        manifest_hash = self._content_hash([
            {"dataset_code": item["dataset_code"], "partition_id": item["partition_id"], "content_hash": item["content_hash"]}
            for item in ordered
        ])
        name = f"ashare-research-{trade_date}-{manifest_hash[:12]}"
        cursor.execute(
            """
            INSERT INTO dataset_snapshots(name,status,knowledge_cutoff_at,manifest_hash)
            VALUES (%s,'draft',NOW(),%s)
            ON CONFLICT(name) DO NOTHING
            RETURNING id
            """,
            (name, manifest_hash),
        )
        row = cursor.fetchone()
        if row:
            snapshot_id = int(row["id"])
            cursor.executemany(
                """
                INSERT INTO dataset_snapshot_items(snapshot_id,partition_id,dataset_code,content_hash)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT(snapshot_id,partition_id) DO NOTHING
                """,
                [
                    (snapshot_id, item["partition_id"], item["dataset_code"], item["content_hash"])
                    for item in ordered
                ],
            )
            cursor.execute(
                "UPDATE dataset_snapshots SET status='sealed', sealed_at=NOW() WHERE id=%s AND status='draft'",
                (snapshot_id,),
            )
        else:
            cursor.execute("SELECT id FROM dataset_snapshots WHERE name=%s", (name,))
            snapshot_id = int(cursor.fetchone()["id"])
        return {
            "id": snapshot_id,
            "name": name,
            "status": "sealed",
            "manifest_hash": manifest_hash,
            "dataset_codes": [item["dataset_code"] for item in ordered],
        }

    def _publish_research_datasets(
        self,
        cursor,
        *,
        run_id: int,
        instruments: list[dict[str, Any]],
        daily_rows: list[dict[str, Any]],
        trade_date: str | None,
        auxiliary_datasets: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any] | None:
        if not trade_date:
            return None
        dataset_rows: dict[str, list[dict[str, Any]]] = {
            "security_master": [
                {
                    "symbol": row["symbol"],
                    "exchange": row["exchange"],
                    "name": row["name"],
                    "asset_class": "stock",
                    "currency": "CNY",
                    "lot_size": 100,
                    "tick_size": 0.01,
                    "industry": row.get("industry"),
                    "board": row.get("board"),
                    "list_status": row.get("list_status"),
                    "list_date": row.get("list_date"),
                    "delist_date": row.get("delist_date"),
                    "source": "tushare.stock_basic",
                }
                for row in instruments
            ],
            "daily_bars": [
                {
                    "symbol": row["symbol"],
                    "name": row["name"],
                    "trade_date": row["trade_date"],
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": row.get("close"),
                    "volume": row.get("volume"),
                    "amount": row.get("amount"),
                    "source": "tushare.daily",
                }
                for row in daily_rows
            ],
            **auxiliary_datasets,
        }
        required_codes = [
            "security_master", "trade_calendar", "daily_bars", "adj_factor", "daily_basic",
            "suspensions", "price_limits", "corporate_actions", "benchmark_bars",
        ]
        partitions = [
            self._publish_partition(
                cursor,
                dataset_code=code,
                partition_key=f"{code}:{trade_date}:tushare",
                rows=dataset_rows.get(code) or [],
                trade_date=trade_date,
                request_params={"trigger_run_id": run_id, "trade_date": trade_date, "source": "a_share_daily_sync"},
                allow_empty=code in {"suspensions", "corporate_actions"},
            )
            for code in required_codes
        ]
        return self._seal_research_snapshot(cursor, trade_date, partitions)

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
                    SELECT id,trigger,status,provider,sync_scope,trade_date,
                           requested_start_date,requested_end_date,trade_date_count,
                           processed_trade_dates,last_processed_trade_date,
                           instrument_count,daily_count,error_message,started_at,finished_at
                    FROM a_share_daily_sync_runs ORDER BY id DESC LIMIT 1
                    """
                )
                row = cursor.fetchone()
        if not row:
            return None
        return {
            "run_id": int(row["id"]), "trigger": row["trigger"], "status": row["status"],
            "provider": row["provider"], "trade_date": row["trade_date"].isoformat() if row["trade_date"] else None,
            "sync_scope": row["sync_scope"],
            "start_date": row["requested_start_date"].isoformat() if row["requested_start_date"] else None,
            "end_date": row["requested_end_date"].isoformat() if row["requested_end_date"] else None,
            "trade_date_count": int(row["trade_date_count"] or 0),
            "processed_trade_dates": int(row["processed_trade_dates"] or 0),
            "last_processed_trade_date": row["last_processed_trade_date"].isoformat() if row["last_processed_trade_date"] else None,
            "instrument_count": int(row["instrument_count"]), "daily_count": int(row["daily_count"]),
            "error_message": row["error_message"],
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
        }
