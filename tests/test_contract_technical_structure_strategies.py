import asyncio
import sys
from datetime import datetime
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, OrderResult, StrategyState, TickData
from app.strategies.contract_fvg_liquidity_sweep_strategy import ContractFvgLiquiditySweepStrategy
from app.strategies.contract_order_flow_breakout_strategy import ContractOrderFlowBreakoutStrategy
from app.strategies.contract_vwap_volume_profile_strategy import (
    ContractVwapVolumeProfileStrategy,
    highest_volume_zone,
    volume_weighted_average_price,
)


SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]


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


def make_state(name: str, symbols=None) -> StrategyState:
    return StrategyState(
        strategy_id=1900,
        name=name,
        exchange="okx",
        symbols=symbols or SYMBOLS,
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 100.0},
    )


def make_bar(
    index: int,
    *,
    symbol: str = "BTC/USDT:USDT",
    timeframe: str = "1h",
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float = 100.0,
) -> BarData:
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe=timeframe,
        timestamp=1_800_000_000_000 + index * 3_600_000,
        open=float(open_price),
        high=float(high),
        low=float(low),
        close=float(close),
        volume=float(volume),
    )


def init_vwap_strategy(config=None, broker=None) -> tuple[ContractVwapVolumeProfileStrategy, FakeContractBroker]:
    broker = broker or FakeContractBroker()
    strategy = ContractVwapVolumeProfileStrategy(
        make_state("[合约][1H][CTA] BTC/ETH/SOL · VWAP成交量分布趋势 · 100U"),
        broker,
    )
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": SYMBOLS,
            "timeframe": "1h",
            "vwap_window": 4,
            "profile_window": 4,
            "profile_bucket_pct": 0.01,
            "fast_ema_window": 2,
            "slow_ema_window": 3,
            "atr_window": 2,
            "risk_reward_ratio": 1.2,
            "stop_buffer_atr": 0.5,
            "max_holding_bars": 12,
            "trade_notional_pct": 1.0,
            "max_total_notional_pct": 1.0,
            "min_order_notional_usdt": 0.5,
            "leverage": 3,
            "allow_short": True,
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy, broker


def init_fvg_sweep_strategy(config=None, broker=None) -> tuple[ContractFvgLiquiditySweepStrategy, FakeContractBroker]:
    broker = broker or FakeContractBroker()
    strategy = ContractFvgLiquiditySweepStrategy(
        make_state("[合约][15M][CTA] BTC/ETH/SOL · FVG扫流动性结构 · 100U"),
        broker,
    )
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": SYMBOLS,
            "timeframe": "15m",
            "sweep_lookback_bars": 3,
            "sweep_pct": 0.005,
            "sweep_to_fvg_max_bars": 3,
            "zone_max_age_bars": 6,
            "entry_reclaim_ratio": 0.5,
            "use_ema_filter": False,
            "atr_window": 2,
            "min_fvg_gap_pct": 0.0,
            "min_fvg_gap_atr": 0.0,
            "risk_reward_ratio": 1.2,
            "stop_buffer_atr": 0.5,
            "max_holding_bars": 12,
            "trade_notional_pct": 1.0,
            "max_total_notional_pct": 1.0,
            "min_order_notional_usdt": 0.5,
            "leverage": 3,
            "allow_short": True,
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy, broker


def init_order_flow_strategy(config=None, broker=None) -> tuple[ContractOrderFlowBreakoutStrategy, FakeContractBroker]:
    broker = broker or FakeContractBroker()
    strategy = ContractOrderFlowBreakoutStrategy(
        make_state("[合约][5M][CTA] BTC/ETH/SOL · Order Flow短线确认 · 100U"),
        broker,
    )
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": SYMBOLS,
            "timeframe": "5m",
            "breakout_lookback_bars": 4,
            "breakout_buffer_pct": 0.0001,
            "retest_tolerance_pct": 0.002,
            "max_setup_age_bars": 2,
            "min_delta": 100.0,
            "min_imbalance": 0.15,
            "min_depth_ratio": 1.2,
            "max_spread_bps": 5.0,
            "atr_window": 2,
            "risk_reward_ratio": 1.2,
            "stop_buffer_atr": 0.5,
            "max_holding_bars": 12,
            "trade_notional_pct": 1.0,
            "max_total_notional_pct": 1.0,
            "min_order_notional_usdt": 0.5,
            "leverage": 3,
            "allow_short": True,
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy, broker


