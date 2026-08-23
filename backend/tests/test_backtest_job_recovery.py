from __future__ import annotations

import os
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_recovery_is_idempotent_when_no_jobs_are_active() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    assert database_url.endswith("/stockpro_bitpro_rebase_dev")

    from app.db.postgres_db import PostgresDatabase
    from app.services.backtest_job_service import BacktestJobService

    database = PostgresDatabase(database_url)
    try:
        before_jobs = database._fetch_all("SELECT status,COUNT(*)::integer AS count FROM backtest_jobs GROUP BY status ORDER BY status")
        before_runs = database._fetch_all("SELECT status,COUNT(*)::integer AS count FROM backtest_runs GROUP BY status ORDER BY status")

        recovered = BacktestJobService(database).recover_interrupted()

        assert recovered == 0
        assert database._fetch_all("SELECT status,COUNT(*)::integer AS count FROM backtest_jobs GROUP BY status ORDER BY status") == before_jobs
        assert database._fetch_all("SELECT status,COUNT(*)::integer AS count FROM backtest_runs GROUP BY status ORDER BY status") == before_runs
    finally:
        database.close_pool()
