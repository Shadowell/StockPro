from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.strategy.models import ImmutableEvidenceError
from app.main import create_app


VALID_CODE = "def initialize(context):\n    pass\n\ndef handle_data(context, data):\n    pass\n"


class FakeStrategyRepository:
    def __init__(self) -> None:
        self.version = {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "动量轮动",
            "version": 1,
            "script_content": VALID_CODE,
            "content_hash": hashlib.sha256(VALID_CODE.encode()).hexdigest(),
            "validation_status": "valid",
            "historical_contract_metadata": {"strategy_api_version": "historical"},
        }

    def list_strategies(self): return [{"name": "动量轮动", "latest_version": self.version}]
    def get_strategy_version(self, version_id: str): return dict(self.version)
    def create_strategy(self, payload): return {"strategy_version": dict(self.version), "validation": {"valid": True, "issues": []}}
    def create_version(self, parent_id: str, payload): return {"strategy_version": dict(self.version), "validation": {"valid": True, "issues": []}}
    def validate(self, payload): return {"valid": True, "issues": [], "dependencies": []}
    def quick_run(self, version_id: str, payload): return {"status": "success", "promotion_status": "not_evaluated", "intents": []}

    def update_contract_metadata(self, version_id: str, metadata):
        raise ImmutableEvidenceError("historical contract metadata is read-only")


def _client(repository: FakeStrategyRepository) -> TestClient:
    inert = SimpleNamespace()
    context = SimpleNamespace(
        settings=SimpleNamespace(AUTH_ENABLED=False, ADMIN_USERNAME="admin", BACKEND_CORS_ORIGINS=["http://localhost:4444"]),
        repositories=SimpleNamespace(health=inert, auth=inert, strategies=repository),
        clock=lambda: datetime.now(timezone.utc),
    )
    return TestClient(create_app(context))


def test_new_strategy_uses_current_contract_without_public_version_name() -> None:
    response = _client(FakeStrategyRepository()).post("/api/strategies", json={"name": "动量轮动", "description": "封存股票池动量策略", "script_content": VALID_CODE})

    assert response.status_code == 200
    body = response.json()
    assert "api_version" not in body
    assert "strategy_api_version" not in str(body)
    assert body["strategy_version"]["content_hash"]


def test_historical_contract_metadata_is_readonly() -> None:
    repository = FakeStrategyRepository()
    historical = repository.get_strategy_version("historical-id")

    assert historical["historical_contract_metadata"]
    with pytest.raises(ImmutableEvidenceError):
        repository.update_contract_metadata(historical["id"], {})


def test_quick_run_is_never_paper_eligible() -> None:
    client = _client(FakeStrategyRepository())
    version_id = "11111111-1111-1111-1111-111111111111"

    response = client.post(f"/api/strategies/{version_id}/quick-run", json={})

    assert response.status_code == 200
    assert response.json()["promotion_status"] == "not_evaluated"
    assert client.get("/api/v1/strategies").status_code == 404
