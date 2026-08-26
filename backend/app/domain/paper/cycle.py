"""Explicit, bounded Paper cycle advancement orchestration."""
from __future__ import annotations


class PaperCycleService:
    def __init__(self, repository, runner) -> None:
        self.repository = repository
        self.runner = runner

    def advance(self, instance_id: int | str, *, max_dates: int = 1) -> dict:
        budget = max(1, min(int(max_dates), 260))
        pending = self.repository.pending_dates(instance_id)
        cycles = []
        for trade_date in pending[:budget]:
            cycles.append(self.repository.process_date(instance_id, trade_date, self.runner))
        remaining = self.repository.pending_dates(instance_id)
        return {
            "instance_id": instance_id,
            "processed_dates": [str(row["trade_date"]) for row in cycles if not row.get("reused")],
            "cycles": cycles,
            "signal_count": sum(int(row.get("signal_count") or 0) for row in cycles),
            "order_count": sum(int(row.get("order_count") or 0) for row in cycles),
            "trade_count": sum(int(row.get("trade_count") or 0) for row in cycles),
            "pending_remaining": len(remaining),
            "last_processed_trade_date": str(cycles[-1]["trade_date"]) if cycles else None,
        }
