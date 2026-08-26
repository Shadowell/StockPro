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
from app.strategies.contract_fvg_ob_strategy import (
    ContractFvgObStrategy,
    detect_latest_fvg,
    find_order_block_for_fvg,
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
        strategy_id=1801,
        name="[合约][1H][CTA] BTC · FVG/OB结构回踩 · 100U",
        exchange="okx",
        symbols=symbols or ["BTC/USDT:USDT"],
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 100.0},
    )


def make_bar(
    index: int,
    *,
    symbol: str = "BTC/USDT:USDT",
    open_price: float,
    high: float,
    low: float,
    close: float,
) -> BarData:
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="1h",
        timestamp=1_800_000_000_000 + index * 3_600_000,
        open=float(open_price),
        high=float(high),
        low=float(low),
        close=float(close),
        volume=1000.0,
    )


def init_strategy(config=None, broker=None) -> tuple[ContractFvgObStrategy, FakeContractBroker]:
    broker = broker or FakeContractBroker()
    strategy = ContractFvgObStrategy(make_state(), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "timeframe": "1h",
            "ema_window": 2,
            "atr_window": 2,
            "min_fvg_gap_pct": 0.0,
            "min_fvg_gap_atr": 0.0,
            "ob_search_bars": 3,
            "zone_max_age_bars": 6,
            "entry_reclaim_ratio": 0.5,
            "use_ema_filter": False,
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


def test_detect_latest_fvg_uses_three_confirmed_candles():
    bullish = [
        make_bar(0, open_price=100, high=101, low=98, close=99),
        make_bar(1, open_price=99, high=107, low=99, close=106),
        make_bar(2, open_price=106, high=109, low=104, close=108),
    ]
    zone = detect_latest_fvg(bullish, min_gap_pct=0.0, min_gap_atr=0.0, atr_value=2.0)

    assert zone is not None
    assert zone.direction == "bullish"
    assert zone.lower == pytest.approx(101.0)
    assert zone.upper == pytest.approx(104.0)
    assert zone.created_index == 2
    assert zone.midpoint == pytest.approx(102.5)

    bearish = [
        make_bar(0, open_price=110, high=112, low=108, close=111),
        make_bar(1, open_price=111, high=111, low=101, close=102),
        make_bar(2, open_price=102, high=105, low=99, close=100),
    ]
    zone = detect_latest_fvg(bearish, min_gap_pct=0.0, min_gap_atr=0.0, atr_value=2.0)

    assert zone is not None
    assert zone.direction == "bearish"
    assert zone.lower == pytest.approx(105.0)
    assert zone.upper == pytest.approx(108.0)
    assert zone.created_index == 2
    assert zone.midpoint == pytest.approx(106.5)


def test_order_block_uses_last_opposite_body_before_confirmed_fvg():
    bars = [
        make_bar(0, open_price=100, high=101, low=98, close=99),
        make_bar(1, open_price=99, high=107, low=99, close=106),
        make_bar(2, open_price=106, high=109, low=104, close=108),
    ]
    fvg = detect_latest_fvg(bars, min_gap_pct=0.0, min_gap_atr=0.0, atr_value=2.0)
    ob = find_order_block_for_fvg(bars, fvg, search_bars=3, use_body=True)

    assert ob is not None
    assert ob.lower == pytest.approx(99.0)
    assert ob.upper == pytest.approx(100.0)
    assert ob.source_index == 0


def test_strategy_enters_long_after_fvg_retest_using_real_close_price():
    strategy, broker = init_strategy()
    bars = [
        make_bar(0, open_price=100, high=101, low=98, close=99),
        make_bar(1, open_price=99, high=107, low=99, close=106),
        make_bar(2, open_price=106, high=109, low=104, close=108),
        make_bar(3, open_price=108, high=108, low=103, close=105),
    ]

    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders
    order = broker.orders[-1]
    assert order["action"] == "open"
    assert order["side"] == "long"
    assert order["symbol"] == "BTC/USDT:USDT"
    assert order["price"] == pytest.approx(105.0)
    assert order["notional"] == pytest.approx(50.0)
    assert order["leverage"] == 3
