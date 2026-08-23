import asyncio
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.execution.base_strategy import BarData, StrategyState  # noqa: E402
from app.strategies.cross_exchange_funding_arbitrage_strategy import CrossExchangeFundingArbitrageStrategy  # noqa: E402
import app.strategies.cross_exchange_funding_arbitrage_strategy as strategy_module  # noqa: E402


BASE_TS = 1_800_000_000_000


class FakeArbitrageDomainService:
    def __init__(self, opportunities):
        self.opportunities = list(opportunities)
        self.summary_calls = []

    async def summary(self, **kwargs):
        self.summary_calls.append(dict(kwargs))
        return {"opportunities": list(self.opportunities)}


class FakeCrossExchangeBroker:
    def __init__(self):
        self.warmup_mode = False
        self.positions = {}
        self.open_calls = []
        self.close_calls = []

    def advance_bar(self):
        for position in self.positions.values():
            position["bars_held"] = int(position.get("bars_held") or 0) + 1

    def open_pair_from_opportunity(self, opportunity, *, notional_usdt, leverage=None):
        symbol = opportunity["symbol"]
        self.open_calls.append((symbol, float(notional_usdt), float(leverage or 0), dict(opportunity)))
        self.positions[symbol] = {"symbol": symbol, "bars_held": 0, "latest_carry_net_edge_bps": opportunity.get("carry_net_edge_bps")}
        return {"status": "filled", "symbol": symbol}

    def update_from_opportunity(self, opportunity):
        symbol = opportunity["symbol"]
        if symbol in self.positions:
            self.positions[symbol]["latest_carry_net_edge_bps"] = opportunity.get("carry_net_edge_bps")

    def close_pair(self, symbol, *, reason="close_pair"):
        self.close_calls.append((symbol, reason))
        self.positions.pop(symbol, None)
        return {"status": "filled", "symbol": symbol, "reason": reason}

    def export_state(self):
        return {"positions": dict(self.positions)}


def make_state() -> StrategyState:
    return StrategyState(
        strategy_id=971,
        name="[合约][4H][套利] Top50 · Funding-Basis Carry低换手 · 100U",
        exchange="cross_exchange",
        symbols=["BTC/USDT:USDT"],
        created_at=datetime.utcnow(),
        status="running",
    )


def make_bar(timestamp=BASE_TS) -> BarData:
    return BarData(
        exchange="okx",
        symbol="BTC/USDT:USDT",
        timeframe="4h",
        timestamp=timestamp,
        open=100.0,
        high=100.0,
        low=100.0,
        close=100.0,
        volume=100,
    )


def make_strategy(broker, config=None) -> CrossExchangeFundingArbitrageStrategy:
    strategy = CrossExchangeFundingArbitrageStrategy(make_state(), broker)
    strategy.set_config(
        {
            "strategy_key": "cross_exchange_funding_basis_carry",
            "timeframe": "4h",
            "top_n": 50,
            "position_notional_usdt": 30,
            "max_active_pairs": 1,
            "paper_leverage": 3,
            "poll_interval_seconds": 1,
            "funding_period_minutes": 480,
            "expected_funding_events": 8,
            "min_hold_funding_events": 2,
            "max_hold_funding_events": 12,
            "open_edge_field": "carry_net_edge_bps",
            "min_carry_net_edge_bps": 8,
            "close_edge_bps": 2,
            "close_when_edge_disappears": True,
            "basis_credit_ratio": 0.5,
            "max_basis_credit_bps": 12,
            "min_depth_usdt": 100_000,
            **(config or {}),
        }
    )
    asyncio.run(strategy.on_init())
    return strategy


def low_single_event_carry_opportunity():
    return {
        "symbol": "BTC/USDT:USDT",
        "strategy_type": "funding_basis_carry",
        "long_leg": {"exchange": "binanceusdm", "side": "long", "price": 100.05, "funding_rate": 0.0},
        "short_leg": {"exchange": "okx", "side": "short", "price": 99.95, "funding_rate": 0.0004},
        "net_edge_bps": -19.0,
        "carry_net_edge_bps": 9.0,
        "funding_edge_bps": 4.0,
        "projected_funding_edge_bps": 32.0,
        "basis_edge_bps": -10.0,
        "depth_usdt": 160_000,
    }


def test_funding_basis_carry_opens_on_projected_carry_edge(monkeypatch):
    domain = FakeArbitrageDomainService([low_single_event_carry_opportunity()])
    monkeypatch.setattr(strategy_module, "arbitrage_domain_service", domain)
    broker = FakeCrossExchangeBroker()
    strategy = make_strategy(broker)

    asyncio.run(strategy.on_bar(make_bar()))

    assert domain.summary_calls == [
        {
            "expected_funding_events": 8,
            "min_net_edge_bps": 8.0,
            "edge_filter_field": "carry_net_edge_bps",
            "basis_credit_ratio": 0.5,
            "max_basis_credit_bps": 12.0,
            "strategy_type": "funding_basis_carry",
            "min_depth_usdt": 100000.0,
            "top_n": 50,
        }
    ]
    assert broker.open_calls == [("BTC/USDT:USDT", 30.0, 3.0, low_single_event_carry_opportunity())]


def test_funding_basis_carry_prioritizes_configured_edge_field(monkeypatch):
    weaker_carry_with_better_single_event_edge = {
        **low_single_event_carry_opportunity(),
        "symbol": "ETH/USDT:USDT",
        "net_edge_bps": 18.0,
        "carry_net_edge_bps": 8.2,
    }
    stronger_carry = low_single_event_carry_opportunity()
    domain = FakeArbitrageDomainService([weaker_carry_with_better_single_event_edge, stronger_carry])
    monkeypatch.setattr(strategy_module, "arbitrage_domain_service", domain)
    broker = FakeCrossExchangeBroker()
    strategy = make_strategy(broker)

    asyncio.run(strategy.on_bar(make_bar()))

    assert broker.open_calls[0][0] == "BTC/USDT:USDT"


def test_funding_basis_carry_respects_min_hold_before_edge_disappears():
    broker = FakeCrossExchangeBroker()
    broker.positions["BTC/USDT:USDT"] = {"symbol": "BTC/USDT:USDT", "bars_held": 3}
    strategy = make_strategy(broker)

    asyncio.run(strategy._update_active_positions([]))

    assert "BTC/USDT:USDT" in broker.positions
    assert broker.close_calls == []

    broker.positions["BTC/USDT:USDT"]["bars_held"] = 4
    asyncio.run(strategy._update_active_positions([]))

    assert "BTC/USDT:USDT" not in broker.positions
    assert broker.close_calls == [("BTC/USDT:USDT", "max_hold_or_edge_disappeared")]