def test_vwap_helpers_use_real_ohlcv_volume_not_synthetic_ticks():
    bars = [
        make_bar(0, open_price=100, high=101, low=99, close=100, volume=100),
        make_bar(1, open_price=100, high=101.5, low=99.5, close=101, volume=200),
        make_bar(2, open_price=101, high=102, low=100.5, close=101, volume=300),
        make_bar(3, open_price=101, high=102, low=100.5, close=101, volume=400),
    ]

    vwap = volume_weighted_average_price(bars)
    zone = highest_volume_zone(bars, bucket_pct=0.01)

    assert vwap == pytest.approx(100.95)
    assert zone is not None
    assert zone.volume == pytest.approx(900.0)
    assert zone.lower <= 101.0 <= zone.upper


def test_vwap_strategy_enters_long_after_vwap_reclaim_and_volume_zone_retest():
    strategy, broker = init_vwap_strategy()
    bars = [
        make_bar(0, open_price=100, high=101, low=99, close=100, volume=100),
        make_bar(1, open_price=100, high=101.5, low=99.5, close=101, volume=160),
        make_bar(2, open_price=101, high=102, low=100.5, close=101.1, volume=300),
        make_bar(3, open_price=101.1, high=102.0, low=100.7, close=101.2, volume=280),
        make_bar(4, open_price=101.2, high=102.6, low=100.8, close=102.1, volume=180),
    ]

    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders
    order = broker.orders[-1]
    assert order["action"] == "open"
    assert order["side"] == "long"
    assert order["symbol"] == "BTC/USDT:USDT"
    assert order["price"] == pytest.approx(102.1)
    assert order["notional"] == pytest.approx(100.0)
    assert order["leverage"] == 3


def test_vwap_strategy_profit_protection_closes_after_peak_pullback():
    strategy, broker = init_vwap_strategy(
        {
            "profit_protection_enabled": True,
            "fixed_take_profit_enabled": False,
            "break_even_at_r": 0.5,
            "break_even_buffer_bps": 5,
            "profit_trailing_start_r": 1.0,
            "profit_peak_pullback_pct": 0.35,
            "profit_tighten_at_r": 2.0,
            "profit_tight_pullback_pct": 0.2,
        }
    )
    bars = [
        make_bar(0, open_price=100, high=101, low=99, close=100, volume=100),
        make_bar(1, open_price=100, high=101.5, low=99.5, close=101, volume=160),
        make_bar(2, open_price=101, high=102, low=100.5, close=101.1, volume=300),
        make_bar(3, open_price=101.1, high=102.0, low=100.7, close=101.2, volume=280),
        make_bar(4, open_price=101.2, high=102.6, low=100.8, close=102.1, volume=180),
        make_bar(5, open_price=102.1, high=112.0, low=101.8, close=111.0, volume=220),
        make_bar(6, open_price=111.0, high=112.5, low=104.8, close=105.0, volume=240),
    ]

    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    assert [order["action"] for order in broker.orders] == ["open", "close"]
    assert broker.orders[-1]["side"] == "long"
    assert broker.orders[-1]["price"] == pytest.approx(105.0)


