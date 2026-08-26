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
from app.strategies.okx_contract_funding_carry_strategy import OkxContractFundingCarryStrategy
import app.strategies.okx_contract_funding_carry_strategy as strategy_module


BASE_TS = 1_800_000_000_000
FUNDING_TS = BASE_TS + 120_000
NEXT_CYCLE_TS = FUNDING_TS + 480 * 60_000


class FakeFundingService:
    def __init__(self, opportunities=None, rates=None):
        self.opportunities = list(opportunities or [])
        self.rates = dict(rates or {})
        self.opportunity_calls = []
        self.rate_calls = []

    async def get_opportunities(self, exchange, min_rate, limit=20):
        self.opportunity_calls.append((exchange, min_rate, limit))
        return list(self.opportunities)

    async def get_funding_rate(self, exchange, symbol):
        self.rate_calls.append((exchange, symbol))
        value = self.rates.get(symbol, {"current_rate": 0.0})
        if isinstance(value, list):
            if len(value) > 1:
                return dict(value.pop(0))
            return dict(value[0])
        if isinstance(value, dict):
            return dict(value)
        return {"current_rate": float(value)}


class FakeContractOnlyBroker:
    def __init__(self, *, available_balance=10_000.0):
        self.available_balance = float(available_balance)
        self.contract_positions = {}
        self.orders = []
        self.funding_events = []
        self.warmup_mode = False

    async def get_available_balance(self, currency="USDT"):
        return self.available_balance

    def min_contract_notional(self, symbol, price):
        return 0.0

    async def buy(self, *args, **kwargs):
        raise AssertionError("contract funding carry must not buy spot")

    async def sell(self, *args, **kwargs):
        raise AssertionError("contract funding carry must not sell spot")

    async def open_contract(self, symbol, side, notional_usdt, leverage=None, price=None):
        self.contract_positions[(symbol, side)] = {
            "symbol": symbol,
            "pos_side": side,
            "notional_usdt": float(notional_usdt),
            "entry_price": float(price),
        }
        self.orders.append(("open_contract", symbol, side, float(notional_usdt), float(leverage), float(price)))
        return OrderResult(
            {
                "status": "filled",
                "symbol": symbol,
                "pos_side": side,
                "notional_usdt": float(notional_usdt),
                "price": float(price),
            }
        )

    async def close_contract(self, symbol, side, ratio=1.0, contracts=None, price=None):
        self.contract_positions.pop((symbol, side), None)
        self.orders.append(("close_contract", symbol, side, float(ratio), float(price)))
        return OrderResult({"status": "filled", "symbol": symbol, "pos_side": side, "price": float(price)})

    async def get_contract_position(self, symbol, side):
        return self.contract_positions.get((symbol, side))

    def apply_funding(self, symbol, funding_rate):
        self.funding_events.append((symbol, float(funding_rate)))
        return [{"symbol": symbol, "funding_rate": float(funding_rate), "cash_delta": 1.0}]


def make_state() -> StrategyState:
    return StrategyState(
        strategy_id=955,
        name="[合约][1M][信号] 全市场 · 资金费率方向信号 · 100U",
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
        created_at=datetime.utcnow(),
        status="running",
    )


def make_bar(symbol="BTC/USDT:USDT", close=50_000.0, timestamp=BASE_TS) -> BarData:
    return BarData(
        exchange="okx",
        symbol=symbol,
        timeframe="1m",
        timestamp=timestamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=100,
    )


