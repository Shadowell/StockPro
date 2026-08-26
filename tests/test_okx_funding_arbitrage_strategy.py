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
from app.strategies.okx_funding_arbitrage_strategy import OkxFundingArbitrageStrategy
import app.strategies.okx_funding_arbitrage_strategy as strategy_module


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
        value = self.rates.get(symbol, 0.0)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, dict):
            row = dict(value)
            row.setdefault("current_rate", row.get("rate", 0.0))
            row.setdefault("symbol", symbol)
            return row
        return {"current_rate": value, "symbol": symbol}


class FakeHybridBroker:
    def __init__(
        self,
        *,
        available_balance=10_000.0,
        contract_fail=False,
        missing_contract_metadata=False,
        min_contract_notional_value=0.0,
        spot_markets=None,
        funding_apply_events=None,
        close_contract_fail=False,
    ):
        self.available_balance = float(available_balance)
        self.contract_fail = contract_fail
        self.missing_contract_metadata = missing_contract_metadata
        self.min_contract_notional_value = float(min_contract_notional_value)
        self.spot_markets = set(spot_markets or {"BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT", "PEPE/USDT"})
        self.funding_apply_events = funding_apply_events
        self.close_contract_fail = close_contract_fail
        self.close_contract_calls = 0
        self.spot_positions = {}
        self.contract_positions = {}
        self.orders = []
        self.funding_events = []
        self.warmup_mode = False

    async def get_available_balance(self, currency="USDT"):
        return self.available_balance

    def min_contract_notional(self, symbol, price):
        if self.missing_contract_metadata:
            raise ValueError(f"missing OKX SWAP instrument metadata for {symbol}")
        return self.min_contract_notional_value

    def has_spot_market(self, symbol):
        return symbol in self.spot_markets

    async def buy(self, symbol, amount, price=None, *, order_type="market"):
        qty = float(amount)
        px = float(price)
        self.spot_positions[symbol] = {
            "symbol": symbol,
            "size": qty,
            "entry_price": px,
        }
        self.orders.append(("buy", symbol, qty, px, order_type))
        return OrderResult({"status": "filled", "symbol": symbol, "amount": qty, "price": px, "cost": qty * px})

    async def sell(self, symbol, amount, price=None, *, order_type="market"):
        qty = float(amount)
        px = float(price)
        pos = self.spot_positions.get(symbol)
        if pos:
            pos["size"] = max(0.0, float(pos.get("size") or 0.0) - qty)
        self.orders.append(("sell", symbol, qty, px, order_type))
        return OrderResult({"status": "filled", "symbol": symbol, "amount": qty, "price": px, "cost": qty * px})

    async def open_contract(self, symbol, side, notional_usdt, leverage=None, price=None):
        if self.contract_fail:
            return OrderResult({"status": "rejected", "reason": "contract failed", "symbol": symbol, "pos_side": side})
        self.contract_positions[(symbol, side)] = {
            "symbol": symbol,
            "pos_side": side,
            "notional_usdt": float(notional_usdt),
        }
        self.orders.append(("open_contract", symbol, side, float(notional_usdt), float(leverage), float(price)))
        return OrderResult({"status": "filled", "symbol": symbol, "pos_side": side, "notional_usdt": float(notional_usdt), "price": float(price)})

    async def close_contract(self, symbol, side, ratio=1.0, contracts=None, price=None):
        self.close_contract_calls += 1
        if self.close_contract_fail:
            return OrderResult({"status": "rejected", "reason": "close failed", "symbol": symbol, "pos_side": side})
        self.contract_positions.pop((symbol, side), None)
        self.orders.append(("close_contract", symbol, side, float(ratio), float(price)))
        return OrderResult({"status": "filled", "symbol": symbol, "pos_side": side, "price": float(price)})

    async def get_contract_position(self, symbol, side):
        return self.contract_positions.get((symbol, side))

    def apply_funding(self, symbol, funding_rate):
        self.funding_events.append((symbol, float(funding_rate)))
        if self.funding_apply_events is not None:
            return list(self.funding_apply_events)
        return [{"symbol": symbol, "funding_rate": float(funding_rate), "cash_delta": 1.0}]


