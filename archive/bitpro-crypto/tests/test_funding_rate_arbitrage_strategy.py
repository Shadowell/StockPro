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
from app.services.contract_paper_account import ContractInstrument
from app.services.strategy_engine import ContractPaperBroker
from app.strategies.funding_rate_arbitrage_strategy import FundingRateArbitrageStrategy
import app.strategies.funding_rate_arbitrage_strategy as funding_strategy_module


class FakeFundingService:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    async def get_funding_rate(self, exchange, symbol):
        self.calls.append((exchange, symbol))
        if not self.values:
            return {"current_rate": 0.0}
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return {"current_rate": value}


class FakeHybridBroker:
    def __init__(self):
        self.spot_positions = {}
        self.contract_positions = {}
        self.orders = []
        self.funding_events = []
        self.warmup_mode = False

    async def buy(self, symbol, amount, price=None, *, order_type="market"):
        cost = float(amount) * float(price)
        self.spot_positions[symbol] = {
            "symbol": symbol,
            "size": float(amount),
            "entry_price": float(price),
        }
        self.orders.append(("buy", symbol, float(amount), float(price)))
        return OrderResult({"status": "filled", "symbol": symbol, "amount": float(amount), "price": float(price), "cost": cost})

    async def sell(self, symbol, amount, price=None, *, order_type="market"):
        pos = self.spot_positions.get(symbol)
        if not pos or pos["size"] <= 0:
            return OrderResult({"status": "skipped", "reason": "no_position", "symbol": symbol})
        qty = min(float(amount), pos["size"])
        pos["size"] -= qty
        self.orders.append(("sell", symbol, qty, float(price)))
        return OrderResult({"status": "filled", "symbol": symbol, "amount": qty, "price": float(price), "cost": qty * float(price)})

    async def close_position(self, symbol):
        return await self.sell(symbol, self.spot_positions.get(symbol, {}).get("size", 0.0))

    async def open_contract(self, symbol, side, notional_usdt, leverage=None, price=None):
        self.contract_positions[(symbol, side)] = {
            "symbol": symbol,
            "pos_side": side,
            "notional_usdt": float(notional_usdt),
            "contracts": 1.0,
        }
        self.orders.append(("open_contract", symbol, side, float(notional_usdt), float(leverage), float(price)))
        return OrderResult({"status": "filled", "symbol": symbol, "pos_side": side, "notional_usdt": float(notional_usdt), "price": float(price)})

    async def close_contract(self, symbol, side, ratio=1.0, contracts=None, price=None):
        if (symbol, side) not in self.contract_positions:
            return OrderResult({"status": "skipped", "reason": "no_position", "symbol": symbol, "pos_side": side})
        self.contract_positions.pop((symbol, side), None)
        self.orders.append(("close_contract", symbol, side, float(ratio), float(price)))
        return OrderResult({"status": "filled", "symbol": symbol, "pos_side": side, "price": float(price)})

    async def get_contract_position(self, symbol, side):
        return self.contract_positions.get((symbol, side))

    def apply_funding(self, symbol, funding_rate):
        event = {"symbol": symbol, "funding_rate": funding_rate, "amount": 1.0}
        self.funding_events.append(event)
        return [event]


def make_state() -> StrategyState:
    return StrategyState(
        strategy_id=777,
        name="[合约] 资金费率套利 · test",
        exchange="okx",
        symbols=["BTC/USDT:USDT"],
        created_at=datetime.utcnow(),
        status="running",
    )


def make_bar(close: float, timestamp: int) -> BarData:
    return BarData(
        exchange="okx",
        symbol="BTC/USDT:USDT",
        timeframe="1m",
        timestamp=timestamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=100,
    )


