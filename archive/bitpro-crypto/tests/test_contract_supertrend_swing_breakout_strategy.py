import asyncio
import sys
from datetime import datetime
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, OrderResult, StrategyState
from app.strategies.contract_supertrend_swing_breakout_strategy import (
    ContractSupertrendSwingBreakoutStrategy,
    confirmed_swing_levels,
)


class FakeContractBroker:
    def __init__(self, equity: float = 100.0):
        self.equity = equity
        self.positions = {}
        self.orders = []

    async def open_contract(self, symbol: str, side: str, notional_usdt: float, leverage=None, price=None):
        self.orders.append(
            {
                "action": "open",
                "symbol": symbol,
                "side": side,
                "notional": notional_usdt,
                "leverage": leverage,
                "price": price,
            }
        )
        self.positions[(symbol, side)] = {
            "symbol": symbol,
            "pos_side": side,
            "entry_price": price,
            "mark_price": price,
            "contracts": 1.0,
            "notional_usdt": notional_usdt,
        }
        return OrderResult({"status": "filled", "side": side, "notional_usdt": notional_usdt})

    async def close_contract(self, symbol: str, side: str, ratio: float = 1.0, contracts=None, price=None):
        self.orders.append({"action": "close", "symbol": symbol, "side": side, "ratio": ratio, "price": price})
        self.positions.pop((symbol, side), None)
        return OrderResult({"status": "filled", "side": side, "ratio": ratio})

    async def get_contract_position(self, symbol: str, side: str):
        return self.positions.get((symbol, side))


def make_state() -> StrategyState:
    return StrategyState(
        strategy_id=901,
        name="supertrend swing",
        exchange="okx",
        symbols=["SOL/USDT:USDT"],
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 100.0},
    )


def make_bar(symbol: str, open_: float, high: float, low: float, close: float, index: int) -> BarData:
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="15m",
        timestamp=1_800_000_000_000 + index * 900_000,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=10_000.0,
    )


def strategy_config(**overrides):
    cfg = {
        "market_type": "swap",
        "trade_symbols": ["SOL/USDT:USDT"],
        "initial_capital": 100,
        "trade_notional_usdt": 50,
        "max_total_notional_pct": 1.5,
        "min_order_notional_usdt": 0.5,
        "leverage": 5,
        "swing_lookback_bars": 1,
        "swing_confirm_bars": 1,
        "efficiency_window": 3,
        "min_efficiency_ratio": 0.05,
        "atr_window": 2,
        "supertrend_factor": 0.1,
        "initial_trailing_atr_mult": 1.0,
        "max_trailing_atr_mult": 1.5,
        "trailing_relax_bars": 4,
        "min_stop_pct": 0.001,
        "allow_short": True,
        "reversal_exit": True,
    }
    cfg.update(overrides)
    return cfg


def test_confirmed_swing_levels_ignore_unconfirmed_current_pivot():
    bars = [
        make_bar("SOL/USDT:USDT", 100, 101, 99, 100, 0),
        make_bar("SOL/USDT:USDT", 101, 103, 100, 102, 1),
        make_bar("SOL/USDT:USDT", 102, 102, 100, 101, 2),
        make_bar("SOL/USDT:USDT", 101, 104, 100, 103, 3),
    ]

    levels = confirmed_swing_levels(bars, lookback_bars=1, confirm_bars=1)

    assert levels.swing_high == pytest.approx(103)
    assert levels.swing_low is None

    levels = confirmed_swing_levels(
        [*bars, make_bar("SOL/USDT:USDT", 103, 103.2, 101, 102, 4)],
        lookback_bars=1,
        confirm_bars=1,
    )

    assert levels.swing_high == pytest.approx(104)


def test_supertrend_swing_breakout_opens_after_confirmed_breakout():
    broker = FakeContractBroker(equity=100.0)
    strategy = ContractSupertrendSwingBreakoutStrategy(make_state(), broker)
    strategy.set_config(strategy_config())
    asyncio.run(strategy.on_init())

    bars = [
        make_bar("SOL/USDT:USDT", 100, 101, 99, 100, 0),
        make_bar("SOL/USDT:USDT", 100, 103, 99.5, 102, 1),
        make_bar("SOL/USDT:USDT", 102, 102, 99, 101, 2),
        make_bar("SOL/USDT:USDT", 101, 102.5, 100.5, 102, 3),
        make_bar("SOL/USDT:USDT", 102, 105, 101.8, 104.5, 4),
    ]
    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["side"] == "long"
    assert broker.orders[-1]["notional"] == pytest.approx(50)
    assert ("SOL/USDT:USDT", "long") in strategy._position_state


