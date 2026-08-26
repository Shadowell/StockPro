from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import scheduler_service as scheduler_module  # noqa: E402


def test_scheduler_registers_only_configured_data_sync(monkeypatch) -> None:
    registered: list[str] = []

    class FakeScheduler:
        def __init__(self, *args, **kwargs):
            pass

        def add_job(self, func, trigger, *, id, **kwargs):
            registered.append(id)

        def start(self):
            return None

        def get_jobs(self):
            return []

    monkeypatch.setattr(scheduler_module, "AsyncIOScheduler", FakeScheduler)
    service = scheduler_module.SchedulerService()
    monkeypatch.setattr(service, "_register_default_ai_prediction_targets", lambda: None)

    asyncio.run(service.start())

    assert "configured_data_sync" in registered
    assert "daily_sync_okx" not in registered
    assert "quick_sync" not in registered
