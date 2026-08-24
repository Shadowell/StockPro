"""A 股运营调度器：把"每天自动运行"还给产品。

对齐 BitPro 的 APScheduler 运营模式（Asia/Shanghai、coalesce、单实例、
PG 持久化计划），但只承载 A 股任务：

1. ``daily_reference_publication`` —— 盘后日终链：
   交易日历门禁 → 全市场日线同步 → 封存数据快照 → 辅助分区 → Universe →
   因子日度计划 → 行情证据；随后推进所有运行中的 Paper 实例并刷新 Qlib 导出。
2. ``paper_advance_guard`` —— 兜底推进运行中 Paper 实例（幂等）。
3. ``operations_heartbeat`` —— 系统心跳写入服务健康快照。

所有同步 DB 工作经 ``asyncio.to_thread`` 卸载，不阻塞事件循环。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import psycopg2.extras
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.app_context import AppContext
from app.services.daily_reference_sync_service import (
    DailyReferenceSyncService,
    SCHEDULE_CODE,
)

logger = logging.getLogger("stockpro.scheduler")

SHANGHAI = ZoneInfo("Asia/Shanghai")
DAILY_JOB_ID = "daily_reference_publication"
PAPER_GUARD_JOB_ID = "paper_advance_guard"
HEARTBEAT_JOB_ID = "operations_heartbeat"
PAPER_GUARD_MINUTES = 60


def resolve_all_ashare_symbols(database) -> List[str]:
    """Resolve the working symbol list from persisted facts only."""
    with database.get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT r.payload->>'symbol' AS symbol
                FROM dataset_partition_records r
                JOIN dataset_definitions d ON d.id = r.dataset_id
                WHERE d.code = 'universe_history'
                  AND r.created_at >= NOW() - INTERVAL '30 days'
                ORDER BY 1
                """
            )
            rows = cursor.fetchall()
    symbols: List[str] = []
    for (raw,) in rows:
        text = str(raw or "").strip().upper()
        if len(text) >= 6 and text[0].isdigit():
            # universe rows store bare six-digit codes; normalize to SH_/SZ_/BJ_.
            if text.startswith("6"):
                text = f"SH_{text}"
            elif text.startswith(("8", "4")):
                text = f"BJ_{text}"
            else:
                text = f"SZ_{text}"
        if text and text not in symbols:
            symbols.append(text)
    if not symbols:
        raise ValueError("近 30 天没有已发布的 Universe 分区，无法解析 A 股标的清单")
    return symbols


