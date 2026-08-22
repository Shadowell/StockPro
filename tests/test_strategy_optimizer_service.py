from __future__ import annotations

import sys
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.local_db import LocalDatabase  # noqa: E402
from app.services.strategy_optimizer_service import StrategyOptimizerService, iso  # noqa: E402


VALID_OPTIMIZED_STRATEGY_CODE = '''
from collections import deque
from app.core.execution.base_strategy import BaseStrategy, BarData


class OptimizedSmokeStrategy(BaseStrategy):
    async def on_init(self) -> None:
        self._closes = {}
        self._last_signal = {}

    async def on_bar(self, bar: BarData) -> None:
        closes = self._closes.setdefault(bar.symbol, deque(maxlen=8))
        closes.append(float(bar.close))
        if len(closes) < 3:
            return
        if float(closes[-1]) > float(closes[-2]):
            self._last_signal[bar.symbol] = "up"
'''


class FakeDb:
    def __init__(self, now: datetime):
        self.now = now
        self.config = {
            "enabled": False,
            "interval_hours": 4.0,
            "low_return_pct": 0.0,
            "trial_hours": 4.0,
            "trial_success_return_pct": 0.0,
            "running": False,
        }
        self.strategies: List[Dict[str, Any]] = []
        self.runs: Dict[str, Dict[str, Any]] = {}
        self.events: List[Dict[str, Any]] = []
        self.trades: Dict[int, List[Dict[str, Any]]] = {}
        self.saved_candidates: List[Dict[str, Any]] = []
        self.next_strategy_id = 1000

    def get_strategy_optimizer_config(self):
        return dict(self.config)

    def update_strategy_optimizer_config(self, updates):
        self.config.update(updates)
        return dict(self.config)

    def set_strategy_optimizer_runtime(self, **kwargs):
        self.config.update(kwargs)

    def get_strategies(self):
        return [dict(s) for s in self.strategies]

    def get_strategy_by_id(self, strategy_id):
        for item in self.strategies + self.saved_candidates:
            if int(item["id"]) == int(strategy_id):
                return dict(item)
        return None

    def get_strategy_trades(self, strategy_id, limit=50):
        return list(self.trades.get(int(strategy_id), []))[:limit]

    def get_active_strategy_optimization_runs(self, source_strategy_id=None):
        out = [
            dict(run)
            for run in self.runs.values()
            if run.get("status") in {"running", "trial_running"}
        ]
        if source_strategy_id is not None:
            out = [r for r in out if int(r["source_strategy_id"]) == int(source_strategy_id)]
        return out

    def save_strategy_optimization_run(self, run):
        self.runs[run["id"]] = dict(run)

    def get_strategy_optimization_run(self, run_id):
        return dict(self.runs[run_id]) if run_id in self.runs else None

    def get_strategy_optimization_runs(self, limit=50):
        return list(self.runs.values())[:limit]

    def add_strategy_optimization_event(self, run_id, stage, message, detail=None, ts=None):
        self.events.append({"run_id": run_id, "stage": stage, "message": message, "detail": detail or {}})

    def get_strategy_optimization_events(self, run_id, limit=100):
        return [e for e in self.events if e["run_id"] == run_id][:limit]

    def delete_strategy_optimization_run(self, run_id):
        before_events = len(self.events)
        self.events = [e for e in self.events if e["run_id"] != run_id]
        run_deleted = 1 if self.runs.pop(run_id, None) is not None else 0
        return {"run_deleted": run_deleted, "events_deleted": before_events - len(self.events)}

    def save_strategy(self, **kwargs):
        self.next_strategy_id += 1
        row = {
            "id": self.next_strategy_id,
            "status": "stopped",
            **kwargs,
        }
        self.saved_candidates.append(row)
        return self.next_strategy_id


class FakeEngine:
    def __init__(self):
        self.statuses: Dict[int, Dict[str, Any]] = {}
        self.paused: List[int] = []
        self.stopped: List[int] = []
        self.started: List[int] = []

    def get_strategy_status(self, strategy_id):
        return dict(self.statuses.get(int(strategy_id), {}))

    async def pause_strategy(self, strategy_id):
        self.paused.append(int(strategy_id))
        return True

    async def stop_strategy(self, strategy_id, clear_metrics=False):
        self.stopped.append(int(strategy_id))
        return True

    async def start_strategy(self, strategy_id):
        self.started.append(int(strategy_id))
        return True


