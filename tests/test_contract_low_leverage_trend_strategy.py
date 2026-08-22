import asyncio
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, OrderResult, StrategyState
from app.strategies.contract_low_leverage_trend_strategy import ContractLowLeverageTrendStrategy


class FakeLowLeverageBroker:
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
        strategy_id=1911,
        name="[合约][1H][CTA] ETH · 低杠杆稳健趋势跟踪 · 10U",
        exchange="okx",
        symbols=["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"],
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 10.0},
    )


def make_bar(index: int, close: float, *, day: int = 0, symbol: str = "BTC/USDT:USDT") -> BarData:
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="1h",
        timestamp=1_800_000_000_000 + day * 86_400_000 + index * 3_600_000,
        open=float(close - 0.4),
        high=float(close + 1.0),
        low=float(close - 1.0),
        close=float(close),
        volume=500.0,
    )


def init_strategy(config=None, broker=None):
    broker = broker or FakeLowLeverageBroker()
    strategy = ContractLowLeverageTrendStrategy(make_state(), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "trade_symbols": ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"],
            "timeframe": "1h",
            "initial_capital": 10,
            "trade_notional_usdt": 5,
            "trade_notional_pct": 0.5,
            "max_total_notional_pct": 0.8,
            "min_order_notional_usdt": 1,
            "leverage": 2,
            "max_leverage": 3,
            "allow_short": True,
            "max_positions": 1,
            "fast_window": 2,
            "slow_window": 3,
            "atr_window": 2,
            "momentum_lookback_bars": 1,
            "momentum_threshold_pct": 0.001,
            "min_atr_pct": 0.001,
            "max_atr_pct": 0.05,
            "atr_stop_mult": 1.0,
            "risk_reward_ratio": 1.5,
            "trailing_atr_mult": 1.2,
            "break_even_at_r": 1.0,
            "max_holding_bars": 12,
            "daily_loss_limit_usdt": 0.3,
            "account_drawdown_stop_pct": 0.25,
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy, broker


def run_bars(strategy, bars):
    for bar in bars:
        asyncio.run(strategy.on_bar(bar))


def test_enters_long_on_confirmed_1h_trend_with_low_leverage_size():
    strategy, broker = init_strategy()

    run_bars(strategy, [make_bar(0, 100), make_bar(1, 101), make_bar(2, 102), make_bar(3, 104)])

    assert broker.orders
    order = broker.orders[-1]
    assert order["action"] == "open"
    assert order["symbol"] == "BTC/USDT:USDT"
    assert order["side"] == "long"
    assert order["notional"] == 5.0
    assert order["leverage"] == 2.0


def test_total_notional_cap_blocks_second_symbol_entry():
    strategy, broker = init_strategy()
    broker.positions[("BTC/USDT:USDT", "long")] = {
        "symbol": "BTC/USDT:USDT",
        "pos_side": "long",
        "notional_usdt": 8.0,
        "entry_price": 100.0,
    }

    run_bars(
        strategy,
        [
            make_bar(0, 2000, symbol="ETH/USDT:USDT"),
            make_bar(1, 2010, symbol="ETH/USDT:USDT"),
            make_bar(2, 2020, symbol="ETH/USDT:USDT"),
            make_bar(3, 2050, symbol="ETH/USDT:USDT"),
        ],
    )

    assert [order for order in broker.orders if order["action"] == "open"] == []


def test_daily_loss_guard_closes_positions_and_blocks_same_day_reentry():
    strategy, broker = init_strategy()
    broker.positions[("BTC/USDT:USDT", "long")] = {"notional_usdt": 5, "entry_price": 100}
    broker.positions[("ETH/USDT:USDT", "short")] = {"notional_usdt": 5, "entry_price": 2000}

    asyncio.run(strategy.on_bar(make_bar(0, 100)))
    broker.equity = 9.65
    asyncio.run(strategy.on_bar(make_bar(1, 101)))

    closes = [order for order in broker.orders if order["action"] == "close"]
    assert closes[0]["symbol"] == "BTC/USDT:USDT"
    assert closes[0]["price"] == 101.0
    assert closes[1]["symbol"] == "ETH/USDT:USDT"
    assert closes[1]["price"] == 0.0

    open_count = sum(1 for order in broker.orders if order["action"] == "open")
    broker.equity = 10.2
    run_bars(strategy, [make_bar(2, 102), make_bar(3, 104), make_bar(4, 106), make_bar(5, 108)])
    assert sum(1 for order in broker.orders if order["action"] == "open") == open_count
    assert strategy.state.positions["_low_leverage_trend_stopped_reason"] == "daily_loss_limit"


def test_next_utc_day_resets_daily_loss_guard():
    strategy, broker = init_strategy()
    asyncio.run(strategy.on_bar(make_bar(0, 100)))
    broker.equity = 9.65
    asyncio.run(strategy.on_bar(make_bar(1, 101)))
    assert strategy.state.positions["_low_leverage_trend_stopped_reason"] == "daily_loss_limit"

    broker.equity = 9.65
    run_bars(
        strategy,
        [
            make_bar(0, 100, day=1),
            make_bar(1, 101, day=1),
            make_bar(2, 102, day=1),
            make_bar(3, 104, day=1),
        ],
    )

    assert any(order["action"] == "open" for order in broker.orders)
    assert "_low_leverage_trend_stopped_reason" not in strategy.state.positions


def test_account_drawdown_guard_closes_and_blocks_entries():
    strategy, broker = init_strategy({"daily_loss_limit_usdt": 0})
    broker.positions[("BTC/USDT:USDT", "long")] = {"notional_usdt": 5, "entry_price": 100}

    asyncio.run(strategy.on_bar(make_bar(0, 100)))
    broker.equity = 7.4
    asyncio.run(strategy.on_bar(make_bar(1, 99)))

    assert broker.orders[-1]["action"] == "close"
    assert strategy.state.positions["_low_leverage_trend_stopped_reason"] == "account_drawdown_stop"
