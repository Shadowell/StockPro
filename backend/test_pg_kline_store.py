import os
import unittest
from datetime import date, timedelta

from app.db.postgres_db import PostgresDatabase


class PostgresKlineStoreTest(unittest.TestCase):
    def setUp(self):
        database_url = os.getenv(
            "STOCKPRO_TEST_DATABASE_URL",
            "postgresql://stockpro:stockpro@127.0.0.1:55432/stockpro",
        )
        self.db = PostgresDatabase(database_url=database_url)
        self.db.init_db()
        self.symbols = ["SH_909001", "SZ_909002"]
        self.start_date = "2099-02-01"
        self.end_date = "2099-02-05"
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        with self.db.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM kline_1d WHERE symbol = ANY(%s) AND trade_date BETWEEN %s AND %s",
                    (self.symbols, self.start_date, self.end_date),
                )
                cursor.execute(
                    "DELETE FROM kline_history WHERE symbol = ANY(%s) AND trade_date BETWEEN %s AND %s",
                    (self.symbols, self.start_date, self.end_date),
                )
                cursor.execute(
                    "DELETE FROM sync_metadata WHERE symbol = ANY(%s)",
                    (self.symbols,),
                )
                cursor.execute(
                    "DELETE FROM sync_jobs WHERE job_name LIKE %s",
                    ("test-kline-sync-%",),
                )

    def _bars(self, symbol: str, name: str):
        start = date(2099, 2, 1)
        closes = [10.0, 10.4, 10.8, 10.3, 11.1]
        return [
            {
                "exchange": "cn",
                "symbol": symbol,
                "name": name,
                "date": (start + timedelta(days=idx)).isoformat(),
                "open": close - 0.1,
                "high": close + 0.2,
                "low": close - 0.3,
                "close": close,
                "volume": 1000000 + idx * 1000,
                "turnover": 10000000 + idx * 10000,
                "source": "unit-test",
            }
            for idx, close in enumerate(closes)
        ]

    def test_insert_klines_writes_split_table_unified_table_and_metadata(self):
        self.db.insert_klines(self._bars("SH_909001", "测试K线A"), timeframe="1d")

        rows = self.db.get_kline_history(
            "SH_909001",
            timeframe="1d",
            start_date=self.start_date,
            end_date=self.end_date,
        )
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["date"], self.start_date)
        self.assertEqual(rows[-1]["date"], self.end_date)
        self.assertEqual(rows[-1]["close"], 11.1)

        with self.db.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM kline_1d WHERE symbol = %s AND trade_date BETWEEN %s AND %s",
                    ("SH_909001", self.start_date, self.end_date),
                )
                self.assertEqual(cursor.fetchone()[0], 5)
                cursor.execute(
                    "SELECT COUNT(*) FROM kline_history WHERE symbol = %s AND timeframe = %s",
                    ("SH_909001", "1d"),
                )
                self.assertEqual(cursor.fetchone()[0], 5)

        metadata = self.db.get_sync_metadata("SH_909001", timeframe="1d")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["status"], "success")
        self.assertEqual(metadata["total_records"], 5)
        self.assertEqual(metadata["first_timestamp"], self.start_date)
        self.assertEqual(metadata["last_timestamp"], self.end_date)

        coverage = self.db.kline_coverage()
        matching = [item for item in coverage if item["symbol"] == "SH_909001" and item["timeframe"] == "1d"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["rows"], 5)

    def test_sync_job_lifecycle_tracks_items_and_progress(self):
        job_id = self.db.create_sync_job(
            job_name="test-kline-sync-209902",
            symbols=self.symbols,
            timeframes=["1d"],
            start_date=self.start_date,
            end_date=self.end_date,
            source="unit-test",
        )

        pending = self.db.get_sync_job_items(job_id, status="pending")
        self.assertEqual(len(pending), 2)
        self.assertEqual({item["symbol"] for item in pending}, set(self.symbols))

        self.db.update_sync_job_item(
            pending[0]["id"],
            status="success",
            records_count=5,
            error_message=None,
        )
        self.db.refresh_sync_job_progress(job_id)
        job = self.db.get_sync_job(job_id)
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["completed_items"], 1)
        self.assertEqual(job["failed_items"], 0)

        self.db.update_sync_job_item(
            pending[1]["id"],
            status="failed",
            records_count=0,
            error_message="AkShare unavailable",
        )
        self.db.refresh_sync_job_progress(job_id)
        job = self.db.get_sync_job(job_id)
        self.assertEqual(job["status"], "partial")
        self.assertEqual(job["completed_items"], 1)
        self.assertEqual(job["failed_items"], 1)
        self.assertEqual(job["total_items"], 2)


if __name__ == "__main__":
    unittest.main()
