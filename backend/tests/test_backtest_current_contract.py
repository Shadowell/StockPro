from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.backtest_application_service import BacktestApplicationService


class FakeBacktestRepository:
    def run(self, payload, mode: str):
        return {"id": f"run-{mode}", "mode": mode, "promotion_status": "eligible" if mode == "full" else "not_evaluated", "promotion_checks": [{"code": "FULL_SEALED_RUN", "passed": True}] if mode == "full" else []}

    def run_matrix(self, payload):
        return {"experiment_id": "exp-1", "cells": [{"id": "cell-1", "promotion_status": "eligible"}, {"id": "cell-2", "promotion_status": "eligible"}]}

    def run_walk_forward(self, payload):
        return {"job_id": "walk-1", "folds": [{"index": 1, "promotion_eligible": True}]}


def test_only_full_protocol_run_can_be_paper_eligible() -> None:
    service = BacktestApplicationService(FakeBacktestRepository())

    quick = service.run({}, mode="quick")
    matrix = service.run_matrix({"parameter_grid": {"lookback": [5, 10]}})
    walk = service.run_walk_forward({"train_sessions": 252, "test_sessions": 63, "step_sessions": 63})
    full = service.run({}, mode="full")

    assert quick["promotion_status"] == "not_evaluated"
    assert all(cell["promotion_status"] == "not_evaluated" for cell in matrix["cells"])
    assert all(fold["promotion_eligible"] is False for fold in walk["folds"])
    assert full["promotion_checks"]