def test_supertrend_swing_breakout_requires_atr_buffer_beyond_swing():
    broker = FakeContractBroker(equity=100.0)
    strategy = ContractSupertrendSwingBreakoutStrategy(make_state(), broker)
    strategy.set_config(
        strategy_config(
            breakout_atr_buffer=1.0,
            min_efficiency_ratio=0.01,
            supertrend_factor=0.1,
        )
    )
    asyncio.run(strategy.on_init())

    bars = [
        make_bar("SOL/USDT:USDT", 100, 101, 99, 100, 0),
        make_bar("SOL/USDT:USDT", 100, 103, 99.5, 102, 1),
        make_bar("SOL/USDT:USDT", 102, 102, 99, 101, 2),
        make_bar("SOL/USDT:USDT", 101, 102.5, 100.5, 102, 3),
        make_bar("SOL/USDT:USDT", 102, 103.4, 101.8, 103.2, 4),
    ]
    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders == []


def test_supertrend_swing_breakout_cools_down_after_close():
    broker = FakeContractBroker(equity=100.0)
    strategy = ContractSupertrendSwingBreakoutStrategy(make_state(), broker)
    strategy.set_config(strategy_config(cooldown_bars=3))
    asyncio.run(strategy.on_init())

    setup_bars = [
        make_bar("SOL/USDT:USDT", 100, 101, 99, 100, 0),
        make_bar("SOL/USDT:USDT", 100, 103, 99.5, 102, 1),
        make_bar("SOL/USDT:USDT", 102, 102, 99, 101, 2),
        make_bar("SOL/USDT:USDT", 101, 102.5, 100.5, 102, 3),
        make_bar("SOL/USDT:USDT", 102, 105, 101.8, 104.5, 4),
    ]
    for bar in setup_bars:
        asyncio.run(strategy.on_bar(bar))

    key = ("SOL/USDT:USDT", "long")
    strategy._position_state[key]["trail_stop"] = 103.7
    strategy._position_state[key]["extreme_price"] = 105.0
    asyncio.run(strategy.on_bar(make_bar("SOL/USDT:USDT", 104.5, 105, 103.2, 103.5, 5)))

    assert strategy._cooldown_until_bar["SOL/USDT:USDT"] > strategy._bar_counts["SOL/USDT:USDT"]
    close_count = len([order for order in broker.orders if order["action"] == "close"])
    asyncio.run(strategy.on_bar(make_bar("SOL/USDT:USDT", 103.5, 106.5, 103.2, 106.0, 6)))

    assert len([order for order in broker.orders if order["action"] == "close"]) == close_count
    assert broker.orders[-1]["action"] == "close"


def test_supertrend_swing_breakout_ema_slope_filter_blocks_flat_breakout():
    broker = FakeContractBroker(equity=100.0)
    strategy = ContractSupertrendSwingBreakoutStrategy(make_state(), broker)
    strategy.set_config(
        strategy_config(
            trend_ema_window=4,
            trend_ema_slope_bars=2,
            min_trend_ema_slope_atr=1.0,
            min_efficiency_ratio=0.01,
            supertrend_factor=0.1,
        )
    )
    asyncio.run(strategy.on_init())

    bars = [
        make_bar("SOL/USDT:USDT", 100, 101, 99, 100, 0),
        make_bar("SOL/USDT:USDT", 100, 103, 99.5, 102, 1),
        make_bar("SOL/USDT:USDT", 102, 102, 99, 101, 2),
        make_bar("SOL/USDT:USDT", 101, 102.5, 100.5, 102, 3),
        make_bar("SOL/USDT:USDT", 102, 105, 101.8, 104.5, 4),
    ]
    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders == []


def test_supertrend_swing_breakout_closes_when_trailing_stop_is_touched():
    broker = FakeContractBroker(equity=100.0)
    strategy = ContractSupertrendSwingBreakoutStrategy(make_state(), broker)
    strategy.set_config(strategy_config())
    asyncio.run(strategy.on_init())

    setup_bars = [
        make_bar("SOL/USDT:USDT", 100, 101, 99, 100, 0),
        make_bar("SOL/USDT:USDT", 100, 103, 99.5, 102, 1),
        make_bar("SOL/USDT:USDT", 102, 102, 99, 101, 2),
        make_bar("SOL/USDT:USDT", 101, 102.5, 100.5, 102, 3),
        make_bar("SOL/USDT:USDT", 102, 105, 101.8, 104.5, 4),
    ]
    for bar in setup_bars:
        asyncio.run(strategy.on_bar(bar))

    key = ("SOL/USDT:USDT", "long")
    strategy._position_state[key]["trail_stop"] = 103.7
    strategy._position_state[key]["extreme_price"] = 105.0

    asyncio.run(strategy.on_bar(make_bar("SOL/USDT:USDT", 104.5, 105, 103.2, 103.5, 5)))

    assert {"action": "close", "symbol": "SOL/USDT:USDT", "side": "long", "ratio": 1.0, "price": pytest.approx(103.7)} in broker.orders
    assert key not in strategy._position_state
