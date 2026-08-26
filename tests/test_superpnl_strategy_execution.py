import asyncio
import json
import sys
import threading
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, OrderResult, StrategyState
from app.services.superpnl_model_inference_service import SuperPnLSignal
from app.services.superpnl_feature_builder import (
    SuperPnLFeatureBuilder,
    canonical_bar_timestamp_ms,
)
import app.strategies.superpnl_15m_low_turnover_strategy as superpnl_strategy_module
from app.strategies.superpnl_contract_mainstream_strategy import (
    SuperPnLContractMainstreamStrategy,
)
from app.strategies.superpnl_15m_low_turnover_strategy import (
    AccountSnapshot,
    PositionSnapshot,
    SuperPnL15mLowTurnoverStrategy,
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
        pos = self.positions.setdefault(
            symbol,
            {"size": 0.0, "entry_price": px, "mark_price": px, "unrealized_pnl": 0.0},
        )
        old_size = float(pos.get("size") or 0.0)
        old_entry = float(pos.get("entry_price") or px)
        pos["entry_price"] = (
            (old_entry * old_size + px * amount) / (old_size + amount)
            if old_size + amount > 0
            else px
        )
        pos["size"] = old_size + amount
        pos["mark_price"] = px
        return OrderResult({"status": "filled", "amount": amount, "price": px})

    async def sell(self, symbol: str, amount: float, price=None, *, order_type: str = "market") -> OrderResult:
        px = float(price or self._last_prices.get(symbol) or 100.0)
        self.orders.append({"side": "sell", "symbol": symbol, "amount": amount, "notional": amount * px})
        pos = self.positions.setdefault(
            symbol,
            {"size": 0.0, "entry_price": px, "mark_price": px, "unrealized_pnl": 0.0},
        )
        actual = min(float(pos.get("size") or 0.0), amount)
        pos["size"] = max(0.0, float(pos.get("size") or 0.0) - actual)
        pos["mark_price"] = px
        self.cash += actual * px
        return OrderResult({"status": "filled", "amount": actual, "price": px})

    async def close_position(self, symbol: str) -> OrderResult:
        size = float(self.positions.get(symbol, {}).get("size") or 0.0)
        return await self.sell(symbol, size)


class FakeContractBroker:
    def __init__(self, cash=10_000.0, positions=None, prices=None):
        self.cash = cash
        self.positions = positions or {}
        self._last_prices = prices or {}
        self.orders = []
        self.equity = cash + sum(
            float(raw.get("unrealized_pnl") or 0.0)
            for raw in self.positions.values()
            if isinstance(raw, dict)
        )

    async def get_available_balance(self, currency: str = "USDT") -> float:
        return self.cash if currency.upper() == "USDT" else 0.0

    async def open_contract(self, symbol: str, side: str, notional_usdt: float, leverage=None, price=None) -> OrderResult:
        px = float(price or self._last_prices.get(symbol) or 100.0)
        self.orders.append(
            {
                "action": "open",
                "symbol": symbol,
                "side": side,
                "notional": notional_usdt,
                "leverage": leverage,
            }
        )
        key = (symbol, side)
        self.positions[key] = {
            "symbol": symbol,
            "pos_side": side,
            "base_qty": notional_usdt / px,
            "contracts": notional_usdt / px,
            "entry_price": px,
            "mark_price": px,
            "notional_usdt": notional_usdt,
            "unrealized_pnl": 0.0,
        }
        return OrderResult(
            {
                "status": "filled",
                "action": "open",
                "symbol": symbol,
                "pos_side": side,
                "base_qty": notional_usdt / px,
                "contracts": notional_usdt / px,
                "price": px,
                "notional_usdt": notional_usdt,
                "leverage": leverage,
            }
        )

    async def close_contract(self, symbol: str, side: str, ratio: float = 1.0, contracts=None, price=None) -> OrderResult:
        px = float(price or self._last_prices.get(symbol) or 100.0)
        self.orders.append({"action": "close", "symbol": symbol, "side": side, "ratio": ratio})
        key = (symbol, side)
        pos = self.positions.get(key) or {}
        base_qty = float(pos.get("base_qty") or pos.get("contracts") or 0.0) * ratio
        entry = float(pos.get("entry_price") or px)
        notional = float(pos.get("notional_usdt") or base_qty * px) * ratio
        realized = (px - entry) * base_qty
        if ratio >= 0.999:
            self.positions.pop(key, None)
        else:
            pos["base_qty"] = max(0.0, float(pos.get("base_qty") or 0.0) - base_qty)
            pos["contracts"] = max(0.0, float(pos.get("contracts") or 0.0) - base_qty)
            pos["notional_usdt"] = max(0.0, float(pos.get("notional_usdt") or 0.0) - notional)
            pos["mark_price"] = px
        return OrderResult(
            {
                "status": "filled",
                "action": "close",
                "symbol": symbol,
                "pos_side": side,
                "base_qty": base_qty,
                "contracts": base_qty,
                "price": px,
                "notional_usdt": notional,
                "realized_pnl": realized,
            }
        )

    async def get_contract_position(self, symbol: str, side: str):
        return self.positions.get((symbol, side))

    async def buy(self, symbol: str, amount: float, price=None, *, order_type: str = "market") -> OrderResult:
        self.orders.append({"action": "spot_buy", "symbol": symbol, "amount": amount})
        return OrderResult({"status": "rejected", "reason": "spot_unavailable"})

    async def sell(self, symbol: str, amount: float, price=None, *, order_type: str = "market") -> OrderResult:
        self.orders.append({"action": "spot_sell", "symbol": symbol, "amount": amount})
        return OrderResult({"status": "rejected", "reason": "spot_unavailable"})

    async def close_position(self, symbol: str) -> OrderResult:
        return OrderResult({"status": "unused"})


def bar(symbol: str, close: float = 100.0, ts: int = 1_800_000_000_000) -> BarData:
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


def signal(symbol: str, pred_ret: float, ts: int = 1_800_000_000_000) -> SuperPnLSignal:
    return SuperPnLSignal(
        symbol=symbol,
        timestamp_ms=ts,
        horizon="15m",
        pred_ret=pred_ret,
        score_bps=pred_ret * 10_000,
        pos_score=max(0.0, min(1.0, 0.5 + pred_ret)),
        source="unit-test",
    )


def make_strategy(symbols, broker=None) -> SuperPnL15mLowTurnoverStrategy:
    state = StrategyState(
        strategy_id=99,
        name="SuperPnL unit",
        exchange="okx",
        symbols=list(symbols),
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 10_000.0},
    )
    strat = SuperPnL15mLowTurnoverStrategy(state, broker or FakeBroker())
    strat.timeframe = "1m"
    strat.horizon = "15m"
    strat.warmup_bars = 0
    strat.threshold_bps = 30.0
    strat.top_k = 1
    strat.rebalance_interval_bars = 30
    strat.min_holding_bars = 60
    strat.cooldown_bars = 60
    strat.max_position_per_symbol = 0.1
    strat.max_total_position = 0.1
    strat.min_order_notional_usdt = 5.0
    strat.min_bar_quote_volume_usdt = 0.0
    strat.allow_cash = True
    strat.fee_bps = 8.0
    strat.slippage_bps = 0.0
    strat.estimated_cost_bps = 8.0
    strat.take_profit_bps = 0.0
    strat.stop_loss_bps = 60.0
    strat.trailing_start_bps = 55.0
    strat.trailing_pullback_bps = 25.0
    strat.profit_floor_start_bps = 45.0
    strat.profit_floor_bps = 20.0
    strat.model_repo_id = "Shadowell/SuperPnL"
    strat.model_revision = "main"
    strat.model_cache_dir = None
    strat.superpnl_max_signal_lag_bars = 3
    strat.superpnl_real_history_backfill = False
    strat.superpnl_backfill_cooldown_sec = 300.0
    strat.superpnl_backfill_min_interval_sec = 0.0
    strat._strategy_diagnostic_ws = True
    strat._strategy_diagnostic_every_n = 1
    strat._states = {symbol: SymbolState(latest_bar=bar(symbol)) for symbol in symbols}
    strat._seen_timestamps = set()
    strat._signal_universe_symbols = {str(symbol) for symbol in symbols}
    strat._signal_seen_symbols_by_ts = {}
    strat._collecting_universe_diag_ts = set()
    strat._missing_universe_diag_ts = set()
    strat._no_signal_diag_ts = set()
    strat._no_signal_symbol_diag_keys = set()
    strat._processed_signal_batch_ts = set()
    strat._portfolio_bar_index = 100
    strat._last_rebalance_bar = 0
    strat._events_seen = 1
    return strat


