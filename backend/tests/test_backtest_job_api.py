import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import backtest


RUN_REQUEST = {
    "strategy_version_id": "11111111-1111-1111-1111-111111111111",
    "dataset_snapshot_id": 1,
    "universe_snapshot_id": 1,
    "symbols": ["SH_600000"],
    "start_date": "2025-01-01",
    "end_date": "2025-01-05",
    "run_mode": "full",
}

WALK_FORWARD_REQUEST = {
    **{key: value for key, value in RUN_REQUEST.items() if key != "run_mode"},
    "train_sessions": 3,
    "test_sessions": 1,
    "step_sessions": 1,
    "parameter_grid": {"lookback": [5, 10]},
    "objective": "sharpe",
}


class BacktestJobApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(backtest.router, prefix="/backtest")
        self.client = TestClient(app)

    @patch.object(backtest.job_service, "create_job")
    def test_create_job_returns_accepted_persisted_job(self, create_job):
        create_job.return_value = {
            "job_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "status": "pending",
            "run_mode": "full",
            "progress": 0,
        }

        response = self.client.post("/backtest/jobs", json=RUN_REQUEST)

        self.assertEqual(202, response.status_code)
        self.assertEqual("pending", response.json()["status"])
        create_job.assert_called_once()
        self.assertEqual("full", create_job.call_args.kwargs["mode"])

    @patch.object(backtest.job_service, "create_walk_forward_job")
    def test_create_walk_forward_job_returns_accepted_persisted_job(self, create_job):
        create_job.return_value = {
            "job_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            "job_type": "walk_forward",
            "status": "pending",
            "run_mode": "full",
            "progress": 0,
        }

        response = self.client.post("/backtest/walk-forward/jobs", json=WALK_FORWARD_REQUEST)

        self.assertEqual(202, response.status_code)
        self.assertEqual("walk_forward", response.json()["job_type"])
        create_job.assert_called_once()

    @patch.object(backtest.job_service, "list_jobs")
    def test_list_jobs_returns_stable_envelope(self, list_jobs):
        list_jobs.return_value = [{"job_id": "job-1", "status": "running"}]

        response = self.client.get("/backtest/jobs")

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, response.json()["total"])

    @patch.object(backtest.job_service, "cancel")
    def test_cancel_job_exposes_cancelling_state(self, cancel):
        cancel.return_value = {
            "job_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "status": "cancelling",
        }

        response = self.client.post(
            "/backtest/jobs/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/cancel"
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("cancelling", response.json()["status"])

    @patch.object(backtest.job_service, "retry")
    def test_retry_job_returns_new_accepted_attempt(self, retry):
        retry.return_value = {
            "job_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "parent_job_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "attempt": 2,
            "status": "pending",
        }

        response = self.client.post(
            "/backtest/jobs/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/retry"
        )

        self.assertEqual(202, response.status_code)
        self.assertEqual(2, response.json()["attempt"])


if __name__ == "__main__":
    unittest.main()
