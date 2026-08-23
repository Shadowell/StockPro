from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path: sys.path.insert(0, str(BACKEND_ROOT))

from app.main import create_app


class FakeOperationsRepository:
    def __init__(self): self.orders = 61; self.trades = 47; self.preview_writes = 0
    def watch_context(self, scope): return {"scope": scope, "instances": [], "signals": [], "orders": [], "trades": [], "positions": [], "risk_events": [], "runtime_events": [], "alerts": []}
    def list_rules(self, scope): return [{"id": "rule-1", "name": "价格异动", "data_purpose": "user"}]
    def preview_rule(self, rule_id): return {"rule_id": rule_id, "writes_performed": False, "matched": 1}
    def evaluate_rule(self, rule_id): return {"rule_id": rule_id, "writes_performed": True, "alerts_created": 1, "orders_created": 0}
    def list_alerts(self, status, limit): return []
    def acknowledge_signal(self, signal_id): return {"id": signal_id, "paper_instance_id": "paper-1", "strategy_version_id": "strategy-1", "symbol": "SZ_000001", "signal_type": "buy", "status": "confirmed", "signal_time": None, "payload": {}}


class FakeAuthRepository:
    def record_auth_event(self, **kwargs): pass


@dataclass
class Repositories:
    auth: object
    operations: object


@dataclass
class Context:
    settings: object
    repositories: object
    clock: object


class Settings:
    AUTH_ENABLED = False
    AUTH_COOKIE_NAME = "stockpro_session"
    AUTH_COOKIE_SECURE = False


def test_rule_preview_is_readonly_and_evaluate_never_orders() -> None:
    repository = FakeOperationsRepository()
    context = Context(Settings(), Repositories(FakeAuthRepository(), repository), lambda: datetime.now(timezone.utc))
    client = TestClient(create_app(context))
    before = (repository.orders, repository.trades)

    preview = client.post("/api/watch/rules/rule-1/preview").json()
    evaluated = client.post("/api/watch/rules/rule-1/evaluate").json()

    assert preview["writes_performed"] is False
    assert evaluated["orders_created"] == 0
    assert (repository.orders, repository.trades) == before
    acknowledged = client.post("/api/signals/signal-1/acknowledge").json()
    assert acknowledged["status"] == "confirmed"
    assert acknowledged["acknowledged_by"] == "admin"
