from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.local_db import LocalDatabase  # noqa: E402
from app.models.schemas import StrategyCreate, StrategyUpdate  # noqa: E402
from app.services import strategy_registry  # noqa: E402
from app.services.strategy_service import StrategyService  # noqa: E402


DYNAMIC_STRATEGY_CODE = """
from app.core.execution.base_strategy import BaseStrategy, BarData


class ExternalAgentDynamicStrategy(BaseStrategy):
    async def on_bar(self, bar: BarData) -> None:
        return
"""

UPDATED_DYNAMIC_STRATEGY_CODE = """
from app.core.execution.base_strategy import BaseStrategy, BarData


class ExternalAgentUpdatedStrategy(BaseStrategy):
    async def on_bar(self, bar: BarData) -> None:
        return
"""


def test_db_script_strategy_source_prevents_name_based_registry_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db import local_db

    strategy_db = LocalDatabase(str(tmp_path / "dynamic-strategies.sqlite"))
    strategy_db.init_db()
    strategy_id = strategy_db.save_strategy(
        name="[合约][15M][CTA] BTC · 外部Agent热注册 · 100U",
        description="Agent 动态注册策略",
        script_content=DYNAMIC_STRATEGY_CODE,
        config={
            "strategy_source": "db_script",
            "script_content_source": "db",
            "timeframe": "15m",
            "market_type": "swap",
            "is_paper_trading": True,
        },
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )

    monkeypatch.setattr(local_db, "db_instance", strategy_db)

    info = strategy_registry.get_strategy_for_id(strategy_id)

    assert info is not None
    assert info["strategy_class"].__name__ == "ExternalAgentDynamicStrategy"
    assert info["db_config"]["strategy_source"] == "db_script"
    assert info["symbols"] == ["BTC/USDT:USDT"]


def test_strategy_create_validates_dynamic_script_and_marks_db_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy_service_module = importlib.import_module("app.services.strategy_service")

    strategy_db = LocalDatabase(str(tmp_path / "create-dynamic.sqlite"))
    strategy_db.init_db()
    monkeypatch.setattr(strategy_service_module, "db", strategy_db)

    payload = StrategyCreate(
        name="[合约][15M][CTA] BTC · Agent动态突破 · 100U",
        description="通过 API/MCP 动态注册，不写 Python 文件",
        script_content=DYNAMIC_STRATEGY_CODE,
        config={"timeframe": "15m", "market_type": "swap", "is_paper_trading": True},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )

    created = asyncio.run(StrategyService().create_strategy(payload))

    assert created["script_content"].strip() == DYNAMIC_STRATEGY_CODE.strip()
    assert created["config"]["strategy_source"] == "db_script"
    assert created["config"]["script_content_source"] == "db"
    assert created["config"]["class_name"] == "ExternalAgentDynamicStrategy"


def test_strategy_create_rejects_invalid_dynamic_script_before_insert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy_service_module = importlib.import_module("app.services.strategy_service")

    strategy_db = LocalDatabase(str(tmp_path / "reject-invalid.sqlite"))
    strategy_db.init_db()
    monkeypatch.setattr(strategy_service_module, "db", strategy_db)

    payload = StrategyCreate(
        name="[合约][15M][CTA] BTC · 非法脚本 · 100U",
        description="invalid",
        script_content="class NotABaseStrategy:\n    pass\n",
        config={"timeframe": "15m", "market_type": "swap"},
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )

    with pytest.raises(ValueError, match="BaseStrategy"):
        asyncio.run(StrategyService().create_strategy(payload))

    assert strategy_db.get_strategies() == []


def test_strategy_update_keeps_existing_row_and_marks_db_script_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy_service_module = importlib.import_module("app.services.strategy_service")

    strategy_db = LocalDatabase(str(tmp_path / "update-dynamic.sqlite"))
    strategy_db.init_db()
    monkeypatch.setattr(strategy_service_module, "db", strategy_db)
    strategy_id = strategy_db.save_strategy(
        name="[合约][15M][CTA] BTC · Agent动态突破 · 100U",
        description="旧版本",
        script_content=DYNAMIC_STRATEGY_CODE,
        config={
            "strategy_source": "db_script",
            "script_content_source": "db",
            "class_name": "ExternalAgentDynamicStrategy",
            "timeframe": "15m",
            "market_type": "swap",
        },
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )

    updated = asyncio.run(
        StrategyService().update_strategy(
            strategy_id,
            StrategyUpdate(
                name="[合约][15M][CTA] BTC · Agent动态突破改良 · 100U",
                description="更新版本",
                script_content=UPDATED_DYNAMIC_STRATEGY_CODE,
                config={"timeframe": "15m", "market_type": "swap"},
                exchange="okx",
                symbols=["ETH/USDT:USDT"],
            ),
        )
    )

    assert updated is not None
    assert updated["id"] == strategy_id
    assert updated["name"] == "[合约][15M][CTA] BTC · Agent动态突破改良 · 100U"
    assert updated["description"] == "更新版本"
    assert updated["script_content"].strip() == UPDATED_DYNAMIC_STRATEGY_CODE.strip()
    assert updated["symbols"] == ["ETH/USDT:USDT"]
    assert updated["config"]["strategy_source"] == "db_script"
    assert updated["config"]["script_content_source"] == "db"
    assert updated["config"]["class_name"] == "ExternalAgentUpdatedStrategy"
    assert [item["id"] for item in strategy_db.get_strategies()] == [strategy_id]


def test_strategy_update_rejects_invalid_script_before_mutating_existing_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy_service_module = importlib.import_module("app.services.strategy_service")

    strategy_db = LocalDatabase(str(tmp_path / "reject-update-invalid.sqlite"))
    strategy_db.init_db()
    monkeypatch.setattr(strategy_service_module, "db", strategy_db)
    strategy_id = strategy_db.save_strategy(
        name="[合约][15M][CTA] BTC · Agent动态突破 · 100U",
        description="旧版本",
        script_content=DYNAMIC_STRATEGY_CODE,
        config={
            "strategy_source": "db_script",
            "script_content_source": "db",
            "class_name": "ExternalAgentDynamicStrategy",
            "timeframe": "15m",
            "market_type": "swap",
        },
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
    )

    with pytest.raises(ValueError, match="BaseStrategy"):
        asyncio.run(
            StrategyService().update_strategy(
                strategy_id,
                StrategyUpdate(
                    script_content="class NotABaseStrategy:\n    pass\n",
                    config={"timeframe": "1h", "market_type": "swap"},
                ),
            )
        )

    unchanged = strategy_db.get_strategy_by_id(strategy_id)
    assert unchanged is not None
    assert unchanged["script_content"].strip() == DYNAMIC_STRATEGY_CODE.strip()
    assert unchanged["config"]["class_name"] == "ExternalAgentDynamicStrategy"
    assert unchanged["config"]["timeframe"] == "15m"
    assert len(strategy_db.get_strategies()) == 1
