from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class PaperInstanceView:
    id: str
    name: str
    lifecycle_status: str
    health_state: str
    initial_cash: Decimal | None
    equity: Decimal | None
    total_pnl: Decimal | None
    return_rate: Decimal | None
    trade_count: int
    position_count: int
    heartbeat_at: Any

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
