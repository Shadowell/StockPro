from __future__ import annotations

from typing import Any

from app.services.paper_runtime_service import PaperRuntimeService
from app.services.watch_rule_service import WatchRuleService


class PostgresOperationsRepository:
    """Read models over the preserved Paper runtime evidence tables."""

    def __init__(self, database: Any) -> None:
        self.database = database
        self.runtime = PaperRuntimeService(database)
        self.rules = WatchRuleService(database)

    def watch_context(self, scope: str) -> dict[str, Any]:
        return self.runtime.watch_context(scope)

    def health(self, scope: str) -> dict[str, Any]:
        return self.runtime.health(scope)

    def list_alerts(self, status: str | None, limit: int) -> list[dict[str, Any]]:
        return self.runtime.list_alerts(status, limit)

    def acknowledge_alert(self, alert_id: str, actor: str) -> dict[str, Any]:
        return self.runtime.acknowledge_alert(alert_id, actor)

    def get_signal(self, signal_id: str) -> dict[str, Any] | None:
        return self.runtime._row("SELECT * FROM strategy_signals WHERE id=%s AND paper_instance_id IS NOT NULL", (signal_id,))

    def acknowledge_signal(self, signal_id: str) -> dict[str, Any]:
        signal = self.get_signal(signal_id)
        if not signal: raise ValueError("信号不存在")
        if signal.get("status") == "new": self.runtime._execute("UPDATE strategy_signals SET status='confirmed',updated_at=NOW() WHERE id=%s", (signal_id,))
        return self.get_signal(signal_id) or {}

    def list_rules(self, scope: str) -> list[dict[str, Any]]: return self.rules.list_rules(scope)
    def create_rule(self, payload: dict[str, Any]) -> dict[str, Any]: return self.rules.create(payload)
    def create_rule_version(self, rule_id: str, payload: dict[str, Any]) -> dict[str, Any]: return self.rules.create_version(rule_id, payload)
    def preview_rule(self, rule_id: str) -> dict[str, Any]: return self.rules.preview(rule_id)
    def evaluate_rule(self, rule_id: str) -> dict[str, Any]: return self.rules.evaluate(rule_id)
