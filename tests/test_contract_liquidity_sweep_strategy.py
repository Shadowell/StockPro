import asyncio
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, OrderResult, StrategyState
from app.strategies.contract_liquidity_sweep_strategy import ContractLiquiditySweepStrategy


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
        strategy_id=1802,
        name="[合约][1H][CTA] DOT · 扫流动性结构回归 · 100U",
        exchange="okx",
        symbols=symbols or ["DOT/USDT:USDT"],
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 100.0},
    )


def make_bar(index: int, *, open_price: float, high: float, low: float, close: float, volume: float = 100.0) -> BarData:
    return BarData(
        exchange="okx",
        symbol="DOT/USDT:USDT",
        timeframe="1h",
        timestamp=1_800_000_000_000 + index * 3_600_000,
        open=float(open_price),
        high=float(high),
        low=float(low),
        close=float(close),
        volume=float(volume),
    )


def init_strategy(config=None, broker=None) -> tuple[ContractLiquiditySweepStrategy, FakeContractBroker]:
    broker = broker or FakeContractBroker()
    strategy = ContractLiquiditySweepStrategy(make_state(), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": ["DOT/USDT:USDT"],
            "timeframe": "1h",
            "sweep_lookback_bars": 3,
            "sweep_pct": 0.01,
            "volume_window": 3,
            "volume_mult": 1.2,
            "trend_filter": "mean_reversion",
            "ema_window": 3,
            "atr_window": 2,
            "risk_reward_ratio": 1.2,
            "stop_buffer_atr": 0.5,
            "max_holding_bars": 2,
            "trade_notional_pct": 1.5,
            "max_total_notional_pct": 1.5,
            "min_order_notional_usdt": 0.5,
            "leverage": 3,
            "allow_short": True,
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy, broker


def test_enters_long_after_confirmed_low_sweep_and_reclaim():
    strategy, broker = init_strategy()
    bars = [
        make_bar(0, open_price=100, high=105, low=98, close=104),
        make_bar(1, open_price=104, high=106, low=99, close=103),
        make_bar(2, open_price=103, high=107, low=100, close=102),
        make_bar(3, open_price=102, high=103, low=96, close=99, volume=300),
    ]

    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders
    order = broker.orders[-1]
    assert order["action"] == "open"
    assert order["side"] == "long"
    assert order["symbol"] == "DOT/USDT:USDT"
    assert order["price"] == 99.0
    assert order["notional"] == 150.0
    assert order["leverage"] == 3


def test_does_not_enter_when_sweep_fails_to_reclaim_prior_low():
    strategy, broker = init_strategy()
    bars = [
        make_bar(0, open_price=100, high=105, low=98, close=104),
        make_bar(1, open_price=104, high=106, low=99, close=103),
        make_bar(2, open_price=103, high=107, low=100, close=102),
        make_bar(3, open_price=102, high=103, low=96, close=97, volume=300),
    ]

    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders == []


def test_enters_short_after_confirmed_high_sweep_and_reclaim():
    strategy, broker = init_strategy()
    bars = [
        make_bar(0, open_price=100, high=105, low=95, close=96),
        make_bar(1, open_price=96, high=106, low=95, close=97),
        make_bar(2, open_price=97, high=107, low=96, close=98),
        make_bar(3, open_price=98, high=110, low=103, close=106, volume=300),
    ]

    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders
    order = broker.orders[-1]
    assert order["action"] == "open"
    assert order["side"] == "short"
    assert order["price"] == 106.0
    assert order["notional"] == 150.0


def test_closes_after_max_holding_bars():
    strategy, broker = init_strategy()
    bars = [
        make_bar(0, open_price=100, high=105, low=98, close=104),
        make_bar(1, open_price=104, high=106, low=99, close=103),
        make_bar(2, open_price=103, high=107, low=100, close=102),
        make_bar(3, open_price=102, high=103, low=96, close=99, volume=300),
        make_bar(4, open_price=99, high=100, low=98, close=99.2, volume=100),
        make_bar(5, open_price=99.2, high=100, low=98.8, close=99.1, volume=100),
    ]

    for bar in bars:
        asyncio.run(strategy.on_bar(bar))

    assert broker.orders[-1]["action"] == "close"
    assert broker.orders[-1]["side"] == "long"
