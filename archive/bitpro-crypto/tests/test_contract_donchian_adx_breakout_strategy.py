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
from app.strategies.contract_donchian_adx_breakout_strategy import (
    ContractDonchianAdxBreakoutStrategy,
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
        strategy_id=926,
        name="[合约][1H][CTA] GRASS · Donchian12/ADX趋势突破 · 100U",
        exchange="okx",
        symbols=["GRASS/USDT:USDT"],
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 100.0},
    )


def make_bar(open_: float, high: float, low: float, close: float, index: int) -> BarData:
    return BarData(
        exchange="okx",
        symbol="GRASS-USDT-SWAP",
        timeframe="1h",
        timestamp=1_800_000_000_000 + index * 3_600_000,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=10_000.0,
    )


def strategy_config(**overrides):
    cfg = {
        "market_type": "swap",
        "trade_symbols": ["GRASS/USDT:USDT"],
        "initial_capital": 100,
        "trade_notional_usdt": 100,
        "max_total_notional_pct": 1.0,
        "min_order_notional_usdt": 0.5,
        "leverage": 5,
        "lookback_bars": 3,
        "atr_window": 2,
        "adx_window": 2,
        "min_adx": 0,
        "breakout_atr_buffer": 0.0,
        "atr_stop_mult": 1.2,
        "trailing_atr_mult": 1.2,
        "exit_fast_ema": 2,
        "exit_slow_ema": 3,
        "cooldown_bars": 0,
        "max_holding_bars": 20,
        "allow_short": True,
        "reversal_exit": True,
    }
    cfg.update(overrides)
    return cfg


def init_strategy(config=None, broker=None):
    broker = broker or FakeContractBroker(equity=100.0)
    strategy = ContractDonchianAdxBreakoutStrategy(make_state(), broker)
    strategy.set_config(strategy_config(**(config or {})))
    asyncio.run(strategy.on_init())
    return strategy, broker


def feed(strategy, bars):
    for bar in bars:
        asyncio.run(strategy.on_bar(bar))


def test_donchian_adx_breakout_opens_long_on_previous_channel_breakout():
    strategy, broker = init_strategy()

    feed(
        strategy,
        [
            make_bar(10.00, 10.20, 9.80, 10.00, 0),
            make_bar(10.00, 10.30, 9.90, 10.10, 1),
            make_bar(10.10, 10.25, 9.95, 10.05, 2),
            make_bar(10.05, 10.80, 10.00, 10.70, 3),
        ],
    )

    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["symbol"] == "GRASS/USDT:USDT"
    assert broker.orders[-1]["side"] == "long"
    assert broker.orders[-1]["notional"] == pytest.approx(100)
    assert broker.orders[-1]["leverage"] == pytest.approx(5)


def test_donchian_adx_breakout_opens_short_when_short_breakout_confirms():
    strategy, broker = init_strategy()

    feed(
        strategy,
        [
            make_bar(10.00, 10.20, 9.80, 10.00, 0),
            make_bar(10.00, 10.10, 9.70, 9.90, 1),
            make_bar(9.90, 10.05, 9.75, 9.85, 2),
            make_bar(9.85, 9.90, 9.20, 9.25, 3),
        ],
    )

    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["symbol"] == "GRASS/USDT:USDT"
    assert broker.orders[-1]["side"] == "short"


def test_donchian_adx_breakout_requires_atr_buffer_beyond_previous_channel():
    strategy, broker = init_strategy({"breakout_atr_buffer": 1.0})

    feed(
        strategy,
        [
            make_bar(10.00, 10.20, 9.80, 10.00, 0),
            make_bar(10.00, 10.30, 9.90, 10.10, 1),
            make_bar(10.10, 10.25, 9.95, 10.05, 2),
            make_bar(10.05, 10.45, 10.00, 10.42, 3),
        ],
    )

    assert broker.orders == []


def test_donchian_adx_breakout_closes_long_when_trailing_stop_is_touched():
    strategy, broker = init_strategy()
    feed(
        strategy,
        [
            make_bar(10.00, 10.20, 9.80, 10.00, 0),
            make_bar(10.00, 10.30, 9.90, 10.10, 1),
            make_bar(10.10, 10.25, 9.95, 10.05, 2),
            make_bar(10.05, 10.80, 10.00, 10.70, 3),
        ],
    )

    key = ("GRASS/USDT:USDT", "long")
    strategy._position_state[key]["trail_stop"] = 10.55
    strategy._position_state[key]["extreme_price"] = 10.80
    asyncio.run(strategy.on_bar(make_bar(10.70, 10.75, 10.50, 10.52, 4)))

    assert {"action": "close", "symbol": "GRASS/USDT:USDT", "side": "long", "ratio": 1.0, "price": pytest.approx(10.55)} in broker.orders
    assert key not in strategy._position_state