def make_state() -> StrategyState:
    return StrategyState(
        strategy_id=901,
        name="[合约] OKX 全市场资金费率套利",
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
        created_at=datetime.utcnow(),
        status="running",
    )


def make_bar(symbol="BTC/USDT:USDT", close=50_000.0, timestamp=1_800_000_000_000) -> BarData:
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


def make_strategy(broker, config=None) -> OkxFundingArbitrageStrategy:
    strategy = OkxFundingArbitrageStrategy(make_state(), broker)
    strategy.set_config(
        {
            "position_notional_usdt": 1_000.0,
            "min_annualized_rate": 0.40,
            "close_annualized_rate": 0.10,
            "max_active_symbols": 3,
            "poll_interval_seconds": 1,
            "funding_period_minutes": 480,
            "min_expected_funding_events": 24,
            "min_hold_funding_events": 1,
            "max_hold_funding_events": 6,
            "min_net_edge_bps": 5,
            "min_funding_rate_per_event": 0.003,
            "max_funding_failures": 3,
            "hedge_drift_threshold_pct": 0.02,
            "critical_hedge_drift_pct": 0.10,
            "taker_fee_bps": 5,
            "slippage_rate": 0.0001,
            "allowed_symbols": ["BTC/USDT:USDT"],
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy


def test_okx_funding_arbitrage_opens_spot_and_short_for_high_positive_rate(monkeypatch):
    next_funding_time = 1_800_000_060_000
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(opportunities=[{"symbol": "BTC/USDT:USDT", "rate": 0.0035, "next_funding_time": next_funding_time}]),
    )
    broker = FakeHybridBroker()
    strategy = make_strategy(broker)

    asyncio.run(strategy.on_bar(make_bar()))

    assert ("buy", "BTC/USDT", pytest.approx(0.02), 50_000.0, "market") in broker.orders
    assert ("open_contract", "BTC/USDT:USDT", "short", 1_000.0, 1.0, 50_000.0) in broker.orders
    assert "BTC/USDT:USDT" in strategy.active_positions
    assert strategy.active_positions["BTC/USDT:USDT"]["next_funding_timestamp_ms"] == next_funding_time


def test_okx_funding_arbitrage_full_market_scan_is_not_limited_by_configured_symbols(monkeypatch):
    next_funding_time = 1_800_000_060_000
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(opportunities=[{"symbol": "ETH/USDT:USDT", "rate": 0.0035, "next_funding_time": next_funding_time}]),
    )
    broker = FakeHybridBroker()
    strategy = make_strategy(
        broker,
        {
            "allowed_symbols": ["BTC/USDT:USDT"],
            "trade_symbols": ["BTC/USDT:USDT"],
        },
    )
    strategy._remember_price("ETH/USDT:USDT", 4_000.0)

    asyncio.run(strategy.on_bar(make_bar(symbol="BTC/USDT:USDT", close=50_000.0)))

    assert ("buy", "ETH/USDT", pytest.approx(0.25), 4_000.0, "market") in broker.orders
    assert ("open_contract", "ETH/USDT:USDT", "short", 1_000.0, 1.0, 4_000.0) in broker.orders
    assert "ETH/USDT:USDT" in strategy.active_positions


