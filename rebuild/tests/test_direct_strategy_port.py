from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException
from starlette.requests import Request


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.domain.strategy.service import StrategyDomainService  # noqa: E402
from app.domain.strategy.validation import validate_strategy_python  # noqa: E402
from app.api.v2.endpoints.strategy import _require_admin_when_auth_enabled  # noqa: E402
from app.core.config import settings  # noqa: E402


class FakeStrategyRepository:
    def __init__(self):
        self.created = []
        self.versioned = []
        self.archived = []

    def list_strategies(self):
        return [
            {
                "legacy_strategy_id": 224,
                "name": "[A股][日线][均值回归] 五日超跌反弹",
                "description": "A-share mean reversion",
                "script_content": "def initialize(context): pass",
                "status": "draft",
                "validation_status": "valid",
                "created_at": "2026-08-25T12:00:00+08:00",
                "updated_at": "2026-08-25T12:00:00+08:00",
            }
        ]

    def get_strategy(self, strategy_id: int):
        return self.list_strategies()[0] if strategy_id == 224 else None

    def create_strategy(self, payload, validation):
        self.created.append((payload, validation))
        return {**self.list_strategies()[0], "legacy_strategy_id": 225, "name": payload["name"], "script_content": payload["script_content"], "parameter_schema": payload["parameter_schema"], "validation_status": "valid"}

    def create_version(self, strategy_id, payload, validation):
        self.versioned.append((strategy_id, payload, validation))
        return {**self.list_strategies()[0], "legacy_strategy_id": strategy_id, "name": payload["name"], "script_content": payload["script_content"], "parameter_schema": payload["parameter_schema"], "validation_status": "valid"}

    def archive_strategy(self, strategy_id):
        self.archived.append(strategy_id)
        return True


def test_bitpro_strategy_catalog_maps_postgres_a_share_versions():
    service = StrategyDomainService(FakeStrategyRepository())
    page = asyncio.run(
        service.list_page(
            page=1,
            per_page=18,
            search="超跌",
            status="all",
            asset_class="all",
            strategy_type="all",
            timeframe="all",
            capital="all",
        )
    )

    assert page["total"] == 1
    assert page["items"][0]["id"] == 224
    assert page["items"][0]["exchange"] == "CN"
    assert page["items"][0]["config"]["asset_class"] == "stock"
    assert page["items"][0]["config"]["timeframe"] == "1d"
    assert page["asset_counts"] == {"all": 1, "stock": 1, "etf": 0}
    assert asyncio.run(service.get(224))["name"].startswith("[A股]")


VALID_CODE = """
def initialize(context):
    set_benchmark('000300.SH')

def handle_data(context, data):
    record(held=len(context.portfolio.positions))
"""


def test_a_share_strategy_validator_blocks_external_capabilities():
    valid = validate_strategy_python(VALID_CODE)
    blocked = validate_strategy_python("import os\n" + VALID_CODE)
    assert valid["valid"] is True
    assert blocked["valid"] is False
    assert any(issue["code"] == "FORBIDDEN_CAPABILITY" for issue in blocked["issues"])