def make_contract_strategy(symbols, broker=None) -> SuperPnLContractMainstreamStrategy:
    state = StrategyState(
        strategy_id=199,
        name="[合约] SuperPnL unit",
        exchange="okx",
        symbols=list(symbols),
        created_at=datetime.utcnow(),
        status="running",
        positions={"_capital": 10_000.0},
    )
    strat = SuperPnLContractMainstreamStrategy(state, broker or FakeContractBroker())
    strat.timeframe = "1m"
    strat.horizon = "15m"
    strat.warmup_bars = 0
    strat.threshold_bps = 30.0
    strat.top_k = 1
    strat.rebalance_interval_bars = 1
    strat.min_holding_bars = 0
    strat.cooldown_bars = 60
    strat.max_position_per_symbol = 0.2
    strat.max_total_position = 0.2
    strat.min_order_notional_usdt = 50.0
    strat.min_bar_quote_volume_usdt = 0.0
    strat.allow_cash = True
    strat.fee_bps = 5.0
    strat.slippage_bps = 1.0
    strat.estimated_cost_bps = 6.0
    strat.take_profit_bps = 0.0
    strat.stop_loss_bps = 60.0
    strat.trailing_start_bps = 55.0
    strat.trailing_pullback_bps = 25.0
    strat.profit_floor_start_bps = 45.0
    strat.profit_floor_bps = 20.0
    strat.leverage = 2.0
    strat.model_repo_id = "Shadowell/SuperPnL"
    strat.model_revision = "main"
    strat.model_cache_dir = None
    strat.superpnl_max_signal_lag_bars = 3
    strat.superpnl_real_history_backfill = False
    strat.superpnl_backfill_cooldown_sec = 300.0
    strat.superpnl_backfill_min_interval_sec = 0.0
    strat._strategy_diagnostic_ws = True
    strat._strategy_diagnostic_every_n = 1
    spot_symbols = [str(symbol).replace(":USDT", "") for symbol in symbols]
    strat.trade_symbols = {spot_symbols[0]}
    strat._contract_symbol_by_spot = {
        spot: f"{spot}:USDT" if ":" not in spot else spot
        for spot in spot_symbols
    }
    strat._states = {symbol: SymbolState(latest_bar=bar(symbol)) for symbol in spot_symbols}
    strat._seen_timestamps = set()
    strat._signal_universe_symbols = set(spot_symbols)
    strat._signal_seen_symbols_by_ts = {}
    strat._collecting_universe_diag_ts = set()
    strat._missing_universe_diag_ts = set()
    strat._no_signal_diag_ts = set()
    strat._no_signal_symbol_diag_keys = set()
    strat._processed_signal_batch_ts = set()
    strat._portfolio_bar_index = 100
    strat._last_rebalance_bar = 0
    strat._events_seen = 1
    strat._recent_trade_wins = []
    strat._entry_guard_until_bar = 0
    strat._risk_blacklisted_symbols = set()
    return strat


