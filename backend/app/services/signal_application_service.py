from __future__ import annotations

from typing import Any

from app.repositories.protocols import OperationsRepository
from app.services.operations_application_service import OperationsApplicationService, public


class SignalApplicationService:
    def __init__(self, repository: OperationsRepository) -> None:
        self.repository = repository
        self.operations = OperationsApplicationService(repository)

    def list(self, scope: str) -> dict[str, Any]:
        items = [self.operations._signal(public(item)) for item in self.repository.list_signals(scope)]
        return {"items": items, "total": len(items), "scope": scope}

    def detail(self, signal_id: str) -> dict[str, Any]:
        item = self.repository.get_signal(signal_id)
        if not item: raise ValueError("信号不存在")
        return self.operations._signal(public(item))

    def acknowledge(self, signal_id: str, actor: str) -> dict[str, Any]:
        result = self.operations._signal(public(self.repository.acknowledge_signal(signal_id)))
        result["acknowledged_by"] = actor
        return result
