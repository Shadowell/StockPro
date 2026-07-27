"""PG-backed, post-close daily-reference orchestration.

The runner deliberately owns only the first trusted slice of the research
pipeline: calendar gate -> unadjusted daily bars -> immutable dataset snapshot
-> factor schedule -> optional post-close market evidence.  Factor calculation
can start only after the dataset and Universe manifests are sealed.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

import psycopg2.extras
from apscheduler.triggers.cron import CronTrigger

from app.services.dataset_snapshot_service import DatasetSnapshotService
from app.services.factor_research_service import FactorResearchService
from app.services.kline_sync_service import KlineSyncService
from app.services.reference_dataset_sync_service import ReferenceDatasetSyncService
from app.services.tushare_catalog_service import TushareCatalogService


SHANGHAI = ZoneInfo("Asia/Shanghai")
SCHEDULE_CODE = "daily_reference_publication"
DEFAULT_CRON = "30 17 * * 1-5"


def normalise_trade_date(value: Any) -> str:
    """Return ISO trade date; reject ambiguous dates before a provider call."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError("trade_date 必须为 YYYY-MM-DD 或 YYYYMMDD") from exc


def compact_trade_date(value: Any) -> str:
    return normalise_trade_date(value).replace("-", "")


def trade_calendar_is_open(records: Iterable[Mapping[str, Any]], trade_date: Any) -> bool:
    """Read TuShare ``trade_cal`` facts without guessing weekdays or holidays."""
    requested = compact_trade_date(trade_date)
    matching: List[Mapping[str, Any]] = []
    for row in records:
        raw_date = row.get("cal_date") or row.get("trade_date") or row.get("date")
        if raw_date is None:
            continue
        try:
            if compact_trade_date(raw_date) == requested:
                matching.append(row)
        except ValueError:
            continue
    if not matching:
        raise ValueError(f"TuShare trade_cal 未返回 {requested} 的交易日状态")
    value = matching[-1].get("is_open")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) == 1
    return str(value or "").strip().lower() in {"1", "true", "t", "y", "yes", "open"}


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