def collect_diagnostics(strat):
    events = []

    async def _emit(_bar, decision, **kwargs):
        events.append((decision, kwargs))

    strat._emit_diag = _emit
    return events


class FakeSuperPnLInferenceService:
    def __init__(self, symbols, *, require_backfill: bool = False):
        self.is_ready = True
        self.last_error = None
        self.model_dir = "/tmp/unit-superpnl"
        self.universe_symbols = list(symbols)
        self.require_backfill = require_backfill
        self.backfilled = False
        self.updates: list[BarData] = []
        self.predict_calls: list[tuple[int, str]] = []
        self.backfill_calls = 0

    async def initialize(self, **_kwargs):
        return None

    async def update_bar(self, update: BarData) -> None:
        self.updates.append(update)

    def latest_complete_timestamp(self, timestamp_ms: int):
        if self.require_backfill and not self.backfilled:
            return None
        status = self.get_build_status(timestamp_ms)
        if status["current_missing_count"] > 0:
            return None
        return canonical_bar_timestamp_ms(int(timestamp_ms))

    def get_build_status(self, timestamp_ms: int):
        ts = canonical_bar_timestamp_ms(int(timestamp_ms))
        seen = sorted(
            {
                update.symbol
                for update in self.updates
                if canonical_bar_timestamp_ms(update.timestamp) == ts
            }
        )
        missing = [symbol for symbol in self.universe_symbols if symbol not in set(seen)]
        latest = None if missing or (self.require_backfill and not self.backfilled) else ts
        return {
            "timestamp_ms": ts,
            "expected_count": len(self.universe_symbols),
            "current_seen_count": len(seen),
            "current_missing_count": len(missing),
            "current_seen_symbols": seen,
            "current_missing_symbols": missing,
            "history_missing_symbols": [] if latest is not None else list(self.universe_symbols),
            "latest_complete_timestamp_ms": latest,
            "latest_complete_lag_bars": 0 if latest is not None else None,
            "reference_symbol": self.universe_symbols[0] if self.universe_symbols else None,
            "required_history_bars": 4,
            "per_symbol_buffers": [
                {
                    "symbol": symbol,
                    "buffer_count": sum(1 for update in self.updates if update.symbol == symbol),
                    "latest_timestamp_ms": ts if symbol in seen else None,
                    "has_current_bar": symbol in seen,
                }
                for symbol in self.universe_symbols
            ],
            "reason": "ready" if latest is not None else "history_window_incomplete",
        }

    async def backfill_history_from_exchange(self, **_kwargs):
        self.backfill_calls += 1
        self.backfilled = True
        return {"attempted": True, "reason": "completed", "total_loaded_count": 8}

    async def predict_timestamp(self, timestamp_ms: int, horizon: str = "15m"):
        ts = canonical_bar_timestamp_ms(int(timestamp_ms))
        self.predict_calls.append((ts, horizon))
        return {
            symbol: signal(symbol, 0.010 if symbol == "BTC/USDT" else 0.005, ts)
            for symbol in self.universe_symbols
        }


