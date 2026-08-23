from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.paper.models import PaperInstanceView
from app.repositories.protocols import PaperRepository
from app.services.data_purpose import filter_records_for_scope, resolve_data_purpose


PRIVATE_FIELDS = frozenset({"api_version", "strategy_api_version", "migration_status"})


def _public(value: Any) -> Any:
    if isinstance(value, list):
        return [_public(item) for item in value]
    if isinstance(value, dict):
        return {key: _public(item) for key, item in value.items() if key not in PRIVATE_FIELDS}
    return value


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _health_state(item: dict[str, Any]) -> str:
    if item.get("latest_cycle_error") or item.get("latest_cycle_status") == "failed":
        return "error"
    lifecycle = str(item.get("status") or "unknown")
    if lifecycle in {"starting", "pausing", "stopping"}:
        return "warning"
    if lifecycle in {"draft", "paused", "stopped", "running"}:
        return "healthy"
    return "unavailable"


class PaperApplicationService:
    def __init__(self, repository: PaperRepository) -> None:
        self.repository = repository

    @staticmethod
    def _view(item: dict[str, Any]) -> dict[str, Any]:
        initial_cash = _decimal(item.get("initial_cash"))
        equity = _decimal(item.get("equity"))
        total_pnl = equity - initial_cash if equity is not None and initial_cash is not None else None
        return PaperInstanceView(
            id=str(item["id"]),
            name=str(item.get("name") or item["id"]),
            lifecycle_status=str(item.get("status") or "unknown"),
            health_state=_health_state(item),
            initial_cash=initial_cash,
            equity=equity,
            total_pnl=total_pnl,
            return_rate=(total_pnl / initial_cash if total_pnl is not None and initial_cash else None),
            trade_count=int(item.get("trade_count") or 0),
            position_count=int(item.get("position_count") or 0),
            heartbeat_at=item.get("heartbeat_at"),
        ).to_dict()

    @classmethod
    def _detail(cls, item: dict[str, Any]) -> dict[str, Any]:
        return _public({**item, "view": cls._view(item)})

    def list_instances(self, scope: str = "business") -> dict[str, Any]:
        rows = self.repository.list_instances()
        normalized = [
            {
                **item,
                "data_purpose": resolve_data_purpose(item.get("data_purpose"), item.get("name")),
            }
            for item in rows
        ]
        scoped = filter_records_for_scope(normalized, scope)
        items = [self._view(item) for item in scoped]
        return {"items": items, "total": len(items), "scope": scope}

    def get_instance(self, instance_id: str) -> dict[str, Any]:
        return self._detail(self.repository.get_instance(instance_id))

    def create_instance(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._detail(self.repository.create_instance(payload))

    def transition(self, instance_id: str, action: str) -> dict[str, Any]:
        handler = getattr(self.repository, action, None)
        if handler is None or action not in {"start", "pause", "resume", "stop"}:
            raise ValueError("不支持的 Paper 生命周期操作")
        return self._detail(handler(instance_id))

    def advance(self, instance_id: str, max_dates: int) -> dict[str, Any]:
        return _public(self.repository.advance(instance_id, max_dates))
