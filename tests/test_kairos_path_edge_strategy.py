import asyncio
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.strategies.kairos_path_edge_strategy as strategy_module
from app.core.execution.base_strategy import BarData, OrderResult, StrategyState
from app.services.strategy_registry import get_base_strategy_registry
from app.strategies.kairos_path_edge_strategy import (
    AccountSnapshot,
    KairosPathEdgeStrategy,
    PositionSnapshot,
    SymbolState,
)


class FakeBroker:
    def __init__(self, cash=10_000.0, prices=None):
        self.cash = cash
        self.positions = {}
        self._last_prices = prices or {}
        self.orders = []

    async def get_available_balance(self, currency: str = "USDT") -> float:
        return self.cash if currency.upper() == "USDT" else 0.0

    async def buy(self, symbol: str, amount: float, price=None, *, order_type: str = "market") -> OrderResult:
        fill_price = float(price or self._last_prices.get(symbol) or 100.0)
        notional = amount * fill_price
        self.orders.append({"side": "buy", "symbol": symbol, "amount": amount, "notional": notional})
        self.cash -= notional
        self.positions[symbol] = {
            "size": amount,
            "entry_price": fill_price,
            "mark_price": fill_price,
            "notional": notional,
        }
        return OrderResult({"status": "filled", "amount": amount, "price": fill_price})

    async def sell(self, symbol: str, amount: float, price=None, *, order_type: str = "market") -> OrderResult:
        fill_price = float(price or self._last_prices.get(symbol) or 100.0)
        self.orders.append({"side": "sell", "symbol": symbol, "amount": amount, "notional": amount * fill_price})
        position = self.positions.setdefault(symbol, {"size": 0.0, "entry_price": fill_price, "mark_price": fill_price})
        actual = min(float(position.get("size") or 0.0), amount)
        position["size"] = max(0.0, float(position.get("size") or 0.0) - actual)
        self.cash += actual * fill_price
        return OrderResult({"status": "filled", "amount": actual, "price": fill_price})

    async def close_position(self, symbol: str) -> OrderResult:
        return await self.sell(symbol, float(self.positions.get(symbol, {}).get("size") or 0.0))


def make_bar(symbol: str, close: float = 100.0, ts: int = 1_800_000_000_000) -> BarData:
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="1m",
        timestamp=ts,
        open=close - 0.2,
        high=close + 0.5,
        low=close - 0.5,
        close=close,
        volume=1.0,
    )


def make_strategy(symbols, broker=None) -> KairosPathEdgeStrategy:
    state = StrategyState(
        strategy_id=888,
        name="path edge unit",
        exchange="okx",
        symbols=list(symbols),
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 10_000.0},
    )
    strategy = KairosPathEdgeStrategy(state, broker or FakeBroker())
    strategy.timeframe = "1m"
    strategy.predict_steps = 5
    strategy.window_size = 5
    strategy.warmup_bars = 0
    strategy.decision_interval_bars = 1
    strategy.max_active_positions = 1
    strategy.allow_dca_existing_positions = False
    strategy.min_net_edge_bps = 10.0
    strategy.min_path_slope_bps = 2.0
    strategy.min_path_positive_ratio = 0.55
    strategy.min_confidence = 0.1
    strategy.max_predicted_drawdown_bps = 50.0
    strategy.fee_bps = 10.0
    strategy.slippage_bps = 2.0
    strategy.round_trip_cost_bps = 22.0
    strategy.base_error_buffer_bps = 8.0
    strategy.error_buffer_multiplier = 0.4
    strategy.min_error_samples = 3
    strategy.error_sample_size = 20
    strategy.entry_quote_usdt = 200.0
    strategy.entry_equity_pct = 0.02
    strategy.max_position_pct = 0.1
    strategy.max_total_position_pct = 0.2
    strategy.min_order_notional_usdt = 5.0
    strategy.min_holding_bars = 3
    strategy.max_holding_bars = 20
    strategy.cooldown_bars = 5
    strategy.take_profit_bps = 80.0
    strategy.stop_loss_bps = 35.0
    strategy.trailing_start_bps = 45.0
    strategy.trailing_pullback_bps = 22.0
    strategy.profit_floor_start_bps = 45.0
    strategy.profit_floor_bps = 22.0
    strategy.exit_on_negative_edge = True
    strategy._strategy_diagnostic_ws = False
    strategy._strategy_diagnostic_every_n = 1
    strategy._states = {}
    base_ts = 1_800_000_000_000
    for symbol in symbols:
        symbol_state = SymbolState()
        for index in range(5):
            symbol_state.history.append(make_bar(symbol, 100.0, base_ts + index * 60_000))
        symbol_state.latest_bar = symbol_state.history[-1]
        strategy._states[symbol] = symbol_state
    strategy._symbols = set(symbols)
    strategy._seen_symbols_by_ts = defaultdict(set)
    strategy._evaluated_timestamps = set()
    strategy._portfolio_bar_index = 0
    strategy._last_decision_bar = None
    strategy._events_seen = 0
    return strategy


def prediction(prices, confidence=0.5):
    return SimpleNamespace(
        predicted_prices=prices,
        confidence=confidence,
        score=0.7,
        direction="bullish",
    )


def test_registry_exposes_kairos_path_edge_strategy():
    assert get_base_strategy_registry()["kairos_path_edge"] is KairosPathEdgeStrategy


