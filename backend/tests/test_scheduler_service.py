import asyncio
from unittest.mock import Mock


def test_news_scheduler_runs_sync_fetch_in_worker_thread(monkeypatch):
    from app.services import scheduler_service as module

    service = module.SchedulerService()
    sync_news = Mock(return_value={"count": 0})
    to_thread = Mock(return_value={"count": 0})

    monkeypatch.setattr(module.data_sync_service, "sync_news", sync_news)
    monkeypatch.setattr(module.asyncio, "to_thread", to_thread)

    asyncio.run(service._sync_news())

    to_thread.assert_called_once_with(sync_news)
    sync_news.assert_not_called()


def test_scheduler_shutdown_does_not_wait_for_long_running_jobs():
    from app.services.scheduler_service import SchedulerService

    service = SchedulerService()
    scheduler = Mock()
    scheduler.running = True
    service.scheduler = scheduler

    asyncio.run(service.shutdown())

    scheduler.shutdown.assert_called_once_with(wait=False)
