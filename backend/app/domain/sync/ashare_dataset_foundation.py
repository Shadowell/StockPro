"""Read-only A-share dataset foundation contract.

This module describes the canonical StockPro research datasets and projects
current PostgreSQL evidence into a UI/API contract. It deliberately has no
provider client and performs no writes on reads.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Protocol

import psycopg2
import psycopg2.extras

from app.core.config import settings


@dataclass(frozen=True)
class AshareDatasetSpec:
    code: str
    name: str
    family: str
    primary_source: str
    fallback_source: str | None
    cadence: str
    partition_grain: str
    required_for_research_snapshot: bool
    seal_policy: str
    available_at_policy: str


CANONICAL_ASHARE_DATASETS: tuple[AshareDatasetSpec, ...] = (
    AshareDatasetSpec(
        code="security_master",
        name="证券主数据与历史状态",
        family="reference",
        primary_source="tushare",
        fallback_source="akshare",
        cadence="daily",
        partition_grain="trade_date",
        required_for_research_snapshot=True,
        seal_policy="must_be_quality_checked_before_snapshot",
        available_at_policy="reference facts are available after collection finishes",
    ),
    AshareDatasetSpec(
        code="trade_calendar",
        name="A股交易日历",
        family="calendar",
        primary_source="tushare",
        fallback_source=None,
        cadence="daily",
        partition_grain="date_range",
        required_for_research_snapshot=True,
        seal_policy="must_cover_snapshot_range",
        available_at_policy="calendar facts are available after collection finishes",
    ),
    AshareDatasetSpec(
        code="daily_bars",
        name="未复权日线行情",
        family="market_eod",
        primary_source="tushare",
        fallback_source="akshare",
        cadence="trade_day",
        partition_grain="trade_date",
        required_for_research_snapshot=True,
        seal_policy="must_be_quality_checked_before_snapshot",
        available_at_policy="D daily bar is available after D close collection",
    ),
    AshareDatasetSpec(
        code="adj_factor",
        name="复权因子",
        family="market_eod",
        primary_source="tushare",
        fallback_source=None,
        cadence="trade_day",
        partition_grain="trade_date",
        required_for_research_snapshot=True,
        seal_policy="must_be_quality_checked_before_snapshot",
        available_at_policy="D adjustment factor is available after D close collection",
    ),
    AshareDatasetSpec(
        code="daily_basic",
        name="每日估值与换手",
        family="market_eod",
        primary_source="tushare",
        fallback_source="akshare",
        cadence="trade_day",
        partition_grain="trade_date",
        required_for_research_snapshot=True,
        seal_policy="null valuation facts remain null",
        available_at_policy="D valuation facts are available after source publishes them",
    ),
    AshareDatasetSpec(
        code="suspensions",
        name="停复牌",
        family="execution_reference",
        primary_source="tushare",
        fallback_source=None,
        cadence="trade_day",
        partition_grain="trade_date",
        required_for_research_snapshot=True,
        seal_policy="valid empty partition is sealable",
        available_at_policy="D suspension facts are available after collection finishes",
    ),
    AshareDatasetSpec(
        code="price_limits",
        name="涨跌停价格",
        family="execution_reference",
        primary_source="tushare",
        fallback_source="akshare",
        cadence="trade_day",
        partition_grain="trade_date",
        required_for_research_snapshot=True,
        seal_policy="ipo/no-limit sentinel must be explicit",
        available_at_policy="D limit facts are available before execution replay uses D",
    ),
    AshareDatasetSpec(
        code="corporate_actions",
        name="公司行动",
        family="corporate_action",
        primary_source="tushare",
        fallback_source=None,
        cadence="daily",
        partition_grain="ex_date",
        required_for_research_snapshot=True,
        seal_policy="announcement_available_at is required",
        available_at_policy="only facts with announcement_available_at <= simulated_at are usable",
    ),
    AshareDatasetSpec(
        code="benchmark_bars",
        name="基准指数日线",
        family="benchmark",
        primary_source="tushare",
        fallback_source=None,
        cadence="trade_day",
        partition_grain="trade_date",
        required_for_research_snapshot=True,
        seal_policy="must_cover_snapshot_range",
        available_at_policy="D benchmark bar is available after D close collection",
    ),
)

CANONICAL_CODES = tuple(item.code for item in CANONICAL_ASHARE_DATASETS)
REQUIRED_RESEARCH_CODES = tuple(
    item.code for item in CANONICAL_ASHARE_DATASETS if item.required_for_research_snapshot
)


class AshareDatasetFoundationRepository(Protocol):
    def load_state(self, dataset_codes: tuple[str, ...], required_codes: tuple[str, ...]) -> dict[str, Any]:
        ...


class PostgresAshareDatasetFoundationRepository:
    def __init__(
        self,
        database_url: str | None = None,
        *,
        connection_factory: Callable[..., object] = psycopg2.connect,
    ) -> None:
        self.database_url = database_url or settings.DATABASE_URL
        self.connection_factory = connection_factory

    def _connect(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for A-share dataset foundation")
        connection = self.connection_factory(self.database_url)
        connection.set_session(readonly=True, autocommit=False)
        return connection

    def load_state(self, dataset_codes: tuple[str, ...], required_codes: tuple[str, ...]) -> dict[str, Any]:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT code,name,primary_source,fallback_source,schema_version,enabled,quality_policy
                    FROM dataset_definitions
                    WHERE code=ANY(%s)
                    ORDER BY code
                    """,
                    (list(dataset_codes),),
                )
                definitions = [dict(row) for row in cursor.fetchall()]

                cursor.execute(
                    """
                    SELECT dataset_code,source,permission_state,cache_policy,export_policy,checked_at
                    FROM source_entitlements
                    WHERE dataset_code=ANY(%s)
                    ORDER BY dataset_code,source
                    """,
                    (list(dataset_codes),),
                )
                entitlements = [dict(row) for row in cursor.fetchall()]

                cursor.execute(
                    """
                    SELECT d.code AS dataset_code,
                           COUNT(p.id) AS partition_count,
                           COALESCE(SUM(p.row_count),0) AS row_count,
                           COALESCE(SUM(p.symbol_count),0) AS symbol_count,
                           MIN(p.start_date) AS start_date,
                           MAX(p.end_date) AS end_date,
                           MAX(p.knowledge_cutoff_at) AS latest_knowledge_cutoff_at,
                           COUNT(*) FILTER (WHERE p.status='sealed') AS sealed_partition_count,
                           COUNT(*) FILTER (WHERE p.status='failed') AS failed_partition_count,
                           COUNT(q.id) FILTER (WHERE q.severity='blocking') AS blocking_issue_count
                    FROM dataset_definitions d
                    LEFT JOIN dataset_partitions p ON p.dataset_id=d.id
                    LEFT JOIN data_quality_issues q ON q.partition_id=p.id
                    WHERE d.code=ANY(%s)
                    GROUP BY d.code
                    """,
                    (list(dataset_codes),),
                )
                partitions = [dict(row) for row in cursor.fetchall()]

                cursor.execute(
                    """
                    SELECT i.dataset_code,COUNT(DISTINCT i.snapshot_id) AS sealed_snapshot_count
                    FROM dataset_snapshot_items i
                    JOIN dataset_snapshots s ON s.id=i.snapshot_id
                    WHERE s.status='sealed' AND i.dataset_code=ANY(%s)
                    GROUP BY i.dataset_code
                    """,
                    (list(dataset_codes),),
                )
                snapshot_usage = [dict(row) for row in cursor.fetchall()]

                cursor.execute(
                    """
                    SELECT d.code AS dataset_code,w.last_published_trade_date,w.updated_at
                    FROM dataset_watermarks w
                    JOIN dataset_definitions d ON d.id=w.dataset_id
                    WHERE d.code=ANY(%s)
                    """,
                    (list(dataset_codes),),
                )
                watermarks = [dict(row) for row in cursor.fetchall()]

                cursor.execute(
                    """
                    WITH sealed AS (
                        SELECT s.id,s.name,s.knowledge_cutoff_at,s.manifest_hash,
                               ARRAY_AGG(DISTINCT i.dataset_code ORDER BY i.dataset_code) AS dataset_codes,
                               COUNT(DISTINCT i.dataset_code) FILTER (WHERE i.dataset_code=ANY(%s)) AS required_count
                        FROM dataset_snapshots s
                        JOIN dataset_snapshot_items i ON i.snapshot_id=s.id
                        WHERE s.status='sealed'
                        GROUP BY s.id
                    )
                    SELECT id,name,knowledge_cutoff_at,manifest_hash,dataset_codes
                    FROM sealed
                    WHERE required_count=%s
                    ORDER BY knowledge_cutoff_at DESC,id DESC
                    LIMIT 1
                    """,
                    (list(required_codes), len(required_codes)),
                )
                latest_snapshot = cursor.fetchone()
        return {
            "definitions": definitions,
            "entitlements": entitlements,
            "partitions": partitions,
            "snapshot_usage": snapshot_usage,
            "watermarks": watermarks,
            "latest_research_snapshot": dict(latest_snapshot) if latest_snapshot else None,
        }