def test_path_edge_signal_includes_cost_and_error_buffer(monkeypatch):
    strategy = make_strategy(["ETH/USDT"])

    async def fake_predict_trajectory(*args, **kwargs):
        return prediction([100.1, 100.25, 100.45, 100.65, 100.9], confidence=0.6)

    monkeypatch.setattr(strategy_module.kairos_predictor, "predict_trajectory", fake_predict_trajectory)

    signal = asyncio.run(strategy._predict_path_edge("ETH/USDT"))

    assert signal is not None
    assert signal.endpoint_return_bps > 80
    assert signal.cost_bps == 22.0
    assert signal.error_buffer_bps == 8.0
    assert signal.net_edge_bps > 50
    assert signal.passes is True


def test_waits_for_full_symbol_batch_before_entry(monkeypatch):
    broker = FakeBroker(prices={"BTC/USDT": 100.0, "ETH/USDT": 100.0})
    strategy = make_strategy(["BTC/USDT", "ETH/USDT"], broker)

    async def fake_predict_trajectory(*args, **kwargs):
        symbol = kwargs["symbol"]
        if symbol == "ETH/USDT":
            return prediction([100.1, 100.25, 100.45, 100.65, 100.9], confidence=0.6)
        return prediction([100.0, 99.98, 99.95, 99.92, 99.9], confidence=0.4)

    monkeypatch.setattr(strategy_module.kairos_predictor, "predict_trajectory", fake_predict_trajectory)
    current_ts = 1_800_000_000_000 + 5 * 60_000

    asyncio.run(strategy.on_bar(make_bar("BTC/USDT", 100.0, current_ts)))
    assert broker.orders == []

    asyncio.run(strategy.on_bar(make_bar("ETH/USDT", 100.0, current_ts)))
    assert broker.orders
    assert broker.orders[0]["symbol"] == "ETH/USDT"
    assert round(broker.orders[0]["notional"], 2) == 200.0


def test_can_enter_multiple_path_edge_candidates_per_batch(monkeypatch):
    broker = FakeBroker(prices={"BTC/USDT": 100.0, "ETH/USDT": 100.0, "SOL/USDT": 100.0})
    strategy = make_strategy(["BTC/USDT", "ETH/USDT", "SOL/USDT"], broker)
    strategy.max_active_positions = 2
    strategy.max_total_position_pct = 0.06

    async def fake_predict_trajectory(*args, **kwargs):
        symbol = kwargs["symbol"]
        if symbol == "BTC/USDT":
            return prediction([100.05, 100.1, 100.2, 100.3, 100.4], confidence=0.5)
        if symbol == "ETH/USDT":
            return prediction([100.1, 100.25, 100.45, 100.65, 100.9], confidence=0.7)
        return prediction([100.08, 100.2, 100.36, 100.52, 100.7], confidence=0.65)

    monkeypatch.setattr(strategy_module.kairos_predictor, "predict_trajectory", fake_predict_trajectory)
    current_ts = 1_800_000_000_000 + 5 * 60_000

    asyncio.run(strategy.on_bar(make_bar("BTC/USDT", 100.0, current_ts)))
    asyncio.run(strategy.on_bar(make_bar("ETH/USDT", 100.0, current_ts)))
    asyncio.run(strategy.on_bar(make_bar("SOL/USDT", 100.0, current_ts)))

    assert [order["symbol"] for order in broker.orders] == ["ETH/USDT", "SOL/USDT"]
    assert round(sum(order["notional"] for order in broker.orders), 2) == 400.0


def test_recent_error_calibration_expands_buffer():
    strategy = make_strategy(["ETH/USDT"])
    state = strategy._states["ETH/USDT"]
    state.abs_error_bps.extend([40.0, 50.0, 60.0])

    assert strategy._calibration_error_bps(state) == 50.0


def test_entry_quote_uses_equity_pct_when_configured():
    strategy = make_strategy(["ETH/USDT"])
    strategy.entry_quote_usdt = 50.0
    strategy.entry_equity_pct = 0.05
    account = AccountSnapshot(cash_usdt=10_000.0, equity=10_000.0, positions={})

    assert strategy._entry_quote_for("ETH/USDT", account, 100.0) == 500.0


def test_manage_position_triggers_profit_floor_sell():
    broker = FakeBroker(cash=9_900.0, prices={"ETH/USDT": 100.25})
    broker.positions["ETH/USDT"] = {"size": 1.0, "entry_price": 100.0, "mark_price": 100.25}
    strategy = make_strategy(["ETH/USDT"], broker)
    events = []

    async def emit(_bar, decision, **kwargs):
        events.append((decision, kwargs))

    strategy._emit_diag = emit
    strategy.profit_floor_start_bps = 50.0
    strategy.profit_floor_bps = 30.0
    state = strategy._states["ETH/USDT"]
    state.qty = 1.0
    state.entry_price = 100.0
    state.peak_price = 101.0
    state.holding_start_bar = 0
    strategy._portfolio_bar_index = 5
    account = AccountSnapshot(
        cash_usdt=9_900.0,
        equity=10_000.25,
        positions={"ETH/USDT": PositionSnapshot("ETH/USDT", 1.0, 100.25, 100.25, 100.0, 0.25)},
    )

    asyncio.run(strategy._manage_position_for_bar(make_bar("ETH/USDT", 100.25), account))

    assert broker.orders
    assert broker.orders[0]["side"] == "sell"
    assert events[-1][0] == "exit_profit_floor"
