"""Immutable, local PostgreSQL research dataset manifests.

The legacy K-line cache is mutable because an upstream provider can correct a
bar.  This service publishes a *new* content-addressed partition and seals a
manifest over it, so factor and backtest code can later select an exact input
without performing a provider request.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

import psycopg2.extras


SHANGHAI = ZoneInfo("Asia/Shanghai")

DATASETS: Sequence[Dict[str, Any]] = (
    {"code": "security_master", "name": "证券主数据", "primary": "tushare", "fallback": "akshare", "quality": {"historical": True}},
    {"code": "trade_calendar", "name": "交易日历", "primary": "tushare", "fallback": "akshare", "quality": {"open_day_required": True}},
    {"code": "daily_bars", "name": "A 股不复权日线", "primary": "tushare", "fallback": "akshare", "quality": {"ohlc": "blocking", "mixed_source": "blocking"}},
    {"code": "adjustment_factors", "name": "复权因子", "primary": "tushare", "fallback": "akshare", "quality": {"required_for_adjusted_research": True}},
    {"code": "daily_valuation", "name": "每日估值与换手", "primary": "tushare", "fallback": "akshare", "quality": {"optional_fields": "warning"}},
    {"code": "suspensions", "name": "停复牌", "primary": "tushare", "fallback": "akshare", "quality": {"suspension_explains_missing_bar": True}},
    {"code": "price_limits", "name": "涨跌停价格", "primary": "tushare", "fallback": "akshare", "quality": {"limit_price": "blocking"}},
    {"code": "benchmark_bars", "name": "基准指数日线", "primary": "tushare", "fallback": "akshare", "quality": {"benchmark": True}},
    {"code": "corporate_actions", "name": "公司行为", "primary": "tushare", "fallback": "akshare", "quality": {"availability": "blocking"}},
    {"code": "universe_history", "name": "历史证券池与行业", "primary": "tushare", "fallback": "akshare", "quality": {"effective_dated": True}},
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_daily_bar_rows(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Return deterministic quality findings; an empty result is publishable."""
    issues: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        symbol = str(row.get("symbol") or "")
        trade_date = str(row.get("trade_date") or "")
        record_key = f"{symbol}:{trade_date}"
        if (symbol, trade_date) in seen:
            issues.append({"check_code": "duplicate_daily_bar", "severity": "blocking", "record_key": record_key, "message": "同一标的交易日存在重复日线", "details": {}})
            continue
        seen.add((symbol, trade_date))

        values: Dict[str, Optional[float]] = {}
        invalid_numeric = False
        for field in ("open", "high", "low", "close", "volume", "turnover"):
            raw = row.get(field)
            if raw is None:
                values[field] = None
                continue
            try:
                values[field] = float(raw)
            except (TypeError, ValueError):
                values[field] = None
                invalid_numeric = True
        if invalid_numeric:
            issues.append({"check_code": "invalid_numeric", "severity": "blocking", "record_key": record_key, "message": "日线含不可解析数值", "details": {}})
            continue
        if any(values[field] is None or values[field] <= 0 for field in ("open", "high", "low", "close")):
            issues.append({"check_code": "missing_or_non_positive_ohlc", "severity": "blocking", "record_key": record_key, "message": "OHLC 必须为正数", "details": {key: values[key] for key in ("open", "high", "low", "close")}})
            continue
        if values["high"] < max(values["open"], values["close"], values["low"]) or values["low"] > min(values["open"], values["close"], values["high"]):
            issues.append({"check_code": "illegal_ohlc", "severity": "blocking", "record_key": record_key, "message": "最高/最低价不满足 OHLC 约束", "details": {key: values[key] for key in ("open", "high", "low", "close")}})
        if (values["volume"] is not None and values["volume"] < 0) or (values["turnover"] is not None and values["turnover"] < 0):
            issues.append({"check_code": "negative_volume_or_turnover", "severity": "blocking", "record_key": record_key, "message": "成交量或成交额为负数", "details": {"volume": values["volume"], "turnover": values["turnover"]}})
    return issues