def test_target_builder_respects_top_k_and_max_total_position():
    strat = make_strategy(["BTC/USDT", "ETH/USDT", "LTC/USDT"])
    ranked = [
        (0.010, "BTC/USDT", signal("BTC/USDT", 0.010)),
        (0.009, "ETH/USDT", signal("ETH/USDT", 0.009)),
        (0.008, "LTC/USDT", signal("LTC/USDT", 0.008)),
    ]
    result = strat._build_target_positions(ranked)
    targets = result["targets"]
    assert list(targets) == ["BTC/USDT"]
    assert sum(targets.values()) <= 0.1
    assert targets["BTC/USDT"] == 0.1


def test_target_builder_scales_down_when_total_cap_is_exceeded():
    strat = make_strategy(["BTC/USDT", "ETH/USDT"])
    strat.top_k = 2
    strat.max_position_per_symbol = 0.2
    strat.max_total_position = 0.1
    ranked = [
        (0.010, "BTC/USDT", signal("BTC/USDT", 0.010)),
        (0.009, "ETH/USDT", signal("ETH/USDT", 0.009)),
    ]
    result = strat._build_target_positions(ranked)
    assert sum(result["targets"].values()) <= 0.1
    assert result["target_total_after_cap"] <= 0.1


def test_rebalance_closes_non_topk_old_position_after_min_holding():
    broker = FakeBroker(
        cash=9000.0,
        positions={"LTC/USDT": {"size": 10.0, "entry_price": 100.0, "mark_price": 100.0}},
        prices={"BTC/USDT": 100.0, "LTC/USDT": 100.0},
    )
    strat = make_strategy(["BTC/USDT", "LTC/USDT"], broker)
    events = collect_diagnostics(strat)
    strat._states["BTC/USDT"].latest_signal = signal("BTC/USDT", 0.010)
    strat._states["LTC/USDT"].latest_signal = signal("LTC/USDT", 0.001)

    asyncio.run(strat._rebalance(bar("BTC/USDT")))

    assert any(o["side"] == "sell" and o["symbol"] == "LTC/USDT" for o in broker.orders)
    assert any(decision == "close_non_topk" for decision, _ in events)


def test_rebalance_keeps_non_topk_position_during_min_holding():
    broker = FakeBroker(
        cash=9000.0,
        positions={"LTC/USDT": {"size": 10.0, "entry_price": 100.0, "mark_price": 100.0}},
        prices={"BTC/USDT": 100.0, "LTC/USDT": 100.0},
    )
    strat = make_strategy(["BTC/USDT", "LTC/USDT"], broker)
    events = collect_diagnostics(strat)
    strat._states["BTC/USDT"].latest_signal = signal("BTC/USDT", 0.010)
    strat._states["LTC/USDT"].latest_signal = signal("LTC/USDT", 0.001)
    strat._states["LTC/USDT"].qty = 10.0
    strat._states["LTC/USDT"].holding_start_bar = strat._portfolio_bar_index - 10

    asyncio.run(strat._rebalance(bar("BTC/USDT")))

    assert not any(o["side"] == "sell" and o["symbol"] == "LTC/USDT" for o in broker.orders)
    assert any(decision == "skip_min_holding" for decision, _ in events)


def test_profit_floor_exits_winning_position_before_it_turns_loss():
    broker = FakeBroker(
        cash=9_900.0,
        positions={"BTC/USDT": {"size": 1.0, "entry_price": 100.0, "mark_price": 100.25}},
        prices={"BTC/USDT": 100.25},
    )
    strat = make_strategy(["BTC/USDT"], broker)
    events = collect_diagnostics(strat)
    strat.profit_floor_start_bps = 50.0
    strat.profit_floor_bps = 30.0
    state = strat._states["BTC/USDT"]
    state.qty = 1.0
    state.entry_price = 100.0
    state.peak_price = 101.0
    state.holding_start_bar = strat._portfolio_bar_index - 5
    state.latest_bar = bar("BTC/USDT", 100.25)

    exited = asyncio.run(strat._manage_profit_protection(bar("BTC/USDT", 100.25)))

    assert exited is True
    assert broker.orders
    assert broker.orders[0]["side"] == "sell"
    assert events[-1][0] == "exit_profit_floor"
    assert round(events[-1][1]["pnl_bps"], 2) == 25.0


