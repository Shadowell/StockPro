from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path: sys.path.insert(0, str(BACKEND_ROOT))

from app.services.monitor_application_service import MonitorApplicationService


class FakeRepository:
    def health(self, scope):
        return {"scope": scope, "status": "warning", "strategy_health": [{"id": "paper-1", "status": "running", "health_state": "stale"}], "services": [{"service_code": "paper_runtime", "status": "warning", "freshness": "stale"}]}


def test_stale_service_does_not_change_paper_lifecycle() -> None:
    view = MonitorApplicationService(FakeRepository()).summary(scope="business")
    instance = view["strategy_health"][0]
    assert instance["lifecycle_status"] == "running"
    assert instance["health_state"] == "stale"
    assert view["overall_status"] == "warning"