def _strategy(strategy_id: int, *, status="running", paper=True, started_hours=5):
    now = datetime(2026, 5, 3, 8, 0, tzinfo=timezone.utc)
    return {
        "id": strategy_id,
        "name": f"strategy-{strategy_id}",
        "status": status,
        "exchange": "okx",
        "symbols": ["BTC/USDT"],
        "script_content": "class X: pass",
        "config": {"is_paper_trading": paper, "initial_capital": 10000, "timeframe": "1m"},
        "run_started_at": iso(now - timedelta(hours=started_hours)),
    }


def test_optimizer_config_defaults_off(tmp_path):
    db = LocalDatabase(str(tmp_path / "optimizer.db"))
    db.init_db()

    cfg = db.get_strategy_optimizer_config()

    assert cfg["enabled"] is False
    assert cfg["interval_hours"] == 4
    assert cfg["low_return_pct"] == 0
    assert cfg["trial_hours"] == 4
    assert cfg["trial_success_return_pct"] == 0


def test_eligible_sources_only_running_paper_old_negative():
    now = datetime(2026, 5, 3, 8, 0, tzinfo=timezone.utc)
    db = FakeDb(now)
    engine = FakeEngine()
    db.strategies = [
        _strategy(1, status="running", paper=True, started_hours=5),
        _strategy(2, status="running", paper=False, started_hours=5),
        _strategy(3, status="paused", paper=True, started_hours=5),
        _strategy(4, status="running", paper=True, started_hours=2),
        _strategy(5, status="running", paper=True, started_hours=5),
    ]
    engine.statuses = {
        1: {"status": "running", "return_pct": -0.1, "equity": 9990, "initial_capital": 10000},
        2: {"status": "running", "return_pct": -5.0, "equity": 9500, "initial_capital": 10000},
        3: {"status": "paused", "return_pct": -5.0, "equity": 9500, "initial_capital": 10000},
        4: {"status": "running", "return_pct": -5.0, "equity": 9500, "initial_capital": 10000},
        5: {"status": "running", "return_pct": 0.0, "equity": 10000, "initial_capital": 10000},
    }
    svc = StrategyOptimizerService(database=db, engine=engine, now_fn=lambda: now)

    eligible = svc._eligible_sources(db.config, now)

    assert [source["id"] for source, _ in eligible] == [1]


def test_active_run_blocks_duplicate_source():
    now = datetime(2026, 5, 3, 8, 0, tzinfo=timezone.utc)
    db = FakeDb(now)
    engine = FakeEngine()
    db.strategies = [_strategy(1, status="running", paper=True, started_hours=5)]
    engine.statuses[1] = {"status": "running", "return_pct": -1.0, "equity": 9900, "initial_capital": 10000}
    db.runs["opt_existing"] = {
        "id": "opt_existing",
        "source_strategy_id": 1,
        "stage": "trial",
        "status": "trial_running",
    }
    svc = StrategyOptimizerService(database=db, engine=engine, now_fn=lambda: now)

    assert svc._eligible_sources(db.config, now) == []


def test_evaluate_trials_positive_candidate_pauses_source():
    now = datetime(2026, 5, 3, 8, 0, tzinfo=timezone.utc)
    db = FakeDb(now)
    engine = FakeEngine()
    db.strategies = [_strategy(1), _strategy(101)]
    db.runs["opt1"] = {
        "id": "opt1",
        "source_strategy_id": 1,
        "candidate_strategy_id": 101,
        "stage": "trial",
        "status": "trial_running",
        "trial_started_at": iso(now - timedelta(hours=4, minutes=1)),
    }
    engine.statuses[101] = {"status": "running", "return_pct": 0.5, "equity": 10050, "initial_capital": 10000}
    svc = StrategyOptimizerService(database=db, engine=engine, now_fn=lambda: now)

    actions = asyncio.run(svc.evaluate_trials(db.config, now))

    assert actions == ["replaced:1:candidate=101:return=0.50%"]
    assert engine.paused == [1]
    assert db.runs["opt1"]["status"] == "replaced"


