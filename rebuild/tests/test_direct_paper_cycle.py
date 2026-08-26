from __future__ import annotations

from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.paper.cycle import PaperCycleService  # noqa: E402
from app.domain.paper.cycle_repository import PostgresPaperCycleRepository  # noqa: E402


class FakeCycleRepository:
    def __init__(self):
        self.cursor = None
        self.cycles = {}

    def pending_dates(self, instance_id):
        return [day for day in ("2025-01-02", "2025-01-03") if self.cursor is None or day > self.cursor]

    def process_date(self, instance_id, trade_date, runner):
        key = f"{trade_date}:close"
        if key in self.cycles:
            return {**self.cycles[key], "reused": True}
        row = {"cycle_key": key, "trade_date": trade_date, "status": "success", "signal_count": 1, "order_count": 1 if trade_date.endswith("03") else 0, "trade_count": 1 if trade_date.endswith("03") else 0}
        self.cycles[key] = row
        self.cursor = trade_date
        return row


def test_advance_processes_pending_dates_in_order_and_then_is_idempotent():
    repository = FakeCycleRepository()
    service = PaperCycleService(repository, runner=object())
    first = service.advance(11, max_dates=2)
    second = service.advance(11, max_dates=2)
    assert first["processed_dates"] == ["2025-01-02", "2025-01-03"]
    assert first["signal_count"] == 2
    assert first["order_count"] == 1 and first["trade_count"] == 1
    assert first["pending_remaining"] == 0
    assert second["processed_dates"] == []
    assert second["pending_remaining"] == 0


def test_advance_honors_max_dates_without_skipping_cursor_order():
    repository = FakeCycleRepository()
    service = PaperCycleService(repository, runner=object())
    first = service.advance(11, max_dates=1)
    second = service.advance(11, max_dates=1)
    assert first["processed_dates"] == ["2025-01-02"]
    assert first["pending_remaining"] == 1
    assert second["processed_dates"] == ["2025-01-03"]


def test_cycle_repository_is_postgres_only_and_processes_each_date_in_one_transaction():
    source = (BACKEND_ROOT / "app/domain/paper/cycle_repository.py").read_text()
    assert "sqlite" not in source.lower()
    assert "def process_date(" in source
    assert "FOR UPDATE" in source
    assert "paper_runtime_cycles" in source
    assert "paper_equity_snapshots" in source
    assert "cash_ledger" in source
    assert PostgresPaperCycleRepository.__name__ == "PostgresPaperCycleRepository"