class AshareDatasetFoundationService:
    def __init__(self, repository: AshareDatasetFoundationRepository | None = None) -> None:
        self.repository = repository or PostgresAshareDatasetFoundationRepository()

    @staticmethod
    def _iso(value: Any) -> str | None:
        return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)

    @staticmethod
    def _index(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
        return {str(row[key]): row for row in rows if row.get(key) is not None}

    def snapshot(self) -> dict[str, Any]:
        state = self.repository.load_state(CANONICAL_CODES, REQUIRED_RESEARCH_CODES)
        definitions = self._index(state.get("definitions") or [], "code")
        partitions = self._index(state.get("partitions") or [], "dataset_code")
        usage = self._index(state.get("snapshot_usage") or [], "dataset_code")
        watermarks = self._index(state.get("watermarks") or [], "dataset_code")

        entitlements_by_code: dict[str, list[dict[str, Any]]] = {}
        for row in state.get("entitlements") or []:
            entitlements_by_code.setdefault(str(row.get("dataset_code")), []).append(row)

        datasets: list[dict[str, Any]] = []
        missing_required: list[str] = []
        blocking_required: list[str] = []
        unsealed_required: list[str] = []
        for spec in CANONICAL_ASHARE_DATASETS:
            definition = definitions.get(spec.code)
            partition = partitions.get(spec.code) or {}
            snapshot_count = int((usage.get(spec.code) or {}).get("sealed_snapshot_count") or 0)
            blocking_issues = int(partition.get("blocking_issue_count") or 0)
            partition_count = int(partition.get("partition_count") or 0)
            row_count = int(partition.get("row_count") or 0)

            if not definition:
                readiness = "missing_definition"
            elif blocking_issues > 0:
                readiness = "blocked_quality"
            elif snapshot_count > 0:
                readiness = "sealed"
            elif partition_count > 0:
                readiness = "collected_unsealed"
            else:
                readiness = "missing_partition"

            if spec.required_for_research_snapshot:
                if readiness == "missing_definition" or partition_count <= 0:
                    missing_required.append(spec.code)
                elif blocking_issues > 0:
                    blocking_required.append(spec.code)
                elif snapshot_count <= 0:
                    unsealed_required.append(spec.code)

            datasets.append(
                {
                    **asdict(spec),
                    "registered": bool(definition),
                    "enabled": bool(definition.get("enabled")) if definition else False,
                    "schema_version": str(definition.get("schema_version")) if definition else None,
                    "entitlements": [
                        {
                            "source": item.get("source"),
                            "permission_state": item.get("permission_state"),
                            "cache_policy": item.get("cache_policy"),
                            "export_policy": item.get("export_policy"),
                            "checked_at": self._iso(item.get("checked_at")),
                        }
                        for item in entitlements_by_code.get(spec.code, [])
                    ],
                    "coverage": {
                        "partition_count": partition_count,
                        "sealed_snapshot_count": snapshot_count,
                        "row_count": row_count,
                        "symbol_count": int(partition.get("symbol_count") or 0),
                        "start_date": self._iso(partition.get("start_date")),
                        "end_date": self._iso(partition.get("end_date")),
                        "latest_knowledge_cutoff_at": self._iso(partition.get("latest_knowledge_cutoff_at")),
                        "last_published_trade_date": self._iso((watermarks.get(spec.code) or {}).get("last_published_trade_date")),
                        "blocking_issue_count": blocking_issues,
                        "failed_partition_count": int(partition.get("failed_partition_count") or 0),
                    },
                    "readiness": readiness,
                }
            )

        latest_snapshot = state.get("latest_research_snapshot")
        ready = bool(latest_snapshot) and not missing_required and not blocking_required and not unsealed_required
        return {
            "market": "CN",
            "contract_version": "ashare-dataset-foundation.v1",
            "datasets": datasets,
            "research_snapshot": {
                "required_dataset_codes": list(REQUIRED_RESEARCH_CODES),
                "ready": ready,
                "status": "ready" if ready else "blocked",
                "missing_required": missing_required,
                "blocking_required": blocking_required,
                "unsealed_required": unsealed_required,
                "latest": {
                    "id": int(latest_snapshot["id"]),
                    "name": latest_snapshot["name"],
                    "knowledge_cutoff_at": self._iso(latest_snapshot.get("knowledge_cutoff_at")),
                    "manifest_hash": latest_snapshot.get("manifest_hash"),
                    "dataset_codes": list(latest_snapshot.get("dataset_codes") or []),
                }
                if latest_snapshot
                else None,
            },
            "sync_boundary": {
                "get_requests_start_provider": False,
                "get_requests_write_database": False,
                "startup_runs_sync": False,
                "default_schedule_enabled": False,
                "real_broker_connected": False,
                "paper_history_mutated": False,
            },
        }


ashare_dataset_foundation_service = AshareDatasetFoundationService()