def test_fvg_sweep_strategy_requires_sweep_before_confirmed_fvg_retest():
    strategy, broker = init_fvg_sweep_strategy()
    bars = [
        make_bar(0, timeframe="15m", open_price=100, high=101, low=98, close=100),
        make_bar(1, timeframe="15m", open_price=100, high=102, low=99, close=101),
        make_bar(2, timeframe="15m", open_price=101, high=103, low=100, close=102),
        make_bar(3, timeframe="15m", open_price=102, high=100.5, low=97, close=99.5),
        make_bar(4, timeframe="15m", open_price=99.5, high=104, low=99, close=103),
        make_bar(5, timeframe="15m", open_price=103, high=105, low=101.5, close=104),
        make_bar(6, timeframe="15m", open_price=104, high=104, low=101.0, close=102.5),
    ]

    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders
    order = broker.orders[-1]
    assert order["action"] == "open"
    assert order["side"] == "long"
    assert order["price"] == pytest.approx(102.5)


def test_fvg_sweep_strategy_does_not_enter_when_liquidity_sweep_is_missing():
    strategy, broker = init_fvg_sweep_strategy()
    bars = [
        make_bar(0, timeframe="15m", open_price=100, high=101, low=98, close=100),
        make_bar(1, timeframe="15m", open_price=100, high=102, low=99, close=101),
        make_bar(2, timeframe="15m", open_price=101, high=103, low=100, close=102),
        make_bar(3, timeframe="15m", open_price=102, high=100.5, low=98.5, close=99.5),
        make_bar(4, timeframe="15m", open_price=99.5, high=104, low=99, close=103),
        make_bar(5, timeframe="15m", open_price=103, high=105, low=101.5, close=104),
        make_bar(6, timeframe="15m", open_price=104, high=104, low=101.0, close=102.5),
    ]

    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders == []


def test_order_flow_strategy_skips_when_real_delta_or_depth_is_missing():
    strategy, broker = init_order_flow_strategy()
    for idx, close in enumerate([100.0, 100.5, 101.0, 101.5]):
        asyncio.run(
            strategy.on_bar(
                make_bar(idx, timeframe="5m", open_price=close - 0.3, high=close + 0.5, low=close - 0.5, close=close)
            )
        )

    asyncio.run(
        strategy.on_tick(
            TickData(
                exchange="okx",
                symbol="BTC/USDT:USDT",
                timestamp=1_800_000_020_000,
                last=102.2,
                bid=102.1,
                ask=102.2,
                bid_depth=100_000,
                ask_depth=60_000,
                spread_bps=1.0,
                imbalance=0.2,
            )
        )
    )
    asyncio.run(
        strategy.on_bar(
            make_bar(4, timeframe="5m", open_price=102.0, high=102.5, low=101.5, close=102.3)
        )
    )

    assert broker.orders == []
    assert strategy.last_skip_reason == "order_flow_data_unavailable"


def test_order_flow_strategy_enters_after_real_breakout_delta_and_retest():
    strategy, broker = init_order_flow_strategy()
    for idx, close in enumerate([100.0, 100.5, 101.0, 101.5]):
        asyncio.run(
            strategy.on_bar(
                make_bar(idx, timeframe="5m", open_price=close - 0.3, high=close + 0.5, low=close - 0.5, close=close)
            )
        )

    asyncio.run(
        strategy.on_tick(
            TickData(
                exchange="okx",
                symbol="BTC/USDT:USDT",
                timestamp=1_800_000_020_000,
                last=102.2,
                bid=102.1,
                ask=102.2,
                volume=10.0,
                bid_depth=120_000,
                ask_depth=70_000,
                spread_bps=1.0,
                imbalance=0.25,
                delta=180.0,
                aggressive_buy_volume=240.0,
                aggressive_sell_volume=60.0,
            )
        )
    )
    asyncio.run(
        strategy.on_bar(
            make_bar(4, timeframe="5m", open_price=102.0, high=102.6, low=101.45, close=102.4)
        )
    )

    assert broker.orders
    order = broker.orders[-1]
    assert order["action"] == "open"
    assert order["side"] == "long"
    assert order["symbol"] == "BTC/USDT:USDT"
    assert order["price"] == pytest.approx(102.4)
