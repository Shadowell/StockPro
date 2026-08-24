import asyncio
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, OrderResult, StrategyState
from app.strategies.contract_daily_target_scalp_strategy import ContractDailyTargetScalpStrategy


class FakeDailyTargetBroker:
    def __init__(self, equity: float = 10.0):
        self.equity = equity
        self.positions = {}
        self.orders = []
        self.next_close_pnl = 0.0

    async def open_contract(self, symbol: str, side: str, notional_usdt: float, leverage=None, price=None) -> OrderResult:
        self.orders.append(
            {
                "action": "open",
                "symbol": symbol,
                "side": side,
                "notional": float(notional_usdt),
                "leverage": float(leverage or 0),
                "price": float(price or 0),
            }
        )
        self.positions[(symbol, side)] = {
            "symbol": symbol,
            "pos_side": side,
            "entry_price": float(price or 0),
            "mark_price": float(price or 0),
            "notional_usdt": float(notional_usdt),
            "leverage": float(leverage or 0),
        }
        return OrderResult({"status": "filled", "side": side, "notional_usdt": float(notional_usdt), "price": price})

    async def close_contract(self, symbol: str, side: str, ratio: float = 1.0, contracts=None, price=None) -> OrderResult:
        pnl = float(self.next_close_pnl)
        self.equity += pnl
        self.next_close_pnl = 0.0
        self.orders.append(
            {
                "action": "close",
                "symbol": symbol,
                "side": side,
                "ratio": float(ratio),
                "price": float(price or 0),
                "realized_pnl": pnl,
            }
        )
        self.positions.pop((symbol, side), None)
        return OrderResult({"status": "filled", "side": side, "ratio": ratio, "price": price, "realized_pnl": pnl})

    async def get_contract_position(self, symbol: str, side: str):
        return self.positions.get((symbol, side))


def make_state() -> StrategyState:
    return StrategyState(
        strategy_id=1901,
        name="[合约][5M][CTA] Top5 · 日目标动量快频 · 10U",
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 10.0},
    )


def make_bar(index: int, close: float, *, day: int = 0, symbol: str = "BTC/USDT:USDT") -> BarData:
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="5m",
        timestamp=1_800_000_000_000 + day * 86_400_000 + index * 300_000,
        open=float(close - 0.1),
        high=float(close + 0.4),
        low=float(close - 0.4),
        close=float(close),
        volume=200.0,
    )


def init_strategy(config=None, broker=None):
    broker = broker or FakeDailyTargetBroker()
    strategy = ContractDailyTargetScalpStrategy(make_state(), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT"],
            "timeframe": "5m",
            "initial_capital": 10,
            "daily_profit_target_usdt": 1.0,
            "daily_loss_limit_usdt": 1.0,
            "trade_notional_usdt": 30.0,
            "max_total_notional_pct": 3.0,
            "min_order_notional_usdt": 1.0,
            "leverage": 20,
            "max_leverage": 20,
            "allow_short": True,
            "fast_window": 2,
            "slow_window": 3,
            "atr_window": 2,
            "momentum_lookback_bars": 1,
            "momentum_threshold_pct": 0.001,
            "atr_stop_mult": 0.5,
            "risk_reward_ratio": 1.0,
            "max_holding_bars": 4,
            "max_daily_trades": 20,
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy, broker


def run_bars(strategy, bars):
    for bar in bars:
        asyncio.run(strategy.on_bar(bar))


def test_enters_long_on_confirmed_fast_momentum_signal():
    strategy, broker = init_strategy()

    run_bars(strategy, [make_bar(0, 100), make_bar(1, 101), make_bar(2, 102), make_bar(3, 104)])

    assert broker.orders
    order = broker.orders[-1]
    assert order["action"] == "open"
    assert order["side"] == "long"
    assert order["notional"] == 30.0
    assert order["leverage"] == 20.0


def test_daily_profit_target_closes_open_position_and_blocks_reentry_same_day():
    strategy, broker = init_strategy()
    run_bars(strategy, [make_bar(0, 100), make_bar(1, 101), make_bar(2, 102), make_bar(3, 104)])
    assert broker.orders[-1]["action"] == "open"

    broker.equity = 11.05
    asyncio.run(strategy.on_bar(make_bar(4, 105)))
    assert broker.orders[-1]["action"] == "close"
    assert broker.orders[-1]["side"] == "long"

    open_count = sum(1 for order in broker.orders if order["action"] == "open")
    run_bars(strategy, [make_bar(5, 106), make_bar(6, 107), make_bar(7, 108)])
    assert sum(1 for order in broker.orders if order["action"] == "open") == open_count


def test_daily_loss_limit_blocks_new_entries_same_day():
    strategy, broker = init_strategy()
    run_bars(strategy, [make_bar(0, 100), make_bar(1, 100.2), make_bar(2, 100.4)])

    broker.equity = 8.95
    run_bars(strategy, [make_bar(3, 102), make_bar(4, 103), make_bar(5, 104)])

    assert broker.orders == []


def test_next_utc_day_resets_daily_stop_state():
    strategy, broker = init_strategy()
    run_bars(strategy, [make_bar(0, 100), make_bar(1, 101), make_bar(2, 102), make_bar(3, 104)])
    broker.equity = 11.1
    asyncio.run(strategy.on_bar(make_bar(4, 105)))
    assert broker.orders[-1]["action"] == "close"

    open_count = sum(1 for order in broker.orders if order["action"] == "open")
    broker.equity = 11.1
    asyncio.run(strategy.on_bar(make_bar(0, 106, day=1)))

    assert sum(1 for order in broker.orders if order["action"] == "open") == open_count + 1


def test_daily_stop_does_not_reuse_current_bar_price_for_other_symbols():
    strategy, broker = init_strategy({"trade_symbols": ["BTC/USDT:USDT", "ETH/USDT:USDT"]})
    broker.positions[("BTC/USDT:USDT", "long")] = {"notional_usdt": 30, "entry_price": 100}
    broker.positions[("ETH/USDT:USDT", "short")] = {"notional_usdt": 30, "entry_price": 2000}

    asyncio.run(strategy.on_bar(make_bar(0, 100)))
    broker.equity = 11.2
    asyncio.run(strategy.on_bar(make_bar(1, 101)))

    closes = [order for order in broker.orders if order["action"] == "close"]
    assert closes[0]["symbol"] == "BTC/USDT:USDT"
    assert closes[0]["price"] == 101.0
    assert closes[1]["symbol"] == "ETH/USDT:USDT"
    assert closes[1]["price"] == 0.0
