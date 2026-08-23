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
from app.strategies.contract_volatility_compression_breakout_strategy import (
    ContractVolatilityCompressionBreakoutStrategy,
    atr_compression_ratio,
    previous_breakout_channel,
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


def make_state(symbols=None) -> StrategyState:
    return StrategyState(
        strategy_id=941,
        name="[合约][4H][CTA] Top20 · 波动压缩突破高收益实验 · 100U",
        exchange="okx",
        symbols=symbols or ["BTC/USDT:USDT"],
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 100.0},
    )


def make_bar(symbol: str, open_: float, high: float, low: float, close: float, index: int, volume: float = 100.0) -> BarData:
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="4h",
        timestamp=1_900_000_000_000 + index * 14_400_000,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def strategy_config(**overrides):
    cfg = {
        "market_type": "swap",
        "trade_symbols": ["BTC/USDT:USDT"],
        "initial_capital": 100,
        "trade_notional_usdt": 60,
        "trade_notional_pct": 0.6,
        "max_total_notional_pct": 1.2,
        "min_order_notional_usdt": 0.5,
        "leverage": 8,
        "max_leverage": 8,
        "warmup_bars": 0,
        "history_limit": 120,
        "compression_window": 3,
        "compression_baseline_window": 8,
        "max_compression_atr_ratio": 0.45,
        "breakout_lookback_bars": 3,
        "atr_window": 3,
        "breakout_atr_buffer": 0.1,
        "volume_window": 3,
        "min_volume_ratio": 1.2,
        "require_volume_confirmation": True,
        "trend_ema_window": 0,
        "initial_stop_atr_mult": 1.2,
        "trailing_atr_mult": 1.0,
        "min_stop_pct": 0.001,
        "failed_breakout_exit_bars": 2,
        "failure_buffer_atr": 0.1,
        "max_holding_bars": 12,
        "cooldown_bars": 2,
        "max_positions": 2,
        "allow_short": True,
        "reversal_exit": True,
    }
    cfg.update(overrides)
    return cfg


def compression_setup(symbol="BTC/USDT:USDT"):
    bars = [
        make_bar(symbol, 100, 103, 97, 100, 0, 140),
        make_bar(symbol, 100, 102.8, 97.2, 99.8, 1, 140),
        make_bar(symbol, 99.8, 103, 97.0, 100.2, 2, 135),
        make_bar(symbol, 100.2, 102.7, 97.5, 99.9, 3, 135),
        make_bar(symbol, 99.9, 102.9, 97.1, 100.1, 4, 130),
        make_bar(symbol, 100.1, 102.6, 97.4, 100.0, 5, 130),
        make_bar(symbol, 100.0, 100.30, 99.70, 100.0, 6, 100),
        make_bar(symbol, 100.0, 100.28, 99.72, 100.05, 7, 100),
        make_bar(symbol, 100.05, 100.32, 99.74, 100.02, 8, 100),
        make_bar(symbol, 100.02, 100.30, 99.76, 100.04, 9, 100),
    ]
    return bars


def test_previous_breakout_channel_excludes_current_signal_bar():
    bars = compression_setup()
    bars.append(make_bar("BTC/USDT:USDT", 100.04, 104.0, 99.8, 103.2, 10, 220))

    channel = previous_breakout_channel(bars, lookback_bars=3)

    assert channel.high == pytest.approx(100.32)
    assert channel.low == pytest.approx(99.72)


def test_atr_compression_ratio_detects_prior_squeeze():
    bars = compression_setup()

    ratio = atr_compression_ratio(bars, compression_window=3, baseline_window=8)

    assert ratio is not None
    assert ratio < 0.45


def test_volatility_compression_breakout_opens_long_after_squeeze_breakout():
    broker = FakeContractBroker(equity=100.0)
    strategy = ContractVolatilityCompressionBreakoutStrategy(make_state(), broker)
    strategy.set_config(strategy_config())
    asyncio.run(strategy.on_init())

    bars = compression_setup()
    bars.append(make_bar("BTC/USDT:USDT", 100.04, 102.8, 99.9, 102.2, 10, 240))
    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["side"] == "long"
    assert broker.orders[-1]["symbol"] == "BTC/USDT:USDT"
    assert broker.orders[-1]["notional"] == pytest.approx(60)
    assert broker.orders[-1]["leverage"] == pytest.approx(8)
    assert ("BTC/USDT:USDT", "long") in strategy._position_state