def test_evaluate_trials_non_positive_candidate_stops_candidate():
    now = datetime(2026, 5, 3, 8, 0, tzinfo=timezone.utc)
    db = FakeDb(now)
    engine = FakeEngine()
    db.strategies = [_strategy(1), _strategy(101)]
    db.runs["opt1"] = {
        "id": "opt1",
        "source_strategy_id": 1,
        "candidate_strategy_id": 101,
        "stage": "trial",
        "status": "trial_running",
        "trial_started_at": iso(now - timedelta(hours=4, minutes=1)),
    }
    engine.statuses[101] = {"status": "running", "return_pct": 0.0, "equity": 10000, "initial_capital": 10000}
    svc = StrategyOptimizerService(database=db, engine=engine, now_fn=lambda: now)

    actions = asyncio.run(svc.evaluate_trials(db.config, now))

    assert actions == ["trial_failed:101:return=0.00%"]
    assert engine.stopped == [101]
    assert engine.paused == []
    assert db.runs["opt1"]["status"] == "failed"


def test_stop_current_cancels_active_runs_and_trial_candidate():
    now = datetime(2026, 5, 3, 8, 0, tzinfo=timezone.utc)
    db = FakeDb(now)
    engine = FakeEngine()
    db.runs["opt_running"] = {
        "id": "opt_running",
        "source_strategy_id": 1,
        "stage": "optimize",
        "status": "running",
    }
    db.runs["opt_trial"] = {
        "id": "opt_trial",
        "source_strategy_id": 2,
        "candidate_strategy_id": 102,
        "stage": "trial",
        "status": "trial_running",
    }
    svc = StrategyOptimizerService(database=db, engine=engine, now_fn=lambda: now)

    result = asyncio.run(svc.stop_current())

    assert result["stopped"] is True
    assert set(result["cancelled_runs"]) == {"opt_running", "opt_trial"}
    assert db.runs["opt_running"]["status"] == "cancelled"
    assert db.runs["opt_trial"]["status"] == "cancelled"
    assert engine.stopped == [102]
    assert db.config["running"] is False
    assert db.config["last_error"] == "用户停止"


def test_stop_current_cancels_background_optimizer_task():
    now = datetime(2026, 5, 3, 8, 0, tzinfo=timezone.utc)
    db = FakeDb(now)
    db.config["enabled"] = True
    engine = FakeEngine()
    db.strategies = [_strategy(1, status="running", paper=True, started_hours=5)]
    engine.statuses[1] = {"status": "running", "return_pct": -1.0, "equity": 9900, "initial_capital": 10000}

    class SlowOptimizer(StrategyOptimizerService):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.entered = asyncio.Event()

        async def _process_source_run(self, run, source, snapshot, cfg, now):
            self.entered.set()
            await asyncio.sleep(60)

    async def scenario():
        svc = SlowOptimizer(database=db, engine=engine, now_fn=lambda: now)
        task = asyncio.create_task(svc.run_once(force=True))
        await asyncio.wait_for(svc.entered.wait(), timeout=1.0)

        result = await svc.stop_current()
        run_result = await asyncio.wait_for(task, timeout=1.0)

        assert result["stopped"] is True
        assert result["running"] is False
        assert run_result["stopped"] is True
        assert svc.is_running is False
        assert db.config["running"] is False
        assert db.config["last_error"] == "用户停止"
        assert len(result["cancelled_runs"]) == 1
        assert next(iter(db.runs.values()))["status"] == "cancelled"

    asyncio.run(scenario())


def test_recover_interrupted_runs_marks_restart_lost_running_runs_failed():
    now = datetime(2026, 5, 3, 8, 0, tzinfo=timezone.utc)
    db = FakeDb(now)
    db.config["running"] = True
    db.runs["opt_backtest"] = {
        "id": "opt_backtest",
        "source_strategy_id": 1,
        "stage": "backtest",
        "status": "running",
        "updated_at": iso(now - timedelta(minutes=30)),
    }
    db.runs["opt_trial"] = {
        "id": "opt_trial",
        "source_strategy_id": 2,
        "candidate_strategy_id": 102,
        "stage": "trial",
        "status": "trial_running",
    }
    svc = StrategyOptimizerService(database=db, engine=FakeEngine(), now_fn=lambda: now)

    result = svc.recover_interrupted_runs()

    assert result["failed_runs"] == ["opt_backtest"]
    assert db.runs["opt_backtest"]["status"] == "failed"
    assert db.runs["opt_backtest"]["stage"] == "failed"
    assert "服务重启" in db.runs["opt_backtest"]["error_message"]
    assert db.runs["opt_trial"]["status"] == "trial_running"
    assert db.config["running"] is False
    assert "服务重启" in db.config["last_error"]
    assert db.events[-1]["run_id"] == "opt_backtest"
    assert db.events[-1]["stage"] == "failed"


