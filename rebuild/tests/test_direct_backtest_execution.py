from __future__ import annotations

from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ashare_backtest_engine import AShareBacktestEngine  # noqa: E402
from app.services.ashare_execution import AShareSpotBroker  # noqa: E402
from app.services.backtest_metrics_service import calculate_backtest_metrics, monthly_returns  # noqa: E402


COST = {
    "commission_rate": 0.0003,
    "minimum_commission": 5,
    "stamp_duty_rate": 0.0005,
    "transfer_fee_rate": 0.00001,
    "slippage_rate": 0.0002,
    "max_participation_rate": 0.10,
}


def bars(prices=(10, 11, 12, 13), turnover=10_000_000):
    dates = ("2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07")
    return [
        {
            "trade_date": day,
            "symbol": "600000.SH",
            "name": "浦发银行",
            "open": price,
            "high": price * 1.02,
            "low": price * 0.98,
            "close": price,
            "volume": 1_000_000,
            "turnover": turnover,
            "source": "akshare",
        }
        for day, price in zip(dates, prices)
    ]


def intent(intent_type="order", value=100, day="2025-01-02", ordinal=0):
    payload = {
        "event_ordinal": ordinal,
        "simulated_at": f"{day}T15:00:00+08:00",
        "available_at": f"{day}T15:00:00+08:00",
        "symbol": "600000.SH",
        "intent_type": intent_type,
        "value": value,
    }
    return {"id": ordinal + 1, **payload, "payload": payload}


def run(intents, **kwargs):
    return AShareBacktestEngine(
        bars=kwargs.pop("bars", bars()),
        intents=intents,
        initial_cash=kwargs.pop("initial_cash", 100_000),
        cost_model=kwargs.pop("cost_model", COST),
        benchmark_symbol="000300.SH",
        **kwargs,
    ).run()


def test_signal_fills_only_on_next_trading_day_and_never_same_bar():
    result = run([intent()])
    order = result["orders"][0]
    assert order["signal_at"][:10] == "2025-01-02"
    assert order["earliest_fill_at"][:10] == "2025-01-03"
    assert order["filled_at"][:10] == "2025-01-03"


def test_board_lot_and_t1_are_enforced():
    invalid_lot = run([intent(value=50)])
    same_day_sell = run([intent("order", 100), intent("order_target", 0, ordinal=1)])
    assert invalid_lot["orders"][0]["rejection_code"] == "INVALID_LOT_SIZE"
    assert same_day_sell["orders"][1]["rejection_code"] == "T1_NOT_AVAILABLE"


def test_previous_day_position_can_sell_with_full_a_share_fees():
    result = run([intent(), intent("order_target", 0, "2025-01-03", 1)])
    buy, sell = result["trades"]
    assert sell["side"] == "sell"
    assert buy["commission"] == 5.0
    assert buy["tax"] == 0
    assert sell["tax"] > 0
    assert buy["transfer_fee"] > 0 and sell["transfer_fee"] > 0


def test_limit_up_and_suspension_are_explicit_execution_evidence():
    limited = run(
        [intent()],
        price_limits=[{"trade_date": "2025-01-03", "symbol": "600000.SH", "has_price_limit": True, "up_limit": 11, "down_limit": 9}],
    )
    suspended = run(
        [intent()],
        suspensions=[{"trade_date": "2025-01-03", "symbol": "600000.SH", "suspend_type": "S"}],
    )
    assert limited["orders"][0]["rejection_code"] == "LIMIT_UP"
    assert suspended["orders"][0]["filled_at"][:10] == "2025-01-06"


def test_cash_positions_equity_and_cost_metrics_reconcile():
    result = run([intent("order_target_percent", 0.5)])
    assert result["trades"][0]["quantity"] % 100 == 0
    assert result["trades"][0]["slippage_cost"] > 0
    for row in result["daily_equity"]:
        assert abs(row["cash"] + row["market_value"] - row["equity"]) < 1e-6
    metrics = {item["metric_code"]: item for item in result["metrics"]}
    assert metrics["total_cost"]["metric_value"] > 0
    assert metrics["strategy_return"]["metric_value"] is not None


