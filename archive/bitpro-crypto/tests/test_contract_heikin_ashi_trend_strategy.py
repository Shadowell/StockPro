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
from app.strategies.contract_heikin_ashi_trend_strategy import (
    ContractHeikinAshiTrendStrategy,
    heikin_ashi_candles,
)


class FakeContractBroker:
    def __init__(self, equity: float = 100.0):
        self.equity = equity
        self.positions = {}
        self.orders = []

    async def open_contract(self, symbol: str, side: str, notional_usdt: float, leverage=None, price=None) -> OrderResult:
        self.orders.append(
            {
                "action": "open",
                "symbol": symbol,
                "side": side,
                "notional": float(notional_usdt),
                "leverage": leverage,
                "price": price,
            }
        )
        self.positions[(symbol, side)] = {
            "symbol": symbol,
            "pos_side": side,
            "entry_price": price,
            "mark_price": price,
            "base_qty": float(notional_usdt) / float(price),
            "notional_usdt": float(notional_usdt),
            "leverage": leverage,
        }
        return OrderResult({"status": "filled", "side": side, "notional_usdt": notional_usdt, "price": price})

    async def close_contract(self, symbol: str, side: str, ratio: float = 1.0, contracts=None, price=None) -> OrderResult:
        self.orders.append({"action": "close", "symbol": symbol, "side": side, "ratio": ratio, "price": price})
        self.positions.pop((symbol, side), None)
        return OrderResult({"status": "filled", "side": side, "ratio": ratio, "price": price})

    async def get_contract_position(self, symbol: str, side: str):
        return self.positions.get((symbol, side))


def make_state(symbols=None) -> StrategyState:
    return StrategyState(
        strategy_id=1701,
        name="[合约][15M][CTA] BTC · Heikin Ashi趋势跟踪 · 100U",
        exchange="okx",
        symbols=symbols or ["BTC/USDT:USDT"],
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 100.0},
    )


def make_bar(close: float, index: int, *, open_price: float | None = None, spread: float = 1.0) -> BarData:
    open_value = float(open_price if open_price is not None else close - 0.4)
    return BarData(
        exchange="okx",
        symbol="BTC/USDT:USDT",
        timeframe="15m",
        timestamp=1_800_000_000_000 + index * 900_000,
        open=open_value,
        high=max(open_value, close) + spread,
        low=min(open_value, close) - spread,
        close=float(close),
        volume=1000.0,
    )


def init_strategy(config=None, broker=None) -> tuple[ContractHeikinAshiTrendStrategy, FakeContractBroker]:
    broker = broker or FakeContractBroker()
    strategy = ContractHeikinAshiTrendStrategy(make_state(), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "ema_window": 4,
            "atr_window": 2,
            "stoch_rsi_period": 2,
            "stoch_rsi_stoch_period": 2,
            "stoch_rsi_k_period": 1,
            "stoch_rsi_d_period": 1,
            "stoch_rsi_oversold": 45,
            "stoch_rsi_overbought": 55,
            "min_ha_body_ratio": 0.0,
            "risk_reward_ratio": 1.5,
            "atr_stop_mult": 1.0,
            "trade_notional_pct": 0.5,
            "max_total_notional_pct": 0.5,
            "min_order_notional_usdt": 0.5,
            "leverage": 3,
            "allow_short": True,
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy, broker


def run_bars(strategy: ContractHeikinAshiTrendStrategy, values: list[float]) -> None:
    for index, close in enumerate(values):
        asyncio.run(strategy.on_bar(make_bar(close, index)))


def test_heikin_ashi_candles_are_signal_only_derived_from_real_ohlc():
    candles = heikin_ashi_candles(
        [
            make_bar(102.0, 0, open_price=100.0, spread=4.0),
            make_bar(105.0, 1, open_price=101.0, spread=3.0),
        ]
    )

    assert candles[0]["close"] == pytest.approx((100.0 + 106.0 + 96.0 + 102.0) / 4.0)
    assert candles[0]["open"] == pytest.approx(101.0)
    assert candles[1]["open"] == pytest.approx((candles[0]["open"] + candles[0]["close"]) / 2.0)
    assert candles[1]["high"] >= candles[1]["close"]
    assert candles[1]["low"] <= candles[1]["open"]


def test_heikin_ashi_trend_opens_long_with_real_close_price():
    strategy, broker = init_strategy()

    run_bars(strategy, [100.0, 101.0, 102.0, 103.0, 104.0, 101.0, 103.0])

    assert broker.orders
    order = broker.orders[-1]
    assert order["action"] == "open"
    assert order["side"] == "long"
    assert order["symbol"] == "BTC/USDT:USDT"
    assert order["price"] == pytest.approx(103.0)
    assert order["notional"] == pytest.approx(50.0)
    assert order["leverage"] == 3


def test_heikin_ashi_trend_closes_long_on_atr_stop():
    strategy, broker = init_strategy({"reversal_exit": False})

    run_bars(strategy, [100.0, 101.0, 102.0, 103.0, 104.0, 101.0, 103.0])
    asyncio.run(strategy.on_bar(make_bar(99.0, 7)))

    assert broker.orders[-1]["action"] == "close"
    assert broker.orders[-1]["side"] == "long"
    assert broker.orders[-1]["price"] == pytest.approx(99.0)