def make_strategy(broker, config=None) -> OkxContractFundingCarryStrategy:
    strategy = OkxContractFundingCarryStrategy(make_state(), broker)
    strategy.set_config(
        {
            "margin_per_symbol_usdt": 20.0,
            "position_notional_usdt": 200.0,
            "min_funding_rate_per_event": 0.003,
            "max_active_symbols": 3,
            "poll_interval_seconds": 1,
            "settlement_entry_window_minutes": 3,
            "no_entry_before_settlement_seconds": 60,
            "post_settlement_close_delay_seconds": 60,
            "min_net_edge_bps": 5,
            "taker_fee_bps": 5,
            "slippage_bps": 5,
            "leverage": 10,
            "hard_stop_loss_pct": 0.08,
            "hard_take_profit_pct": 0.0,
            "profit_protection_enabled": True,
            "profit_trailing_start_pct": 0.12,
            "profit_peak_pullback_pct": 0.35,
            "profit_tighten_at_pct": 0.25,
            "profit_tight_pullback_pct": 0.20,
            "allowed_symbols": ["BTC/USDT:USDT"],
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy


def test_contract_funding_carry_opens_top_three_absolute_rates_inside_window(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(
            opportunities=[
                {"symbol": "AAA/USDT:USDT", "rate": -0.0029, "mark_price": 1.0, "next_funding_time": FUNDING_TS},
                {"symbol": "BBB/USDT:USDT", "rate": -0.0031, "mark_price": 2.0, "next_funding_time": FUNDING_TS},
                {"symbol": "CCC/USDT:USDT", "rate": 0.0040, "mark_price": 3.0, "next_funding_time": FUNDING_TS},
                {"symbol": "DDD/USDT:USDT", "rate": -0.0060, "mark_price": 4.0, "next_funding_time": FUNDING_TS},
                {"symbol": "EEE/USDT:USDT", "rate": 0.0035, "mark_price": 5.0, "next_funding_time": FUNDING_TS},
            ]
        ),
    )
    broker = FakeContractOnlyBroker()
    strategy = make_strategy(broker)
    events = []

    async def capture(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture

    asyncio.run(strategy.on_bar(make_bar()))

    assert broker.orders == [
        ("open_contract", "DDD/USDT:USDT", "short", 200.0, 10.0, 4.0),
        ("open_contract", "CCC/USDT:USDT", "long", 200.0, 10.0, 3.0),
        ("open_contract", "EEE/USDT:USDT", "long", 200.0, 10.0, 5.0),
    ]
    assert sorted(strategy.active_positions) == ["CCC/USDT:USDT", "DDD/USDT:USDT", "EEE/USDT:USDT"]
    open_events = [event for event in events if event["decision"] == "open_contract_carry"]
    assert len(open_events) == 3
    first_details = open_events[0]["details"]
    assert first_details["symbol"] == "DDD/USDT:USDT"
    assert first_details["direction"] == "short"
    assert first_details["notional_usdt"] == 200.0
    assert first_details["margin_usdt"] == 20.0
    assert first_details["leverage"] == 10.0
    assert first_details["min_funding_rate_per_event"] == 0.003
    assert first_details["funding_rate"] == -0.006
    assert first_details["estimated_funding_payment_bps"] == pytest.approx(60.0)
    assert first_details["next_funding_timestamp_ms"] == FUNDING_TS
    assert first_details["seconds_to_funding"] == 120.0
    assert first_details["estimated_round_trip_cost_bps"] == 20.0
    assert first_details["estimated_net_signal_bps"] == pytest.approx(40.0)


def test_contract_funding_carry_waits_until_entry_window(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(
            opportunities=[
                {"symbol": "BTC/USDT:USDT", "rate": 0.0060, "mark_price": 50_000.0, "next_funding_time": BASE_TS + 600_000}
            ]
        ),
    )
    broker = FakeContractOnlyBroker()
    strategy = make_strategy(broker)

    asyncio.run(strategy.on_bar(make_bar()))

    assert broker.orders == []
    assert strategy.active_positions == {}


def test_contract_funding_carry_logs_estimated_open_time_and_event_rate_first(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(
            opportunities=[
                {
                    "symbol": "BTC/USDT:USDT",
                    "rate": 0.0060,
                    "mark_price": 50_000.0,
                    "next_funding_time": BASE_TS + 600_000,
                }
            ]
        ),
    )
    broker = FakeContractOnlyBroker()
    strategy = make_strategy(broker)
    events = []

    async def capture(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture

    asyncio.run(strategy.on_bar(make_bar()))

    scan_event = next(item for item in events if item["decision"] == "scan_contract_funding")
    assert "BTC/USDT:USDT +0.6000%/次(+657.00%/年)" in scan_event["summary"]
    assert "预计开仓" in scan_event["summary"]
    top_row = scan_event["details"]["top_funding_rates"][0]
    assert top_row["estimated_open_timestamp_ms"] == BASE_TS + 420_000
    assert top_row["estimated_open_time"]

    skip_event = next(item for item in events if item["decision"] == "open_skipped")
    assert "预计开仓" in skip_event["summary"]
    assert skip_event["details"]["estimated_open_timestamp_ms"] == BASE_TS + 420_000
    assert skip_event["details"]["estimated_open_time"] == top_row["estimated_open_time"]


def test_contract_funding_carry_stops_new_entries_in_final_seconds(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(
            opportunities=[
                {"symbol": "BTC/USDT:USDT", "rate": 0.0060, "mark_price": 50_000.0, "next_funding_time": BASE_TS + 30_000}
            ]
        ),
    )
    broker = FakeContractOnlyBroker()
    strategy = make_strategy(broker)

    asyncio.run(strategy.on_bar(make_bar()))

    assert broker.orders == []
    assert strategy.active_positions == {}


def test_contract_funding_carry_does_not_estimate_next_cycle_from_default_period(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(
            opportunities=[
                {"symbol": "BTC/USDT:USDT", "rate": 0.0060, "mark_price": 50_000.0, "next_funding_time": BASE_TS + 30_000}
            ]
        ),
    )
    broker = FakeContractOnlyBroker()
    strategy = make_strategy(broker)
    events = []

    async def capture(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture

    asyncio.run(strategy.on_bar(make_bar()))

    scan_event = next(item for item in events if item["decision"] == "scan_contract_funding")
    top_row = scan_event["details"]["top_funding_rates"][0]
    assert top_row["estimated_open_timestamp_ms"] is None
    assert top_row["estimated_open_time"] == ""
    assert "预计开仓" not in scan_event["summary"]

    skip_event = next(item for item in events if item["decision"] == "open_skipped")
    assert skip_event["details"]["estimated_open_timestamp_ms"] is None
    assert skip_event["details"]["estimated_open_time"] == ""
    assert "预计开仓" not in skip_event["summary"]


def test_contract_funding_carry_does_not_apply_funding_without_exchange_due_time(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(
            rates={
                "BTC/USDT:USDT": {
                    "current_rate": -0.0040,
                }
            }
        ),
    )
    broker = FakeContractOnlyBroker()
    broker.contract_positions[("BTC/USDT:USDT", "short")] = {
        "symbol": "BTC/USDT:USDT",
        "pos_side": "short",
        "notional_usdt": 200.0,
        "entry_price": 50_000.0,
    }
    strategy = make_strategy(broker)
    strategy.active_positions["BTC/USDT:USDT"] = {
        "contract_symbol": "BTC/USDT:USDT",
        "side": "short",
        "entry_timestamp_ms": BASE_TS,
        "entry_price": 50_000.0,
        "entry_funding_rate": -0.004,
        "notional_usdt": 200.0,
        "funding_collections": 0,
        "last_funding_timestamp_ms": BASE_TS,
    }
    events = []

    async def capture(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture

    asyncio.run(strategy.on_bar(make_bar(timestamp=BASE_TS + 480 * 60_000 + 61_000, close=50_100.0)))

    assert broker.funding_events == []
    assert not [order for order in broker.orders if order[0] == "close_contract"]
    assert strategy.active_positions["BTC/USDT:USDT"]["funding_collections"] == 0
    assert not [event for event in events if event["decision"] == "funding_collected"]


def test_contract_funding_carry_applies_due_funding_before_overwriting_next_cycle_and_closes(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(
            rates={
                "BTC/USDT:USDT": {
                    "current_rate": -0.0040,
                    "next_funding_time": NEXT_CYCLE_TS,
                }
            }
        ),
    )
    broker = FakeContractOnlyBroker()
    broker.contract_positions[("BTC/USDT:USDT", "short")] = {
        "symbol": "BTC/USDT:USDT",
        "pos_side": "short",
        "notional_usdt": 200.0,
        "entry_price": 50_000.0,
    }
    strategy = make_strategy(broker)
    strategy.active_positions["BTC/USDT:USDT"] = {
        "contract_symbol": "BTC/USDT:USDT",
        "side": "short",
        "entry_timestamp_ms": BASE_TS,
        "entry_price": 50_000.0,
        "entry_funding_rate": -0.004,
        "notional_usdt": 200.0,
        "funding_collections": 0,
        "last_funding_timestamp_ms": BASE_TS,
        "next_funding_timestamp_ms": FUNDING_TS,
    }

    asyncio.run(strategy.on_bar(make_bar(timestamp=FUNDING_TS + 61_000, close=50_100.0)))

    assert broker.funding_events == [("BTC/USDT:USDT", -0.004)]
    assert ("close_contract", "BTC/USDT:USDT", "short", 1.0, 50_100.0) in broker.orders
    assert strategy.active_positions == {}


def test_contract_funding_carry_closes_immediately_when_funding_signal_flips_before_settlement(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(
            rates={
                "BTC/USDT:USDT": {
                    "current_rate": 0.0040,
                    "next_funding_time": FUNDING_TS,
                }
            }
        ),
    )
    broker = FakeContractOnlyBroker()
    broker.contract_positions[("BTC/USDT:USDT", "short")] = {
        "symbol": "BTC/USDT:USDT",
        "pos_side": "short",
        "notional_usdt": 200.0,
        "entry_price": 50_000.0,
    }
    strategy = make_strategy(broker)
    strategy.active_positions["BTC/USDT:USDT"] = {
        "contract_symbol": "BTC/USDT:USDT",
        "side": "short",
        "entry_timestamp_ms": BASE_TS,
        "entry_price": 50_000.0,
        "entry_funding_rate": -0.004,
        "notional_usdt": 200.0,
        "funding_collections": 0,
        "last_funding_timestamp_ms": BASE_TS,
        "next_funding_timestamp_ms": FUNDING_TS,
    }

    asyncio.run(strategy.on_bar(make_bar(timestamp=FUNDING_TS - 90_000, close=50_100.0)))

    assert broker.funding_events == []
    assert ("close_contract", "BTC/USDT:USDT", "short", 1.0, 50_100.0) in broker.orders
    assert strategy.active_positions == {}


def test_contract_funding_carry_dynamic_stop_loss_closes_on_margin_roi(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(
            rates={
                "BTC/USDT:USDT": {
                    "current_rate": 0.0040,
                    "next_funding_time": FUNDING_TS,
                }
            }
        ),
    )
    broker = FakeContractOnlyBroker()
    broker.contract_positions[("BTC/USDT:USDT", "long")] = {
        "symbol": "BTC/USDT:USDT",
        "pos_side": "long",
        "notional_usdt": 200.0,
        "entry_price": 50_000.0,
    }
    strategy = make_strategy(broker)
    strategy.active_positions["BTC/USDT:USDT"] = {
        "contract_symbol": "BTC/USDT:USDT",
        "side": "long",
        "entry_timestamp_ms": BASE_TS,
        "entry_price": 50_000.0,
        "entry_funding_rate": 0.004,
        "notional_usdt": 200.0,
        "margin_usdt": 20.0,
        "leverage": 10,
        "funding_collections": 0,
        "last_funding_timestamp_ms": BASE_TS,
        "next_funding_timestamp_ms": FUNDING_TS,
    }
    events = []

    async def capture(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture

    asyncio.run(strategy.on_bar(make_bar(timestamp=BASE_TS + 30_000, close=49_500.0)))

    assert broker.funding_events == []
    assert ("close_contract", "BTC/USDT:USDT", "long", 1.0, 49_500.0) in broker.orders
    close_event = next(event for event in events if event["decision"] == "close_contract_carry")
    assert close_event["details"]["reason"] == "dynamic_stop_loss"
    assert close_event["details"]["current_margin_roi"] == pytest.approx(-0.10)
    assert strategy.active_positions == {}


def test_contract_funding_carry_dynamic_profit_pullback_closes(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(
            rates={
                "BTC/USDT:USDT": {
                    "current_rate": 0.0040,
                    "next_funding_time": FUNDING_TS,
                }
            }
        ),
    )
    broker = FakeContractOnlyBroker()
    broker.contract_positions[("BTC/USDT:USDT", "long")] = {
        "symbol": "BTC/USDT:USDT",
        "pos_side": "long",
        "notional_usdt": 200.0,
        "entry_price": 50_000.0,
    }
    strategy = make_strategy(broker)
    strategy.active_positions["BTC/USDT:USDT"] = {
        "contract_symbol": "BTC/USDT:USDT",
        "side": "long",
        "entry_timestamp_ms": BASE_TS,
        "entry_price": 50_000.0,
        "entry_funding_rate": 0.004,
        "notional_usdt": 200.0,
        "margin_usdt": 20.0,
        "leverage": 10,
        "funding_collections": 0,
        "last_funding_timestamp_ms": BASE_TS,
        "next_funding_timestamp_ms": FUNDING_TS,
        "peak_margin_roi": 0.20,
    }
    events = []

    async def capture(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture

    asyncio.run(strategy.on_bar(make_bar(timestamp=BASE_TS + 30_000, close=50_600.0)))

    assert ("close_contract", "BTC/USDT:USDT", "long", 1.0, 50_600.0) in broker.orders
    close_event = next(event for event in events if event["decision"] == "close_contract_carry")
    assert close_event["details"]["reason"] == "dynamic_profit_pullback"
    assert close_event["details"]["current_margin_roi"] == pytest.approx(0.12)
    assert close_event["details"]["peak_margin_roi"] == pytest.approx(0.20)
    assert strategy.active_positions == {}


def test_contract_funding_carry_maps_funding_rate_to_directional_signal():
    assert OkxContractFundingCarryStrategy._side_for_rate(0.003) == "long"
    assert OkxContractFundingCarryStrategy._side_for_rate(-0.003) == "short"
    assert OkxContractFundingCarryStrategy._side_matches_signal("long", 0.003) is True
    assert OkxContractFundingCarryStrategy._side_matches_signal("short", -0.003) is True
    assert OkxContractFundingCarryStrategy._side_matches_signal("long", -0.003) is False
    assert OkxContractFundingCarryStrategy._side_matches_signal("short", 0.003) is False
