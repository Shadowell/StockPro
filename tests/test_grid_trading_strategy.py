import asyncio
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, OrderResult, StrategyState
from app.strategies.grid_trading_strategy import GridTradingStrategy


class FakeContractBroker:
    def __init__(self, equity: float = 10_000.0):
        self.equity = equity
        self.positions = {}
        self.orders = []
        self.warmup_mode = False

    async def open_contract(self, symbol: str, side: str, notional_usdt: float, leverage=None, price=None) -> OrderResult:
        contracts = round(notional_usdt / price, 6) if price else 0.0
        self.orders.append(
            {
                "action": "open",
                "symbol": symbol,
                "side": side,
                "notional": notional_usdt,
                "leverage": leverage,
                "price": price,
                "contracts": contracts,
            }
        )
        key = (symbol, side)
        existing = self.positions.get(key)
        if existing:
            existing["contracts"] += contracts
            existing["base_qty"] += contracts
            existing["notional_usdt"] += notional_usdt
            existing["mark_price"] = price
        else:
            self.positions[key] = {
                "symbol": symbol,
                "pos_side": side,
                "contracts": contracts,
                "base_qty": contracts,
                "entry_price": price,
                "mark_price": price,
                "notional_usdt": notional_usdt,
            }
        return OrderResult(
            {
                "status": "filled",
                "side": side,
                "contracts": contracts,
                "base_qty": contracts,
                "notional_usdt": notional_usdt,
                "price": price,
            }
        )

    async def close_contract(self, symbol: str, side: str, ratio: float = 1.0, contracts=None, price=None) -> OrderResult:
        pos = self.positions.get((symbol, side))
        close_contracts = min(float(contracts or 0.0), float((pos or {}).get("contracts") or 0.0))
        self.orders.append(
            {
                "action": "close",
                "symbol": symbol,
                "side": side,
                "ratio": ratio,
                "contracts": close_contracts,
                "price": price,
            }
        )
        if pos and close_contracts > 0:
            pos["contracts"] -= close_contracts
            pos["base_qty"] -= close_contracts
            pos["notional_usdt"] = max(0.0, pos["notional_usdt"] - close_contracts * price)
            if pos["contracts"] <= 1e-9:
                self.positions.pop((symbol, side), None)
        return OrderResult({"status": "filled", "side": side, "contracts": close_contracts, "price": price})

    async def get_contract_position(self, symbol: str, side: str):
        return self.positions.get((symbol, side))


def make_state() -> StrategyState:
    return StrategyState(
        strategy_id=1101,
        name="[合约] Grid test",
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 10_000.0},
    )


def make_bar(close: float, index: int, *, high=None, low=None) -> BarData:
    return BarData(
        exchange="okx",
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        timestamp=1_800_000_000_000 + index * 3_600_000,
        open=close,
        high=close if high is None else high,
        low=close if low is None else low,
        close=close,
        volume=1000.0,
    )


def init_strategy(config=None, broker=None) -> tuple[GridTradingStrategy, FakeContractBroker]:
    broker = broker or FakeContractBroker()
    strategy = GridTradingStrategy(make_state(), broker)
    strategy.set_config(
        {
            "market_type": "swap",
            "target_symbol": "BTC/USDT",
            "grid_low": 90,
            "grid_high": 110,
            "grid_count": 4,
            "order_notional_usdt": 100,
            "min_order_notional_usdt": 10,
            "max_total_notional_pct": 1.0,
            "leverage": 2,
            "trend_filter_enabled": False,
            "order_timeout_bars": 2,
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy, broker


def test_grid_initializes_expected_price_lines():
    strategy, _ = init_strategy()

    assert strategy.grid_prices == [90, 95, 100, 105, 110]
    assert len(strategy.grid_states) == 4


def test_grid_places_limit_buy_then_fills_on_next_bar_low_touch():
    strategy, broker = init_strategy()

    asyncio.run(strategy.on_bar(make_bar(101, 1, high=102, low=100.5)))

    assert broker.orders == []
    assert len(strategy._active_orders) == 1
    assert strategy._active_orders[0]["action"] == "buy"
    assert strategy._active_orders[0]["price"] == 100

    asyncio.run(strategy.on_bar(make_bar(102, 2, high=103, low=99.5)))

    assert broker.orders[0]["action"] == "open"
    assert broker.orders[0]["price"] == 100
    assert strategy.grid_states[2]["filled_buy"] is True
    assert any(order["action"] == "sell" and order["price"] == 105 for order in strategy._active_orders)


def test_grid_diagnostics_use_chinese_labels_and_summaries():
    strategy, _ = init_strategy()
    events = []

    async def capture_event(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture_event

    asyncio.run(strategy.on_bar(make_bar(101, 1, high=102, low=100.5)))

    assert events
    assert events[-1]["decision"] == "place_grid_buy"
    assert events[-1]["decision_label"] == "挂网格买入"
    assert events[-1]["summary"] == "已挂内部网格买入限价单"


def test_grid_sell_limit_closes_recorded_lot_when_upper_line_touched():
    strategy, broker = init_strategy()

    asyncio.run(strategy.on_bar(make_bar(101, 1, high=102, low=100.5)))
    asyncio.run(strategy.on_bar(make_bar(102, 2, high=103, low=99.5)))
    asyncio.run(strategy.on_bar(make_bar(104, 3, high=106, low=103)))

    assert broker.orders[-1]["action"] == "close"
    assert broker.orders[-1]["price"] == 105
    assert strategy.grid_states[2]["filled_buy"] is False
    assert strategy.grid_states[2]["filled_sell"] is True
    assert 2 not in strategy._grid_lots


def test_grid_trend_guard_blocks_new_buy_orders_after_warmup():
    strategy, broker = init_strategy(
        {
            "grid_low": 70,
            "grid_high": 110,
            "grid_count": 4,
            "trend_filter_enabled": True,
            "trend_ema_window": 3,
            "trend_pause_pct": 0.05,
        }
    )
    broker.warmup_mode = True
    for index, close in enumerate([100, 100, 100], start=1):
        asyncio.run(strategy.on_bar(make_bar(close, index)))
    broker.warmup_mode = False

    asyncio.run(strategy.on_bar(make_bar(80, 4, high=81, low=79)))

    assert strategy._trend_guard(list(strategy._bars["BTC/USDT:USDT"]), 80) == "block_buy"
    assert not any(order["action"] == "buy" for order in strategy._active_orders)


def test_grid_breakout_pauses_strategy():
    strategy, _ = init_strategy()

    asyncio.run(strategy.on_bar(make_bar(80, 1)))

    assert strategy.state.status == "paused"
    assert "网格价格区间失效" in strategy.state.error_message


def test_grid_stale_limit_order_is_cancelled_and_reposted():
    strategy, broker = init_strategy({"order_timeout_bars": 1})

    asyncio.run(strategy.on_bar(make_bar(101, 1, high=102, low=100.5)))
    first_id = strategy._active_orders[0]["id"]
    asyncio.run(strategy.on_bar(make_bar(102, 2, high=103, low=101.5)))

    assert broker.orders == []
    assert len(strategy._active_orders) == 1
    assert strategy._active_orders[0]["action"] == "buy"
    assert strategy._active_orders[0]["id"] != first_id
    assert strategy._active_orders[0]["placed_bar"] == 2