def test_rolling_win_rate_guard_blocks_new_entries_after_bad_sample():
    broker = FakeBroker(cash=10_000.0, positions={}, prices={"BTC/USDT": 100.0})
    strat = make_strategy(["BTC/USDT"], broker)
    events = collect_diagnostics(strat)
    strat.rolling_win_rate_min_trades = 4
    strat.rolling_win_rate_threshold = 0.55
    strat.rolling_win_rate_cooldown_bars = 8
    strat._recent_trade_wins = [False, False, True, False]
    strat._states["BTC/USDT"].latest_signal = signal("BTC/USDT", 0.020)

    asyncio.run(strat._rebalance(bar("BTC/USDT")))

    assert broker.orders == []
    assert strat._entry_guard_until_bar == strat._portfolio_bar_index + 8
    assert events[-1][0] == "skip_win_rate_guard"
    assert events[-1][1]["rolling_win_rate"] == 0.25


def test_symbol_consecutive_losses_cooldown_blocks_reentry_and_blacklists():
    broker = FakeBroker(cash=10_000.0, positions={}, prices={"BTC/USDT": 100.0})
    strat = make_strategy(["BTC/USDT"], broker)
    events = collect_diagnostics(strat)
    state = strat._states["BTC/USDT"]
    strat.max_symbol_consecutive_losses = 2
    strat.symbol_loss_cooldown_bars = 12
    strat.symbol_blacklist_after_losses = 3

    strat._record_closed_trade_outcome("BTC/USDT", -20.0)
    strat._record_closed_trade_outcome("BTC/USDT", -5.0)

    assert state.consecutive_losses == 2
    assert state.loss_cooldown_until_bar == strat._portfolio_bar_index + 12

    state.latest_signal = signal("BTC/USDT", 0.020)
    asyncio.run(strat._rebalance(bar("BTC/USDT")))

    assert broker.orders == []
    assert events[-1][0] == "skip_symbol_loss_cooldown"

    strat._record_closed_trade_outcome("BTC/USDT", -1.0)

    assert "BTC/USDT" in strat._risk_blacklisted_symbols


def test_superpnl_seed_entries_are_not_active():
    seed_path = ROOT / "data" / "seed" / "strategies.json"
    strategies = json.loads(seed_path.read_text())

    assert not [
        item["name"]
        for item in strategies
        if "SuperPnL" in item.get("name", "")
        or str(item.get("strategy_key", "")).startswith("superpnl_")
    ]


def test_contract_superpnl_opens_swap_long_instead_of_spot_buy():
    broker = FakeContractBroker(cash=10_000.0, prices={"BTC/USDT:USDT": 100.0})
    strat = make_contract_strategy(["BTC/USDT:USDT"], broker)
    account = AccountSnapshot(cash_usdt=10_000.0, equity=10_000.0, positions={})

    asyncio.run(
        strat._buy_to_target(
            "BTC/USDT",
            bar("BTC/USDT", 100.0),
            target=0.2,
            current=0.0,
            account=account,
            signal=signal("BTC/USDT", 0.010),
            rank=1,
        )
    )

    assert broker.orders == [
        {
            "action": "open",
            "symbol": "BTC/USDT:USDT",
            "side": "long",
            "notional": 2000.0,
            "leverage": 2.0,
        }
    ]


def test_contract_superpnl_maps_contract_feed_to_spot_signal_and_swap_order(monkeypatch):
    fake_service = FakeSuperPnLInferenceService(["BTC/USDT", "ETH/USDT"])
    monkeypatch.setattr(superpnl_strategy_module, "superpnl_model_inference_service", fake_service)
    broker = FakeContractBroker(
        cash=10_000.0,
        prices={"BTC/USDT:USDT": 100.0, "ETH/USDT:USDT": 200.0},
    )
    strat = make_contract_strategy(["BTC/USDT:USDT", "ETH/USDT:USDT"], broker)
    events = collect_diagnostics(strat)
    ts = canonical_bar_timestamp_ms(1_800_000_000_000)

    asyncio.run(strat.on_bar(bar("BTC/USDT:USDT", 100.0, ts)))
    asyncio.run(strat.on_bar(bar("ETH/USDT:USDT", 200.0, ts)))

    assert [update.symbol for update in fake_service.updates] == ["BTC/USDT", "ETH/USDT"]
    assert fake_service.predict_calls == [(ts, "15m")]
    assert broker.orders[0]["action"] == "open"
    assert broker.orders[0]["symbol"] == "BTC/USDT:USDT"
    assert not any(order["action"].startswith("spot_") for order in broker.orders)
    assert any(decision == "buy_filled" for decision, _ in events)


