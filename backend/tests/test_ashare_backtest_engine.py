import unittest

from app.services.ashare_backtest_engine import AShareBacktestEngine
from app.services.backtest_metrics_service import calculate_backtest_metrics, drawdown_series, monthly_returns


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
            "trade_date": day, "symbol": "SH_600000", "name": "浦发银行",
            "open": price, "high": price * 1.02, "low": price * 0.98, "close": price,
            "volume": 1_000_000, "turnover": turnover, "source": "akshare",
        }
        for day, price in zip(dates, prices)
    ]


def intent(intent_type="order", value=100, day="2025-01-02", ordinal=0):
    return {
        "id": ordinal + 1,
        "event_ordinal": ordinal,
        "simulated_at": f"{day}T15:00:00+08:00",
        "available_at": f"{day}T15:00:00+08:00",
        "symbol": "SH_600000",
        "intent_type": intent_type,
        "payload": {
            "event_ordinal": ordinal, "simulated_at": f"{day}T15:00:00+08:00",
            "available_at": f"{day}T15:00:00+08:00", "symbol": "SH_600000",
            "intent_type": intent_type, "value": value,
        },
    }


def engine(intents, **kwargs):
    return AShareBacktestEngine(
        bars=kwargs.pop("bars", bars()), intents=intents, initial_cash=kwargs.pop("initial_cash", 100_000),
        cost_model=kwargs.pop("cost_model", COST), benchmark_symbol="SH_000300", **kwargs,
    ).run()


