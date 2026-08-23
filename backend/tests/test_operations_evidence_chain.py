from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.operations_application_service import OperationsApplicationService


class FakeOperationsRepository:
    def watch_context(self, scope: str):
        paper_id = "paper-1"
        return {
            "scope": scope,
            "instances": [{"id": paper_id, "name": "A股模拟"}],
            "signals": [{"id": "signal-1", "paper_instance_id": paper_id, "strategy_version_id": "strategy-1", "symbol": "SZ_000001", "signal_type": "target_weight", "status": "executed", "signal_time": None, "evidence": {"score": 0.8}}],
            "orders": [{"id": "order-1", "paper_instance_id": paper_id}],
            "trades": [{"id": "trade-1", "paper_instance_id": paper_id}],
            "positions": [{"id": "position-1", "paper_instance_id": paper_id}],
            "risk_events": [{"id": "risk-1", "paper_instance_id": paper_id}],
            "runtime_events": [{"id": "event-1", "paper_instance_id": paper_id}],
            "alerts": [{"id": "alert-1", "paper_instance_id": paper_id, "status": "active"}],
        }

    def health(self, scope: str): return {"scope": scope, "status": "healthy"}


def test_operations_objects_link_same_paper_instance() -> None:
    service = OperationsApplicationService(FakeOperationsRepository())
    context = service.watch_context(scope="business")
    paper_id = context["instances"][0]["id"]

    for group in ("signals", "orders", "trades", "positions", "risk_events", "runtime_events", "alerts"):
        assert all(item["paper_instance_id"] == paper_id for item in context[group])
    assert context["signals"][0]["evidence"] == {"score": 0.8}
