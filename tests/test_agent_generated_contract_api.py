from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.agent.code_sandbox import CodeSafetyError, validate_base_strategy_contract  # noqa: E402


def test_agent_contract_rejects_open_short_before_backtest() -> None:
    strategy_code = '''
from app.core.execution.base_strategy import BaseStrategy, BarData


class TestBadShortcutStrategy(BaseStrategy):
    async def on_bar(self, bar: BarData) -> None:
        await self.open_short(bar.symbol, 1000.0, leverage=2.0)
'''

    try:
        validate_base_strategy_contract(strategy_code)
    except CodeSafetyError as exc:
        message = str(exc)
        assert "open_short" in message
        assert "open_contract" in message
    else:
        raise AssertionError("BaseStrategy sandbox should reject self.open_short before backtest")


def test_agent_contract_rejects_broker_close_short_before_backtest() -> None:
    strategy_code = '''
from app.core.execution.base_strategy import BaseStrategy, BarData


class TestBadBrokerShortcutStrategy(BaseStrategy):
    async def on_bar(self, bar: BarData) -> None:
        await self.broker.close_short(bar.symbol, ratio=1.0)
'''

    try:
        validate_base_strategy_contract(strategy_code)
    except CodeSafetyError as exc:
        message = str(exc)
        assert "self.broker.close_short" in message
        assert "close_contract" in message
    else:
        raise AssertionError("BaseStrategy sandbox should reject self.broker.close_short before backtest")


def test_agent_contract_allows_current_contract_api() -> None:
    strategy_code = '''
from app.core.execution.base_strategy import BaseStrategy, BarData


class TestCurrentContractApiStrategy(BaseStrategy):
    async def on_bar(self, bar: BarData) -> None:
        position = await self.get_contract_position(bar.symbol, "short")
        stop_loss_price = float(bar.close) * 1.005
        take_profit_price = float(bar.close) * 0.99
        if position and float(bar.high) >= stop_loss_price:
            await self.close_contract(bar.symbol, "short", ratio=1.0, price=stop_loss_price)
            return
        if position and float(bar.low) <= take_profit_price:
            await self.close_contract(bar.symbol, "short", ratio=1.0, price=take_profit_price)
            return
        if position:
            return
        await self.open_contract(bar.symbol, "short", 1000.0, leverage=2.0)
'''

    validate_base_strategy_contract(strategy_code)


def test_agent_contract_rejects_contract_strategy_without_stop_loss_and_take_profit() -> None:
    strategy_code = '''
from app.core.execution.base_strategy import BaseStrategy, BarData


class TestUnprotectedContractStrategy(BaseStrategy):
    async def on_bar(self, bar: BarData) -> None:
        await self.open_contract(bar.symbol, "long", 100.0, leverage=2.0)
        await self.close_contract(bar.symbol, "long", ratio=1.0)
'''

    try:
        validate_base_strategy_contract(strategy_code)
    except CodeSafetyError as exc:
        message = str(exc)
        assert "止损" in message
        assert "止盈" in message
    else:
        raise AssertionError("contract strategy validation must reject missing exit protection")