def test_contract_profit_floor_closes_swap_long():
    broker = FakeContractBroker(
        cash=9_900.0,
        positions={
            ("BTC/USDT:USDT", "long"): {
                "symbol": "BTC/USDT:USDT",
                "pos_side": "long",
                "base_qty": 1.0,
                "contracts": 1.0,
                "entry_price": 100.0,
                "mark_price": 100.25,
                "notional_usdt": 100.25,
                "unrealized_pnl": 0.25,
            }
        },
        prices={"BTC/USDT:USDT": 100.25},
    )
    broker.equity = 10_000.25
    strat = make_contract_strategy(["BTC/USDT:USDT"], broker)
    events = collect_diagnostics(strat)
    strat.profit_floor_start_bps = 50.0
    strat.profit_floor_bps = 30.0
    state = strat._states["BTC/USDT"]
    state.qty = 1.0
    state.entry_price = 100.0
    state.peak_price = 101.0
    state.holding_start_bar = strat._portfolio_bar_index - 5
    state.latest_bar = bar("BTC/USDT", 100.25)

    exited = asyncio.run(strat._manage_profit_protection(bar("BTC/USDT", 100.25)))

    assert exited is True
    assert broker.orders[-1]["action"] == "close"
    assert broker.orders[-1]["symbol"] == "BTC/USDT:USDT"
    assert events[-1][0] == "exit_profit_floor"


def test_small_delta_notional_is_not_ordered():
    broker = FakeBroker(cash=901.0, positions={"BTC/USDT": {"size": 0.99, "entry_price": 100.0, "mark_price": 100.0}}, prices={"BTC/USDT": 100.0})
    strat = make_strategy(["BTC/USDT"], broker)
    events = collect_diagnostics(strat)
    account = AccountSnapshot(
        cash_usdt=901.0,
        equity=1000.0,
        positions={"BTC/USDT": PositionSnapshot("BTC/USDT", 0.99, 100.0, 99.0, 100.0, 0.0)},
    )

    asyncio.run(
        strat._buy_to_target(
            "BTC/USDT",
            bar("BTC/USDT"),
            target=0.1,
            current=0.099,
            account=account,
            signal=signal("BTC/USDT", 0.010),
            rank=1,
        )
    )

    assert broker.orders == []
    assert events[-1][0] == "skip_qty_too_small"


def test_broker_position_overrides_strategy_cache_for_weight():
    broker = FakeBroker(
        cash=9000.0,
        positions={"LTC/USDT": {"size": 10.0, "entry_price": 100.0, "mark_price": 100.0}},
        prices={"LTC/USDT": 100.0},
    )
    strat = make_strategy(["LTC/USDT"], broker)
    strat._states["LTC/USDT"].qty = 0.0
    account = asyncio.run(strat._get_account_snapshot())

    assert strat._current_weight("LTC/USDT", account) == 0.1


def test_signal_universe_tracking_reports_missing_symbols_once():
    strat = make_strategy(["BTC/USDT", "ETH/USDT", "LTC/USDT"])
    signal_ts = canonical_bar_timestamp_ms(1_800_000_012_345)

    seen_count, expected_count, missing = strat._mark_signal_bar_seen(signal_ts, "BTC/USDT")

    assert seen_count == 1
    assert expected_count == 3
    assert missing == ["ETH/USDT", "LTC/USDT"]
    assert strat._claim_missing_universe_diag(signal_ts) is True
    assert strat._claim_missing_universe_diag(signal_ts) is False


def test_target_to_qty_uses_account_equity_and_close_price():
    broker = FakeBroker(cash=10_000.0, positions={}, prices={"BTC/USDT": 100.0})
    strat = make_strategy(["BTC/USDT"], broker)
    account = AccountSnapshot(cash_usdt=10_000.0, equity=10_000.0, positions={})

    asyncio.run(
        strat._buy_to_target(
            "BTC/USDT",
            bar("BTC/USDT", 100.0),
            target=0.1,
            current=0.0,
            account=account,
            signal=signal("BTC/USDT", 0.010),
            rank=1,
        )
    )

    assert broker.orders[0]["amount"] == 10.0
    assert broker.orders[0]["notional"] == 1000.0


def test_low_liquidity_gate_blocks_new_or_increased_entry():
    broker = FakeBroker(cash=10_000.0, positions={}, prices={"BTC/USDT": 100.0})
    strat = make_strategy(["BTC/USDT"], broker)
    strat.min_bar_quote_volume_usdt = 50_000.0
    account = AccountSnapshot(cash_usdt=10_000.0, equity=10_000.0, positions={})
    events = collect_diagnostics(strat)

    asyncio.run(
        strat._buy_to_target(
            "BTC/USDT",
            bar("BTC/USDT", close=100.0),
            target=0.1,
            current=0.0,
            account=account,
            signal=signal("BTC/USDT", 0.010),
            rank=1,
        )
    )

    assert broker.orders == []
    assert events[-1][0] == "skip_low_liquidity"
    assert events[-1][1]["bar_quote_volume_usdt"] == 100.0
    assert events[-1][1]["min_bar_quote_volume_usdt"] == 50_000.0


