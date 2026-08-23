import asyncio
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.contract_paper_account import ContractInstrument, ContractPaperAccount, normalize_contract_symbol
from app.services.strategy_engine import ContractPaperBroker


def btc_swap() -> ContractInstrument:
    return ContractInstrument(
        symbol="BTC/USDT:USDT",
        inst_id="BTC-USDT-SWAP",
        ct_val=0.01,
        lot_sz=1.0,
        min_sz=1.0,
        tick_sz=0.1,
        max_leverage=5.0,
        state="live",
    )


def test_normalize_contract_symbol_accepts_okx_swap_shorthand():
    assert normalize_contract_symbol("BTC-SWAP") == "BTC/USDT:USDT"
    assert normalize_contract_symbol("BTC-USDT-SWAP") == "BTC/USDT:USDT"
    assert normalize_contract_symbol("btc/usdt:usdt") == "BTC/USDT:USDT"
    assert normalize_contract_symbol("ETH") == "ETH/USDT:USDT"
    assert normalize_contract_symbol("SPACEX-USDT-SWAP") == "SPCX/USDT:USDT"
    assert normalize_contract_symbol("SPACEX/USDT:USDT") == "SPCX/USDT:USDT"


def test_open_contract_rounds_to_okx_lot_size_and_charges_margin_and_fee():
    account = ContractPaperAccount(
        initial_equity=10_000.0,
        instruments={"BTC/USDT:USDT": btc_swap()},
        taker_fee_bps=5.0,
        max_leverage=5.0,
    )
    account.update_mark_price("BTC/USDT:USDT", 50_000.0)

    order = account.open_position("BTC/USDT:USDT", "long", notional_usdt=1_200.0, leverage=5.0)

    assert order["status"] == "filled"
    assert order["contracts"] == 2.0
    assert order["base_qty"] == 0.02
    assert order["notional_usdt"] == 1_000.0
    assert order["margin"] == 200.0
    assert order["fee"] == pytest.approx(0.5)
    assert order["fee_bps"] == pytest.approx(5.0)
    assert order["liquidity"] == "taker"
    assert account.free_balance == pytest.approx(9_799.5)


def test_market_contract_orders_use_taker_fee_not_maker_fee():
    account = ContractPaperAccount(
        initial_equity=10_000.0,
        instruments={"BTC/USDT:USDT": btc_swap()},
        taker_fee_bps=4.5,
        maker_fee_bps=1.8,
        max_leverage=5.0,
    )
    account.update_mark_price("BTC/USDT:USDT", 50_000.0)

    opened = account.open_position("BTC/USDT:USDT", "long", notional_usdt=1_000.0, leverage=5.0)
    closed = account.close_position("BTC/USDT:USDT", "long", ratio=1.0, price=50_000.0)

    assert opened["fee_bps"] == pytest.approx(4.5)
    assert opened["fee"] == pytest.approx(0.45)
    assert opened["liquidity"] == "taker"
    assert closed["fee_bps"] == pytest.approx(4.5)
    assert closed["fee"] == pytest.approx(0.45)
    assert closed["liquidity"] == "taker"


def test_restore_contract_position_keeps_opened_at_from_open_trade_timestamp():
    account = ContractPaperAccount(
        initial_equity=10_000.0,
        instruments={"BTC/USDT:USDT": btc_swap()},
        taker_fee_bps=0.0,
        max_leverage=5.0,
    )
    opened_at = 1_800_000_000_000

    account.restore_from_trades(
        [
            {
                "id": 1,
                "timestamp": opened_at,
                "exchange": "okx",
                "symbol": "BTC/USDT:USDT",
                "side": "open_long",
                "price": 50_000.0,
                "quantity": 2.0,
                "fee": 0.0,
                "meta": {
                    "market_type": "swap",
                    "action": "open",
                    "pos_side": "long",
                    "notional_usdt": 1_000.0,
                    "leverage": 5.0,
                },
            }
        ]
    )

    position = account.get_position("BTC/USDT:USDT", "long")
    assert position is not None
    assert position["opened_at"] == opened_at