def test_volatility_compression_breakout_requires_real_compression():
    broker = FakeContractBroker(equity=100.0)
    strategy = ContractVolatilityCompressionBreakoutStrategy(make_state(), broker)
    strategy.set_config(strategy_config())
    asyncio.run(strategy.on_init())

    bars = [
        make_bar("BTC/USDT:USDT", 100, 101.0, 99.0, 100.0, 0, 100),
        make_bar("BTC/USDT:USDT", 100, 101.1, 99.1, 100.1, 1, 100),
        make_bar("BTC/USDT:USDT", 100.1, 101.2, 99.2, 100.0, 2, 100),
        make_bar("BTC/USDT:USDT", 100, 101.0, 99.0, 100.0, 3, 100),
        make_bar("BTC/USDT:USDT", 100, 101.0, 99.1, 100.0, 4, 100),
        make_bar("BTC/USDT:USDT", 100, 101.2, 99.0, 100.1, 5, 100),
        make_bar("BTC/USDT:USDT", 100.1, 101.1, 99.2, 100.0, 6, 100),
        make_bar("BTC/USDT:USDT", 100, 101.2, 99.0, 100.1, 7, 100),
        make_bar("BTC/USDT:USDT", 100.1, 101.1, 99.1, 100.0, 8, 100),
        make_bar("BTC/USDT:USDT", 100, 101.2, 99.0, 100.1, 9, 100),
        make_bar("BTC/USDT:USDT", 100.1, 103.0, 99.8, 102.4, 10, 250),
    ]
    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders == []


def test_volatility_compression_breakout_requires_volume_confirmation():
    broker = FakeContractBroker(equity=100.0)
    strategy = ContractVolatilityCompressionBreakoutStrategy(make_state(), broker)
    strategy.set_config(strategy_config())
    asyncio.run(strategy.on_init())

    bars = compression_setup()
    bars.append(make_bar("BTC/USDT:USDT", 100.04, 102.8, 99.9, 102.2, 10, 110))
    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders == []


def test_volatility_compression_breakout_opens_short_on_breakdown():
    broker = FakeContractBroker(equity=100.0)
    strategy = ContractVolatilityCompressionBreakoutStrategy(make_state(), broker)
    strategy.set_config(strategy_config())
    asyncio.run(strategy.on_init())

    bars = compression_setup()
    bars.append(make_bar("BTC/USDT:USDT", 100.04, 100.2, 97.4, 97.8, 10, 240))
    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders[-1]["action"] == "open"
    assert broker.orders[-1]["side"] == "short"
    assert ("BTC/USDT:USDT", "short") in strategy._position_state


def test_volatility_compression_breakout_closes_failed_breakout():
    broker = FakeContractBroker(equity=100.0)
    strategy = ContractVolatilityCompressionBreakoutStrategy(make_state(), broker)
    strategy.set_config(strategy_config(failed_breakout_exit_bars=1))
    asyncio.run(strategy.on_init())

    bars = compression_setup()
    bars.append(make_bar("BTC/USDT:USDT", 100.04, 102.8, 99.9, 102.2, 10, 240))
    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    asyncio.run(strategy.on_bar(make_bar("BTC/USDT:USDT", 102.2, 102.4, 100.0, 100.1, 11, 130)))

    assert broker.orders[-1]["action"] == "close"
    assert broker.orders[-1]["side"] == "long"
    assert ("BTC/USDT:USDT", "long") not in strategy._position_state


def test_volatility_compression_breakout_enforces_portfolio_position_cap():
    broker = FakeContractBroker(equity=100.0)
    broker.positions[("BTC/USDT:USDT", "long")] = {
        "symbol": "BTC/USDT:USDT",
        "pos_side": "long",
        "entry_price": 102.0,
        "mark_price": 102.0,
        "contracts": 1.0,
        "notional_usdt": 60.0,
    }
    strategy = ContractVolatilityCompressionBreakoutStrategy(
        make_state(["BTC/USDT:USDT", "ETH/USDT:USDT"]),
        broker,
    )
    strategy.set_config(strategy_config(trade_symbols=["BTC/USDT:USDT", "ETH/USDT:USDT"], max_positions=1))
    asyncio.run(strategy.on_init())

    bars = compression_setup("ETH/USDT:USDT")
    bars.append(make_bar("ETH/USDT:USDT", 100.04, 102.8, 99.9, 102.2, 10, 240))
    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    assert [order for order in broker.orders if order["action"] == "open"] == []