def make_strategy(broker, config=None) -> FundingRateArbitrageStrategy:
    strategy = FundingRateArbitrageStrategy(make_state(), broker)
    strategy.set_config(
        {
            "target_symbol": "BTC/USDT",
            "contract_symbol": "BTC/USDT:USDT",
            "position_notional_usdt": 1_000.0,
            "min_annualized_rate": 0.15,
            "funding_check_interval_minutes": 1,
            "funding_period_minutes": 8,
            "max_funding_failures": 3,
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy


def test_funding_rate_arbitrage_opens_spot_and_short_when_rate_is_high(monkeypatch):
    broker = FakeHybridBroker()
    monkeypatch.setattr(funding_strategy_module, "funding_service", FakeFundingService([0.0002]))
    strategy = make_strategy(broker)

    asyncio.run(strategy.on_bar(make_bar(50_000.0, 1_800_000_000_000)))

    assert broker.orders[0][0] == "buy"
    assert broker.orders[1][0] == "open_contract"
    assert broker.orders[1][2] == "short"
    assert broker.orders[1][3] == pytest.approx(1_000.0)
    assert strategy.arb_state == FundingRateArbitrageStrategy.HEDGED
    assert strategy.entry_annualized_rate == pytest.approx(0.0002 * 3 * 365)


def test_funding_rate_arbitrage_logs_wait_reason_when_rate_is_below_threshold(monkeypatch):
    broker = FakeHybridBroker()
    monkeypatch.setattr(funding_strategy_module, "funding_service", FakeFundingService([0.00001]))
    strategy = make_strategy(broker)
    events = []

    async def capture(payload):
        events.append(payload)

    strategy.broadcast_strategy_channel = capture

    asyncio.run(strategy.on_bar(make_bar(50_000.0, 1_800_000_000_000)))

    assert broker.orders == []
    assert events[-1]["decision"] == "funding_below_threshold"
    assert events[-1]["decision_label"] == "费率低于阈值"
    assert events[-1]["summary"] == "资金费率未达到开仓阈值，继续等待"
    assert events[-1]["details"]["annualized_rate"] == pytest.approx(0.00001 * 3 * 365)
    assert events[-1]["details"]["min_annualized_rate"] == 0.15


def test_funding_rate_arbitrage_closes_when_rate_decays_below_entry_threshold(monkeypatch):
    broker = FakeHybridBroker()
    monkeypatch.setattr(funding_strategy_module, "funding_service", FakeFundingService([0.0002, 0.00005]))
    strategy = make_strategy(broker)

    asyncio.run(strategy.on_bar(make_bar(50_000.0, 1_800_000_000_000)))
    asyncio.run(strategy.on_bar(make_bar(50_100.0, 1_800_000_060_000)))

    assert ("close_contract", "BTC/USDT:USDT", "short", 1.0, 50_100.0) in broker.orders
    assert any(order[0] == "sell" for order in broker.orders)
    assert strategy.arb_state == FundingRateArbitrageStrategy.IDLE


def test_funding_rate_arbitrage_closes_when_rate_turns_negative(monkeypatch):
    broker = FakeHybridBroker()
    monkeypatch.setattr(funding_strategy_module, "funding_service", FakeFundingService([0.0002, -0.00001]))
    strategy = make_strategy(broker)

    asyncio.run(strategy.on_bar(make_bar(50_000.0, 1_800_000_000_000)))
    asyncio.run(strategy.on_bar(make_bar(49_950.0, 1_800_000_060_000)))

    assert any(order[0] == "sell" for order in broker.orders)
    assert any(order[0] == "close_contract" for order in broker.orders)
    assert strategy.arb_state == FundingRateArbitrageStrategy.IDLE


def test_funding_rate_arbitrage_applies_funding_after_collection_period(monkeypatch):
    broker = FakeHybridBroker()
    monkeypatch.setattr(funding_strategy_module, "funding_service", FakeFundingService([0.0002, 0.0002]))
    strategy = make_strategy(broker)

    asyncio.run(strategy.on_bar(make_bar(50_000.0, 1_800_000_000_000)))
    asyncio.run(strategy.on_bar(make_bar(50_000.0, 1_800_000_480_000)))

    assert broker.funding_events == [{"symbol": "BTC/USDT:USDT", "funding_rate": 0.0002, "amount": 1.0}]
    assert strategy._funding_collections == 1


def test_funding_rate_arbitrage_self_pauses_after_three_funding_failures(monkeypatch):
    broker = FakeHybridBroker()
    monkeypatch.setattr(
        funding_strategy_module,
        "funding_service",
        FakeFundingService([RuntimeError("okx down"), RuntimeError("okx down"), RuntimeError("okx down")]),
    )
    strategy = make_strategy(broker)

    asyncio.run(strategy.on_bar(make_bar(50_000.0, 1_800_000_000_000)))
    asyncio.run(strategy.on_bar(make_bar(50_000.0, 1_800_000_060_000)))
    asyncio.run(strategy.on_bar(make_bar(50_000.0, 1_800_000_120_000)))

    assert strategy.state.status == "paused"
    assert strategy._self_paused is True
    assert "资金费率接口连续失败" in strategy.state.error_message


def test_contract_paper_broker_supports_spot_hedge_leg_with_swap_position():
    broker = ContractPaperBroker(
        initial_capital=10_000.0,
        strategy_id=0,
        exchange_name="okx",
        symbols=["BTC/USDT:USDT"],
        config={
            "commission_rate": 0.001,
            "taker_fee_bps": 5,
            "contract_instruments": {
                "BTC/USDT:USDT": {
                    "inst_id": "BTC-USDT-SWAP",
                    "ct_val": 0.01,
                    "lot_sz": 1,
                    "min_sz": 1,
                    "tick_sz": 0.1,
                    "max_leverage": 5,
                    "state": "live",
                }
            },
        },
    )
    broker.update_mark_price("BTC/USDT:USDT", 50_000.0)

    buy = asyncio.run(broker.buy("BTC/USDT", 0.02, price=50_000.0))
    short = asyncio.run(broker.open_contract("BTC/USDT:USDT", "short", 1_000.0, leverage=2.0, price=50_000.0))

    assert buy["status"] == "filled"
    assert short["status"] == "filled"
    assert broker.list_spot_positions()[0]["symbol"] == "BTC/USDT"
    assert broker.account.get_position("BTC/USDT:USDT", "short")["pos_side"] == "short"
    assert broker.equity > 0


def test_contract_paper_broker_persists_close_trade_with_position_leverage(monkeypatch):
    inserted = []

    class FakeDb:
        def insert_strategy_trade(self, strategy_id, trade):
            inserted.append((strategy_id, trade))

    monkeypatch.setattr("app.services.strategy_engine.db", FakeDb())
    broker = ContractPaperBroker(
        initial_capital=10_000.0,
        strategy_id=77,
        exchange_name="okx",
        symbols=["BTC/USDT:USDT"],
        config={
            "taker_fee_bps": 5,
            "max_leverage": 5,
            "contract_instruments": {
                "BTC/USDT:USDT": {
                    "inst_id": "BTC-USDT-SWAP",
                    "ct_val": 0.01,
                    "lot_sz": 1,
                    "min_sz": 1,
                    "tick_sz": 0.1,
                    "max_leverage": 5,
                    "state": "live",
                }
            },
        },
    )
    broker.update_mark_price("BTC/USDT:USDT", 50_000.0)

    asyncio.run(broker.open_contract("BTC/USDT:USDT", "long", 1_000.0, leverage=2.0, price=50_000.0))
    asyncio.run(broker.close_contract("BTC/USDT:USDT", "long", ratio=1.0, price=51_000.0))

    assert [item[0] for item in inserted] == [77, 77]
    assert inserted[0][1]["meta"]["leverage"] == pytest.approx(2.0)
    assert inserted[1][1]["side"] == "close_long"
    assert inserted[1][1]["meta"]["leverage"] == pytest.approx(2.0)
