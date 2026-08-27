from __future__ import annotations

from pathlib import Path
import sys
import asyncio
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v2.endpoints import factorlab  # noqa: E402


def test_factorlab_task_routes_persist_rejected_trial_evidence(monkeypatch) -> None:
    task = {
        "task_id": "task-1", "status": "completed", "mode": "manual", "exchange": "CN",
        "market_type": "stock", "symbols": ["920000.BJ"], "timeframe": "1d",
        "start_ms": 1, "end_ms": 2, "factor_instance_ids": ["fv:1"],
        "manual_combination_count": 1, "provider_key": "", "model": "",
        "reasoning_effort": "", "speed_mode": "", "horizon_bars": 1,
        "base_cost_bps": 20, "stress_cost_bps": 40, "n_splits": 5,
        "max_candidates": 1, "max_runtime_sec": 60, "max_no_improvement": 1,
        "max_combination_leaves": 1, "target_accepted_candidates": 1,
        "dataset_snapshot_id": "factor-snapshot:1", "trial_cursor": 1,
        "best_trial_id": None, "stop_reason": "hard_gate_failure: fold_count",
        "archived_at": None, "created_at": "2026-08-28T00:00:00+08:00",
        "updated_at": "2026-08-28T00:00:00+08:00", "orders_created": 0, "paper_mutated": False,
    }
    trial = {
        "trial_id": "trial-1", "task_id": "task-1", "ordinal": 1,
        "semantic_hash": "hash", "model_type": "equal_weight", "feature_ids": ["fv:1"],
        "parameters": {"source": "sealed_factor_snapshot"}, "status": "rejected",
        "metrics": {"coverage": 1, "fold_count": 1, "accepted": False},
        "hard_gate_failures": ["fold_count", "cost_return_non_positive"],
        "created_at": "2026-08-28T00:00:00+08:00", "orders_created": 0, "paper_mutated": False,
    }
    monkeypatch.setattr(factorlab.factor_research_task_service, "create_task", lambda payload: task)
    monkeypatch.setattr(factorlab.factor_research_task_service, "list_tasks", lambda: [task])
    monkeypatch.setattr(factorlab.factor_research_task_service, "list_trials", lambda task_id: [trial])
    app = FastAPI()
    app.include_router(factorlab.router, prefix="/api/v2/factorlab")
    client = TestClient(app)

    created = client.post("/api/v2/factorlab/research/tasks", json={"symbols": ["920000.BJ"]})
    listed = client.get("/api/v2/factorlab/research/tasks")
    trials = client.get("/api/v2/factorlab/research/tasks/task-1/trials")

    assert created.status_code == 200
    assert created.json()["data"]["paper_mutated"] is False
    assert listed.json()["data"][0]["trial_cursor"] == 1
    assert trials.json()["data"][0]["hard_gate_failures"] == ["fold_count", "cost_return_non_positive"]


def test_factorlab_contract_uses_postgresql_counts_and_enabled_research_action() -> None:
    endpoint = (ROOT / "backend/app/api/v2/endpoints/factorlab.py").read_text(encoding="utf-8")
    page = (ROOT / "frontend/src/pages/FactorLab.tsx").read_text(encoding="utf-8")
    migration = ROOT / "backend/postgres/migrations/202608280002_factorlab_research_tasks.sql"

    assert migration.exists()
    assert "factor_lab_research_tasks" in migration.read_text(encoding="utf-8")
    assert "factor_lab_research_trials" in migration.read_text(encoding="utf-8")
    assert "factor_daily_values" in endpoint
    assert "factor_lab_research_tasks" in endpoint
    assert "启动研究待接通" not in page
    assert "26 个连续因子可用" not in page
    assert "SQLite 控制面" not in page
    assert "PostgreSQL 控制面" in page
    assert "createResearchTask" in page


def test_factorlab_summary_singleflight_reuses_one_database_read(monkeypatch) -> None:
    calls = {"count": 0}

    def slow_summary():
        calls["count"] += 1
        time.sleep(0.05)
        return {"status": "ready", "statistics": {"definition_count": 20}}

    monkeypatch.setattr(factorlab, "_summary", slow_summary)
    monkeypatch.setattr(factorlab, "_summary_cache", None)

    async def run():
        return await asyncio.gather(factorlab.summary(), factorlab.summary())

    results = asyncio.run(run())

    assert calls["count"] == 1
    assert len(results) == 2
