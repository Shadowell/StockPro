import os
import unittest

from app.db.postgres_db import PostgresDatabase
from app.services.kline_sync_service import KlineSyncService


class KlineSyncServiceTest(unittest.TestCase):
    def setUp(self):
        database_url = os.getenv(
            "STOCKPRO_TEST_DATABASE_URL",
            "postgresql://stockpro:stockpro@127.0.0.1:55432/stockpro",
        )
        self.db = PostgresDatabase(database_url=database_url)
        self.db.init_db()
        self.symbol = "SH_909003"
        self.start_date = "2099-03-01"
        self.end_date = "2099-03-03"
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        with self.db.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM kline_1d WHERE symbol = %s AND trade_date BETWEEN %s AND %s",
                    (self.symbol, self.start_date, self.end_date),
                )
                cursor.execute(
                    "DELETE FROM kline_history WHERE symbol = %s AND trade_date BETWEEN %s AND %s",
                    (self.symbol, self.start_date, self.end_date),
                )
                cursor.execute("DELETE FROM sync_metadata WHERE symbol = %s", (self.symbol,))
                cursor.execute("DELETE FROM sync_jobs WHERE job_name LIKE %s", ("test-service-sync-%",))

    def test_run_history_sync_job_fetches_klines_and_marks_job_success(self):
        def fake_fetcher(symbol, timeframe, start_date, end_date):
            self.assertEqual(symbol, self.symbol)
            self.assertEqual(timeframe, "1d")
            self.assertEqual(start_date, self.start_date)
            self.assertEqual(end_date, self.end_date)
            return [
                {"symbol": symbol, "name": "测试同步", "date": "2099-03-01", "open": 10, "high": 11, "low": 9.8, "close": 10.5, "volume": 1000, "turnover": 10000},
                {"symbol": symbol, "name": "测试同步", "date": "2099-03-02", "open": 10.5, "high": 11.2, "low": 10.1, "close": 11, "volume": 1100, "turnover": 12100},
                {"symbol": symbol, "name": "测试同步", "date": "2099-03-03", "open": 11, "high": 11.5, "low": 10.8, "close": 11.4, "volume": 1200, "turnover": 13680},
            ]

        service = KlineSyncService(self.db, fetcher=fake_fetcher)
        job_id = service.create_history_sync_job(
            symbols=[self.symbol],
            timeframes=["1d"],
            start_date=self.start_date,
            end_date=self.end_date,
            job_name="test-service-sync-209903",
        )
        result = service.run_job(job_id)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["completed_items"], 1)
        self.assertEqual(result["failed_items"], 0)
        rows = self.db.get_kline_history(self.symbol, timeframe="1d", start_date=self.start_date, end_date=self.end_date)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]["close"], 11.4)


if __name__ == "__main__":
    unittest.main()