def test_delete_run_removes_terminal_optimizer_history_and_events():
    now = datetime(2026, 5, 3, 8, 0, tzinfo=timezone.utc)
    db = FakeDb(now)
    db.runs["opt_done"] = {
        "id": "opt_done",
        "source_strategy_id": 1,
        "stage": "failed",
        "status": "failed",
    }
    db.events = [
        {"run_id": "opt_done", "stage": "monitor", "message": "old", "detail": {}},
        {"run_id": "other", "stage": "monitor", "message": "keep", "detail": {}},
    ]
    svc = StrategyOptimizerService(database=db, engine=FakeEngine(), now_fn=lambda: now)

    result = svc.delete_run("opt_done")

    assert result == {"deleted": True, "run_id": "opt_done", "events_deleted": 1}
    assert "opt_done" not in db.runs
    assert [event["run_id"] for event in db.events] == ["other"]


def test_delete_run_rejects_active_optimizer_history():
    now = datetime(2026, 5, 3, 8, 0, tzinfo=timezone.utc)
    db = FakeDb(now)
    db.runs["opt_active"] = {
        "id": "opt_active",
        "source_strategy_id": 1,
        "stage": "trial",
        "status": "trial_running",
    }
    svc = StrategyOptimizerService(database=db, engine=FakeEngine(), now_fn=lambda: now)

    try:
        svc.delete_run("opt_active")
    except ValueError as exc:
        assert "仍在运行中" in str(exc)
    else:
        raise AssertionError("active optimizer run should not be deleted")

    assert "opt_active" in db.runs


def test_optimizer_prompt_forbids_legacy_bitpro_strategy_imports():
    now = datetime(2026, 5, 4, 8, 0, tzinfo=timezone.utc)
    svc = StrategyOptimizerService(database=FakeDb(now), engine=FakeEngine(), now_fn=lambda: now)

    prompt = svc._build_optimizer_prompt(_strategy(1), {"return_pct": -1.0})

    assert "禁止 `from bitpro.strategy" in prompt
    assert "from app.core.execution.base_strategy import BaseStrategy, BarData" in prompt
    assert "strategy(ctx)" in prompt


def test_generate_candidate_retries_when_ai_uses_legacy_bitpro_imports(monkeypatch):
    now = datetime(2026, 5, 4, 8, 0, tzinfo=timezone.utc)
    db = FakeDb(now)
    svc = StrategyOptimizerService(database=db, engine=FakeEngine(), now_fn=lambda: now)

    class FakeClient:
        def __init__(self):
            self.calls: List[List[Dict[str, Any]]] = []
            self.models = []

        async def chat_json(self, messages, **kwargs):
            self.calls.append([dict(message) for message in messages])
            if len(self.calls) == 1:
                return {
                    "strategy_name": "旧框架错误候选",
                    "strategy_class_code": (
                        "from bitpro.strategy import Strategy\n"
                        "from bitpro.data import Bar\n\n"
                        "class BadOptimizedStrategy(Strategy):\n"
                        "    pass\n"
                    ),
                }
            return {
                "strategy_name": "合约正确候选",
                "strategy_class_code": VALID_OPTIMIZED_STRATEGY_CODE,
            }

    fake_client = FakeClient()
    monkeypatch.setattr("app.services.strategy_optimizer_service.has_agent_api_key", lambda: True)
    def fake_get_qwen_client(model=None):
        fake_client.models.append(model)
        return fake_client

    monkeypatch.setattr("app.services.strategy_optimizer_service.get_qwen_client", fake_get_qwen_client)
    db.update_strategy_optimizer_config({"llm_model": "deepseek-v4-flash"})

    candidate = asyncio.run(svc._generate_candidate(_strategy(1), {"return_pct": -1.0}))

    assert candidate["strategy_name"] == "合约正确候选"
    assert candidate["strategy_class_code"] == VALID_OPTIMIZED_STRATEGY_CODE.strip()
    assert fake_client.models == ["deepseek-v4-flash"]
    assert len(fake_client.calls) == 2
    retry_feedback = fake_client.calls[1][-1]["content"]
    assert "bitpro.strategy" in retry_feedback
    assert "当前 BaseStrategy 合约" in retry_feedback
