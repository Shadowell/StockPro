import unittest
from unittest.mock import MagicMock, patch

from app.services.agent.llm_client import parse_json_block
from app.services.agent.orchestrator import AgentOrchestrator
from app.services.agent.schemas import AgentTask, EvalScores, GoalCriteria, IterationRecord, StrategySpec
from app.services.strategy_runtime_service import validate_strategy_python

VALID_CODE = '''"""AI 生成策略。"""

def initialize(context):
    set_option("avoid_future_data", True)

def handle_data(context, data):
    for symbol in context.universe:
        closes = history(symbol, 5, "1d", "close")
        if len(closes) >= 5 and closes.mean() > 0:
            order_target_percent(symbol, 0.1)
'''

INVALID_CODE = '''import os

def initialize(context):
    os.system("ls")

def handle_data(context, data):
    print(data)
'''

GOOD_METRICS = {
    "sharpe": 1.4,
    "maximum_drawdown": 0.08,
    "win_rate": 0.55,
    "strategy_return": 0.12,
    "completed_trades": 9.0,
    "profit_loss_ratio": 1.6,
}


class GoalCriteriaTests(unittest.TestCase):
    def test_check_requires_all_thresholds(self):
        goal = GoalCriteria()
        self.assertTrue(goal.check(dict(GOOD_METRICS)))
        self.assertFalse(goal.check({**GOOD_METRICS, "sharpe": 0.1}))
        self.assertFalse(goal.check({**GOOD_METRICS, "maximum_drawdown": 0.9}))
        self.assertFalse(goal.check({k: None for k in GOOD_METRICS}))

    def test_from_dict_ignores_unknown_and_invalid_values(self):
        goal = GoalCriteria.from_dict({"min_sharpe": "2.0", "min_trades": "3", "bogus": 1, "min_return": "abc"})
        self.assertEqual(goal.min_sharpe, 2.0)
        self.assertEqual(goal.min_trades, 3)
        self.assertEqual(goal.min_return, GoalCriteria().min_return)


class ParseJsonBlockTests(unittest.TestCase):
    def test_strips_code_fences(self):
        parsed = parse_json_block('```json\n{"a": 1}\n```')
        self.assertEqual(parsed, {"a": 1})

    def test_extracts_json_from_prose(self):
        parsed = parse_json_block('结果如下：\n{"a": {"b": 2}}\n以上。')
        self.assertEqual(parsed, {"a": {"b": 2}})


class EvalScoreTests(unittest.TestCase):
    def test_total_score_is_weighted(self):
        scores = EvalScores(risk_control=80, profitability=60, robustness=40, strategy_logic=100, originality=0)
        self.assertEqual(scores.total_score, 80 * .25 + 60 * .25 + 40 * .20 + 100 * .15 + 0 * .15)


def _make_task(**overrides):
    task = AgentTask(
        task_id="0b0e3f26-0000-4000-8000-000000000001",
        name="动量研究",
        goal=GoalCriteria(),
        research_config={
            "dataset_snapshot_id": 1,
            "universe_snapshot_id": 2,
            "symbols": ["SH_600000"],
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "benchmark_code": "000300.SH",
            "event_limit": 45,
            "initial_cash": 1_000_000,
        },
        strategy_spec=StrategySpec(recommended_approach="日线动量", risk_considerations="控制回撤"),
        llm_model="qwen-plus",
    )
    for key, value in overrides.items():
        setattr(task, key, value)
    return task


