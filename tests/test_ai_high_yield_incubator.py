from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ai_high_yield_incubator.py"
spec = importlib.util.spec_from_file_location("ai_high_yield_incubator", SCRIPT_PATH)
incubator = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = incubator
spec.loader.exec_module(incubator)


class FakeClient:
    def __init__(self):
        self.tasks: List[Dict[str, Any]] = []
        self.iterations: Dict[str, List[Dict[str, Any]]] = {}
        self.dashboards: Dict[int, Dict[str, Any]] = {}
        self.created_tasks: List[Dict[str, Any]] = []
        self.accepted: List[tuple[str, int]] = []
        self.configured: List[tuple[int, Dict[str, Any]]] = []
        self.started: List[int] = []
        self.stopped: List[int] = []
        self.next_strategy_id = 100

    def list_tasks(self):
        return list(self.tasks)

    def create_task(self, payload):
        task_id = f"task{len(self.created_tasks) + 1}"
        self.created_tasks.append(payload)
        self.tasks.append(
            {
                "task_id": task_id,
                "status": "pending",
                "timeframe": payload["timeframe"],
                "created_at": "2026-05-03T00:00:00Z",
                "iterations_count": 0,
            }
        )
        return {"task_id": task_id}

    def resume_task(self, task_id):
        for task in self.tasks:
            if task["task_id"] == task_id:
                task["status"] = "pending"
        return {"task_id": task_id, "status": "pending"}

    def get_iterations(self, task_id):
        return list(self.iterations.get(task_id, []))

    def accept_iteration(self, task_id, iteration):
        self.accepted.append((task_id, iteration))
        self.next_strategy_id += 1
        return {"strategy_id": self.next_strategy_id, "strategy_name": f"candidate-{self.next_strategy_id}"}

    def configure_paper_strategy(self, strategy_id, **kwargs):
        self.configured.append((strategy_id, dict(kwargs)))
        return {"strategy_id": strategy_id, "configured": True}

    def start_strategy(self, strategy_id):
        self.started.append(strategy_id)
        self.dashboards.setdefault(
            strategy_id,
            {
                "system": {"state": "running", "dry_run": True, "mode": "paper"},
                "performance": {"total_pnl_pct": 0},
            },
        )
        self.dashboards[strategy_id]["system"]["state"] = "running"
        return {"strategy_id": strategy_id, "started": True}

    def stop_strategy(self, strategy_id):
        self.stopped.append(strategy_id)
        self.dashboards.setdefault(strategy_id, {"system": {}})
        self.dashboards[strategy_id]["system"]["state"] = "stopped"
        return {"strategy_id": strategy_id, "stopped": True}

    def dashboard(self, strategy_id):
        return self.dashboards[strategy_id]


def test_acceptance_candidates_prefers_high_return_and_filters_bad_records():
    cfg = incubator.IncubatorConfig(min_backtest_return_pct=10, min_backtest_trades=20)
    records = [
        {
            "iteration": 0,
            "strategy_code": "code",
            "score": 80,
            "backtest_metrics": {"total_return_pct": 9, "total_trades": 80},
        },
        {
            "iteration": 1,
            "strategy_code": "code",
            "score": 50,
            "backtest_metrics": {"total_return_pct": 40, "total_trades": 5},
        },
        {
            "iteration": 2,
            "strategy_code": "code",
            "score": 70,
            "backtest_metrics": {"total_return_pct": 25, "total_trades": 30, "profit_factor": 1.4},
        },
        {
            "iteration": 3,
            "strategy_code": "code",
            "score": 65,
            "backtest_metrics": {"total_return_pct": 35, "total_trades": 30, "profit_factor": 1.2},
        },
    ]

    selected = incubator.acceptance_candidates(records, cfg, accepted_iterations=[])

    assert [r["iteration"] for r in selected] == [3, 2]


def test_evaluate_candidates_stops_four_hour_underperformer():
    now = datetime(2026, 5, 3, 8, 0, tzinfo=timezone.utc)
    cfg = incubator.IncubatorConfig(evaluation_hours=4, target_return_pct=10)
    state = incubator.empty_state()
    state["candidates"]["101"] = {
        "strategy_id": 101,
        "started_at": incubator.iso(now - timedelta(hours=4, minutes=1)),
        "qualified": False,
        "stopped": False,
    }
    client = FakeClient()
    client.dashboards[101] = {
        "system": {"state": "running", "dry_run": True, "mode": "paper"},
        "performance": {"total_pnl_pct": 9.5},
    }

    actions = incubator.evaluate_candidates(client, state, cfg, now)

    assert actions == ["stopped_underperformer:101:9.50%"]
    assert client.stopped == [101]
    assert state["candidates"]["101"]["stopped"] is True
    assert state["candidates"]["101"]["stop_reason"] == "four_hour_return_below_target"


def test_evaluate_candidates_qualifies_and_keeps_high_return_running():
    now = datetime(2026, 5, 3, 8, 0, tzinfo=timezone.utc)
    cfg = incubator.IncubatorConfig(evaluation_hours=4, target_return_pct=10)
    state = incubator.empty_state()
    state["candidates"]["102"] = {
        "strategy_id": 102,
        "started_at": incubator.iso(now - timedelta(hours=4)),
        "qualified": False,
        "stopped": False,
    }
    client = FakeClient()
    client.dashboards[102] = {
        "system": {"state": "running", "dry_run": True, "mode": "paper"},
        "performance": {"total_pnl_pct": 12.25},
    }

    actions = incubator.evaluate_candidates(client, state, cfg, now)

    assert actions == ["qualified:102:12.25%"]
    assert client.stopped == []
    assert state["candidates"]["102"]["qualified"] is True


def test_run_once_accepts_completed_task_and_starts_candidate():
    now = datetime(2026, 5, 3, 8, 0, tzinfo=timezone.utc)
    cfg = incubator.IncubatorConfig(
        target_count=5,
        min_backtest_return_pct=10,
        min_backtest_trades=20,
        max_concurrent_tasks=0,
    )
    state = incubator.empty_state()
    state["tasks"]["task-complete"] = {
        "task_id": "task-complete",
        "timeframe": "1m",
        "accepted_iterations": [],
        "processed": False,
    }
    client = FakeClient()
    client.tasks = [
        {
            "task_id": "task-complete",
            "status": "completed",
            "timeframe": "1m",
            "iterations_count": 1,
        }
    ]
    client.iterations["task-complete"] = [
        {
            "iteration": 0,
            "strategy_name": "high yield",
            "strategy_code": "code",
            "score": 80,
            "backtest_metrics": {"total_return_pct": 22, "total_trades": 45},
        }
    ]

    actions = incubator.run_once(client, state, cfg, now)

    assert actions == ["accepted_started:101:task=task-complete:iter=0"]
    assert client.accepted == [("task-complete", 0)]
    assert client.configured == [(101, {"timeframe": "1m", "initial_equity": 100.0, "loop_interval_sec": 60})]
    assert client.started == [101]
    assert state["candidates"]["101"]["backtest_return_pct"] == 22


def test_incubator_default_initial_equity_is_100u():
    cfg = incubator.IncubatorConfig()
    parser = incubator.build_arg_parser()
    args = parser.parse_args([])

    assert cfg.initial_equity == 100.0
    assert incubator.cfg_from_args(args).initial_equity == 100.0
    assert args.api_base == "http://127.0.0.1:8889/api/v2"
    assert [key for key in vars(args) if key.endswith("_base")] == ["api_base"]