class DailyReferenceSyncService:
    """Persisted plan + idempotent one-day runner guarded by a PG advisory lock."""

    def __init__(
        self,
        database,
        kline_service: Optional[KlineSyncService] = None,
        catalog_service: Optional[TushareCatalogService] = None,
        snapshot_service: Optional[DatasetSnapshotService] = None,
        reference_service: Optional[ReferenceDatasetSyncService] = None,
        factor_service: Optional[FactorResearchService] = None,
    ):
        self.database = database
        self.kline_service = kline_service or KlineSyncService(database)
        self.catalog_service = catalog_service or TushareCatalogService(database)
        self.snapshot_service = snapshot_service or DatasetSnapshotService(database)
        self.reference_service = reference_service or ReferenceDatasetSyncService(
            database,
            catalog_service=self.catalog_service,
            snapshot_service=self.snapshot_service,
        )
        self.factor_service = factor_service or FactorResearchService(database)

    def get_schedule(self) -> Dict[str, Any]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                row = self._schedule_row(cursor)
                cursor.execute(
                    """
                    SELECT w.last_published_trade_date, w.updated_at
                    FROM dataset_watermarks w
                    JOIN dataset_definitions d ON d.id = w.dataset_id
                    WHERE d.code = 'daily_bars'
                    """
                )
                watermark = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT id, trade_date, status, sync_job_id, snapshot_id,
                           market_evidence_snapshot_id, attempt_count, result,
                           error_message, started_at, finished_at, updated_at
                    FROM dataset_orchestration_runs
                    WHERE schedule_code = %s
                    ORDER BY trade_date DESC, id DESC
                    LIMIT 1
                    """,
                    (SCHEDULE_CODE,),
                )
                latest_run = cursor.fetchone()
        return self._schedule_payload(row, watermark, latest_run)

    def update_schedule(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        current = self.get_schedule()
        cron = str(payload.get("cron", current["cron"]) or "").strip()
        timezone = str(payload.get("timezone", current["timezone"]) or "").strip()
        self._validate_schedule(cron, timezone)
        enabled = bool(payload.get("enabled", current["enabled"]))
        catchup_days = self._bounded_int(payload.get("catchupDays", payload.get("catchup_days", current["catchupDays"])), 1, 10)
        max_retries = self._bounded_int(payload.get("maxRetries", payload.get("max_retries", current["maxRetries"])), 1, 5)
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO dataset_sync_schedules(code, cron, timezone, enabled, catchup_days, max_retries)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (code) DO UPDATE SET
                        cron = EXCLUDED.cron,
                        timezone = EXCLUDED.timezone,
                        enabled = EXCLUDED.enabled,
                        catchup_days = EXCLUDED.catchup_days,
                        max_retries = EXCLUDED.max_retries,
                        updated_at = NOW()
                    """,
                    (SCHEDULE_CODE, cron, timezone, enabled, catchup_days, max_retries),
                )
        return self.get_schedule()

    def run(self, trade_date: Any, symbols: Sequence[str], force: bool = False) -> Dict[str, Any]:
        """Execute one date once, recording every terminal outcome in PostgreSQL."""
        normalized_date = normalise_trade_date(trade_date)
        normalized_symbols = list(dict.fromkeys(str(symbol).strip() for symbol in symbols if str(symbol).strip()))
        lock_key = f"daily_reference_publication:{normalized_date}"
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(hashtext(%s)) AS acquired", (lock_key,))
                if not cursor.fetchone()["acquired"]:
                    return {
                        "status": "locked",
                        "tradeDate": normalized_date,
                        "message": "同一交易日的日终数据发布已在另一进程运行",
                    }
                try:
                    schedule = self._schedule_row(cursor)
                    if not schedule["enabled"]:
                        return {
                            "status": "disabled",
                            "tradeDate": normalized_date,
                            "message": "PG 日终参考数据计划已停用",
                        }
                    existing = self._run_row(cursor, normalized_date)
                    if existing and existing["status"] == "sealed" and not force:
                        return {
                            "status": "skipped",
                            "reason": "already_sealed",
                            "tradeDate": normalized_date,
                            "run": self._run_payload(existing),
                        }
                    if not normalized_symbols:
                        raise ValueError("未解析到 A 股标的，拒绝创建空日线快照")

                    run = self._start_run(cursor, normalized_date, normalized_symbols)
                    calendar = self.catalog_service.sync_endpoint(
                        "trade_cal",
                        params={"exchange": "SSE", "start_date": compact_trade_date(normalized_date), "end_date": compact_trade_date(normalized_date)},
                        include_records=True,
                    )
                    is_open = trade_calendar_is_open(calendar.get("records") or [], normalized_date)
                    calendar_summary = {
                        "endpointRunId": calendar.get("run_id"),
                        "responseHash": calendar.get("response_hash"),
                        "isTradingDay": is_open,
                    }
                    if not is_open:
                        return self._finish_run(
                            cursor,
                            run["id"],
                            "not_trading_day",
                            {"tradeDate": normalized_date, "calendar": calendar_summary},
                        )

                    calendar_partition = self.reference_service.sync_trade_calendar_records(
                        calendar.get("records") or [],
                        normalized_date,
                        endpoint_run_id=calendar.get("run_id"),
                    )
                    if calendar_partition.get("status") != "published":
                        raise ValueError("交易日历质量门禁未通过，禁止继续日终发布")
                    security_master = None
                    if self.reference_service.security_master_is_due(normalized_date):
                        security_master = self.reference_service.sync_security_master(normalized_date)
                        if security_master.get("status") != "published":
                            raise ValueError("证券主数据质量门禁未通过，禁止继续日终发布")
                    auxiliary = self.reference_service.sync_daily_auxiliary_datasets(normalized_date)
                    blocked_auxiliary = [
                        code for code, item in auxiliary.items()
                        if item.get("status") != "published"
                    ]
                    if blocked_auxiliary:
                        raise ValueError(f"日频参考数据质量门禁未通过：{','.join(blocked_auxiliary)}")
                    universe = self.reference_service.publish_universe_snapshot(normalized_date)
                    if universe.get("status") != "sealed" or (universe.get("dataset_partition") or {}).get("status") != "published":
                        raise ValueError("Universe 快照或其历史分区未封存，禁止继续日终发布")
                    reference_summary = {
                        "tradeCalendar": calendar_partition,
                        "securityMaster": security_master or {"status": "fresh_cache"},
                        "dailyAuxiliary": auxiliary,
                        "universe": universe,
                    }

                    job_id = self.kline_service.create_history_sync_job(
                        symbols=normalized_symbols,
                        timeframes=["1d"],
                        start_date=normalized_date,
                        end_date=normalized_date,
                        job_name=f"daily-reference-{compact_trade_date(normalized_date)}",
                    )
                    cursor.execute(
                        "UPDATE dataset_orchestration_runs SET sync_job_id = %s, updated_at = NOW() WHERE id = %s",
                        (job_id, run["id"]),
                    )
                    sync_result = self.kline_service.run_job(job_id)
                    if str(sync_result.get("status") or "").lower() != "success":
                        return self._finish_run(
                            cursor,
                            run["id"],
                            "failed",
                            {"tradeDate": normalized_date, "calendar": calendar_summary, "syncJobId": job_id, "sync": sync_result},
                            error_message="日线同步未完全成功，禁止封存研究快照",
                        )

                    publication = self.snapshot_service.publish_daily_bars(
                        normalized_date,
                        reference_dataset_codes=(
                            "security_master",
                            "trade_calendar",
                            "adjustment_factors",
                            "daily_valuation",
                            "suspensions",
                            "price_limits",
                            "benchmark_bars",
                            "corporate_actions",
                            "universe_history",
                        ),
                    )
                    if publication.get("status") != "sealed":
                        return self._finish_run(
                            cursor,
                            run["id"],
                            "blocked",
                            {"tradeDate": normalized_date, "calendar": calendar_summary, "references": reference_summary, "syncJobId": job_id, "sync": sync_result, "publication": publication},
                            error_message="日线质量门禁阻止快照封存",
                        )

                    market_evidence: Dict[str, Any]
                    try:
                        market_evidence = self.catalog_service.sync_market_evidence(normalized_date)
                    except Exception as exc:  # Optional evidence never invalidates a sealed reference snapshot.
                        market_evidence = {"status": "failed", "error": str(exc)}
                    snapshot = publication.get("snapshot") or {}
                    try:
                        factor_schedule = self.factor_service.run_daily_schedule(
                            normalized_date,
                            int(snapshot["id"]),
                            int(universe["universe_snapshot_id"]),
                        )
                    except Exception as exc:
                        factor_schedule = {"status": "failed", "error": str(exc)}
                    result = {
                        "tradeDate": normalized_date,
                        "calendar": calendar_summary,
                        "references": reference_summary,
                        "syncJobId": job_id,
                        "sync": sync_result,
                        "publication": publication,
                        "factorSchedule": factor_schedule,
                        "marketEvidence": market_evidence,
                    }
                    return self._finish_run(
                        cursor,
                        run["id"],
                        "sealed",
                        result,
                        sync_job_id=job_id,
                        snapshot_id=snapshot.get("id"),
                        market_evidence_snapshot_id=market_evidence.get("snapshot_id"),
                    )
                except Exception as exc:
                    if "run" in locals() and run:
                        return self._finish_run(
                            cursor,
                            run["id"],
                            "failed",
                            {"tradeDate": normalized_date, "error": str(exc)},
                            error_message=str(exc),
                        )
                    return {"status": "failed", "tradeDate": normalized_date, "message": str(exc)}
                finally:
                    cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", (lock_key,))

    def _schedule_row(self, cursor) -> Dict[str, Any]:
        cursor.execute(
            """
            SELECT code, cron, timezone, enabled, catchup_days, max_retries, updated_at
            FROM dataset_sync_schedules
            WHERE code = %s
            """,
            (SCHEDULE_CODE,),
        )
        row = cursor.fetchone()
        if row:
            return {**dict(row), "configured": True}
        return {
            "code": SCHEDULE_CODE,
            "cron": DEFAULT_CRON,
            "timezone": "Asia/Shanghai",
            "enabled": False,
            "catchup_days": 5,
            "max_retries": 3,
            "updated_at": None,
            "configured": False,
        }

    def _run_row(self, cursor, trade_date: str) -> Optional[Dict[str, Any]]:
        cursor.execute(
            """
            SELECT id, trade_date, status, sync_job_id, snapshot_id, market_evidence_snapshot_id,
                   attempt_count, result, error_message, started_at, finished_at, updated_at
            FROM dataset_orchestration_runs
            WHERE schedule_code = %s AND trade_date = %s
            """,
            (SCHEDULE_CODE, trade_date),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def _start_run(self, cursor, trade_date: str, symbols: Sequence[str]) -> Dict[str, Any]:
        cursor.execute(
            """
            INSERT INTO dataset_orchestration_runs
            (schedule_code, trade_date, status, requested_symbols, attempt_count, started_at, finished_at, error_message, result)
            VALUES (%s, %s, 'running', %s, 1, NOW(), NULL, NULL, '{}'::jsonb)
            ON CONFLICT (schedule_code, trade_date) DO UPDATE SET
                status = 'running',
                requested_symbols = EXCLUDED.requested_symbols,
                attempt_count = dataset_orchestration_runs.attempt_count + 1,
                started_at = NOW(),
                finished_at = NULL,
                error_message = NULL,
                updated_at = NOW()
            RETURNING id, trade_date, status, attempt_count
            """,
            (SCHEDULE_CODE, trade_date, psycopg2.extras.Json(list(symbols))),
        )
        return dict(cursor.fetchone())

    def _finish_run(
        self,
        cursor,
        run_id: int,
        status: str,
        result: Mapping[str, Any],
        *,
        error_message: Optional[str] = None,
        sync_job_id: Optional[int] = None,
        snapshot_id: Optional[int] = None,
        market_evidence_snapshot_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        cursor.execute(
            """
            UPDATE dataset_orchestration_runs
            SET status = %s,
                sync_job_id = COALESCE(%s, sync_job_id),
                snapshot_id = COALESCE(%s, snapshot_id),
                market_evidence_snapshot_id = COALESCE(%s, market_evidence_snapshot_id),
                result = %s,
                error_message = %s,
                finished_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
            RETURNING id, trade_date, status, sync_job_id, snapshot_id, market_evidence_snapshot_id,
                      attempt_count, result, error_message, started_at, finished_at, updated_at
            """,
            (
                status,
                sync_job_id,
                snapshot_id,
                market_evidence_snapshot_id,
                psycopg2.extras.Json(_jsonable(dict(result))),
                error_message,
                run_id,
            ),
        )
        row = dict(cursor.fetchone())
        return {"status": status, "tradeDate": normalise_trade_date(row["trade_date"]), "run": self._run_payload(row), **_jsonable(dict(result))}

    def _schedule_payload(self, schedule: Mapping[str, Any], watermark: Optional[Mapping[str, Any]], latest_run: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        timezone = str(schedule["timezone"])
        trigger = CronTrigger.from_crontab(str(schedule["cron"]), timezone=ZoneInfo(timezone))
        next_run = trigger.get_next_fire_time(None, datetime.now(ZoneInfo(timezone)))
        return {
            "code": str(schedule["code"]),
            "cron": str(schedule["cron"]),
            "timezone": timezone,
            "configured": bool(schedule.get("configured", True)),
            "enabled": bool(schedule["enabled"]),
            "catchupDays": int(schedule["catchup_days"]),
            "maxRetries": int(schedule["max_retries"]),
            "updatedAt": _jsonable(schedule.get("updated_at")),
            "nextRunAt": _jsonable(next_run),
            "dailyBarsWatermark": _jsonable((watermark or {}).get("last_published_trade_date")),
            "watermarkUpdatedAt": _jsonable((watermark or {}).get("updated_at")),
            "lastRun": self._run_payload(latest_run) if latest_run else None,
        }

    def _run_payload(self, row: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "tradeDate": normalise_trade_date(row["trade_date"]),
            "status": str(row["status"]),
            "syncJobId": row.get("sync_job_id"),
            "snapshotId": row.get("snapshot_id"),
            "marketEvidenceSnapshotId": row.get("market_evidence_snapshot_id"),
            "attemptCount": int(row.get("attempt_count") or 0),
            "result": _jsonable(row.get("result") or {}),
            "errorMessage": row.get("error_message"),
            "startedAt": _jsonable(row.get("started_at")),
            "finishedAt": _jsonable(row.get("finished_at")),
            "updatedAt": _jsonable(row.get("updated_at")),
        }

    def _validate_schedule(self, cron: str, timezone: str) -> None:
        if not cron:
            raise ValueError("cron 不能为空")
        try:
            ZoneInfo(timezone)
            CronTrigger.from_crontab(cron, timezone=ZoneInfo(timezone))
        except Exception as exc:
            raise ValueError("cron 或 timezone 无效") from exc

    @staticmethod
    def _bounded_int(value: Any, minimum: int, maximum: int) -> int:
        try:
            return max(minimum, min(maximum, int(value)))
        except (TypeError, ValueError):
            return minimum
