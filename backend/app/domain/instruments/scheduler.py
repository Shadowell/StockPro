from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


class AshareDailySyncScheduler:
    def __init__(self, *, service, configured_settings, scheduler=None, trigger_factory=None):
        self.service = service
        self.settings = configured_settings
        self.scheduler = scheduler or AsyncIOScheduler(timezone=configured_settings.A_SHARE_DAILY_SYNC_TIMEZONE)
        self.trigger_factory = trigger_factory or CronTrigger

    async def run_once(self) -> dict:
        return await asyncio.to_thread(self.service.sync_all, trigger="scheduled")

    def start(self) -> None:
        if not self.settings.A_SHARE_DAILY_SYNC_ENABLED:
            return
        if not str(self.settings.TUSHARE_TOKEN or "").strip():
            raise RuntimeError("A_SHARE_DAILY_SYNC_ENABLED=true requires TUSHARE_TOKEN")
        trigger = self.trigger_factory(
            hour=int(self.settings.A_SHARE_DAILY_SYNC_HOUR),
            minute=int(self.settings.A_SHARE_DAILY_SYNC_MINUTE),
            timezone=self.settings.A_SHARE_DAILY_SYNC_TIMEZONE,
        )
        self.scheduler.add_job(
            self.run_once,
            trigger,
            id="a-share-daily-instrument-sync",
            name="StockPro 全量 A 股证券与日线同步",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        self.scheduler.start()

    def stop(self) -> None:
        if getattr(self.scheduler, "running", False):
            self.scheduler.shutdown(wait=False)

    def status(self) -> dict:
        next_run = None
        getter = getattr(self.scheduler, "get_job", None)
        job = getter("a-share-daily-instrument-sync") if callable(getter) else None
        if job is not None and getattr(job, "next_run_time", None) is not None:
            next_run = job.next_run_time.isoformat()
        return {
            "enabled": bool(self.settings.A_SHARE_DAILY_SYNC_ENABLED),
            "provider_configured": bool(str(self.settings.TUSHARE_TOKEN or "").strip()),
            "hour": int(self.settings.A_SHARE_DAILY_SYNC_HOUR),
            "minute": int(self.settings.A_SHARE_DAILY_SYNC_MINUTE),
            "timezone": self.settings.A_SHARE_DAILY_SYNC_TIMEZONE,
            "next_run_at": next_run,
        }


from app.core.config import settings  # noqa: E402
from app.domain.instruments.service import instrument_sync_service  # noqa: E402

a_share_daily_sync_scheduler = AshareDailySyncScheduler(
    service=instrument_sync_service,
    configured_settings=settings,
)