def test_okx_funding_arbitrage_skips_negative_rate_instead_of_opening_contract_leg(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(opportunities=[{"symbol": "BTC/USDT:USDT", "rate": -0.004, "next_funding_time": 1_800_000_060_000}]),
    )
    broker = FakeHybridBroker()
    strategy = make_strategy(broker)
    events = []

    async def capture(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture

    asyncio.run(strategy.on_bar(make_bar()))

    assert broker.orders == []
    skip_event = next(item for item in events if item["decision"] == "open_skipped")
    assert skip_event["details"]["skip_reason"] == "negative_funding_rate"
    assert "负资金费率" in skip_event["summary"]


def test_okx_funding_arbitrage_requires_exchange_next_funding_time_for_entry(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(opportunities=[{"symbol": "BTC/USDT:USDT", "rate": 0.004}]),
    )
    broker = FakeHybridBroker()
    strategy = make_strategy(broker)
    events = []

    async def capture(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture

    asyncio.run(strategy.on_bar(make_bar()))

    assert broker.orders == []
    skip_event = next(item for item in events if item["decision"] == "open_skipped")
    assert skip_event["details"]["skip_reason"] == "missing_next_funding_time"
    assert "结算时间" in skip_event["summary"]


def test_okx_funding_arbitrage_skips_when_matching_spot_market_is_missing(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(opportunities=[{"symbol": "QQQ/USDT:USDT", "rate": 0.004, "next_funding_time": 1_800_000_060_000}]),
    )
    broker = FakeHybridBroker(spot_markets={"BTC/USDT"})
    strategy = make_strategy(broker)
    strategy._remember_price("QQQ/USDT:USDT", 700.0)
    events = []

    async def capture(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture

    asyncio.run(strategy.on_bar(make_bar()))

    assert broker.orders == []
    skip_event = next(item for item in events if item["decision"] == "open_skipped")
    assert skip_event["details"]["skip_reason"] == "missing_spot_market"
    assert skip_event["details"]["spot_available"] is False
    assert "现货市场不存在" in skip_event["summary"]


def test_okx_funding_arbitrage_closes_when_rate_drops_below_threshold(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(rates={"BTC/USDT:USDT": 0.00001}),
    )
    broker = FakeHybridBroker()
    broker.spot_positions["BTC/USDT"] = {"symbol": "BTC/USDT", "size": 0.02, "entry_price": 50_000.0}
    broker.contract_positions[("BTC/USDT:USDT", "short")] = {"symbol": "BTC/USDT:USDT", "pos_side": "short", "notional_usdt": 1_000.0}
    strategy = make_strategy(broker, {"min_hold_funding_events": 0})
    strategy.active_positions["BTC/USDT:USDT"] = {"spot_symbol": "BTC/USDT", "entry_price": 50_000.0}

    asyncio.run(strategy.on_bar(make_bar(close=50_100.0)))

    assert any(order[0] == "sell" and order[1] == "BTC/USDT" for order in broker.orders)
    assert ("close_contract", "BTC/USDT:USDT", "short", 1.0, 50_100.0) in broker.orders
    assert strategy.active_positions == {}


def test_okx_funding_arbitrage_skips_entry_when_funding_edge_does_not_cover_costs(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(opportunities=[{"symbol": "BTC/USDT:USDT", "rate": 0.0031, "next_funding_time": 1_800_000_060_000}]),
    )
    broker = FakeHybridBroker()
    strategy = make_strategy(broker, {"min_annualized_rate": 0.10, "min_expected_funding_events": 1, "min_net_edge_bps": 20})
    events = []

    async def capture(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture

    asyncio.run(strategy.on_bar(make_bar()))

    assert broker.orders == []
    skip_event = next(item for item in events if item["decision"] == "open_skipped")
    assert skip_event["details"]["estimated_net_edge_bps"] < skip_event["details"]["min_net_edge_bps"]
    assert "未覆盖手续费" in skip_event["summary"]


def test_okx_funding_arbitrage_does_not_close_before_min_funding_collection(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(rates={"BTC/USDT:USDT": 0.00001}),
    )
    broker = FakeHybridBroker()
    broker.spot_positions["BTC/USDT"] = {"symbol": "BTC/USDT", "size": 0.02, "entry_price": 50_000.0}
    broker.contract_positions[("BTC/USDT:USDT", "short")] = {"symbol": "BTC/USDT:USDT", "pos_side": "short", "notional_usdt": 1_000.0}
    strategy = make_strategy(broker, {"min_hold_funding_events": 1})
    strategy.active_positions["BTC/USDT:USDT"] = {
        "spot_symbol": "BTC/USDT",
        "entry_price": 50_000.0,
        "entry_timestamp_ms": 1_800_000_000_000,
        "last_funding_timestamp_ms": 1_800_000_000_000,
        "funding_collections": 0,
    }

    asyncio.run(strategy.on_bar(make_bar(close=50_100.0, timestamp=1_800_000_060_000)))

    assert not any(order[0] == "sell" for order in broker.orders)
    assert "BTC/USDT:USDT" in strategy.active_positions


def test_okx_funding_arbitrage_applies_funding_then_closes_when_rate_decays(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(rates={"BTC/USDT:USDT": 0.00001}),
    )
    broker = FakeHybridBroker()
    broker.spot_positions["BTC/USDT"] = {"symbol": "BTC/USDT", "size": 0.02, "entry_price": 50_000.0}
    broker.contract_positions[("BTC/USDT:USDT", "short")] = {"symbol": "BTC/USDT:USDT", "pos_side": "short", "notional_usdt": 1_000.0}
    strategy = make_strategy(broker, {"min_hold_funding_events": 1})
    timestamp = 1_800_000_000_000
    strategy.active_positions["BTC/USDT:USDT"] = {
        "spot_symbol": "BTC/USDT",
        "entry_price": 50_000.0,
        "entry_funding_rate": 0.0005,
        "entry_timestamp_ms": timestamp,
        "last_funding_timestamp_ms": timestamp,
        "next_funding_timestamp_ms": timestamp + 480 * 60 * 1000,
        "funding_collections": 0,
        "expected_funding_events": 24,
    }

    asyncio.run(strategy.on_bar(make_bar(close=50_100.0, timestamp=timestamp + 480 * 60 * 1000)))

    assert broker.funding_events == [("BTC/USDT:USDT", 0.00001)]
    assert any(order[0] == "sell" and order[1] == "BTC/USDT" for order in broker.orders)
    assert ("close_contract", "BTC/USDT:USDT", "short", 1.0, 50_100.0) in broker.orders
    assert strategy.active_positions == {}


def test_okx_funding_arbitrage_applies_funding_at_exchange_next_funding_time(monkeypatch):
    timestamp = 1_800_000_000_000
    next_funding_time = timestamp + 60_000
    funding = FakeFundingService(
        opportunities=[
            {
                "symbol": "BTC/USDT:USDT",
                "rate": 0.0035,
                "next_funding_time": next_funding_time,
            }
        ],
        rates={"BTC/USDT:USDT": {"current_rate": 0.0035, "next_funding_time": next_funding_time}},
    )
    monkeypatch.setattr(strategy_module, "funding_service", funding)
    broker = FakeHybridBroker()
    strategy = make_strategy(broker, {"max_active_symbols": 1})

    asyncio.run(strategy.on_bar(make_bar(close=50_000.0, timestamp=timestamp)))
    asyncio.run(strategy.on_bar(make_bar(close=50_000.0, timestamp=next_funding_time)))

    assert broker.funding_events == [("BTC/USDT:USDT", 0.0035)]
    assert strategy.active_positions["BTC/USDT:USDT"]["funding_collections"] == 1
    assert strategy.active_positions["BTC/USDT:USDT"]["next_funding_timestamp_ms"] == next_funding_time + 480 * 60 * 1000


def test_okx_funding_arbitrage_does_not_count_funding_when_broker_returns_no_events(monkeypatch):
    timestamp = 1_800_000_000_000
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(rates={"BTC/USDT:USDT": {"current_rate": 0.0035, "next_funding_time": timestamp + 60_000}}),
    )
    broker = FakeHybridBroker(funding_apply_events=[])
    broker.spot_positions["BTC/USDT"] = {"symbol": "BTC/USDT", "size": 0.02, "entry_price": 50_000.0}
    broker.contract_positions[("BTC/USDT:USDT", "short")] = {"symbol": "BTC/USDT:USDT", "pos_side": "short", "notional_usdt": 1_000.0}
    strategy = make_strategy(broker, {"min_hold_funding_events": 1})
    strategy.active_positions["BTC/USDT:USDT"] = {
        "spot_symbol": "BTC/USDT",
        "entry_price": 50_000.0,
        "entry_funding_rate": 0.0035,
        "entry_timestamp_ms": timestamp,
        "last_funding_timestamp_ms": timestamp,
        "next_funding_timestamp_ms": timestamp + 60_000,
        "funding_collections": 0,
        "expected_funding_events": 2,
    }

    asyncio.run(strategy.on_bar(make_bar(close=50_100.0, timestamp=timestamp + 60_000)))

    assert broker.funding_events == [("BTC/USDT:USDT", 0.0035)]
    assert strategy.active_positions["BTC/USDT:USDT"]["funding_collections"] == 0
    assert "BTC/USDT:USDT" in strategy.active_positions


def test_okx_funding_arbitrage_rolls_back_spot_leg_when_contract_open_fails(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(opportunities=[{"symbol": "BTC/USDT:USDT", "rate": 0.0035, "next_funding_time": 1_800_000_060_000}]),
    )
    broker = FakeHybridBroker(contract_fail=True)
    strategy = make_strategy(broker)

    asyncio.run(strategy.on_bar(make_bar()))

    assert broker.orders[0][0] == "buy"
    assert any(order[0] == "sell" and order[1] == "BTC/USDT" for order in broker.orders)
    assert strategy.active_positions == {}


def test_okx_funding_arbitrage_skips_when_contract_metadata_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(opportunities=[{"symbol": "QQQ/USDT:USDT", "rate": 0.0035, "next_funding_time": 1_800_000_060_000}]),
    )
    broker = FakeHybridBroker(missing_contract_metadata=True, spot_markets={"QQQ/USDT"})
    strategy = make_strategy(broker)
    strategy._remember_price("QQQ/USDT:USDT", 700.0)
    events = []

    async def capture(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture

    asyncio.run(strategy.on_bar(make_bar()))

    assert broker.orders == []
    skip_event = next(item for item in events if item["decision"] == "open_skipped")
    assert "合约元数据" in skip_event["summary"]
    assert skip_event["details"]["symbol"] == "QQQ/USDT:USDT"
    assert "missing OKX SWAP instrument metadata for QQQ/USDT:USDT" in skip_event["details"]["error"]


def test_okx_funding_arbitrage_skips_when_usdt_balance_is_insufficient(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(opportunities=[{"symbol": "BTC/USDT:USDT", "rate": 0.0035, "next_funding_time": 1_800_000_060_000}]),
    )
    broker = FakeHybridBroker(available_balance=1_500.0)
    strategy = make_strategy(broker)

    asyncio.run(strategy.on_bar(make_bar()))

    assert broker.orders == []
    assert strategy.active_positions == {}


def test_okx_funding_arbitrage_keeps_position_and_retries_when_close_leg_fails(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(rates={"BTC/USDT:USDT": {"current_rate": -0.0001, "next_funding_time": 1_800_000_060_000}}),
    )
    broker = FakeHybridBroker(close_contract_fail=True)
    broker.spot_positions["BTC/USDT"] = {"symbol": "BTC/USDT", "size": 0.02, "entry_price": 50_000.0}
    broker.contract_positions[("BTC/USDT:USDT", "short")] = {"symbol": "BTC/USDT:USDT", "pos_side": "short", "notional_usdt": 1_000.0}
    strategy = make_strategy(broker, {"min_hold_funding_events": 0})
    strategy.active_positions["BTC/USDT:USDT"] = {"spot_symbol": "BTC/USDT", "entry_price": 50_000.0, "funding_collections": 1}
    events = []

    async def capture(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture

    asyncio.run(strategy.on_bar(make_bar(close=50_100.0)))

    assert "BTC/USDT:USDT" in strategy.active_positions
    assert next(item for item in events if item["decision"] == "close_failed")["details"]["failed_legs"] == ["contract"]

    broker.close_contract_fail = False
    asyncio.run(strategy.on_bar(make_bar(close=50_050.0, timestamp=1_800_000_061_000)))

    assert strategy.active_positions == {}
    assert broker.close_contract_calls == 2


def test_okx_funding_arbitrage_closes_when_hedge_drift_is_critical(monkeypatch):
    monkeypatch.setattr(
        strategy_module,
        "funding_service",
        FakeFundingService(rates={"BTC/USDT:USDT": {"current_rate": 0.0035, "next_funding_time": 1_800_000_060_000}}),
    )
    broker = FakeHybridBroker()
    broker.spot_positions["BTC/USDT"] = {"symbol": "BTC/USDT", "size": 0.01, "entry_price": 50_000.0}
    broker.contract_positions[("BTC/USDT:USDT", "short")] = {"symbol": "BTC/USDT:USDT", "pos_side": "short", "notional_usdt": 1_000.0}
    strategy = make_strategy(broker, {"min_hold_funding_events": 0, "critical_hedge_drift_pct": 0.10})
    strategy.active_positions["BTC/USDT:USDT"] = {"spot_symbol": "BTC/USDT", "entry_price": 50_000.0, "funding_collections": 1}
    events = []

    async def capture(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture

    asyncio.run(strategy.on_bar(make_bar(close=50_000.0)))

    assert any(order[0] == "sell" and order[1] == "BTC/USDT" for order in broker.orders)
    assert ("close_contract", "BTC/USDT:USDT", "short", 1.0, 50_000.0) in broker.orders
    assert strategy.active_positions == {}
    assert any(item["decision"] == "hedge_drift_alert" for item in events)


def test_okx_funding_arbitrage_logs_top_5_funding_rates(monkeypatch):
    funding = FakeFundingService(
        opportunities=[
            {"symbol": "BTC/USDT:USDT", "rate": 0.0002},
            {"symbol": "ETH/USDT:USDT", "rate": 0.0006},
            {"symbol": "SOL/USDT:USDT", "rate": -0.0007},
            {"symbol": "DOGE/USDT:USDT", "rate": 0.0001},
            {"symbol": "XRP/USDT:USDT", "rate": 0.0004},
            {"symbol": "PEPE/USDT:USDT", "rate": 0.0003},
        ]
    )
    monkeypatch.setattr(strategy_module, "funding_service", funding)
    broker = FakeHybridBroker()
    strategy = make_strategy(broker, {"min_annualized_rate": 2.0, "funding_scan_limit": 100})
    events = []

    async def capture(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture

    asyncio.run(strategy.on_bar(make_bar()))

    assert funding.opportunity_calls == [("okx", 0.0, 100)]
    event = next(item for item in events if item["decision"] == "scan_opportunities")
    assert "Top5" in event["summary"]
    assert "ETH/USDT:USDT +0.0600%/次(+65.70%/年" in event["summary"]
    top_rows = event["details"]["top_funding_rates"]
    assert [row["symbol"] for row in top_rows] == [
        "ETH/USDT:USDT",
        "XRP/USDT:USDT",
        "PEPE/USDT:USDT",
        "BTC/USDT:USDT",
        "DOGE/USDT:USDT",
    ]
    assert top_rows[0]["annualized_pct"] == pytest.approx(65.7)


def test_okx_funding_arbitrage_falls_back_to_configured_symbols_for_top_5(monkeypatch):
    funding = FakeFundingService(
        opportunities=[],
        rates={
            "BTC/USDT:USDT": 0.0002,
            "ETH/USDT:USDT": 0.0006,
            "SOL/USDT:USDT": -0.0007,
        },
    )
    monkeypatch.setattr(strategy_module, "funding_service", funding)
    broker = FakeHybridBroker()
    strategy = make_strategy(
        broker,
        {
            "min_annualized_rate": 2.0,
            "allowed_symbols": ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"],
        },
    )
    events = []

    async def capture(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture

    asyncio.run(strategy.on_bar(make_bar()))

    assert funding.opportunity_calls == [("okx", 0.0, 100)]
    assert set(funding.rate_calls) == {
        ("okx", "BTC/USDT:USDT"),
        ("okx", "ETH/USDT:USDT"),
        ("okx", "SOL/USDT:USDT"),
    }
    event = next(item for item in events if item["decision"] == "scan_opportunities")
    assert event["details"]["scan_source"] == "configured_symbols"
    assert event["details"]["top_funding_rates"][0]["symbol"] == "ETH/USDT:USDT"
    assert "ETH/USDT:USDT +0.0600%/次(+65.70%/年" in event["summary"]