class OrchestratorLoopTests(unittest.TestCase):
    def setUp(self):
        import threading
        self.orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
        self.orchestrator.database = MagicMock()
        self.orchestrator._tasks = {}
        self.orchestrator._runners = {}
        self.orchestrator._lock = threading.RLock()
        self.orchestrator._planner = MagicMock()
        self.orchestrator._strategist = MagicMock()
        self.orchestrator._evaluator = MagicMock()
        self.orchestrator._backtester = MagicMock()
        self.orchestrator._backtester.validate = validate_strategy_python
        self.persisted_tasks = []
        self.persisted_iterations = []
        self.orchestrator._persist_task = lambda task, insert=False: self.persisted_tasks.append(task)
        self.orchestrator._persist_iteration = lambda task, record: self.persisted_iterations.append(record)

    def _patch_llm(self):
        enter = patch("app.services.agent.orchestrator.llm_available", return_value=True)
        client = MagicMock()
        client.model = "qwen-plus"
        factory = patch("app.services.agent.orchestrator.QwenClient", return_value=client)
        return enter, factory, client

    def test_missing_api_key_fails_fast(self):
        task = _make_task()
        self.orchestrator._tasks[task.task_id] = task
        with patch("app.services.agent.orchestrator.llm_available", return_value=False):
            self.orchestrator.run_task(task.task_id)
        self.assertEqual(task.status, "failed")
        self.assertIn("QWEN_API_KEY", task.error_message)

    def test_sandbox_rejection_is_recorded_without_backtest(self):
        task = _make_task(max_iterations=1)
        self.orchestrator._tasks[task.task_id] = task
        llm_patch, factory_patch, client = self._patch_llm()
        self.orchestrator._strategist.generate.return_value = {
            "strategy_name": "坏策略", "strategy_code": INVALID_CODE, "reasoning": "",
        }
        self.orchestrator._evaluator.evaluate.return_value = {
            "eval_scores": EvalScores(), "meets_goal": False, "score": 0,
            "analysis": "", "suggestions": [], "next_action": "refine",
        }
        with llm_patch, factory_patch:
            self.orchestrator.run_task(task.task_id)
        self.assertEqual(len(task.iterations), 1)
        record = task.iterations[0]
        self.assertIn("SANDBOX_REJECTED", record.error)
        self.assertFalse(record.meets_goal)
        self.orchestrator._backtester.run.assert_not_called()
        self.assertEqual(len(self.persisted_iterations), 1)

    def test_happy_path_completes_when_goal_met(self):
        task = _make_task(max_iterations=3)
        self.orchestrator._tasks[task.task_id] = task
        llm_patch, factory_patch, client = self._patch_llm()
        self.orchestrator._strategist.generate.return_value = {
            "strategy_name": "动量", "strategy_code": VALID_CODE, "reasoning": "动量逻辑",
        }
        self.orchestrator._backtester.run.return_value = {
            "strategy_version_id": "11111111-0000-4000-8000-000000000002",
            "backtest_run_id": "22222222-0000-4000-8000-000000000003",
            "metrics": dict(GOOD_METRICS),
            "sandbox_report": {"valid": True},
        }
        self.orchestrator._evaluator.evaluate.return_value = {
            "eval_scores": EvalScores(risk_control=70, profitability=80, robustness=60, strategy_logic=70, originality=50),
            "meets_goal": True,
            "score": 69.0,
            "analysis": "ok",
            "suggestions": [],
            "next_action": "refine",
        }
        with llm_patch, factory_patch:
            self.orchestrator.run_task(task.task_id)
        self.assertEqual(task.status, "completed")
        self.assertEqual(len(task.iterations), 1)
        record = task.iterations[0]
        self.assertTrue(record.meets_goal)
        self.assertEqual(record.score, 69.0)
        self.assertEqual(task.best_iteration, 0)
        self.assertEqual(record.strategy_version_id, "11111111-0000-4000-8000-000000000002")

    def test_stop_task_halts_loop(self):
        task = _make_task(max_iterations=2)
        task.status = "running"
        self.orchestrator._tasks[task.task_id] = task
        self.assertTrue(self.orchestrator.stop_task(task.task_id))
        self.assertEqual(task.status, "stopped")

    def test_update_best_ignores_losing_iterations(self):
        task = _make_task()
        losing = IterationRecord(iteration=0, strategy_code="x", score=90,
                                 backtest_metrics={"strategy_return": -0.1})
        winning = IterationRecord(iteration=1, strategy_code="x", score=60,
                                  backtest_metrics={"strategy_return": 0.05})
        task.iterations = [losing, winning]
        self.orchestrator._update_best(task)
        self.assertEqual(task.best_iteration, 1)


class ResearchConfigTests(unittest.TestCase):
    def setUp(self):
        self.orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
        self.orchestrator.database = MagicMock()

    def test_resolve_research_config_requires_snapshot(self):
        self.orchestrator._row = MagicMock(return_value=None)
        with self.assertRaisesRegex(ValueError, "数据快照"):
            self.orchestrator.resolve_research_config({})

    def test_event_limit_is_clamped(self):
        self.orchestrator._row = MagicMock(side_effect=[
            {"id": 7, "name": "snap", "start_date": "2026-01-01", "end_date": "2026-06-30"},
            {"id": 9, "code": "research20"},
            {"id": "cm-1", "code": "ashare_default"},
        ])
        self.orchestrator._rows = MagicMock(return_value=[{"symbol": "SH_600000"}])
        config = self.orchestrator.resolve_research_config({"event_limit": 999})
        self.assertEqual(config["event_limit"], 60)
        self.assertEqual(config["symbols"], ["SH_600000"])


if __name__ == "__main__":
    unittest.main()