def test_contract_paper_broker_defaults_fee_schedule_by_exchange():
    config = {
        "contract_instruments": {
            "BTC/USDT:USDT": {
                "inst_id": "BTC-USDT-SWAP",
                "ct_val": 0.01,
                "lot_sz": 1.0,
                "min_sz": 1.0,
                "tick_sz": 0.1,
                "max_leverage": 5.0,
                "state": "live",
            }
        },
        "max_leverage": 5.0,
    }

    okx_broker = ContractPaperBroker(
        initial_capital=10_000.0,
        strategy_id=0,
        exchange_name="okx",
        symbols=["BTC/USDT:USDT"],
        config=config,
    )
    binance_broker = ContractPaperBroker(
        initial_capital=10_000.0,
        strategy_id=0,
        exchange_name="binanceusdm",
        symbols=["BTC/USDT:USDT"],
        config=config,
    )

    assert okx_broker.account.maker_fee_bps == pytest.approx(2.0)
    assert okx_broker.account.taker_fee_bps == pytest.approx(5.0)
    assert binance_broker.account.maker_fee_bps == pytest.approx(1.8)
    assert binance_broker.account.taker_fee_bps == pytest.approx(4.5)


def test_contract_paper_broker_attaches_signal_bar_timestamp_to_open_position():
    signal_ts = 1_800_000_000_000
    broker = ContractPaperBroker(
        initial_capital=10_000.0,
        strategy_id=0,
        exchange_name="okx",
        symbols=["BTC/USDT:USDT"],
        config={
            "contract_instruments": {
                "BTC/USDT:USDT": {
                    "inst_id": "BTC-USDT-SWAP",
                    "ct_val": 0.01,
                    "lot_sz": 1.0,
                    "min_sz": 1.0,
                    "tick_sz": 0.1,
                    "max_leverage": 5.0,
                    "state": "live",
                }
            },
            "max_leverage": 5.0,
        },
    )
    broker.update_mark_price("BTC/USDT:USDT", 50_000.0)
    broker.set_signal_bar_timestamp(signal_ts)

    opened = asyncio.run(broker.open_contract("BTC/USDT:USDT", "long", 1_000.0, leverage=5.0))
    position = asyncio.run(broker.get_contract_position("BTC/USDT:USDT", "long"))

    assert opened["opened_bar_timestamp"] == signal_ts
    assert position["opened_bar_timestamp"] == signal_ts


def test_open_contract_rejects_below_min_size_and_excessive_leverage():
    account = ContractPaperAccount(
        initial_equity=1_000.0,
        instruments={"BTC/USDT:USDT": btc_swap()},
        max_leverage=5.0,
    )
    account.update_mark_price("BTC/USDT:USDT", 50_000.0)

    with pytest.raises(ValueError, match="below OKX minSz"):
        account.open_position("BTC/USDT:USDT", "long", notional_usdt=100.0, leverage=5.0)

    with pytest.raises(ValueError, match="max leverage"):
        account.open_position("BTC/USDT:USDT", "long", notional_usdt=1_000.0, leverage=10.0)


def test_long_and_short_positions_can_exist_independently_and_close_with_pnl():
    account = ContractPaperAccount(
        initial_equity=10_000.0,
        instruments={"BTC/USDT:USDT": btc_swap()},
        taker_fee_bps=5.0,
        max_leverage=5.0,
    )
    account.update_mark_price("BTC/USDT:USDT", 50_000.0)
    account.open_position("BTC/USDT:USDT", "long", notional_usdt=1_000.0, leverage=5.0)
    account.open_position("BTC/USDT:USDT", "short", notional_usdt=1_000.0, leverage=5.0)

    assert account.get_position("BTC/USDT:USDT", "long")["contracts"] == 2.0
    assert account.get_position("BTC/USDT:USDT", "short")["contracts"] == 2.0

    account.update_mark_price("BTC/USDT:USDT", 51_000.0)
    closed_long = account.close_position("BTC/USDT:USDT", "long", ratio=1.0)
    closed_short = account.close_position("BTC/USDT:USDT", "short", ratio=1.0)

    assert closed_long["realized_pnl"] == pytest.approx(20.0 - 0.51)
    assert closed_short["realized_pnl"] == pytest.approx(-20.0 - 0.51)
    assert account.get_position("BTC/USDT:USDT", "long") is None
    assert account.get_position("BTC/USDT:USDT", "short") is None