class AShareExecutionTests(unittest.TestCase):
    def test_close_signal_first_fills_on_next_trading_day(self):
        result = engine([intent()])
        order = result["orders"][0]
        self.assertEqual(order["signal_at"][:10], "2025-01-02")
        self.assertEqual(order["earliest_fill_at"][:10], "2025-01-03")
        self.assertEqual(order["filled_at"][:10], "2025-01-03")

    def test_same_bar_fill_never_occurs(self):
        result = engine([intent()])
        self.assertNotEqual(result["orders"][0]["signal_at"][:10], result["orders"][0]["filled_at"][:10])

    def test_last_day_signal_expires_after_a_future_earliest_fill_timestamp(self):
        result = engine([intent(day="2025-01-07")])
        order = result["orders"][0]
        self.assertEqual(order["status"], "expired")
        self.assertGreater(order["earliest_fill_at"][:10], "2025-01-07")

    def test_explicit_buy_requires_one_hundred_share_lot(self):
        result = engine([intent(value=50)])
        self.assertEqual(result["orders"][0]["rejection_code"], "INVALID_LOT_SIZE")

    def test_target_percent_rounds_down_to_board_lot(self):
        result = engine([intent("order_target_percent", 0.123)])
        self.assertEqual(result["orders"][0]["filled_quantity"] % 100, 0)

    def test_order_value_rounds_down_to_board_lot(self):
        result = engine([intent("order_value", 1_500)])
        self.assertEqual(result["orders"][0]["filled_quantity"], 100)

    def test_order_target_creates_delta_from_current_position(self):
        result = engine([intent("order_target", 300), intent("order_target", 500, "2025-01-03", 1)])
        self.assertEqual([item["filled_quantity"] for item in result["orders"]], [300, 200])

    def test_order_target_value_uses_execution_price(self):
        result = engine([intent("order_target_value", 2_500)])
        self.assertEqual(result["orders"][0]["filled_quantity"], 200)

    def test_target_percent_rejects_short_or_leverage(self):
        left = engine([intent("order_target_percent", -0.1)])
        right = engine([intent("order_target_percent", 1.1)])
        self.assertEqual(left["orders"][0]["rejection_code"], "SHORT_OR_LEVERAGE_NOT_SUPPORTED")
        self.assertEqual(right["orders"][0]["rejection_code"], "SHORT_OR_LEVERAGE_NOT_SUPPORTED")

    def test_same_day_buy_cannot_be_sold_under_t1(self):
        result = engine([intent("order", 100), intent("order_target", 0, ordinal=1)])
        self.assertEqual(result["orders"][1]["rejection_code"], "T1_NOT_AVAILABLE")

    def test_previous_day_position_is_sellable(self):
        result = engine([intent("order", 100), intent("order_target", 0, "2025-01-03", 1)])
        self.assertEqual(result["orders"][1]["status"], "filled")
        self.assertEqual(result["orders"][1]["side"], "sell")

    def test_full_position_sell_allows_odd_lot_remainder(self):
        result = engine([intent("order_target", 150), intent("order_target", 0, "2025-01-03", 1)])
        self.assertEqual(result["orders"][0]["filled_quantity"], 100)
        self.assertEqual(result["orders"][1]["filled_quantity"], 100)

    def test_suspension_delays_matching_until_next_bar(self):
        result = engine([intent()], suspensions=[{"trade_date": "2025-01-03", "symbol": "SH_600000", "suspend_type": "S"}])
        self.assertEqual(result["orders"][0]["filled_at"][:10], "2025-01-06")

    def test_permanent_suspension_expires_with_evidence(self):
        suspensions = [{"trade_date": day, "symbol": "SH_600000", "suspend_type": "S"} for day in ("2025-01-03", "2025-01-06", "2025-01-07")]
        result = engine([intent()], suspensions=suspensions)
        self.assertEqual(result["orders"][0]["rejection_code"], "SUSPENDED")

    def test_buy_at_limit_up_is_rejected(self):
        result = engine([intent()], price_limits=[{"trade_date": "2025-01-03", "symbol": "SH_600000", "has_price_limit": True, "up_limit": 11, "down_limit": 9}])
        self.assertEqual(result["orders"][0]["rejection_code"], "LIMIT_UP")

    def test_sell_at_limit_down_is_rejected(self):
        custom_bars = bars((10, 11, 9, 9))
        limits = [{"trade_date": "2025-01-06", "symbol": "SH_600000", "has_price_limit": True, "up_limit": 12, "down_limit": 9}]
        result = engine([intent(), intent("order_target", 0, "2025-01-03", 1)], bars=custom_bars, price_limits=limits)
        self.assertEqual(result["orders"][1]["rejection_code"], "LIMIT_DOWN")

    def test_no_limit_day_can_fill(self):
        rules = [{"trade_date": "2025-01-03", "symbol": "SH_600000", "has_price_limit": False, "up_limit": None, "down_limit": None}]
        self.assertEqual(engine([intent()], price_limits=rules)["orders"][0]["status"], "filled")

    def test_insufficient_cash_rejects_order(self):
        result = engine([intent("order", 100)], initial_cash=100)
        self.assertEqual(result["orders"][0]["rejection_code"], "INSUFFICIENT_CASH")

    def test_commission_minimum_is_charged(self):
        result = engine([intent()])
        self.assertEqual(result["trades"][0]["commission"], 5.0)

    def test_stamp_duty_only_applies_to_sell(self):
        result = engine([intent(), intent("order_target", 0, "2025-01-03", 1)])
        self.assertEqual(result["trades"][0]["tax"], 0)
        self.assertGreater(result["trades"][1]["tax"], 0)

    def test_transfer_fee_applies_to_both_sides(self):
        result = engine([intent(), intent("order_target", 0, "2025-01-03", 1)])
        self.assertTrue(all(item["transfer_fee"] > 0 for item in result["trades"]))

    def test_slippage_cost_is_attributed(self):
        result = engine([intent()])
        self.assertGreater(result["trades"][0]["slippage_cost"], 0)
        self.assertTrue(any(item["attribution_key"] == "slippage" for item in result["attribution"]))

    def test_cash_and_position_reconcile_to_equity(self):
        result = engine([intent("order_target_percent", 0.5)])
        for row in result["daily_equity"]:
            self.assertAlmostEqual(row["cash"] + row["market_value"], row["equity"], places=6)

    def test_capacity_warning_uses_turnover_participation(self):
        result = engine([intent("order", 1000)], bars=bars(turnover=1000))
        self.assertGreater(result["capacity_warning_count"], 0)

    def test_missing_turnover_and_limit_rules_are_explicit_quality_warnings(self):
        result = engine([intent()], bars=bars(turnover=0))
        self.assertTrue(any(item.startswith("MISSING_TURNOVER") for item in result["quality_warnings"]))
        self.assertTrue(any(item.startswith("MISSING_PRICE_LIMIT") for item in result["quality_warnings"]))

    def test_cash_dividend_increases_cash(self):
        action = {"ex_date": "2025-01-06", "symbol": "SH_600000", "cash_div_tax": 0.2, "announcement_available_at": "2025-01-01T09:00:00+08:00"}
        base = engine([intent()])
        adjusted = engine([intent()], corporate_actions=[action])
        self.assertAlmostEqual(adjusted["daily_equity"][-1]["cash"] - base["daily_equity"][-1]["cash"], 20.0, places=4)

    def test_share_dividend_reconciles_quantity_and_cost(self):
        action = {"ex_date": "2025-01-06", "symbol": "SH_600000", "stk_div": 0.1, "announcement_available_at": "2025-01-01T09:00:00+08:00"}
        result = engine([intent()], corporate_actions=[action])
        position = result["daily_positions"][-1]
        self.assertEqual(position["quantity"], 110)
        self.assertLess(position["avg_cost"], result["trades"][0]["price"])

    def test_future_unannounced_corporate_action_is_not_applied(self):
        action = {"ex_date": "2025-01-06", "symbol": "SH_600000", "stk_div": 0.1, "announcement_available_at": "2025-01-07T09:00:00+08:00"}
        result = engine([intent()], corporate_actions=[action])
        self.assertEqual(result["daily_positions"][-1]["quantity"], 100)

    def test_benchmark_nav_is_persisted_without_provider_calls(self):
        benchmark = [
            {"trade_date": day, "symbol": "SH_000300", "close": close}
            for day, close in zip(("2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"), (100, 101, 102, 104))
        ]
        result = engine([intent()], benchmark_bars=benchmark)
        self.assertAlmostEqual(result["daily_equity"][-1]["benchmark_nav"], 1.04)

    def test_daily_position_records_t1_available_quantity(self):
        result = engine([intent()])
        fill_day = [item for item in result["daily_positions"] if item["trade_date"] == "2025-01-03"][0]
        next_day = [item for item in result["daily_positions"] if item["trade_date"] == "2025-01-06"][0]
        self.assertEqual(fill_day["available_quantity"], 0)
        self.assertEqual(next_day["available_quantity"], 100)