def test_empty_candidates_clear_unprotected_old_positions():
    broker = FakeBroker(
        cash=9000.0,
        positions={"LTC/USDT": {"size": 10.0, "entry_price": 100.0, "mark_price": 100.0}},
        prices={"LTC/USDT": 100.0},
    )
    strat = make_strategy(["LTC/USDT"], broker)
    strat._states["LTC/USDT"].latest_signal = signal("LTC/USDT", 0.001)

    asyncio.run(strat._rebalance(bar("LTC/USDT")))

    assert any(o["side"] == "sell" and o["symbol"] == "LTC/USDT" for o in broker.orders)


def test_rebalance_can_use_latest_complete_lagged_signal_timestamp():
    broker = FakeBroker(cash=10_000.0, positions={}, prices={"BTC/USDT": 100.0})
    strat = make_strategy(["BTC/USDT"], broker)
    current_ts = canonical_bar_timestamp_ms(1_800_000_120_000)
    lagged_ts = current_ts - 60_000
    strat._states["BTC/USDT"].latest_bar = bar("BTC/USDT", 100.0, current_ts)
    strat._states["BTC/USDT"].latest_signal = signal("BTC/USDT", 0.010, lagged_ts)

    asyncio.run(strat._rebalance(bar("BTC/USDT", 100.0, current_ts), signal_ts=lagged_ts))

    assert broker.orders
    assert broker.orders[0]["side"] == "buy"


def test_trade_symbols_limit_entries_while_full_universe_feeds_model():
    broker = FakeBroker(
        cash=10_000.0,
        positions={},
        prices={"BTC/USDT": 100.0, "ZKJ/USDT": 2.0},
    )
    strat = make_strategy(["BTC/USDT", "ZKJ/USDT"], broker)
    strat.trade_symbols = {"ZKJ/USDT"}
    strat._states["BTC/USDT"].latest_signal = signal("BTC/USDT", 0.020)
    strat._states["ZKJ/USDT"].latest_signal = signal("ZKJ/USDT", 0.010)

    asyncio.run(strat._rebalance(bar("BTC/USDT")))

    assert broker.orders
    assert broker.orders[0]["symbol"] == "ZKJ/USDT"


def test_empty_rebalance_without_candidate_does_not_reset_entry_check():
    broker = FakeBroker(cash=10_000.0, positions={}, prices={"BTC/USDT": 100.0})
    strat = make_strategy(["BTC/USDT"], broker)
    strat._states["BTC/USDT"].latest_bar = bar("BTC/USDT")
    strat._states["BTC/USDT"].latest_signal = signal("BTC/USDT", 0.001)
    strat.threshold_bps = 30.0
    strat._last_rebalance_bar = 0
    events = collect_diagnostics(strat)

    asyncio.run(strat._rebalance(bar("BTC/USDT"), signal_ts=1_800_000_000_000))

    assert broker.orders == []
    assert strat._last_rebalance_bar == 0
    assert events[-1][0] == "skip_no_rebalance_candidate"
    assert events[-1][1]["top_signal_symbol"] == "BTC/USDT"


def test_on_bar_waits_for_complete_superpnl_batch_before_prediction(monkeypatch):
    fake_service = FakeSuperPnLInferenceService(["BTC/USDT", "ETH/USDT"])
    monkeypatch.setattr(superpnl_strategy_module, "superpnl_model_inference_service", fake_service)
    broker = FakeBroker(cash=10_000.0, prices={"BTC/USDT": 100.0, "ETH/USDT": 200.0})
    strat = make_strategy(["BTC/USDT", "ETH/USDT"], broker)
    strat.rebalance_interval_bars = 1
    strat.threshold_bps = 30.0
    events = collect_diagnostics(strat)
    ts = canonical_bar_timestamp_ms(1_800_000_000_000)

    asyncio.run(strat.on_bar(bar("BTC/USDT", 100.0, ts)))

    assert fake_service.predict_calls == []
    assert broker.orders == []
    assert events[-1][0] == "skip_missing_universe_bar"
    assert "完整 SuperPnL 币池分钟批次" in events[-1][1]["summary"]

    asyncio.run(strat.on_bar(bar("ETH/USDT", 200.0, ts)))

    assert fake_service.predict_calls == [(ts, "15m")]
    assert broker.orders
    assert broker.orders[0]["symbol"] == "BTC/USDT"