def test_data_availability_blocks_fill_until_following_session():
    delayed = intent()
    delayed["available_at"] = delayed["payload"]["available_at"] = "2025-01-06T15:00:00+08:00"
    order = run([delayed])["orders"][0]
    assert order["earliest_fill_at"][:10] == "2025-01-07"
    assert order["filled_at"][:10] == "2025-01-07"


def test_preopen_data_available_on_next_session_can_fill_that_session():
    available = intent()
    available["available_at"] = available["payload"]["available_at"] = "2025-01-03T08:00:00+08:00"
    order = run([available])["orders"][0]
    assert order["earliest_fill_at"] == "2025-01-03T09:30:00+08:00"


def test_symbol_aliases_normalize_but_exchange_less_intents_are_rejected():
    legacy_bars = [{**row, "symbol": "SH_600000"} for row in bars()]
    normalized = run([intent()], bars=legacy_bars)
    bare = intent()
    bare["symbol"] = bare["payload"]["symbol"] = "600000"
    rejected = run([bare])
    assert normalized["orders"][0]["status"] == "filled"
    assert normalized["trades"][0]["symbol"] == "600000.SH"
    assert rejected["orders"][0]["rejection_code"] == "INVALID_SYMBOL"


def test_bare_symbols_fail_closed_in_shared_broker_and_auxiliary_evidence():
    broker = AShareSpotBroker(COST).evaluate(
        side="buy", symbol="600000", quantity=100, price=10, trade_date="2025-01-02",
        cash=100_000, available_quantity=0, bar=bars()[0],
    )
    assert broker["rejection_code"] == "INVALID_SYMBOL"
    malformed = AShareSpotBroker(COST).evaluate(
        side="buy", symbol="foo600000.SH", quantity=100, price=10, trade_date="2025-01-02",
        cash=100_000, available_quantity=0, bar=bars()[0],
    )
    assert malformed["rejection_code"] == "INVALID_SYMBOL"
    try:
        run([intent()], price_limits=[{"trade_date": "2025-01-03", "symbol": "600000", "has_price_limit": True, "up_limit": 11}])
    except ValueError as exc:
        assert "INVALID_SYMBOL:price_limit" in str(exc)
    else:
        raise AssertionError("bare auxiliary symbol must fail closed")


def test_missing_position_bar_carries_last_close_with_quality_evidence():
    source = bars()
    missing_day = "2025-01-06"
    mixed = [row for row in source if row["trade_date"] != missing_day]
    mixed.append({**source[2], "symbol": "000001.SZ"})
    result = run([intent()], bars=mixed)
    mark = next(row for row in result["daily_positions"] if row["trade_date"] == missing_day and row["symbol"] == "600000.SH")
    assert mark["close_price"] == 11
    assert f"MISSING_MARK_PRICE:{missing_day}:600000.SH" in result["quality_warnings"]


def test_suspended_position_carries_last_valid_close():
    custom = bars((10, 11, 1, 13))
    result = run(
        [intent()],
        bars=custom,
        suspensions=[{"trade_date": "2025-01-06", "symbol": "600000.SH", "suspend_type": "S"}],
    )
    mark = next(row for row in result["daily_positions"] if row["trade_date"] == "2025-01-06")
    assert mark["close_price"] == 11
    assert "SUSPENDED_MARK_PRICE:2025-01-06:600000.SH" in result["quality_warnings"]


def test_sealed_calendar_preserves_day_when_all_security_bars_are_missing():
    source = [row for row in bars() if row["trade_date"] != "2025-01-06"]
    calendar = [
        {"trade_date": day, "is_open": 1}
        for day in ("2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07")
    ]
    result = AShareBacktestEngine(
        bars=source,
        intents=[intent()],
        initial_cash=100_000,
        cost_model=COST,
        benchmark_symbol="000300.SH",
        trading_calendar=calendar,
    ).run()
    assert any(row["trade_date"] == "2025-01-06" for row in result["daily_equity"])
    assert "MISSING_MARK_PRICE:2025-01-06:600000.SH" in result["quality_warnings"]


