from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.paper_application_service import PaperApplicationService


class FakePaperRepository:
    def __init__(self) -> None:
        self.manifest = {"instance_count": 15, "order_count": 61, "trade_count": 47, "position_count": 23, "equity_sample_count": 428, "event_count": 681}

    def continuity_manifest(self): return dict(self.manifest)
    def list_instances(self):
        return [{"id": f"paper-{index}", "name": f"Paper {index}", "status": "running", "initial_cash": 1000000, "equity": 1100000, "trade_count": 3, "position_count": 2, "heartbeat_at": None} for index in range(15)]


def test_paper_view_model_does_not_change_ledger() -> None:
    repository = FakePaperRepository()
    service = PaperApplicationService(repository)
    before = repository.continuity_manifest()

    view = service.list_instances(scope="business")

    assert len(view["items"]) == 15
    assert repository.continuity_manifest() == before
    assert view["items"][0]["id"] == "paper-0"
    assert view["items"][0]["total_pnl"] == 100000
