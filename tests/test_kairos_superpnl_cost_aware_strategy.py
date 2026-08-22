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
from app.services.superpnl_feature_builder import canonical_bar_timestamp_ms
from app.services.superpnl_model_inference_service import SuperPnLSignal
from app.strategies.kairos_superpnl_cost_aware_strategy import (
    AccountSnapshot,
    KairosSignal,
    KairosSuperPnLCostAwareStrategy,
    PositionSnapshot,
    SymbolState,
)


class FakeBroker:
    def __init__(self, cash=10_000.0, positions=None, prices=None):
        self.cash = cash
        self.positions = positions or {}
        self._last_prices = prices or {}
        self.orders = []

    async def get_available_balance(self, currency: str = "USDT") -> float:
        return self.cash if currency.upper() == "USDT" else 0.0

    async def buy(self, symbol: str, amount: float, price=None, *, order_type: str = "market") -> OrderResult:
        px = float(price or self._last_prices.get(symbol) or 100.0)
        self.orders.append({"side": "buy", "symbol": symbol, "amount": amount, "notional": amount * px})
        self.cash -= amount * px
        self.positions[symbol] = {
            "size": amount,
            "entry_price": px,
            "mark_price": px,
            "notional": amount * px,
        }
        return OrderResult({"status": "filled", "amount": amount, "price": px})

    async def sell(self, symbol: str, amount: float, price=None, *, order_type: str = "market") -> OrderResult:
        px = float(price or self._last_prices.get(symbol) or 100.0)
        self.orders.append({"side": "sell", "symbol": symbol, "amount": amount, "notional": amount * px})
        pos = self.positions.setdefault(symbol, {"size": 0.0, "entry_price": px, "mark_price": px})
        actual = min(float(pos.get("size") or 0.0), amount)
        pos["size"] = max(0.0, float(pos.get("size") or 0.0) - actual)
        pos["mark_price"] = px
        self.cash += actual * px
        return OrderResult({"status": "filled", "amount": actual, "price": px})

    async def close_position(self, symbol: str) -> OrderResult:
        size = float(self.positions.get(symbol, {}).get("size") or 0.0)
        return await self.sell(symbol, size)


def bar(symbol: str, close: float = 100.0, ts: int = 1_800_000_000_000) -> BarData:
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="1m",
        timestamp=ts,
        open=close - 0.2,
        high=close + 0.6,
        low=close - 0.6,
        close=close,
        volume=1.0,
    )


def signal(symbol: str, bps: float, ts: int = 1_800_000_000_000) -> SuperPnLSignal:
    return SuperPnLSignal(
        symbol=symbol,
        timestamp_ms=canonical_bar_timestamp_ms(ts),
        horizon="15m",
        pred_ret=bps / 10_000.0,
        score_bps=bps,
        pos_score=0.5,
        source="unit-test",
    )


def kairos(change_bps: float = 80.0, confidence: float = 0.3) -> KairosSignal:
    return KairosSignal(
        direction=1,
        confidence=confidence,
        predicted_change=change_bps / 10_000.0,
        predicted_change_bps=change_bps,
        model_score=0.65,
        model_direction="bullish",
        horizon_index=29,
        predicted_horizon_close=100.8,
    )


def make_strategy(symbols, broker=None) -> KairosSuperPnLCostAwareStrategy:
    state = StrategyState(
        strategy_id=777,
        name="cost-aware unit",
        exchange="okx",
        symbols=list(symbols),
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 10_000.0},
    )
    strat = KairosSuperPnLCostAwareStrategy(state, broker or FakeBroker())
    strat.timeframe = "1m"
    strat.superpnl_horizon = "15m"
    strat.kairos_predict_steps = 30
    strat.window_size = 5
    strat.warmup_bars = 0
    strat.decision_interval_bars = 15
    strat.max_kairos_candidates = 3
    strat.max_active_positions = 1
    strat.min_superpnl_bps = 50.0
    strat.min_kairos_confidence = 0.2
    strat.min_expected_edge_bps = 60.0
    strat.exit_min_superpnl_bps = 10.0
    strat.entry_quote_usdt = 500.0
    strat.entry_equity_pct = 0.02
    strat.max_position_pct = 0.10
    strat.max_total_position_pct = 0.20
    strat.min_order_notional_usdt = 5.0
    strat.min_holding_bars = 15
    strat.max_holding_bars = 90
    strat.cooldown_bars = 30
    strat.take_profit_bps = 80.0
    strat.stop_loss_bps = 40.0
    strat.trailing_start_bps = 50.0
    strat.trailing_pullback_bps = 25.0
    strat.ema_fast = 2
    strat.ema_slow = 3
    strat.atr_window = 2
    strat.min_atr_bps = 1.0
    strat.max_atr_bps = 500.0
    strat.fee_bps = 10.0
    strat.slippage_bps = 0.0
    strat.round_trip_fee_bps = 20.0
    strat.profit_floor_start_bps = 45.0
    strat.profit_floor_bps = 20.0
    strat.superpnl_max_signal_lag_bars = 3
    strat._strategy_diagnostic_ws = False
    strat._strategy_diagnostic_every_n = 1
    strat._states = {}
    for symbol in symbols:
        st = SymbolState()
        st.history = deque(maxlen=20)
        base_ts = 1_800_000_000_000
        for i in range(5):
            st.history.append(bar(symbol, 100 + i, base_ts + i * 60_000))
        st.latest_bar = st.history[-1]
        strat._states[symbol] = st
    strat._seen_timestamps = set()
    strat._portfolio_bar_index = 100
    strat._last_decision_bar = 0
    strat._last_decision_interval_diag_window = None
    strat._events_seen = 1
    return strat


