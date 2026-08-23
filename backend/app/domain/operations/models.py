from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SignalView:
    id: str
    paper_instance_id: str
    strategy_version_id: str
    symbol: str
    signal_type: str
    status: str
    signal_time: Any
    evidence: Mapping[str, object]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AlertView:
    id: str
    paper_instance_id: str | None
    severity: str
    category: str
    title: str
    message: str
    source_object_type: str
    source_object_id: str
    triggered_at: Any
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
