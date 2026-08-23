from __future__ import annotations

import threading
import time
from typing import Any

from app.domain.operations.models import AlertView, SignalView
from app.repositories.protocols import OperationsRepository


PRIVATE_FIELDS = frozenset({"api_version", "strategy_api_version", "migration_status"})


def public(value: Any) -> Any:
    if isinstance(value, list):
        return [public(item) for item in value]
    if isinstance(value, dict):
        return {key: public(item) for key, item in value.items() if key not in PRIVATE_FIELDS}
    return value


class OperationsApplicationService:
    def __init__(self, repository: OperationsRepository) -> None:
        self.repository = repository
        self._watch_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._watch_lock = threading.Lock()

    @staticmethod
    def _signal(item: dict[str, Any]) -> dict[str, Any]:
        evidence = item.get("evidence") or item.get("payload") or {}
        return SignalView(
            id=str(item["id"]),
            paper_instance_id=str(item["paper_instance_id"]),
            strategy_version_id=str(item.get("strategy_version_id") or ""),
            symbol=str(item.get("symbol") or ""),
            signal_type=str(item.get("signal_type") or item.get("action") or "unknown"),
            status=str(item.get("status") or "pending"),
            signal_time=item.get("signal_time"),
            evidence=public(evidence),
        ).to_dict()

    @staticmethod
    def _alert(item: dict[str, Any]) -> dict[str, Any]:
        return AlertView(
            id=str(item["id"]),
            paper_instance_id=str(item["paper_instance_id"]) if item.get("paper_instance_id") else None,
            severity=str(item.get("severity") or "info"),
            category=str(item.get("category") or "runtime"),
            title=str(item.get("title") or "运行告警"),
            message=str(item.get("message") or ""),
            source_object_type=str(item.get("source_type") or item.get("source_object_type") or "runtime"),
            source_object_id=str(item.get("source_id") or item.get("source_object_id") or ""),
            triggered_at=item.get("triggered_at"),
            status=str(item.get("status") or "active"),
        ).to_dict()

    def watch_context(self, scope: str = "business") -> dict[str, Any]:
        now = time.monotonic()
        cached = self._watch_cache.get(scope)
        if cached and now - cached[0] < 60:
            return cached[1]
        with self._watch_lock:
            cached = self._watch_cache.get(scope)
            if cached and time.monotonic() - cached[0] < 60:
                return cached[1]
            context = public(self.repository.watch_context(scope))
            context["signals"] = [self._signal(item) for item in context.get("signals", [])]
            context["alerts"] = [self._alert(item) for item in context.get("alerts", [])]
            self._watch_cache[scope] = (time.monotonic(), context)
            return context

    def monitor(self, scope: str = "business") -> dict[str, Any]:
        return public(self.repository.health(scope))