def test_entry_quote_uses_equity_pct_when_configured():
    strat = make_strategy(["BTC/USDT"])
    strat.entry_quote_usdt = 50.0
    strat.entry_equity_pct = 0.05
    account = AccountSnapshot(cash_usdt=10_000.0, equity=10_000.0, positions={})

    assert strat._entry_quote_for("BTC/USDT", account, 100.0) == 500.0


def test_evaluate_entry_buys_top_superpnl_candidate_after_kairos_confirmation():
    broker = FakeBroker(cash=10_000.0, prices={"ETH/USDT": 104.0})
    strat = make_strategy(["BTC/USDT", "ETH/USDT"], broker)
    ts = canonical_bar_timestamp_ms(strat._states["ETH/USDT"].latest_bar.timestamp)
    strat._states["BTC/USDT"].latest_signal = signal("BTC/USDT", 40.0, ts)
    strat._states["ETH/USDT"].latest_signal = signal("ETH/USDT", 75.0, ts)

    async def fake_predict(symbol):
        return kairos(80.0)

    strat._predict_kairos = fake_predict
    account = AccountSnapshot(cash_usdt=10_000.0, equity=10_000.0, positions={})

    asyncio.run(strat._evaluate_entry(trigger_bar=strat._states["BTC/USDT"].latest_bar, signal_ts=ts, account=account))

    assert broker.orders
    assert broker.orders[0]["side"] == "buy"
    assert broker.orders[0]["symbol"] == "ETH/USDT"
    assert round(broker.orders[0]["notional"], 2) == 200.0


def test_evaluate_entry_skips_when_cost_adjusted_edge_is_too_small():
    broker = FakeBroker(cash=10_000.0, prices={"ETH/USDT": 104.0})
    strat = make_strategy(["ETH/USDT"], broker)
    ts = canonical_bar_timestamp_ms(strat._states["ETH/USDT"].latest_bar.timestamp)
    strat._states["ETH/USDT"].latest_signal = signal("ETH/USDT", 75.0, ts)

    async def fake_predict(symbol):
        return kairos(55.0)

    strat._predict_kairos = fake_predict
    account = AccountSnapshot(cash_usdt=10_000.0, equity=10_000.0, positions={})

    asyncio.run(strat._evaluate_entry(trigger_bar=strat._states["ETH/USDT"].latest_bar, signal_ts=ts, account=account))

    assert broker.orders == []


def test_decision_interval_diag_is_emitted_once_per_wait_window():
    strat = make_strategy(["BTC/USDT"])
    strat._last_decision_bar = 100
    strat._portfolio_bar_index = 101

    assert strat._claim_decision_interval_diag() is True
    strat._portfolio_bar_index = 102
    assert strat._claim_decision_interval_diag() is False

    strat._last_decision_bar = 115
    strat._portfolio_bar_index = 116
    assert strat._claim_decision_interval_diag() is True


def test_recent_lagged_superpnl_signal_can_drive_weak_exit_check():
    strat = make_strategy(["BTC/USDT"])
    current_ts = canonical_bar_timestamp_ms(strat._states["BTC/USDT"].latest_bar.timestamp)
    strat._states["BTC/USDT"].latest_signal = signal("BTC/USDT", 5.0, current_ts - 60_000)

    assert strat._is_signal_weak("BTC/USDT", current_ts) is True

    strat._states["BTC/USDT"].latest_signal = signal("BTC/USDT", 5.0, current_ts - 4 * 60_000)

    assert strat._is_signal_weak("BTC/USDT", current_ts) is False


def test_manage_position_triggers_stop_loss_sell():
    broker = FakeBroker(
        cash=9_900.0,
        positions={"BTC/USDT": {"size": 1.0, "entry_price": 100.0, "mark_price": 99.0}},
        prices={"BTC/USDT": 99.0},
    )
    strat = make_strategy(["BTC/USDT"], broker)
    strat._states["BTC/USDT"].qty = 1.0
    strat._states["BTC/USDT"].entry_price = 100.0
    strat._states["BTC/USDT"].holding_start_bar = 90
    account = AccountSnapshot(
        cash_usdt=9_900.0,
        equity=9_999.0,
        positions={"BTC/USDT": PositionSnapshot("BTC/USDT", 1.0, 99.0, 99.0, 100.0, -1.0)},
    )

    asyncio.run(strat._manage_position_for_bar(bar("BTC/USDT", 99.0), account))

    assert broker.orders
    assert broker.orders[0]["side"] == "sell"


def test_manage_position_triggers_profit_floor_sell():
    broker = FakeBroker(
        cash=9_900.0,
        positions={"BTC/USDT": {"size": 1.0, "entry_price": 100.0, "mark_price": 100.25}},
        prices={"BTC/USDT": 100.25},
    )
    strat = make_strategy(["BTC/USDT"], broker)
    events = []

    async def emit(_bar, decision, **kwargs):
        events.append((decision, kwargs))

    strat._emit_diag = emit
    strat.profit_floor_start_bps = 50.0
    strat.profit_floor_bps = 30.0
    strat._states["BTC/USDT"].qty = 1.0
    strat._states["BTC/USDT"].entry_price = 100.0
    strat._states["BTC/USDT"].peak_price = 101.0
    strat._states["BTC/USDT"].holding_start_bar = 90
    account = AccountSnapshot(
        cash_usdt=9_900.0,
        equity=10_000.25,
        positions={"BTC/USDT": PositionSnapshot("BTC/USDT", 1.0, 100.25, 100.25, 100.0, 0.25)},
    )

    asyncio.run(strat._manage_position_for_bar(bar("BTC/USDT", 100.25), account))

    assert broker.orders
    assert broker.orders[0]["side"] == "sell"
    assert events[-1][0] == "exit_profit_floor"