def test_on_bar_backfills_real_history_once_after_complete_batch(monkeypatch):
    fake_service = FakeSuperPnLInferenceService(["BTC/USDT", "ETH/USDT"], require_backfill=True)
    monkeypatch.setattr(superpnl_strategy_module, "superpnl_model_inference_service", fake_service)
    broker = FakeBroker(cash=10_000.0, prices={"BTC/USDT": 100.0, "ETH/USDT": 200.0})
    strat = make_strategy(["BTC/USDT", "ETH/USDT"], broker)
    strat.superpnl_real_history_backfill = True
    strat.superpnl_backfill_cooldown_sec = 0.0
    strat.superpnl_backfill_min_interval_sec = 0.0
    strat.rebalance_interval_bars = 1
    ts = canonical_bar_timestamp_ms(1_800_000_060_000)

    asyncio.run(strat.on_bar(bar("BTC/USDT", 100.0, ts)))
    asyncio.run(strat.on_bar(bar("ETH/USDT", 200.0, ts)))

    assert fake_service.backfill_calls == 1
    assert fake_service.predict_calls == [(ts, "15m")]
    assert broker.orders


def test_feature_builder_buckets_realtime_event_timestamps_to_minute():
    builder = SuperPnLFeatureBuilder(
        symbols=["BTC/USDT", "ETH/USDT"],
        lookback=2,
        feature_windows=[1],
        bar_feature_names=["open_rel", "high_rel", "low_rel", "close_rel"],
        feature_names=[
            "ret_1m",
            "rsi_1m",
            "vol_std_1m",
            "ma_dev_1m",
            "boll_z_1m",
            "market_ret_1m",
            "market_vol_1m",
            "cross_section_ret_rank_1m",
            "cross_section_vol_rank_1m",
            "hour_sin",
            "hour_cos",
            "dayofweek_sin",
            "dayofweek_cos",
        ],
    )
    base_ts = 1_800_000_000_000
    minute_ts = canonical_bar_timestamp_ms(base_ts)
    for idx in range(4):
        ts = minute_ts + idx * 60_000
        builder.update_bar(bar("BTC/USDT", close=100 + idx, ts=ts + 150))
        builder.update_bar(bar("ETH/USDT", close=200 + idx, ts=ts + 950))

    batch = builder.build(minute_ts + 3 * 60_000 + 2_500)

    assert batch is not None
    assert batch.timestamp_ms == minute_ts + 3 * 60_000
    assert batch.symbols == ["BTC/USDT", "ETH/USDT"]

    next_ts = minute_ts + 4 * 60_000
    builder.update_bar(bar("BTC/USDT", close=104, ts=next_ts + 200))

    assert builder.build(next_ts) is None
    assert builder.latest_complete_timestamp(next_ts) == minute_ts + 3 * 60_000
    status = builder.build_status(next_ts)
    assert status["latest_complete_timestamp_ms"] == minute_ts + 3 * 60_000
    assert status["latest_complete_lag_bars"] == 1
    assert status["reason"] == "current_universe_incomplete"
    assert status["current_missing_symbols"] == ["ETH/USDT"]
    per_symbol = {item["symbol"]: item for item in status["per_symbol_buffers"]}
    assert per_symbol["BTC/USDT"]["has_current_bar"] is True
    assert per_symbol["ETH/USDT"]["has_current_bar"] is False
    assert per_symbol["ETH/USDT"]["buffer_count"] == 4


def test_feature_builder_allows_concurrent_reads_and_updates_without_ordered_dict_error():
    builder = SuperPnLFeatureBuilder(
        symbols=["BTC/USDT", "ETH/USDT"],
        lookback=2,
        feature_windows=[1],
        bar_feature_names=["open_rel", "high_rel", "low_rel", "close_rel"],
        feature_names=[
            "ret_1m",
            "rsi_1m",
            "vol_std_1m",
            "ma_dev_1m",
            "boll_z_1m",
            "market_ret_1m",
            "market_vol_1m",
            "cross_section_ret_rank_1m",
            "cross_section_vol_rank_1m",
            "hour_sin",
            "hour_cos",
            "dayofweek_sin",
            "dayofweek_cos",
        ],
    )
    base_ts = canonical_bar_timestamp_ms(1_800_000_000_000)
    for idx in range(6):
        ts = base_ts + idx * 60_000
        builder.update_bar(bar("BTC/USDT", close=100 + idx, ts=ts))
        builder.update_bar(bar("ETH/USDT", close=200 + idx, ts=ts))

    errors: list[BaseException] = []

    def writer() -> None:
        try:
            for idx in range(6, 180):
                ts = base_ts + idx * 60_000
                builder.update_bar(bar("BTC/USDT", close=100 + idx, ts=ts))
                builder.update_bar(bar("ETH/USDT", close=200 + idx, ts=ts))
        except BaseException as exc:  # pragma: no cover - failure path asserted below
            errors.append(exc)

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        for idx in range(6, 180):
            ts = base_ts + idx * 60_000
            builder.latest_complete_timestamp(ts)
            builder.build_status(ts)
            builder.build(ts)
    finally:
        thread.join(timeout=2)

    assert not thread.is_alive()
    assert errors == []