class AshareSchedulerService:
    """Single APScheduler instance owned by the FastAPI lifespan."""

    _active: Optional["AshareSchedulerService"] = None

    def __init__(self, context: AppContext):
        self.context = context
        self.database = context.repositories.data.__dict__.get("database") or self._database_from_context()
        self.scheduler = AsyncIOScheduler(
            timezone=SHANGHAI,
            coalesce=True,
            max_instances=1,
        )
        self._daily_reference: Optional[DailyReferenceSyncService] = None
        self._last_results: Dict[str, Any] = {}

    def _database_from_context(self):
        from app.db.postgres_db import PostgresDatabase

        return PostgresDatabase(self.context.settings.DATABASE_URL)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Async startup used by the FastAPI lifespan (inside the event loop)."""
        import asyncio

        try:
            schedule = await asyncio.to_thread(self.daily_reference_schedule)
            self.refresh_daily_reference_schedule(schedule)
        except Exception:
            logger.warning("Could not read daily reference schedule from PG", exc_info=True)
        self._register_paper_guard()
        self._register_heartbeat()
        self.scheduler.start()
        AshareSchedulerService._active = self
        logger.info("A-share operations scheduler started (%d jobs)", len(self.scheduler.get_jobs()))

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            if AshareSchedulerService._active is self:
                AshareSchedulerService._active = None
            logger.info("A-share operations scheduler stopped")

    @classmethod
    def active(cls) -> Optional["AshareSchedulerService"]:
        """The scheduler instance bound to this process, if started."""
        return cls._active

    def status(self) -> Dict[str, Any]:
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_at": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger),
                }
            )
        return {
            "running": self.scheduler.running,
            "timezone": str(SHANGHAI),
            "jobs": jobs,
            "schedule": self.daily_reference_schedule(),
            "last_results": self._last_results,
        }

    # ------------------------------------------------------------------
    # Job registration
    # ------------------------------------------------------------------
    def daily_reference_schedule(self) -> Dict[str, Any]:
        service = self._daily_reference_service()
        return service.get_schedule()

    def refresh_daily_reference_schedule(self, schedule: Dict[str, Any]) -> None:
        job_id = DAILY_JOB_ID
        if not bool(schedule.get("enabled")):
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
            logger.info("Daily reference publication disabled in PostgreSQL")
            return
        cron = str(schedule.get("cron") or "30 17 * * 1-5")
        timezone = ZoneInfo(str(schedule.get("timezone") or "Asia/Shanghai"))
        trigger = CronTrigger.from_crontab(cron, timezone=timezone)
        self.scheduler.add_job(
            func=self._run_daily_reference_catchup,
            trigger=trigger,
            id=job_id,
            name="A股盘后日终数据与Paper推进",
            replace_existing=True,
            misfire_grace_time=1800,
        )

    def update_daily_reference_schedule(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        service = self._daily_reference_service()
        updated = service.update_schedule(payload)
        self.refresh_daily_reference_schedule(updated)
        return updated

    def trigger_daily_reference_now(self, trade_date: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
        """Manual synchronous run used by the API; returns the runner result."""
        result = self._run_single_date(trade_date, force=force)
        self._after_seal(result)
        return result

    def _register_daily_reference_job(self) -> None:
        try:
            schedule = self.daily_reference_schedule()
        except Exception:
            logger.warning("Could not read daily reference schedule from PG", exc_info=True)
            return
        self.refresh_daily_reference_schedule(schedule)

    def _register_paper_guard(self) -> None:
        self.scheduler.add_job(
            func=self._run_paper_advance_guard,
            trigger=IntervalTrigger(minutes=PAPER_GUARD_MINUTES, timezone=SHANGHAI),
            id=PAPER_GUARD_JOB_ID,
            name="Paper实例推进兜底",
            replace_existing=True,
            misfire_grace_time=600,
        )

    def _register_heartbeat(self) -> None:
        self.scheduler.add_job(
            func=self._run_heartbeat,
            trigger=CronTrigger(hour="8,16,0", minute=5, timezone=SHANGHAI),
            id=HEARTBEAT_JOB_ID,
            name="运营心跳",
            replace_existing=True,
            misfire_grace_time=3600,
        )

    def _daily_reference_service(self) -> DailyReferenceSyncService:
        if self._daily_reference is None:
            self._daily_reference = DailyReferenceSyncService(self.database)
        return self._daily_reference

    # ------------------------------------------------------------------
    # Task bodies
    # ------------------------------------------------------------------
    async def _run_daily_reference_catchup(self) -> None:
        try:
            import asyncio

            schedule = await asyncio.to_thread(self.daily_reference_schedule)
            catchup_days = max(1, min(10, int(schedule.get("catchupDays") or 5)))
            now = datetime.now(ZoneInfo(str(schedule.get("timezone") or "Asia/Shanghai"))).date()
            start = (now - timedelta(days=catchup_days + 14)).isoformat()

            from app.services.tushare_provider import market_data_provider

            try:
                open_dates = market_data_provider.trade_cal_open_dates(start, now.isoformat())
            except Exception:
                logger.warning("Trade calendar unavailable for catchup; falling back to today", exc_info=True)
                open_dates = [now.isoformat()]
            targets = open_dates[-catchup_days:] if open_dates else [now.isoformat()]
            for trade_date in targets:
                result = await asyncio.to_thread(self._run_single_date, trade_date, False)
                status = str(result.get("status"))
                logger.info("Daily reference catchup %s -> %s", trade_date, status)
                if status == "sealed":
                    await asyncio.to_thread(self._after_seal, result)
        except Exception:
            logger.exception("Daily reference publication failed")

    def _run_single_date(self, trade_date: Optional[str], force: bool) -> Dict[str, Any]:
        target_date = trade_date or datetime.now(SHANGHAI).date().isoformat()
        symbols = resolve_all_ashare_symbols(self.database)
        runner = self._daily_reference_service()
        result = runner.run(target_date, symbols, force)
        self._last_results["daily_reference"] = {
            "trade_date": target_date,
            "status": str(result.get("status")),
            "at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        }
        return result

    def _after_seal(self, seal_result: Dict[str, Any]) -> None:
        """Post-seal downstream steps: Paper catch-up and Qlib export refresh."""
        if str(seal_result.get("status")) != "sealed":
            return
        paper_summary: Dict[str, Any]
        try:
            from app.services.paper_runtime_service import PaperRuntimeService

            paper_summary = PaperRuntimeService(self.database).advance_instances()
        except Exception as exc:
            logger.exception("Paper advance after daily seal failed")
            paper_summary = {"error": str(exc)}
        self._last_results["paper_advance"] = paper_summary

        try:
            from app.services.qlib_export_service import QlibExportService

            export = QlibExportService(self.database).export_incremental()
        except Exception as exc:
            logger.exception("Qlib export after daily seal failed")
            export = {"error": str(exc)}
        self._last_results["qlib_export"] = export

    async def _run_paper_advance_guard(self) -> None:
        try:
            import asyncio

            from app.services.paper_runtime_service import PaperRuntimeService

            summary = await asyncio.to_thread(
                PaperRuntimeService(self.database).advance_instances
            )
            self._last_results["paper_advance"] = summary
            processed = int(summary.get("dates_processed") or 0)
            if processed:
                logger.info("Paper guard advanced %d cycles", processed)
        except Exception:
            logger.exception("Paper advance guard failed")

    async def _run_heartbeat(self) -> None:
        try:
            import asyncio

            summary = await asyncio.to_thread(self._heartbeat_once)
            self._last_results["heartbeat"] = summary
        except Exception:
            logger.exception("Operations heartbeat failed")

    def _heartbeat_once(self) -> Dict[str, Any]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("SELECT COUNT(*)::integer AS running FROM paper_instances WHERE status='running'")
                running = int(cursor.fetchone()["running"])
                cursor.execute("SELECT COUNT(*)::integer AS total FROM backtest_runs")
                backtests = int(cursor.fetchone()["total"])
                cursor.execute(
                    """
                    INSERT INTO service_health_snapshots
                    (service_code, status, last_success_at, message, payload)
                    VALUES ('operations_scheduler', %s, NOW(), %s, %s)
                    """,
                    (
                        "healthy",
                        "运营调度器心跳",
                        psycopg2.extras.Json(
                            {
                                "running_paper_instances": running,
                                "backtest_runs": backtests,
                                "scheduler_running": bool(self.scheduler.running),
                            }
                        ),
                    ),
                )
        return {"running_paper_instances": running, "backtest_runs": backtests}