def test_slippage_cannot_cross_price_limit():
    custom = bars((10, 10.999, 12, 13))
    result = run(
        [intent()],
        bars=custom,
        price_limits=[{"trade_date": "2025-01-03", "symbol": "600000.SH", "has_price_limit": True, "up_limit": 11, "down_limit": 9}],
    )
    assert result["orders"][0]["rejection_code"] == "LIMIT_UP"
    assert result["trades"] == []


def test_attribution_is_additive_to_total_equity_pnl():
    result = run([intent(), intent("order_target", 0, "2025-01-03", 1)])
    total_attribution = sum(float(item["amount"]) for item in result["attribution"])
    total_pnl = result["daily_equity"][-1]["equity"] - 100_000
    assert abs(total_attribution - total_pnl) < 0.01


def test_metric_pairing_uses_same_trade_date_and_excess_dates():
    rows = [
        {"trade_date": "2025-01-02", "strategy_nav": 1.0, "strategy_return": None, "benchmark_nav": 1.0, "benchmark_return": None, "excess_nav": 1.0, "equity": 100_000, "gross_exposure": 0},
        {"trade_date": "2025-01-03", "strategy_nav": 1.2, "strategy_return": 0.2, "benchmark_nav": 1.1, "benchmark_return": 0.1, "excess_nav": None, "equity": 120_000, "gross_exposure": 0},
        {"trade_date": "2025-01-06", "strategy_nav": 2.16, "strategy_return": 0.8, "benchmark_nav": None, "benchmark_return": None, "excess_nav": 0.8, "equity": 216_000, "gross_exposure": 0},
        {"trade_date": "2025-01-07", "strategy_nav": 1.944, "strategy_return": -0.1, "benchmark_nav": 1.155, "benchmark_return": 0.05, "excess_nav": 1.2, "equity": 194_400, "gross_exposure": 0},
    ]
    metrics = {item["metric_code"]: item for item in calculate_backtest_metrics(rows, [], [], initial_cash=100_000)}
    assert abs(metrics["daily_average_excess_return"]["metric_value"] - (-0.025)) < 1e-9
    assert metrics["excess_maximum_drawdown"]["metric_payload"]["trough_date"] == "2025-01-06"


def test_missing_benchmark_price_is_unknown_not_zero_return():
    benchmark = [
        {"trade_date": "2025-01-02", "symbol": "000300.SH", "close": 100},
        {"trade_date": "2025-01-03", "symbol": "000300.SH", "close": 101},
        {"trade_date": "2025-01-07", "symbol": "000300.SH", "close": 104},
    ]
    result = AShareBacktestEngine(
        bars=bars(), intents=[intent()], initial_cash=100_000, cost_model=COST,
        benchmark_bars=benchmark, benchmark_symbol="000300.SH",
    ).run()
    missing = next(row for row in result["daily_equity"] if row["trade_date"] == "2025-01-06")
    assert missing["benchmark_nav"] is not None
    assert missing["benchmark_return"] is None
    assert "MISSING_BENCHMARK_PRICE:2025-01-06:000300.SH" in result["quality_warnings"]


def test_monthly_return_includes_previous_month_end_to_first_day_move():
    rows = [
        {"trade_date": "2025-01-31", "strategy_nav": 1.0},
        {"trade_date": "2025-02-03", "strategy_nav": 1.1},
        {"trade_date": "2025-02-28", "strategy_nav": 1.21},
    ]
    values = {item["month"]: item["return"] for item in monthly_returns(rows)}
    assert abs(values["2025-02"] - 0.21) < 1e-9


def test_fixed_inputs_produce_deterministic_order_and_trade_ids():
    left = run([intent()])
    right = run([intent()])
    assert left["orders"][0]["id"] == right["orders"][0]["id"]
    assert left["trades"][0]["id"] == right["trades"][0]["id"]


def test_shared_spot_broker_rejects_unknown_side():
    result = AShareSpotBroker(COST).evaluate(
        side="hold",
        symbol="600000.SH",
        quantity=100,
        price=10,
        trade_date="2025-01-02",
        cash=100_000,
        available_quantity=100,
        bar=bars()[0],
    )
    assert result["accepted"] is False
    assert result["rejection_code"] == "INVALID_SIDE"