class DatasetSnapshotService:
    def __init__(self, database):
        self.database = database

    def install_registry(self) -> int:
        rows = [
            (item["code"], item["name"], item["primary"], item["fallback"], "v1", psycopg2.extras.Json(item["quality"]))
            for item in DATASETS
        ]
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO dataset_definitions
                    (code, name, primary_source, fallback_source, schema_version, quality_policy)
                    VALUES %s
                    ON CONFLICT (code) DO UPDATE SET
                        name = EXCLUDED.name,
                        primary_source = EXCLUDED.primary_source,
                        fallback_source = EXCLUDED.fallback_source,
                        schema_version = EXCLUDED.schema_version,
                        quality_policy = EXCLUDED.quality_policy,
                        updated_at = NOW()
                    """,
                    rows,
                    page_size=2000,
                )
                cursor.execute(
                    """
                    INSERT INTO source_entitlements(dataset_code, source, permission_state, cache_policy, export_policy, contract_version)
                    SELECT code, primary_source, 'catalogue_pending_probe', 'local_pg_research_only', 'disabled', 'tushare-5000-v1'
                    FROM dataset_definitions
                    ON CONFLICT (dataset_code, source) DO UPDATE SET checked_at = NOW(), contract_version = EXCLUDED.contract_version
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO source_entitlements(dataset_code, source, permission_state, cache_policy, export_policy, contract_version)
                    SELECT code, fallback_source, 'fallback_allowed', 'local_pg_research_only', 'disabled', 'akshare-fallback-v1'
                    FROM dataset_definitions WHERE fallback_source IS NOT NULL
                    ON CONFLICT (dataset_code, source) DO UPDATE SET checked_at = NOW(), contract_version = EXCLUDED.contract_version
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO dataset_sync_schedules(code, cron, timezone, enabled, catchup_days, max_retries)
                    VALUES ('daily_reference_publication', '30 17 * * 1-5', 'Asia/Shanghai', FALSE, 5, 3)
                    ON CONFLICT (code) DO NOTHING
                    """
                )
        return len(rows)

    def list_datasets(self) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT d.code, d.name, d.primary_source, d.fallback_source, d.schema_version, d.quality_policy, d.enabled,
                           p.id AS latest_partition_id, p.start_date, p.end_date, p.row_count, p.symbol_count,
                           p.status AS partition_status, p.content_hash, p.available_at, p.knowledge_cutoff_at,
                           f.requested_source, f.actual_source, f.fallback_reason, f.response_hash,
                           COALESCE(q.blocking_issues, 0) AS blocking_issues
                    FROM dataset_definitions d
                    LEFT JOIN LATERAL (
                        SELECT * FROM dataset_partitions p
                        WHERE p.dataset_id = d.id ORDER BY p.created_at DESC LIMIT 1
                    ) p ON TRUE
                    LEFT JOIN source_fetch_runs f ON f.id = p.fetch_run_id
                    LEFT JOIN LATERAL (
                        SELECT COUNT(*)::INTEGER AS blocking_issues FROM data_quality_issues qi
                        WHERE qi.partition_id = p.id AND qi.severity = 'blocking'
                    ) q ON TRUE
                    ORDER BY d.code
                    """
                )
                return [dict(row) for row in cursor.fetchall()]

    def list_quality_issues(self, dataset_code: Optional[str] = None, severity: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if dataset_code:
            clauses.append("d.code = %s")
            params.append(dataset_code)
        if severity:
            clauses.append("qi.severity = %s")
            params.append(severity)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT qi.id, d.code AS dataset_code, qi.partition_id, qi.check_code, qi.severity,
                           qi.record_key, qi.message, qi.details, qi.created_at
                    FROM data_quality_issues qi
                    JOIN dataset_partitions p ON p.id = qi.partition_id
                    JOIN dataset_definitions d ON d.id = p.dataset_id
                    {where}
                    ORDER BY qi.created_at DESC, qi.id DESC
                    LIMIT %s
                    """,
                    params,
                )
                return [dict(row) for row in cursor.fetchall()]

    def list_snapshots(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT s.id, s.name, s.status, s.knowledge_cutoff_at, s.manifest_hash, s.created_at, s.sealed_at,
                           COUNT(i.partition_id)::INTEGER AS partition_count,
                           ARRAY_REMOVE(ARRAY_AGG(DISTINCT i.dataset_code), NULL) AS datasets
                    FROM dataset_snapshots s
                    LEFT JOIN dataset_snapshot_items i ON i.snapshot_id = s.id
                    GROUP BY s.id
                    ORDER BY s.created_at DESC, s.id DESC
                    LIMIT %s
                    """,
                    (max(1, min(int(limit), 200)),),
                )
                return [dict(row) for row in cursor.fetchall()]

    def list_source_entitlements(self) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT dataset_code, source, permission_state, cache_policy, export_policy,
                           contract_version, checked_at
                    FROM source_entitlements
                    ORDER BY dataset_code, source
                    """
                )
                return [dict(row) for row in cursor.fetchall()]

    def get_snapshot(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                return self._snapshot_detail(cursor, int(snapshot_id))

    def load_daily_bars(self, snapshot_id: int, symbols: Optional[Sequence[str]] = None, limit: int = 100_000) -> List[Dict[str, Any]]:
        """Read immutable daily-bar rows from a sealed dataset snapshot only."""
        return self.load_snapshot_dataset(snapshot_id, "daily_bars", symbols=symbols, limit=limit)

    def load_snapshot_dataset(
        self,
        snapshot_id: int,
        dataset_code: str,
        *,
        symbols: Optional[Sequence[str]] = None,
        limit: int = 100_000,
    ) -> List[Dict[str, Any]]:
        """Read one dataset from a sealed manifest without any provider adapter."""
        normalized_symbols = sorted({str(symbol).strip() for symbol in (symbols or []) if str(symbol).strip()})
        normalized_code = str(dataset_code or "").strip()
        if not normalized_code:
            raise ValueError("dataset_code 不能为空")
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT status FROM dataset_snapshots WHERE id = %s", (int(snapshot_id),))
                snapshot = cursor.fetchone()
                if not snapshot:
                    raise ValueError("数据快照不存在")
                if snapshot["status"] != "sealed":
                    raise ValueError("只能读取已封存的数据快照")
                cursor.execute(
                    "SELECT 1 FROM dataset_snapshot_items WHERE snapshot_id = %s AND dataset_code = %s LIMIT 1",
                    (int(snapshot_id), normalized_code),
                )
                if not cursor.fetchone():
                    raise ValueError(f"数据快照不包含数据集：{normalized_code}")
                query = """
                    SELECT r.payload
                    FROM dataset_snapshot_items i
                    JOIN dataset_partition_records r ON r.partition_id = i.partition_id
                    WHERE i.snapshot_id = %s AND i.dataset_code = %s
                """
                params: List[Any] = [int(snapshot_id), normalized_code]
                if normalized_symbols:
                    query += " AND r.payload ->> 'symbol' = ANY(%s)"
                    params.append(normalized_symbols)
                query += " ORDER BY COALESCE(r.payload ->> 'trade_date', r.payload ->> 'as_of_date', ''), r.payload ->> 'symbol', r.record_ordinal LIMIT %s"
                params.append(max(1, min(int(limit), 1_000_000)))
                cursor.execute(query, params)
                return [dict(row["payload"]) for row in cursor.fetchall()]

    def create_snapshot(self, name: str, partition_ids: Sequence[int], knowledge_cutoff_at: Optional[datetime] = None) -> Dict[str, Any]:
        self.install_registry()
        ids = sorted({int(item) for item in partition_ids})
        if not name.strip() or not ids:
            raise ValueError("快照名称和至少一个分区是必填项")
        cutoff = knowledge_cutoff_at or datetime.now(SHANGHAI)
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                partitions = self._partitions(cursor, ids)
                if len(partitions) != len(ids):
                    raise ValueError("存在未找到的数据分区")
                blocked = self._blocking_partition_ids(cursor, ids)
                if blocked:
                    raise ValueError(f"质量门禁阻止封存：分区 {','.join(map(str, blocked))}")
                cursor.execute(
                    """
                    INSERT INTO dataset_snapshots(name, status, knowledge_cutoff_at)
                    VALUES (%s, 'draft', %s)
                    ON CONFLICT (name) DO NOTHING
                    RETURNING id
                    """,
                    (name.strip(), cutoff),
                )
                created = cursor.fetchone()
                if created:
                    snapshot_id = int(created["id"])
                    self._insert_snapshot_items(cursor, snapshot_id, partitions)
                else:
                    cursor.execute("SELECT id FROM dataset_snapshots WHERE name = %s", (name.strip(),))
                    snapshot_id = int(cursor.fetchone()["id"])
                self._seal_snapshot(cursor, snapshot_id)
                return self._snapshot_detail(cursor, snapshot_id) or {}

    def seal_snapshot(self, snapshot_id: int) -> Dict[str, Any]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                self._seal_snapshot(cursor, int(snapshot_id))
                return self._snapshot_detail(cursor, int(snapshot_id)) or {}

    def publish_daily_bars(
        self,
        trade_date: str,
        knowledge_cutoff_at: Optional[datetime] = None,
        reference_dataset_codes: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Seal an immutable daily-bars snapshot from already synchronized PG rows.

        This performs no TuShare/AkShare call.  Provider collection and research
        publication are deliberately separated, so a running backtest cannot
        observe a provider revision halfway through its input selection.
        """
        self.install_registry()
        normalized_date = self._date_text(trade_date)
        cutoff = knowledge_cutoff_at or datetime.now(SHANGHAI)
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s)) AS acquired", (f"daily_bars:{normalized_date}",))
                if not cursor.fetchone()["acquired"]:
                    raise RuntimeError(f"{normalized_date} 已有数据发布任务在运行")
                cursor.execute("SELECT id, created_at FROM dataset_definitions WHERE code = 'daily_bars'")
                dataset = cursor.fetchone()
                if not dataset:
                    raise RuntimeError("数据集未注册：daily_bars")
                dataset_id = int(dataset["id"])
                trust_started_at = dataset["created_at"]
                cursor.execute(
                    """
                    SELECT symbol, name, trade_date, open, high, low, close, volume, turnover, source, collected_at, updated_at
                    FROM kline_history
                    WHERE timeframe = '1d' AND trade_date = %s
                      AND collected_at IS NOT NULL AND collected_at >= %s
                    ORDER BY symbol, timestamp_ms
                    """,
                    (normalized_date, trust_started_at),
                )
                rows = [dict(row) for row in cursor.fetchall()]
                if not rows:
                    raise ValueError(f"{normalized_date} 没有通过来源追溯的日线；请使用当前同步链路重新采集后再封存")

                sources = sorted({str(row.get("source") or "unknown").strip().lower() for row in rows})
                issues = validate_daily_bar_rows(rows)
                if len(sources) != 1:
                    issues.append({
                        "check_code": "mixed_actual_provider",
                        "severity": "blocking",
                        "record_key": normalized_date,
                        "message": "同一日线分区混入多个实际数据源，禁止封存",
                        "details": {"sources": sources},
                    })
                actual_source = sources[0] if len(sources) == 1 else "mixed"
                if actual_source not in {"tushare", "akshare"}:
                    issues.append({
                        "check_code": "untraceable_actual_provider",
                        "severity": "blocking",
                        "record_key": normalized_date,
                        "message": "日线分区缺少可验证的实际数据源",
                        "details": {"source": actual_source},
                    })
                response_hash = canonical_hash(rows)
                run_id = self._create_fetch_run(cursor, dataset_id, actual_source, normalized_date, len(rows), response_hash)
                partition_id = self._create_or_get_partition(
                    cursor, dataset_id, run_id, normalized_date, actual_source, rows, response_hash, cutoff,
                    status="failed" if any(item["severity"] == "blocking" for item in issues) else "published",
                )
                self._store_partition_records(cursor, partition_id, rows)
                self._store_quality_issues(cursor, partition_id, issues)
                if any(item["severity"] == "blocking" for item in issues):
                    return {
                        "status": "failed_quality_gate",
                        "trade_date": normalized_date,
                        "partition_id": partition_id,
                        "requested_source": "tushare",
                        "actual_source": actual_source,
                        "fallback_reason": "akshare_fallback; 具体原因见 sync_job_items" if actual_source == "akshare" else None,
                        "response_hash": response_hash,
                        "available_at": _jsonable(cutoff),
                        "knowledge_cutoff_at": _jsonable(cutoff),
                        "blocking_issues": len([item for item in issues if item["severity"] == "blocking"]),
                    }
                reference_partition_ids = self._latest_reference_partition_ids(
                    cursor,
                    normalized_date,
                    reference_dataset_codes or [],
                )
                historical_daily_partition_ids = self._latest_historical_daily_partition_ids(
                    cursor,
                    normalized_date,
                    partition_id,
                )
                snapshot = self._create_daily_snapshot(
                    cursor,
                    normalized_date,
                    cutoff,
                    partition_id,
                    response_hash,
                    reference_partition_ids=[*historical_daily_partition_ids, *reference_partition_ids],
                )
                cursor.execute(
                    """
                    INSERT INTO dataset_watermarks(dataset_id, last_published_trade_date, last_fetch_run_id, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (dataset_id) DO UPDATE SET
                        last_published_trade_date = EXCLUDED.last_published_trade_date,
                        last_fetch_run_id = EXCLUDED.last_fetch_run_id,
                        updated_at = NOW()
                    """,
                    (dataset_id, normalized_date, run_id),
                )
                return {
                    "status": "sealed",
                    "trade_date": normalized_date,
                    "partition_id": partition_id,
                    "requested_source": "tushare",
                    "actual_source": actual_source,
                    "fallback_reason": "akshare_fallback; 具体原因见 sync_job_items" if actual_source == "akshare" else None,
                    "response_hash": response_hash,
                    "available_at": _jsonable(cutoff),
                    "knowledge_cutoff_at": _jsonable(cutoff),
                    "snapshot": snapshot,
                }

    def publish_daily_bar_range(
        self,
        start_date: str,
        end_date: str,
        symbols: Sequence[str],
        *,
        reference_dataset_codes: Optional[Sequence[str]] = None,
        minimum_rows_per_symbol: int = 400,
    ) -> Dict[str, Any]:
        """Seal a provider-free historical PG slice for factor/backtest lookbacks."""
        self.install_registry()
        normalized_start = self._date_text(start_date)
        normalized_end = self._date_text(end_date)
        if normalized_start > normalized_end:
            raise ValueError("start_date 不能晚于 end_date")
        normalized_symbols = sorted({str(symbol).strip() for symbol in symbols if str(symbol).strip()})
        if not normalized_symbols:
            raise ValueError("历史研究快照至少需要一个标的")
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT created_at FROM dataset_definitions WHERE code = 'daily_bars'")
                dataset = cursor.fetchone()
                if not dataset:
                    raise RuntimeError("数据集未注册：daily_bars")
                cursor.execute(
                    """
                    SELECT symbol, name, trade_date, open, high, low, close, volume, turnover,
                           source, collected_at, updated_at
                    FROM kline_history
                    WHERE timeframe = '1d' AND trade_date BETWEEN %s AND %s
                      AND symbol = ANY(%s)
                      AND collected_at IS NOT NULL AND collected_at >= %s
                    ORDER BY trade_date, symbol, timestamp_ms
                    """,
                    (normalized_start, normalized_end, normalized_symbols, dataset["created_at"]),
                )
                rows = [dict(row) for row in cursor.fetchall()]
        if not rows:
            raise ValueError("所选历史区间没有通过来源追溯的日线")
        issues = validate_daily_bar_rows(rows)
        row_counts: Dict[str, int] = {symbol: 0 for symbol in normalized_symbols}
        for row in rows:
            row_counts[str(row["symbol"])] = row_counts.get(str(row["symbol"]), 0) + 1
        for symbol, count in row_counts.items():
            if count < max(1, int(minimum_rows_per_symbol)):
                issues.append({
                    "check_code": "insufficient_historical_coverage",
                    "severity": "blocking",
                    "record_key": symbol,
                    "message": "标的历史日线不足以支持两年研究基线",
                    "details": {"row_count": count, "minimum": minimum_rows_per_symbol},
                })
        sources = sorted({str(row.get("source") or "unknown").strip().lower() for row in rows})
        if len(sources) != 1 or sources[0] not in {"tushare", "akshare"}:
            issues.append({
                "check_code": "mixed_or_untraceable_historical_provider",
                "severity": "blocking",
                "record_key": f"{normalized_start}:{normalized_end}",
                "message": "历史日线分区必须由单一可追溯数据源生成",
                "details": {"sources": sources},
            })
        actual_source = sources[0] if len(sources) == 1 else "mixed"
        partition = self.publish_normalized_partition(
            "daily_bars",
            f"daily_bars:{normalized_start}:{normalized_end}:{actual_source}:{canonical_hash(normalized_symbols)[:12]}",
            rows,
            start_date=normalized_start,
            end_date=normalized_end,
            actual_source=actual_source,
            fallback_reason="historical_range_akshare_fallback" if actual_source == "akshare" else None,
            request_params={
                "source": "kline_history",
                "start_date": normalized_start,
                "end_date": normalized_end,
                "symbols": normalized_symbols,
            },
            quality_issues=issues,
        )
        if partition["status"] != "published":
            return {"status": "failed_quality_gate", "partition": partition, "row_counts": row_counts}
        codes = list(reference_dataset_codes or [])
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                reference_partition_ids = self._latest_reference_partition_ids(cursor, normalized_end, codes)
        snapshot = self.create_snapshot(
            f"research-history-{normalized_start}-{normalized_end}-{partition['content_hash'][:12]}",
            [int(partition["partition_id"]), *reference_partition_ids],
        )
        return {
            "status": "sealed",
            "start_date": normalized_start,
            "end_date": normalized_end,
            "partition": partition,
            "row_counts": row_counts,
            "snapshot": snapshot,
        }

    def publish_normalized_partition(
        self,
        dataset_code: str,
        partition_key: str,
        rows: Sequence[Mapping[str, Any]],
        *,
        start_date: str,
        end_date: str,
        requested_source: str = "tushare",
        actual_source: str = "tushare",
        fallback_reason: Optional[str] = None,
        request_params: Optional[Mapping[str, Any]] = None,
        knowledge_cutoff_at: Optional[datetime] = None,
        quality_issues: Optional[Sequence[Mapping[str, Any]]] = None,
        allow_empty: bool = False,
    ) -> Dict[str, Any]:
        """Persist a source-labelled normalized non-price dataset partition.

        Provider adapters own fetching; this method owns only deterministic PG
        persistence.  It lets security master and trading calendar facts share
        the same fetch-run, hash, issue and immutable-snapshot boundary as bars.
        """
        self.install_registry()
        if not str(partition_key or "").strip():
            raise ValueError("partition_key 不能为空")
        normalized_rows = [_jsonable(dict(row)) for row in rows]
        if not normalized_rows and not allow_empty:
            raise ValueError(f"{dataset_code} 没有可发布的规范化记录")
        normalized_rows.sort(key=canonical_hash)
        normalized_start = self._date_text(start_date)
        normalized_end = self._date_text(end_date)
        cutoff = knowledge_cutoff_at or datetime.now(SHANGHAI)
        issues = [dict(item) for item in (quality_issues or [])]
        content_hash = canonical_hash(normalized_rows)
        symbol_count = len({str(row.get("symbol") or "").strip() for row in normalized_rows if str(row.get("symbol") or "").strip()})
        status = "failed" if any(item.get("severity") == "blocking" for item in issues) else "published"
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                dataset_id = self._dataset_id(cursor, dataset_code)
                cursor.execute(
                    """
                    INSERT INTO source_entitlements(dataset_code, source, permission_state, cache_policy, export_policy, contract_version, checked_at)
                    VALUES (%s, %s, 'available', 'local_pg_research_only', 'disabled', 'runtime-verified-v1', NOW())
                    ON CONFLICT (dataset_code, source) DO UPDATE SET
                        permission_state = 'available', checked_at = NOW(), contract_version = EXCLUDED.contract_version
                    """,
                    (dataset_code, actual_source),
                )
                cursor.execute(
                    """
                    INSERT INTO source_fetch_runs
                    (dataset_id, requested_source, actual_source, fallback_reason, request_params, schema_version,
                     finished_at, status, row_count, response_hash)
                    VALUES (%s, %s, %s, %s, %s, 'v1', NOW(), 'success', %s, %s)
                    RETURNING id
                    """,
                    (
                        dataset_id,
                        requested_source,
                        actual_source,
                        fallback_reason,
                        psycopg2.extras.Json(_jsonable(dict(request_params or {}))),
                        len(normalized_rows),
                        content_hash,
                    ),
                )
                fetch_run_id = int(cursor.fetchone()["id"])
                cursor.execute(
                    """
                    INSERT INTO dataset_partitions
                    (dataset_id, fetch_run_id, partition_key, start_date, end_date, symbol_count, row_count,
                     content_hash, available_at, knowledge_cutoff_at, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (dataset_id, partition_key, content_hash) DO NOTHING
                    RETURNING id
                    """,
                    (
                        dataset_id,
                        fetch_run_id,
                        str(partition_key).strip(),
                        normalized_start,
                        normalized_end,
                        symbol_count,
                        len(normalized_rows),
                        content_hash,
                        cutoff,
                        cutoff,
                        status,
                    ),
                )
                partition = cursor.fetchone()
                if partition:
                    partition_id = int(partition["id"])
                else:
                    cursor.execute(
                        """
                        SELECT id FROM dataset_partitions
                        WHERE dataset_id = %s AND partition_key = %s AND content_hash = %s
                        """,
                        (dataset_id, str(partition_key).strip(), content_hash),
                    )
                    partition_id = int(cursor.fetchone()["id"])
                self._store_partition_records(cursor, partition_id, normalized_rows)
                self._store_quality_issues(cursor, partition_id, issues)
                return {
                    "dataset_code": dataset_code,
                    "partition_id": partition_id,
                    "source_fetch_run_id": fetch_run_id,
                    "status": status,
                    "requested_source": requested_source,
                    "actual_source": actual_source,
                    "fallback_reason": fallback_reason,
                    "row_count": len(normalized_rows),
                    "symbol_count": symbol_count,
                    "content_hash": content_hash,
                    "response_hash": content_hash,
                    "available_at": _jsonable(cutoff),
                    "knowledge_cutoff_at": _jsonable(cutoff),
                }

    def _dataset_id(self, cursor, code: str) -> int:
        cursor.execute("SELECT id FROM dataset_definitions WHERE code = %s", (code,))
        row = cursor.fetchone()
        if not row:
            raise RuntimeError(f"数据集未注册：{code}")
        return int(row["id"])

    def _create_fetch_run(self, cursor, dataset_id: int, actual_source: str, trade_date: str, row_count: int, response_hash: str) -> int:
        fallback_reason = "akshare_fallback; 具体原因见 sync_job_items" if actual_source == "akshare" else None
        cursor.execute(
            """
            INSERT INTO source_fetch_runs
            (dataset_id, requested_source, actual_source, fallback_reason, request_params, schema_version, finished_at, status, row_count, response_hash)
            VALUES (%s, 'tushare', %s, %s, %s, 'v1', NOW(), 'success', %s, %s)
            RETURNING id
            """,
            (dataset_id, actual_source, fallback_reason, psycopg2.extras.Json({"trade_date": trade_date, "source": "kline_history"}), row_count, response_hash),
        )
        return int(cursor.fetchone()["id"])

    def _create_or_get_partition(self, cursor, dataset_id: int, run_id: int, trade_date: str, actual_source: str, rows: List[Dict[str, Any]], content_hash: str, cutoff: datetime, status: str) -> int:
        partition_key = f"daily_bars:{trade_date}:{actual_source}"
        cursor.execute(
            """
            INSERT INTO dataset_partitions
            (dataset_id, fetch_run_id, partition_key, start_date, end_date, symbol_count, row_count,
             content_hash, available_at, knowledge_cutoff_at, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (dataset_id, partition_key, content_hash) DO NOTHING
            RETURNING id
            """,
            (dataset_id, run_id, partition_key, trade_date, trade_date, len({row["symbol"] for row in rows}), len(rows), content_hash, cutoff, cutoff, status),
        )
        row = cursor.fetchone()
        if row:
            return int(row["id"])
        cursor.execute(
            """
            SELECT id FROM dataset_partitions
            WHERE dataset_id = %s AND partition_key = %s AND content_hash = %s
            """,
            (dataset_id, partition_key, content_hash),
        )
        return int(cursor.fetchone()["id"])

    def _store_quality_issues(self, cursor, partition_id: int, issues: List[Dict[str, Any]]) -> None:
        if not issues:
            return
        values = [
            (partition_id, item["check_code"], item["severity"], item.get("record_key"), item["message"], psycopg2.extras.Json(item.get("details") or {}))
            for item in issues
        ]
        psycopg2.extras.execute_values(
            cursor,
            """
            INSERT INTO data_quality_issues(partition_id, check_code, severity, record_key, message, details)
            VALUES %s
            """,
            values,
                    page_size=2000,
                )

    def _store_partition_records(self, cursor, partition_id: int, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        values = [
            (partition_id, ordinal, canonical_hash(row), psycopg2.extras.Json(_jsonable(row)))
            for ordinal, row in enumerate(rows, start=1)
        ]
        psycopg2.extras.execute_values(
            cursor,
            """
            INSERT INTO dataset_partition_records(partition_id, record_ordinal, record_hash, payload)
            VALUES %s ON CONFLICT (partition_id, record_ordinal) DO NOTHING
            """,
            values,
                    page_size=2000,
                )

    def _create_daily_snapshot(
        self,
        cursor,
        trade_date: str,
        cutoff: datetime,
        partition_id: int,
        content_hash: str,
        *,
        reference_partition_ids: Optional[Sequence[int]] = None,
    ) -> Dict[str, Any]:
        all_partition_ids = [partition_id, *(reference_partition_ids or [])]
        manifest_seed = canonical_hash(sorted(int(item) for item in all_partition_ids))
        name_prefix = "daily-research" if reference_partition_ids else "daily-bars"
        name = f"{name_prefix}-{trade_date}-{manifest_seed[:12] if reference_partition_ids else content_hash[:12]}"
        cursor.execute(
            """
            INSERT INTO dataset_snapshots(name, status, knowledge_cutoff_at)
            VALUES (%s, 'draft', %s)
            ON CONFLICT (name) DO NOTHING
            RETURNING id
            """,
            (name, cutoff),
        )
        row = cursor.fetchone()
        if row:
            snapshot_id = int(row["id"])
            self._insert_snapshot_items(cursor, snapshot_id, self._partitions(cursor, all_partition_ids))
        else:
            cursor.execute("SELECT id FROM dataset_snapshots WHERE name = %s", (name,))
            snapshot_id = int(cursor.fetchone()["id"])
        self._seal_snapshot(cursor, snapshot_id)
        return self._snapshot_detail(cursor, snapshot_id) or {}

    def _latest_reference_partition_ids(self, cursor, trade_date: str, dataset_codes: Sequence[str]) -> List[int]:
        codes = sorted({str(code).strip() for code in dataset_codes if str(code).strip()})
        if not codes:
            return []
        cursor.execute(
            """
            SELECT DISTINCT ON (d.code) d.code, p.id
            FROM dataset_definitions d
            JOIN dataset_partitions p ON p.dataset_id = d.id
            WHERE d.code = ANY(%s)
              AND p.status = 'published'
              AND p.end_date <= %s
            ORDER BY d.code, p.end_date DESC, p.created_at DESC, p.id DESC
            """,
            (codes, trade_date),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        found = {row["code"] for row in rows}
        missing = [code for code in codes if code not in found]
        if missing:
            raise ValueError(f"封存前缺少参考数据分区：{','.join(missing)}")
        return [int(row["id"]) for row in rows]

    def _latest_historical_daily_partition_ids(self, cursor, trade_date: str, current_partition_id: int) -> List[int]:
        """Attach one widest prior PG history slice so daily factors have lookback data."""
        cursor.execute(
            """
            SELECT p.id
            FROM dataset_partitions p
            JOIN dataset_definitions d ON d.id = p.dataset_id
            WHERE d.code = 'daily_bars' AND p.status = 'published' AND p.id <> %s
              AND p.start_date < %s AND p.end_date <= %s
            ORDER BY (p.end_date - p.start_date) DESC, p.row_count DESC, p.created_at DESC, p.id DESC
            LIMIT 1
            """,
            (int(current_partition_id), trade_date, trade_date),
        )
        row = cursor.fetchone()
        return [int(row["id"])] if row else []

    def _partitions(self, cursor, partition_ids: Sequence[int]) -> List[Dict[str, Any]]:
        cursor.execute(
            """
            SELECT p.id, d.code AS dataset_code, p.content_hash
            FROM dataset_partitions p JOIN dataset_definitions d ON d.id = p.dataset_id
            WHERE p.id = ANY(%s)
            ORDER BY d.code, p.id
            """,
            (list(partition_ids),),
        )
        return [dict(row) for row in cursor.fetchall()]

    def _blocking_partition_ids(self, cursor, partition_ids: Sequence[int]) -> List[int]:
        cursor.execute(
            """
            SELECT DISTINCT partition_id FROM data_quality_issues
            WHERE partition_id = ANY(%s) AND severity = 'blocking'
            ORDER BY partition_id
            """,
            (list(partition_ids),),
        )
        return [int(row["partition_id"]) for row in cursor.fetchall()]

    def _insert_snapshot_items(self, cursor, snapshot_id: int, partitions: List[Dict[str, Any]]) -> None:
        psycopg2.extras.execute_values(
            cursor,
            """
            INSERT INTO dataset_snapshot_items(snapshot_id, partition_id, dataset_code, content_hash)
            VALUES %s ON CONFLICT (snapshot_id, partition_id) DO NOTHING
            """,
            [(snapshot_id, item["id"], item["dataset_code"], item["content_hash"]) for item in partitions],
                    page_size=2000,
                )

    def _seal_snapshot(self, cursor, snapshot_id: int) -> None:
        cursor.execute("SELECT status FROM dataset_snapshots WHERE id = %s FOR UPDATE", (snapshot_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError("数据快照不存在")
        if row["status"] == "sealed":
            return
        if row["status"] == "failed":
            raise ValueError("失败的数据快照不能封存")
        cursor.execute(
            """
            SELECT i.dataset_code, i.partition_id, i.content_hash, p.start_date, p.end_date, p.knowledge_cutoff_at
            FROM dataset_snapshot_items i JOIN dataset_partitions p ON p.id = i.partition_id
            WHERE i.snapshot_id = %s ORDER BY i.dataset_code, i.partition_id
            """,
            (snapshot_id,),
        )
        items = [dict(item) for item in cursor.fetchall()]
        if not items:
            raise ValueError("空数据快照不能封存")
        blocked = self._blocking_partition_ids(cursor, [int(item["partition_id"]) for item in items])
        if blocked:
            raise ValueError(f"质量门禁阻止封存：分区 {','.join(map(str, blocked))}")
        manifest_hash = canonical_hash(items)
        cursor.execute(
            """
            UPDATE dataset_snapshots
            SET status = 'sealed', manifest_hash = %s, sealed_at = NOW()
            WHERE id = %s
            """,
            (manifest_hash, snapshot_id),
        )

    def _snapshot_detail(self, cursor, snapshot_id: int) -> Optional[Dict[str, Any]]:
        cursor.execute(
            """
            SELECT id, name, status, knowledge_cutoff_at, manifest_hash, created_at, sealed_at
            FROM dataset_snapshots WHERE id = %s
            """,
            (snapshot_id,),
        )
        snapshot = cursor.fetchone()
        if not snapshot:
            return None
        cursor.execute(
            """
            SELECT i.partition_id, i.dataset_code, i.content_hash, p.start_date, p.end_date,
                   p.row_count, p.symbol_count, p.available_at, p.knowledge_cutoff_at, p.status
            FROM dataset_snapshot_items i JOIN dataset_partitions p ON p.id = i.partition_id
            WHERE i.snapshot_id = %s ORDER BY i.dataset_code, i.partition_id
            """,
            (snapshot_id,),
        )
        payload = dict(snapshot)
        payload["items"] = [dict(row) for row in cursor.fetchall()]
        return payload

    @staticmethod
    def _date_text(value: str) -> str:
        text = str(value).strip().replace("-", "")
        if len(text) != 8 or not text.isdigit():
            raise ValueError("trade_date 必须为 YYYYMMDD 或 YYYY-MM-DD")
        return date(int(text[:4]), int(text[4:6]), int(text[6:])).isoformat()