def test_strategy_validator_blocks_attribute_and_dynamic_call_bypasses():
    attribute_call = validate_strategy_python(VALID_CODE.replace("record(held=len(context.portfolio.positions))", "data.to_csv('/tmp/leak.csv')"))
    dynamic_call = validate_strategy_python(VALID_CODE + "\n__builtins__['__import__']('os').system('id')\n")
    assert attribute_call["valid"] is False
    assert any(issue["code"] == "FORBIDDEN_METHOD_CALL" for issue in attribute_call["issues"])
    assert dynamic_call["valid"] is False
    assert any(issue["code"] in {"FORBIDDEN_CAPABILITY", "FORBIDDEN_DYNAMIC_CALL"} for issue in dynamic_call["issues"])
    receiver_bypass = validate_strategy_python(VALID_CODE.replace("record(held=len(context.portfolio.positions))", "context.http.get('https://example.com')"))
    assert receiver_bypass["valid"] is False
    assert any(issue["code"] == "FORBIDDEN_METHOD_CALL" for issue in receiver_bypass["issues"])
    reassignment_bypass = validate_strategy_python(
        VALID_CODE.replace(
            "record(held=len(context.portfolio.positions))",
            "rows = []\n    rows = context.db\n    rows.get('secrets')",
        )
    )
    assert reassignment_bypass["valid"] is False
    parameter_bypass = validate_strategy_python(
        VALID_CODE.replace(
            "record(held=len(context.portfolio.positions))",
            "data = context.http\n    data.get('https://example.com')",
        )
    )
    assert parameter_bypass["valid"] is False


def test_strategy_validator_allows_only_known_safe_container_methods():
    code = VALID_CODE.replace(
        "record(held=len(context.portfolio.positions))",
        "rows = []\n    rows.append(1)\n    bar = get_current_data().get('600519.SH')\n    record(held=len(rows), close=bar.close)",
    )
    assert validate_strategy_python(code)["valid"] is True


def test_strategy_writes_create_immutable_versions_and_archive():
    repository = FakeStrategyRepository()
    service = StrategyDomainService(repository)
    created = asyncio.run(service.create({"name": "A股测试策略", "script_content": VALID_CODE, "config": {"asset_class": "stock"}, "symbols": ["600519.SH"]}))
    updated = asyncio.run(service.update(224, {"name": "[A股][日线][均值回归] 五日超跌反弹", "script_content": VALID_CODE, "config": {"asset_class": "stock"}}))
    archived = asyncio.run(service.archive(224))
    assert created["exchange"] == "CN"
    assert created["config"]["symbols"] == ["600519.SH"]
    assert created["symbols"] == ["600519.SH"]
    assert updated["config"]["timeframe"] == "1d"
    assert repository.versioned[0][0] == 224
    assert archived == {"archived": True, "strategy_id": 224}


def test_strategy_write_forces_a_share_domain_and_rejects_non_a_share_symbols():
    repository = FakeStrategyRepository()
    service = StrategyDomainService(repository)
    with pytest.raises(ValueError, match="asset_class"):
        asyncio.run(service.create({"name": "bad", "script_content": VALID_CODE, "config": {"asset_class": "crypto"}}))
    with pytest.raises(ValueError, match="无效 A 股标的"):
        asyncio.run(service.create({"name": "bad", "script_content": VALID_CODE, "config": {"asset_class": "stock", "capital": "10USDT"}, "symbols": ["BTC-USDT"]}))


def test_read_only_mcp_token_cannot_mutate_strategies(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "BITPRO_AUTH_ENABLED", True)
    request = Request({"type": "http", "method": "POST", "path": "/api/v2/strategies", "headers": []})
    request.state.auth = {"role": "admin", "auth_method": "mcp_token", "scopes": ["R"]}
    with pytest.raises(HTTPException) as denied:
        _require_admin_when_auth_enabled(request)
    assert denied.value.status_code == 403
    request.state.auth["scopes"] = ["R", "W"]
    _require_admin_when_auth_enabled(request)


def test_bitpro_strategy_editor_exposes_only_a_share_write_contract():
    source = (BACKEND_ROOT.parent / "frontend/src/pages/Strategy.tsx").read_text()
    active = source.split("const STRATEGY_TEMPLATES = [", 1)[1]
    assert "const canWriteStrategy = isAdmin" in source
    assert '<option value="CN">A 股</option>' in source
    assert "A 股标的（逗号分隔）" in source
    assert "order_target_percent" in active
    assert "def initialize(context)" in active
    repository = (BACKEND_ROOT / "app/domain/strategy/repository.py").read_text()
    assert "UPDATE strategy_scripts SET name=" not in repository