def test_close_contract_returns_original_position_leverage():
    account = ContractPaperAccount(
        initial_equity=10_000.0,
        instruments={"BTC/USDT:USDT": btc_swap()},
        taker_fee_bps=5.0,
        max_leverage=5.0,
    )
    account.update_mark_price("BTC/USDT:USDT", 50_000.0)
    account.open_position("BTC/USDT:USDT", "long", notional_usdt=1_000.0, leverage=2.0)

    closed = account.close_position("BTC/USDT:USDT", "long", ratio=1.0, price=51_000.0)

    assert closed["status"] == "filled"
    assert closed["leverage"] == pytest.approx(2.0)


def test_funding_rate_debits_longs_and_credits_shorts():
    account = ContractPaperAccount(
        initial_equity=10_000.0,
        instruments={"BTC/USDT:USDT": btc_swap()},
        taker_fee_bps=0.0,
        max_leverage=5.0,
    )
    account.update_mark_price("BTC/USDT:USDT", 50_000.0)
    account.open_position("BTC/USDT:USDT", "long", notional_usdt=1_000.0, leverage=5.0)
    account.open_position("BTC/USDT:USDT", "short", notional_usdt=1_000.0, leverage=5.0)

    events = account.apply_funding("BTC/USDT:USDT", funding_rate=0.0001)

    long_pos = account.get_position("BTC/USDT:USDT", "long")
    short_pos = account.get_position("BTC/USDT:USDT", "short")
    assert len(events) == 2
    assert long_pos["funding_fee"] == pytest.approx(-0.1)
    assert short_pos["funding_fee"] == pytest.approx(0.1)
    assert account.free_balance == pytest.approx(9_600.0)


def test_mark_price_liquidates_position_when_equity_falls_below_maintenance_margin():
    account = ContractPaperAccount(
        initial_equity=250.0,
        instruments={"BTC/USDT:USDT": btc_swap()},
        taker_fee_bps=0.0,
        maintenance_margin_rate=0.005,
        max_leverage=5.0,
    )
    account.update_mark_price("BTC/USDT:USDT", 50_000.0)
    account.open_position("BTC/USDT:USDT", "long", notional_usdt=1_000.0, leverage=5.0)

    events = account.update_mark_price("BTC/USDT:USDT", 37_000.0)

    assert events[0]["type"] == "liquidation"
    assert events[0]["pos_side"] == "long"
    assert account.get_position("BTC/USDT:USDT", "long") is None


def test_isolated_contract_position_liquidates_even_when_account_has_free_balance():
    account = ContractPaperAccount(
        initial_equity=10_000.0,
        instruments={"BTC/USDT:USDT": btc_swap()},
        taker_fee_bps=0.0,
        maintenance_margin_rate=0.005,
        max_leverage=5.0,
    )
    account.update_mark_price("BTC/USDT:USDT", 50_000.0)
    account.open_position("BTC/USDT:USDT", "long", notional_usdt=1_000.0, leverage=5.0)

    assert account.update_mark_price("BTC/USDT:USDT", 40_300.0) == []
    events = account.update_mark_price("BTC/USDT:USDT", 40_000.0)

    assert len(events) == 1
    event = events[0]
    assert event["type"] == "liquidation"
    assert event["symbol"] == "BTC/USDT:USDT"
    assert event["pos_side"] == "long"
    assert event["liquidation_price"] == pytest.approx(40_201.005, rel=1e-5)
    assert event["position_equity"] <= event["maintenance_margin"]
    assert event["account_equity_before"] > event["maintenance_margin"]
    assert event["notional_usdt"] == pytest.approx(800.0)
    assert event["margin"] == pytest.approx(200.0)
    assert account.get_position("BTC/USDT:USDT", "long") is None
