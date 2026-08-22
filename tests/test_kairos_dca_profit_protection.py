import asyncio
import sys
from collections import deque
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, OrderResult, StrategyState
from app.strategies.kairos_30m_horizon_dca_strategy import DcaLot, Kairos30mHorizonDcaStrategy


class FakeBroker:
    def __init__(self, prices=None):
        self._last_prices = prices or {}
        self.orders = []

    async def sell(self, symbol: str, amount: float, price=None, *, order_type: str = "market") -> OrderResult:
        px = float(price or self._last_prices.get(symbol) or 100.0)
        self.orders.append({"side": "sell", "symbol": symbol, "amount": amount, "notional": amount * px})
        return OrderResult({"status": "filled", "amount": amount, "price": px})


def bar(symbol: str = "BTC/USDT", close: float = 100.0, ts: int = 1_800_000_000_000) -> BarData:
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="1m",
        timestamp=ts,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1.0,
    )


def make_strategy(broker=None) -> Kairos30mHorizonDcaStrategy:
    state = StrategyState(
        strategy_id=123,
        name="dca unit",
        exchange="okx",
        symbols=["BTC/USDT"],
        created_at=datetime.utcnow(),
        status="running",
        positions={},
    )
    strategy = Kairos30mHorizonDcaStrategy(state, broker or FakeBroker())
    strategy.tf_exec = "1m"
    strategy.hold_bars = 30
    strategy.max_hold_bars = 90
    strategy.take_profit_bps = 0.0
    strategy.stop_loss_bps = 60.0
    strategy.trailing_start_bps = 55.0
    strategy.trailing_pullback_bps = 25.0
    strategy.profit_floor_start_bps = 50.0
    strategy.profit_floor_bps = 30.0
    strategy.hold_exit_requires_profit = True
    strategy.hold_exit_min_profit_bps = 20.0
    strategy._bar_count = 40
    strategy._history = deque([bar() for _ in range(5)])
    strategy._lots = deque()
    strategy._dca_sells = 0
    strategy._strategy_diagnostic_ws = True
    strategy._strategy_diagnostic_every_n = 1
    return strategy


def collect_diagnostics(strategy):
    events = []

    async def emit(_bar, _pred, decision, **kwargs):
        events.append((decision, kwargs))

    strategy._maybe_emit_bar_diagnostic = emit
    return events


def test_dca_lot_profit_floor_sells_before_profit_turns_to_loss():
    broker = FakeBroker(prices={"BTC/USDT": 100.25})
    strategy = make_strategy(broker)
    events = collect_diagnostics(strategy)
    strategy._lots.append(DcaLot(entry_bar=32, quantity=1.0, entry_price=100.0, peak_price=101.0))

    asyncio.run(strategy._manage_open_lots(bar(close=100.25)))

    assert broker.orders
    assert broker.orders[0]["side"] == "sell"
    assert events[-1][0] == "exit_profit_floor"
    assert round(events[-1][1]["pnl_bps"], 2) == 25.0


def test_dca_hold_expiry_waits_when_profit_floor_is_not_met():
    broker = FakeBroker(prices={"BTC/USDT": 100.10})
    strategy = make_strategy(broker)
    events = collect_diagnostics(strategy)
    strategy._lots.append(DcaLot(entry_bar=9, quantity=1.0, entry_price=100.0, peak_price=100.20))

    asyncio.run(strategy._manage_open_lots(bar(close=100.10)))

    assert broker.orders == []
    assert len(strategy._lots) == 1
    assert events[-1][0] == "skip_hold_profit_floor"
    assert round(events[-1][1]["pnl_bps"], 2) == 10.0
