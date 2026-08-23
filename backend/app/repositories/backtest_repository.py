from __future__ import annotations

from typing import Any, Mapping


class PostgresBacktestRepository:
    def __init__(self, database) -> None:
        self.database = database
        self._workbench = None
        self._jobs = None
        self._walk = None

    @property
    def workbench(self):
        if self._workbench is None:
            from app.services.backtest_workbench_service import BacktestWorkbenchService

            self._workbench = BacktestWorkbenchService(self.database)
        return self._workbench

    @property
    def jobs(self):
        if self._jobs is None:
            from app.services.backtest_job_service import BacktestJobService

            self._jobs = BacktestJobService(self.database)
        return self._jobs

    @property
    def walk(self):
        if self._walk is None:
            from app.services.walk_forward_plan_service import WalkForwardExecutionService

            self._walk = WalkForwardExecutionService(self.database)
        return self._walk

    def run(self, payload: dict[str, Any], mode: str) -> dict[str, Any]:
        return self.workbench.run(payload, mode=mode)

    def run_matrix(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.workbench.run_matrix(
            str(payload["experiment_id"]),
            payload.get("parameter_grid") or {},
            payload.get("run_payload") or {},
        )

    def run_walk_forward(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.walk.execute(payload)

    def configuration(self) -> dict[str, Any]: return self.workbench.configuration()
    def list_runs(self, limit: int) -> list[dict[str, Any]]: return self.workbench.list_runs(limit)
    def get_run(self, run_id: str) -> dict[str, Any]: return self.workbench.get_run(run_id)
    def metrics(self, run_id: str) -> list[dict[str, Any]]: return self.workbench.metrics(run_id)
    def series(self, run_id: str) -> dict[str, Any]: return self.workbench.series(run_id)
    def orders(self, run_id: str) -> list[dict[str, Any]]: return self.workbench.orders(run_id)
    def trades(self, run_id: str) -> list[dict[str, Any]]: return self.workbench.trades(run_id)
    def positions(self, run_id: str, trade_date: str | None) -> list[dict[str, Any]]: return self.workbench.positions(run_id, trade_date)
    def logs(self, run_id: str) -> list[dict[str, Any]]: return self.workbench.logs(run_id)
    def compare(self, run_ids: list[str]) -> dict[str, Any]: return self.workbench.compare(run_ids)
    def list_jobs(self, principal: Mapping[str, Any], limit: int) -> list[dict[str, Any]]: return self.jobs.list_jobs(principal, limit=limit)
    def get_job(self, job_id: str, principal: Mapping[str, Any]) -> dict[str, Any]: return self.jobs.get_job(job_id, principal)
    def job_logs(self, job_id: str, principal: Mapping[str, Any], after_id: int, limit: int) -> list[dict[str, Any]]: return self.jobs.logs(job_id, principal, after_id=after_id, limit=limit)
    def create_job(self, payload: dict[str, Any], mode: str, principal: Mapping[str, Any]) -> dict[str, Any]: return self.jobs.create_job(payload, mode=mode, principal=principal)
    def cancel_job(self, job_id: str, principal: Mapping[str, Any]) -> dict[str, Any]: return self.jobs.cancel(job_id, principal)
    def retry_job(self, job_id: str, principal: Mapping[str, Any]) -> dict[str, Any]: return self.jobs.retry(job_id, principal)
