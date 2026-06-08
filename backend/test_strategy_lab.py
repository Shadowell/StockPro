import os
import unittest
from datetime import date, timedelta

from app.db.postgres_db import PostgresDatabase
from app.services.strategy_lab_service import StrategyLabService


CUSTOM_STRATEGY = """
import backtrader as bt

class CustomMomentumStrategy(bt.Strategy):
    params = dict(position_pct=0.45)

    def next(self):
        for data in self.datas:
            pos = self.getposition(data)
            cash = self.broker.getcash()
            if not pos and len(data.close) >= 2 and data.close[0] > data.close[-1]:
                size = int((cash * self.p.position_pct / data.close[0]) // 100) * 100
                if size > 0:
                    self.buy(data=data, size=size)
            elif pos and len(data.close) >= 2 and data.close[0] < data.close[-1]:
                self.sell(data=data, size=pos.size)
"""


class StrategyLabServiceTest(unittest.TestCase):
    def setUp(self):
        database_url = os.getenv(
            "STOCKPRO_TEST_DATABASE_URL",
            "postgresql://stockpro:stockpro@127.0.0.1:55432/stockpro",
        )
        self.db = PostgresDatabase(database_url=database_url)
        self.db.init_db()
        self.test_start = "2099-01-01"
        self.test_end = "2099-01-08"
        self.symbols = ["SH_909101", "SZ_909102"]
        self.created_strategy_ids = []
        start = date(2099, 1, 1)
        price_sets = {
            "SH_909101": ("测试浦发", [10, 10.4, 10.9, 10.2, 11.2, 12.0, 12.4, 12.8]),
            "SZ_909102": ("测试平安", [8, 8.2, 8.5, 8.7, 9.0, 8.8, 9.4, 9.8]),
        }
        rows = []
        for symbol, (name, prices) in price_sets.items():
            for idx, close in enumerate(prices):
                rows.append(
                    {
                        "symbol": symbol,
                        "name": name,
                        "date": (start + timedelta(days=idx)).isoformat(),
                        "open": close - 0.1,
                        "high": close + 0.2,
                        "low": close - 0.3,
                        "close": close,
                        "volume": 1000000 + idx * 1000,
                        "turnover": 10000000 + idx * 10000,
                    }
                )
        self.db.insert_stock_history_batch(rows)
        self.strategy_id = self.db.save_strategy(
            name="双股动量策略",
            description="测试策略",
            script_content=CUSTOM_STRATEGY,
            interval_seconds=60,
        )
        self.created_strategy_ids.append(self.strategy_id)
        self.service = StrategyLabService(self.db)

    def tearDown(self):
        with self.db.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id FROM paper_accounts WHERE strategy_id = ANY(%s)", (self.created_strategy_ids,))
                account_ids = [row[0] for row in cursor.fetchall()]
                if account_ids:
                    cursor.execute("DELETE FROM paper_orders WHERE account_id = ANY(%s)", (account_ids,))
                    cursor.execute("DELETE FROM paper_positions WHERE account_id = ANY(%s)", (account_ids,))
                    cursor.execute("DELETE FROM paper_equity_curve WHERE account_id = ANY(%s)", (account_ids,))
                    cursor.execute("DELETE FROM paper_events WHERE account_id = ANY(%s)", (account_ids,))
                    cursor.execute("DELETE FROM paper_accounts WHERE id = ANY(%s)", (account_ids,))
                if self.created_strategy_ids:
                    cursor.execute("DELETE FROM strategy_backtest_results WHERE strategy_id = ANY(%s)", (self.created_strategy_ids,))
                    cursor.execute("DELETE FROM strategy_results WHERE strategy_id = ANY(%s)", (self.created_strategy_ids,))
                    cursor.execute("DELETE FROM strategy_scripts WHERE id = ANY(%s)", (self.created_strategy_ids,))
                cursor.execute(
                    "DELETE FROM stock_history WHERE symbol = ANY(%s) AND date BETWEEN %s AND %s",
                    (self.symbols, self.test_start, self.test_end),
                )
                cursor.execute(
                    "DELETE FROM kline_1d WHERE symbol = ANY(%s) AND trade_date BETWEEN %s AND %s",
                    (self.symbols, self.test_start, self.test_end),
                )
                cursor.execute(
                    "DELETE FROM kline_history WHERE symbol = ANY(%s) AND trade_date BETWEEN %s AND %s",
                    (self.symbols, self.test_start, self.test_end),
                )
                cursor.execute(
                    "DELETE FROM sync_metadata WHERE symbol = ANY(%s)",
                    (self.symbols,),
                )

    def test_backtrader_backtest_generates_portfolio_metrics_curve_and_trades(self):
        result = self.service.run_backtest(
            strategy_id=self.strategy_id,
            symbols=self.symbols,
            start_date=self.test_start,
            end_date=self.test_end,
            initial_capital=100000,
            commission=0.0003,
            stamp_duty=0.001,
            slippage=0.0002,
            min_commission=5,
        )

        self.assertEqual(result["engine"], "backtrader")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(set(result["symbols"]), set(self.symbols))
        self.assertEqual(result["symbol_names"]["SH_909101"], "测试浦发")
        self.assertEqual(result["symbol_names"]["SZ_909102"], "测试平安")
        self.assertGreater(result["final_capital"], 0)
        self.assertGreaterEqual(len(result["equity_curve"]), 8)
        self.assertGreater(result["total_trades"], 0)
        self.assertIn("sharpe", result)
        self.assertIn("annual_return", result)
        self.assertTrue(all(trade["quantity"] % 100 == 0 for trade in result["trades"]))
        self.assertTrue(all(trade["side"] in {"buy", "sell"} for trade in result["trades"]))
        saved = self.service.list_backtest_results(limit=5)
        saved_result = next(item for item in saved if item["backtest_id"] == result["backtest_id"])
        self.assertEqual(saved_result["symbol_names"]["SH_909101"], "测试浦发")
        self.assertEqual(saved_result["symbol_names"]["SZ_909102"], "测试平安")

    def test_custom_strategy_safety_allows_bt_strategy_and_blocks_dangerous_code(self):
        strategy_cls = self.service.load_custom_strategy_class(CUSTOM_STRATEGY)
        self.assertEqual(strategy_cls.__name__, "CustomMomentumStrategy")

        with self.assertRaises(ValueError):
            self.service.load_custom_strategy_class(
                """
import os
import backtrader as bt

class BadStrategy(bt.Strategy):
    def next(self):
        os.system("echo unsafe")
"""
            )

    def test_auto_develop_strategy_saves_full_backtrader_strategy_class(self):
        result = self.service.auto_develop_strategy(
            objective="首板突破",
            symbols=self.symbols,
            risk_level="balanced",
        )
        self.created_strategy_ids.append(result["id"])

        self.assertTrue(result["success"])
        self.assertGreater(result["id"], 0)
        self.assertIn("A股", result["generated_plan"])
        self.assertIn("class", result["strategy"]["script_content"])
        self.assertIn("bt.Strategy", result["strategy"]["script_content"])
        self.assertIn("SH_909101", result["strategy"]["script_content"])
        saved = self.db.get_strategy_by_id(result["id"])
        self.assertIsNotNone(saved)
        self.assertEqual(saved["name"], result["strategy"]["name"])

    def test_paper_account_can_refresh_and_stop_with_events(self):
        started = self.service.run_paper_trading(
            strategy_id=self.strategy_id,
            symbols=self.symbols,
            initial_capital=100000,
        )

        self.assertEqual(started["status"], "running")
        self.assertEqual(started["strategy_id"], self.strategy_id)
        self.assertGreaterEqual(len(started["orders"]), 1)
        self.assertGreaterEqual(len(started["positions"]), 1)
        self.assertGreaterEqual(len(started["events"]), 1)

        refreshed = self.service.refresh_paper_account(started["account_id"])
        self.assertEqual(refreshed["status"], "running")
        self.assertGreaterEqual(len(refreshed["equity_curve"]), 1)
        self.assertGreaterEqual(len(refreshed["events"]), 1)

        stopped = self.service.stop_paper_account(started["account_id"])
        self.assertEqual(stopped["status"], "stopped")
        self.assertGreaterEqual(len(stopped["events"]), 1)


if __name__ == "__main__":
    unittest.main()
