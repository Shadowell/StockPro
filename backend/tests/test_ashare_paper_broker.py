from __future__ import annotations

import pytest

from app.services.ashare_backtest_engine import AShareBacktestEngine
from app.services.ashare_execution import (
    AShareSpotBroker,
    DEFAULT_ASHARE_COST,
    compute_fees,
    instrument_key,
    storage_symbol,
)


COST = {
    "commission_rate": 0.0003,
    "minimum_commission": 5.0,
    "stamp_duty_rate": 0.0005,
    "transfer_fee_rate": 0.00001,
}


def test_instrument_key_is_code_market() -> None:
    assert instrument_key("SH_600000") == "600000.SH"
    assert instrument_key("600000.SH") == "600000.SH"
    assert instrument_key("000001.SZ") == "000001.SZ"
    assert storage_symbol("600000.SH") == "SH_600000"


def test_paper_fees_match_backtest_engine() -> None:
    engine = AShareBacktestEngine(
        bars=[{"trade_date": "2026-08-20", "symbol": "SH_600000", "open": 10, "close": 10, "turnover": 1_000_000}],
        intents=[],
        initial_cash=1_000_000,
        cost_model=COST,
    )
    buy = engine._fees("buy", 10_000)
    sell = engine._fees("sell", 10_000)
    assert buy == compute_fees("buy", 10_000, COST)
    assert sell == compute_fees("sell", 10_000, COST)
    assert buy["tax"] == 0
    assert sell["tax"] == 5
    assert buy["transfer_fee"] == sell["transfer_fee"] == 0.1
    assert buy["commission"] == 5


def test_paper_broker_enforces_t1_and_lot_100() -> None:
    broker = AShareSpotBroker(COST)
    bar = {"open": 10, "close": 10, "volume": 1_000_000}
    odd = broker.evaluate(
        side="buy", symbol="600000.SH", quantity=50, price=10, trade_date="2026-08-21",
        cash=1_000_000, available_quantity=0, bar=bar, explicit_lot=True,
    )
    t1 = broker.evaluate(
        side="sell", symbol="600000.SH", quantity=100, price=10, trade_date="2026-08-21",
        cash=1_000_000, available_quantity=0, bar=bar,
    )
    accepted = broker.evaluate(
        side="buy", symbol="600000.SH", quantity=100, price=10, trade_date="2026-08-21",
        cash=1_000_000, available_quantity=0, bar=bar,
    )
    assert odd["rejection_code"] == "INVALID_LOT_SIZE"
    assert t1["rejection_code"] == "T1_NOT_AVAILABLE"
    assert accepted["accepted"] is True
    assert accepted["symbol"] == "600000.SH"
    assert accepted["amount"] == 1_000
    assert accepted["cash_delta"] == -accepted["amount"] - accepted["fees"]["commission"] - accepted["fees"]["transfer_fee"]


def test_paper_rejects_limit_up_buy_limit_down_sell_and_halt() -> None:
    broker = AShareSpotBroker(
        COST,
        price_limits=[
            {"trade_date": "2026-08-21", "symbol": "600000.SH", "has_price_limit": True, "up_limit": 11, "down_limit": 9},
        ],
        suspensions=[{"trade_date": "2026-08-21", "symbol": "000001.SZ", "suspend_type": "S"}],
    )
    bar = {"open": 11, "close": 11, "volume": 100}
    limit_up = broker.evaluate(
        side="buy", symbol="SH_600000", quantity=100, price=11, trade_date="2026-08-21",
        cash=1_000_000, available_quantity=0, bar=bar,
    )
    limit_down = broker.evaluate(
        side="sell", symbol="600000.SH", quantity=100, price=9, trade_date="2026-08-21",
        cash=1_000_000, available_quantity=100, bar={"open": 9, "close": 9, "volume": 100},
    )
    halted = broker.evaluate(
        side="buy", symbol="000001.SZ", quantity=100, price=10, trade_date="2026-08-21",
        cash=1_000_000, available_quantity=0, bar={"open": 10, "close": 10},
    )
    assert limit_up["rejection_code"] == "LIMIT_UP"
    assert limit_down["rejection_code"] == "LIMIT_DOWN"
    assert halted["rejection_code"] == "SUSPENDED"


def test_paper_rejects_non_trading_day() -> None:
    broker = AShareSpotBroker(COST, calendar_rows=[{"trade_date": "2026-08-22", "is_open": 0}])
    result = broker.evaluate(
        side="buy", symbol="600000.SH", quantity=100, price=10, trade_date="2026-08-22",
        cash=1_000_000, available_quantity=0, bar={"open": 10, "close": 10},
    )
    assert result["rejection_code"] == "NOT_A_TRADING_DAY"


def test_golden_paper_round_matches_backtest_cash_for_same_fill() -> None:
    """One sealed-snapshot style trade: buy then T+1 sell, paper cash == backtest cash."""
    bars = [
        {"trade_date": "2026-08-20", "symbol": "SH_600000", "open": 10, "close": 10.2, "turnover": 5_000_000},
        {"trade_date": "2026-08-21", "symbol": "SH_600000", "open": 10.2, "close": 10.1, "turnover": 5_000_000},
    ]
    intents = [
        {
            "symbol": "SH_600000",
            "intent_type": "order_target_percent",
            "payload": {"value": 0.1},
            "simulated_at": "2026-08-20T15:00:00+08:00",
            "available_at": "2026-08-20T15:00:00+08:00",
        },
        {
            "symbol": "SH_600000",
            "intent_type": "order_target_percent",
            "payload": {"value": 0},
            "simulated_at": "2026-08-21T15:00:00+08:00",
            "available_at": "2026-08-21T15:00:00+08:00",
        },
    ]
    engine = AShareBacktestEngine(bars=bars, intents=intents, initial_cash=1_000_000, cost_model=COST)
    result = engine.run()
    backtest_buy = next(item for item in result["trades"] if item["side"] == "buy")

    broker = AShareSpotBroker(COST)
    paper_buy = broker.evaluate(
        side="buy",
        symbol="600000.SH",
        quantity=backtest_buy["quantity"],
        price=backtest_buy["price"],
        trade_date="2026-08-21",
        cash=1_000_000,
        available_quantity=0,
        bar=bars[1],
    )
    assert paper_buy["accepted"] is True
    assert paper_buy["fees"]["commission"] == pytest.approx(backtest_buy["commission"], abs=1e-3)
    assert paper_buy["fees"]["tax"] == pytest.approx(backtest_buy["tax"], abs=1e-3)
    assert paper_buy["fees"]["transfer_fee"] == pytest.approx(backtest_buy["transfer_fee"], abs=1e-3)
    assert paper_buy["cash_delta"] == pytest.approx(
        -(backtest_buy["amount"] + backtest_buy["commission"] + backtest_buy["transfer_fee"]),
        abs=1e-3,
    )

    paper_sell = broker.evaluate(
        side="sell",
        symbol="600000.SH",
        quantity=backtest_buy["quantity"],
        price=10.2,
        trade_date="2026-08-22",
        cash=1_000_000 + paper_buy["cash_delta"],
        available_quantity=backtest_buy["quantity"],
        bar={"open": 10.2, "close": 10.1, "volume": 1000},
    )
    assert paper_sell["accepted"] is True
    assert paper_sell["fees"]["tax"] > 0
    assert paper_sell["fees"] == compute_fees("sell", paper_sell["amount"], COST)
    assert DEFAULT_ASHARE_COST["stamp_duty_rate"] == 0.0005