class BacktestMetricTests(unittest.TestCase):
    def setUp(self):
        navs = (1.0, 1.02, 0.99, 1.05, 1.08)
        benchmarks = (1.0, 1.01, 1.00, 1.02, 1.03)
        dates = ("2025-01-02", "2025-01-03", "2025-01-06", "2025-02-03", "2025-02-04")
        self.rows = []
        for index, (day, nav, benchmark) in enumerate(zip(dates, navs, benchmarks)):
            self.rows.append({
                "trade_date": day, "strategy_nav": nav,
                "strategy_return": nav / navs[index - 1] - 1 if index else None,
                "benchmark_nav": benchmark,
                "benchmark_return": benchmark / benchmarks[index - 1] - 1 if index else None,
                "excess_nav": nav / benchmark,
                "equity": nav * 100000, "gross_exposure": 0.5,
            })
        self.trades = [
            {"side": "sell", "realized_pnl": 100, "holding_days": 3},
            {"side": "sell", "realized_pnl": -50, "holding_days": 5},
        ]
        self.orders = [{"status": "filled"}, {"status": "rejected", "rejection_code": "LIMIT_UP"}]
        self.metrics = {item["metric_code"]: item for item in calculate_backtest_metrics(self.rows, self.trades, self.orders, initial_cash=100000)}

    def test_total_return(self):
        self.assertAlmostEqual(self.metrics["strategy_return"]["metric_value"], 0.08)

    def test_annualized_return_is_defined(self):
        self.assertIsNotNone(self.metrics["annualized_return"]["metric_value"])

    def test_benchmark_and_excess_return(self):
        self.assertAlmostEqual(self.metrics["benchmark_return"]["metric_value"], 0.03)
        self.assertAlmostEqual(self.metrics["excess_return"]["metric_value"], 0.05)

    def test_maximum_drawdown_and_interval(self):
        metric = self.metrics["maximum_drawdown"]
        self.assertGreater(metric["metric_value"], 0)
        self.assertEqual(metric["metric_payload"]["peak_date"], "2025-01-03")
        self.assertEqual(metric["metric_payload"]["trough_date"], "2025-01-06")

    def test_sharpe_sortino_and_volatility_are_defined(self):
        for code in ("sharpe", "sortino", "annualized_volatility", "downside_volatility"):
            self.assertIsNotNone(self.metrics[code]["metric_value"])

    def test_alpha_beta_and_information_ratio_are_defined(self):
        for code in ("alpha", "beta", "information_ratio", "excess_sharpe"):
            self.assertIsNotNone(self.metrics[code]["metric_value"])

    def test_trade_win_rate_and_profit_loss_ratio(self):
        self.assertEqual(self.metrics["win_rate"]["metric_value"], 0.5)
        self.assertEqual(self.metrics["profit_loss_ratio"]["metric_value"], 2.0)

    def test_daily_win_rate(self):
        self.assertEqual(self.metrics["daily_win_rate"]["metric_value"], 0.75)

    def test_fill_and_rejection_rates(self):
        self.assertEqual(self.metrics["fill_rate"]["metric_value"], 0.5)
        self.assertEqual(self.metrics["rejection_rate"]["metric_value"], 0.5)

    def test_limit_rejection_count(self):
        self.assertEqual(self.metrics["limit_up_rejections"]["metric_value"], 1.0)

    def test_undefined_metrics_are_null_with_reason_not_zero(self):
        metrics = {item["metric_code"]: item for item in calculate_backtest_metrics([], [], [], initial_cash=100000)}
        self.assertIsNone(metrics["sharpe"]["metric_value"])
        self.assertTrue(metrics["sharpe"]["null_reason"])
        self.assertIsNone(metrics["win_rate"]["metric_value"])

    def test_drawdown_series_tracks_peak_and_trough(self):
        series, maximum, peak, trough = drawdown_series([1.0, 1.1, 0.9, 1.2])
        self.assertAlmostEqual(maximum, (1.1 - 0.9) / 1.1)
        self.assertEqual((peak, trough), (1, 2))
        self.assertEqual(series[-1], 0)

    def test_monthly_heatmap_uses_month_end_nav(self):
        matrix = monthly_returns(self.rows)
        self.assertEqual([item["month"] for item in matrix], ["2025-01", "2025-02"])
        self.assertAlmostEqual(matrix[0]["return"], -0.01)

    def test_cost_metrics_reconcile(self):
        values = {item["metric_code"]: item["metric_value"] for item in calculate_backtest_metrics(
            self.rows, self.trades, self.orders, initial_cash=100000,
            total_commission=10, total_tax=2, total_transfer_fee=1, total_slippage_cost=3,
        )}
        self.assertEqual(values["total_cost"], 16)

    def test_average_holding_and_exposure(self):
        self.assertEqual(self.metrics["average_holding_days"]["metric_value"], 4)
        self.assertEqual(self.metrics["average_exposure"]["metric_value"], 0.5)


if __name__ == "__main__":
    unittest.main()
