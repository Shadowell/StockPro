"""AI 策略研发编排器：Planner → [合约 → Strategist → 沙箱 → Backtester → Evaluator] × N。

- 任务与每轮迭代全量落 PostgreSQL，重启后自动恢复未完成任务（BitPro 模式）。
- 回测复用 BacktestWorkbenchService 的 quick 诊断链路，与人工策略同一执行路径。
- 晋级（promote）只把已通过验证的策略版本暴露给策略工作台，Paper 晋级仍受 11 项门控约束。
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import psycopg2.extras

from app.services.agent.backtester_agent import BacktesterAgent
from app.services.agent.evaluator_agent import EvaluatorAgent
from app.services.agent.llm_client import QwenClient, llm_available, resolve_model_name
from app.services.agent.planner_agent import PlannerAgent
from app.services.agent.prompts import build_handoff_context
from app.services.agent.strategist_agent import StrategistAgent
from app.services.agent.schemas import (
    AgentTask,
    EvalScores,
    GoalCriteria,
    IterationRecord,
    SprintContract,
    StrategySpec,
)

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    def __init__(self, database):
        self.database = database
        self._planner = PlannerAgent()
        self._strategist = StrategistAgent()
        self._backtester = BacktesterAgent(database)
        self._evaluator = EvaluatorAgent()
        self._tasks: Dict[str, AgentTask] = {}
        self._runners: Dict[str, threading.Thread] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # 研究环境默认值
    # ------------------------------------------------------------------
    def default_research_config(self) -> Dict[str, Any]:
        dataset = self._row(
            """
            SELECT s.id, s.name, s.knowledge_cutoff_at,
                   MIN(p.start_date) FILTER (WHERE i.dataset_code='daily_bars') AS start_date,
                   MAX(p.end_date) FILTER (WHERE i.dataset_code='daily_bars') AS end_date
            FROM dataset_snapshots s
            JOIN dataset_snapshot_items i ON i.snapshot_id=s.id
            JOIN dataset_partitions p ON p.id=i.partition_id
            WHERE s.status='sealed'
            GROUP BY s.id HAVING COUNT(*) FILTER (WHERE i.dataset_code='daily_bars') > 0
            ORDER BY s.id DESC LIMIT 1
            """
        )
        universe = self._row(
            """
            SELECT s.id, d.code, d.rule_version, s.trade_date
            FROM universe_snapshots s JOIN universe_definitions d ON d.id=s.definition_id
            WHERE s.status='sealed' ORDER BY s.id DESC LIMIT 1
            """
        )
        cost_model = self._row(
            "SELECT id, code, version FROM backtest_cost_models WHERE status='active' ORDER BY code, version DESC LIMIT 1"
        )
        symbols: List[str] = []
        if universe:
            members = self._rows(
                """
                SELECT symbol FROM universe_snapshot_members
                WHERE snapshot_id=%s
                  AND (eligibility_flags->>'eligible_for_research')::boolean IS TRUE
                ORDER BY symbol LIMIT 10
                """,
                (int(universe["id"]),),
            )
            symbols = [str(item["symbol"]) for item in members]
        start_date = str(dataset.get("start_date"))[:10] if dataset and dataset.get("start_date") else ""
        end_date = str(dataset.get("end_date"))[:10] if dataset and dataset.get("end_date") else ""
        return {
            "dataset_snapshot_id": int(dataset["id"]) if dataset else None,
            "dataset_snapshot_name": str(dataset.get("name") or "") if dataset else "",
            "universe_snapshot_id": int(universe["id"]) if universe else None,
            "universe_code": str(universe.get("code") or "") if universe else "",
            "cost_model_id": str(cost_model["id"]) if cost_model else None,
            "benchmark_code": "000300.SH",
            "symbols": symbols,
            "start_date": start_date,
            "end_date": end_date,
            "event_limit": 45,
            "initial_cash": 1_000_000,
        }

    def resolve_research_config(self, overrides: Dict[str, Any]) -> Dict[str, Any]:
        config = self.default_research_config()
        for key in (
            "dataset_snapshot_id", "universe_snapshot_id", "cost_model_id", "benchmark_code",
            "symbols", "start_date", "end_date", "event_limit", "initial_cash",
        ):
            if overrides.get(key) not in (None, "", []):
                config[key] = overrides[key]
        if not config.get("dataset_snapshot_id"):
            raise ValueError("没有已封存的数据快照，请先在数据中心同步并封存日线数据")
        if not config.get("universe_snapshot_id"):
            raise ValueError("没有已封存的 Universe Snapshot，无法确定研究证券范围")
        if not config.get("symbols"):
            raise ValueError("Universe Snapshot 中没有可研究证券，请先生成并封存股票池")
        if not config.get("start_date") or not config.get("end_date") or str(config["start_date"]) > str(config["end_date"]):
            raise ValueError("数据快照缺少可用的日线日期区间")
        config["event_limit"] = max(10, min(int(config.get("event_limit") or 45), 60))
        config["initial_cash"] = max(100_000.0, min(float(config.get("initial_cash") or 1_000_000), 100_000_000.0))
        return config

    # ------------------------------------------------------------------
    # 任务生命周期
    # ------------------------------------------------------------------
    def create_task(self, payload: Dict[str, Any]) -> AgentTask:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("任务名称必填")
        max_iterations = max(1, min(int(payload.get("max_iterations") or 6), 12))
        config = self.resolve_research_config(dict(payload.get("research_config") or {}))
        goal = GoalCriteria.from_dict(payload.get("goal") or {})
        task = AgentTask(
            task_id=str(uuid.uuid4()),
            name=name[:80],
            status="pending",
            stage="planner",
            stage_label="等待启动",
            goal=goal,
            research_config=config,
            max_iterations=max_iterations,
            user_prompt=str(payload.get("user_prompt") or "")[:2000],
            llm_model=resolve_model_name(payload.get("llm_model")) if payload.get("llm_model") else resolve_model_name(None),
            created_at=_now(),
            updated_at=_now(),
        )
        self._persist_task(task, insert=True)
        with self._lock:
            self._tasks[task.task_id] = task
        return task

    def start_task(self, task_id: str) -> AgentTask:
        task = self.get_task(task_id)
        if not task:
            raise ValueError("任务不存在")
        if task.status not in {"pending", "stopped"}:
            raise ValueError(f"任务状态为 {task.status}，不能启动")
        if not llm_available():
            raise ValueError("QWEN_API_KEY 未配置，AI 策略研发不可用")
        runner = threading.Thread(target=self._run_task_safe, args=(task_id,), daemon=True, name=f"agent-{task_id}")
        with self._lock:
            self._runners[task_id] = runner
        runner.start()
        return task

    def stop_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if not task or task.status not in {"pending", "running"}:
            return False
        task.status = "stopped"
        task.stage = "stopped"
        task.stage_label = "任务已停止"
        task.updated_at = _now()
        self._persist_task(task)
        return True

    def delete_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if not task:
            return False
        runner = self._runners.get(task_id)
        if task.status in {"pending", "running"} or (runner and runner.is_alive()):
            raise ValueError("任务仍在运行，请先停止")
        with self._lock:
            self._tasks.pop(task_id, None)
            self._runners.pop(task_id, None)
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM agent_tasks WHERE id=%s", (task_id,))
        return True

    def get_task(self, task_id: str) -> Optional[AgentTask]:
        with self._lock:
            task = self._tasks.get(task_id)
        if task:
            return task
        loaded = self._load_task(task_id)
        if loaded:
            with self._lock:
                self._tasks[task_id] = loaded
            return loaded
        return None

    def list_tasks(self, limit: int = 50) -> List[AgentTask]:
        rows = self._rows(
            """
            SELECT t.*,
                   (SELECT COUNT(*) FROM agent_iterations i WHERE i.task_id=t.id) AS iteration_count,
                   (SELECT MAX(i.score) FROM agent_iterations i WHERE i.task_id=t.id) AS best_score
            FROM agent_tasks t ORDER BY t.created_at DESC LIMIT %s
            """,
            (max(1, min(int(limit), 200)),),
        )
        tasks: List[AgentTask] = []
        for row in rows:
            task_id = str(row["id"])
            with self._lock:
                cached = self._tasks.get(task_id)
            if cached and cached.status in {"pending", "running"}:
                tasks.append(cached)
                continue
            task = self._task_from_row(row)
            task.research_config.setdefault("_iteration_count", int(row.get("iteration_count") or 0))
            task.research_config.setdefault("_best_score", row.get("best_score"))
            tasks.append(task)
        return tasks

    def list_iterations(self, task_id: str) -> List[Dict[str, Any]]:
        return self._rows(
            "SELECT * FROM agent_iterations WHERE task_id=%s ORDER BY iteration", (task_id,)
        )

    def promote(self, task_id: str, iteration: int) -> Dict[str, Any]:
        task = self.get_task(task_id)
        if not task:
            raise ValueError("任务不存在")
        rows = self._rows(
            "SELECT * FROM agent_iterations WHERE task_id=%s AND iteration=%s",
            (task_id, int(iteration)),
        )
        if not rows:
            raise ValueError("迭代不存在")
        row = rows[0]
        if row.get("error"):
            raise ValueError("该迭代存在错误，不能采纳")
        version_id = row.get("strategy_version_id")
        if not version_id:
            raise ValueError("该迭代没有策略版本，不能采纳")
        version = self._row("SELECT * FROM strategy_versions WHERE id=%s", (str(version_id),))
        if not version or version.get("validation_status") != "valid":
            raise ValueError("策略版本未通过验证，不能采纳")
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE agent_tasks SET promoted_strategy_version_id=%s, updated_at=NOW()
                    WHERE id=%s
                    """,
                    (str(version_id), task_id),
                )
        task.promoted_strategy_version_id = str(version_id)
        task.updated_at = _now()
        return {"strategy_version": self._serialize_version(version), "iteration": int(iteration)}

    # ------------------------------------------------------------------
    # 执行闭环
    # ------------------------------------------------------------------
    def _run_task_safe(self, task_id: str) -> None:
        try:
            self.run_task(task_id)
        except Exception as exc:
            logger.exception("Agent task %s crashed", task_id)
            task = self.get_task(task_id)
            if task:
                task.status = "failed"
                task.error_message = str(exc)[:800]
                task.stage = "failed"
                task.stage_label = f"任务失败：{str(exc)[:80]}"
                task.updated_at = _now()
                self._persist_task(task)
        finally:
            with self._lock:
                self._runners.pop(task_id, None)

    def run_task(self, task_id: str) -> AgentTask:
        task = self.get_task(task_id)
        if not task:
            raise ValueError("任务不存在")
        if task.status == "stopped":
            return task
        if not llm_available():
            task.status = "failed"
            task.error_message = "QWEN_API_KEY 未配置"
            task.stage_label = "任务失败：QWEN_API_KEY 未配置"
            self._persist_task(task)
            return task

        task.status = "running"
        task.error_message = ""
        client = QwenClient(model=task.llm_model or None)
        task.llm_model = client.model
        task.updated_at = _now()
        self._set_stage(task, "planner" if not task.strategy_spec else "planner_done",
                        "Planner 正在生成策略规格书" if not task.strategy_spec else "复用已持久化规格书")
        self._persist_task(task)

        try:
            if not task.strategy_spec:
                task.strategy_spec = self._planner.plan(task, client)
                self._set_stage(task, "planner_done", f"Planner 已完成，准备第 1 轮策略生成")
                task.updated_at = _now()
                self._persist_task(task)

            strategy_prefix = f"AI·{task.name}"
            for iteration in range(len(task.iterations), task.max_iterations):
                if task.status == "stopped":
                    return task
                task.current_iteration = iteration
                record = IterationRecord(iteration=iteration, created_at=_now())

                # --- Step 1: Sprint 合约（首轮来自规格书，后续来自上一轮评审） ---
                handoff = build_handoff_context(task, task.iterations[-1]) if task.iterations else ""
                contract = self._build_contract(task, task.iterations[-1] if task.iterations else None)
                record.contract = contract
                record.action = contract.action

                # --- Step 2: Strategist 生成代码 + 沙箱静态校验（一次修复机会） ---
                self._set_stage(task, "strategist", f"第 {iteration + 1} 轮：正在生成策略代码")
                self._persist_task(task)
                try:
                    generated = self._strategist.generate(task, client, contract=contract, handoff_context=handoff)
                    code = generated["strategy_code"]
                    report = self._backtester.validate(code)
                    if not report.get("valid"):
                        generated = self._strategist.generate(
                            task, client, contract=contract, handoff_context=handoff,
                            repair_issues=report.get("issues") or [],
                        )
                        code = generated["strategy_code"]
                        report = self._backtester.validate(code)
                    record.strategy_name = generated["strategy_name"]
                    record.strategy_code = code
                    record.reasoning = generated["reasoning"]
                    record.sandbox_report = report
                    if not report.get("valid"):
                        record.error = "SANDBOX_REJECTED: " + "; ".join(
                            item.get("message", "") for item in (report.get("issues") or [])[:4]
                        )
                except Exception as exc:
                    record.error = f"策略生成失败: {str(exc)[:400]}"

                # --- Step 3: Backtester 走生产链路 ---
                if not record.error:
                    self._set_stage(task, "backtester", f"第 {iteration + 1} 轮：正在执行诊断回测")
                    self._persist_task(task)
                    try:
                        version_name = f"{strategy_prefix}·{generated['strategy_name']}"[:80]
                        bt = self._backtester.run(task, record.strategy_code, version_name, generated["reasoning"])
                        if bt.get("error"):
                            record.error = str(bt["error"])[:600]
                        record.strategy_version_id = bt.get("strategy_version_id")
                        record.backtest_run_id = bt.get("backtest_run_id")
                        record.backtest_metrics = bt.get("metrics") or {}
                    except Exception as exc:
                        record.error = f"回测执行失败: {str(exc)[:400]}"

                # --- Step 4: Evaluator 独立评分 ---
                self._set_stage(task, "evaluator", f"第 {iteration + 1} 轮：正在评分")
                try:
                    evaluation = self._evaluator.evaluate(task, record, client, contract)
                    record.eval_scores = evaluation["eval_scores"]
                    record.meets_goal = evaluation["meets_goal"]
                    record.score = evaluation["score"]
                    record.analysis = evaluation["analysis"]
                    record.suggestions = evaluation["suggestions"]
                    record.next_action = evaluation["next_action"]
                except Exception as exc:
                    evaluation = self._evaluator.deterministic_evaluate(task, record)
                    record.eval_scores = evaluation["eval_scores"]
                    record.meets_goal = evaluation["meets_goal"]
                    record.score = evaluation["score"]
                    record.analysis = f"评估失败，使用确定性评分: {str(exc)[:200]}"
                    record.suggestions = evaluation["suggestions"]

                task.iterations.append(record)
                self._update_best(task)
                self._persist_iteration(task, record)
                task.updated_at = _now()
                self._persist_task(task)
                logger.info(
                    "Agent 任务 %s 第 %d 轮完成: score=%.1f 达标=%s 错误=%s",
                    task_id, iteration + 1, record.score, record.meets_goal, bool(record.error),
                )
                if record.meets_goal and not record.error:
                    task.status = "completed"
                    self._set_stage(task, "completed", f"第 {iteration + 1} 轮已达标")
                    self._finish_task(task)
                    return task

            if task.status == "running":
                task.status = "completed"
                self._set_stage(task, "completed", "研发轮次已用完，请查看最佳迭代")
            self._finish_task(task)
            return task
        except Exception as exc:
            task.status = "failed"
            task.error_message = str(exc)[:800]
            self._set_stage(task, "failed", f"任务失败：{str(exc)[:80]}")
            self._finish_task(task)
            raise

    def _build_contract(self, task: AgentTask, last_record: Optional[IterationRecord]) -> SprintContract:
        spec = task.strategy_spec
        if last_record is None:
            first = (spec.strategy_candidates[0] if spec and spec.strategy_candidates else {})
            return SprintContract(
                strategy_direction=str((spec.recommended_approach if spec else "") or first.get("name") or "A 股日线多头策略"),
                key_indicators=["close", "volume", "turnover"],
                entry_logic_desc=str(first.get("description") or "按规格书推荐方向构建入场条件"),
                exit_logic_desc="趋势失效、止损或风控触发时退出",
                risk_management_desc=str((spec.risk_considerations if spec else "") or "控制最大回撤、单票权重与交易频率"),
                acceptance_criteria=[
                    f"夏普 ≥ {task.goal.min_sharpe}",
                    f"最大回撤 ≤ {task.goal.max_drawdown:.0%}",
                    f"胜率 ≥ {task.goal.min_win_rate:.0%}",
                    f"区间收益 ≥ {task.goal.min_return:.0%}",
                    f"平仓交易数 ≥ {task.goal.min_trades}",
                    f"盈亏比 ≥ {task.goal.min_profit_loss_ratio}",
                ],
                action="new",
            )
        pivot = str(getattr(last_record, "next_action", "refine")) == "pivot"
        return SprintContract(
            strategy_direction=str(last_record.contract.strategy_direction if last_record.contract else "A 股日线多头策略"),
            key_indicators=list((last_record.contract.key_indicators if last_record.contract else []) or ["close", "volume"]),
            entry_logic_desc="根据上一轮评审建议调整入场逻辑",
            exit_logic_desc="根据上一轮评审建议调整出场与风控",
            risk_management_desc=str((spec.risk_considerations if spec else "") or "控制最大回撤、单票权重与交易频率"),
            acceptance_criteria=list((last_record.contract.acceptance_criteria if last_record.contract else []) or []),
            action="pivot" if pivot else "refine",
        )

    def _update_best(self, task: AgentTask) -> None:
        best_index = None
        best_score = -1.0
        for index, record in enumerate(task.iterations):
            if record.error or not record.strategy_code.strip():
                continue
            metrics = record.backtest_metrics or {}
            total_return = _float_or_none(metrics.get("strategy_return"))
            if total_return is None or total_return <= 0 or record.score < 50:
                continue
            if record.score > best_score:
                best_score = record.score
                best_index = index
        task.best_iteration = best_index

    @staticmethod
    def _set_stage(task: AgentTask, stage: str, label: str) -> None:
        task.stage = stage
        task.stage_label = label
        task.updated_at = _now()

    def _finish_task(self, task: AgentTask) -> None:
        task.updated_at = _now()
        self._persist_task(task)

    # ------------------------------------------------------------------
    # 持久化与恢复
    # ------------------------------------------------------------------
    def recover_interrupted(self) -> int:
        rows = self._rows("SELECT id FROM agent_tasks WHERE status IN ('pending', 'running')")
        resumed = 0
        for row in rows:
            task_id = str(row["id"])
            task = self._load_task(task_id)
            if not task:
                continue
            with self._lock:
                self._tasks[task_id] = task
            if not llm_available() or len(task.iterations) >= task.max_iterations:
                task.status = "stopped"
                task.stage_label = "服务重启中断，已停止（可手动重启）"
                task.updated_at = _now()
                self._persist_task(task)
                continue
            runner = threading.Thread(target=self._run_task_safe, args=(task_id,), daemon=True, name=f"agent-resume-{task_id}")
            with self._lock:
                self._runners[task_id] = runner
            runner.start()
            resumed += 1
        return resumed

    def _persist_task(self, task: AgentTask, insert: bool = False) -> None:
        payload = (
            task.name, task.status, task.stage, task.stage_label, task.user_prompt,
            psycopg2.extras.Json(task.goal.to_dict()),
            psycopg2.extras.Json({k: v for k, v in task.research_config.items() if not k.startswith("_")}),
            psycopg2.extras.Json(task.strategy_spec.to_dict()) if task.strategy_spec else None,
            task.max_iterations, task.current_iteration,
            task.iterations[task.best_iteration].iteration if task.best_iteration is not None else None,
            task.llm_model, task.promoted_strategy_version_id, task.error_message or None,
        )
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                if insert:
                    cursor.execute(
                        """
                        INSERT INTO agent_tasks
                        (id, name, status, stage, stage_label, user_prompt, goal, research_config,
                         strategy_spec, max_iterations, current_iteration, best_iteration,
                         llm_model, promoted_strategy_version_id, error_message)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                        """,
                        (task.task_id, *payload),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE agent_tasks SET name=%s,status=%s,stage=%s,stage_label=%s,user_prompt=%s,
                            goal=%s,research_config=%s,strategy_spec=%s,max_iterations=%s,
                            current_iteration=%s,best_iteration=%s,llm_model=%s,
                            promoted_strategy_version_id=%s,error_message=%s,updated_at=NOW(),
                            finished_at=CASE WHEN %s IN ('completed','failed','stopped') THEN NOW() ELSE finished_at END
                        WHERE id=%s
                        """,
                        (*payload, task.status, task.task_id),
                    )

    def _persist_iteration(self, task: AgentTask, record: IterationRecord) -> None:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO agent_iterations
                    (task_id, iteration, action, contract, strategy_name, strategy_version_id,
                     strategy_code, reasoning, sandbox_report, backtest_run_id, backtest_metrics,
                     eval_scores, score, meets_goal, analysis, suggestions, error, next_action)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(task_id, iteration) DO UPDATE SET
                        action=EXCLUDED.action, contract=EXCLUDED.contract,
                        strategy_name=EXCLUDED.strategy_name, strategy_version_id=EXCLUDED.strategy_version_id,
                        strategy_code=EXCLUDED.strategy_code, reasoning=EXCLUDED.reasoning,
                        sandbox_report=EXCLUDED.sandbox_report, backtest_run_id=EXCLUDED.backtest_run_id,
                        backtest_metrics=EXCLUDED.backtest_metrics, eval_scores=EXCLUDED.eval_scores,
                        score=EXCLUDED.score, meets_goal=EXCLUDED.meets_goal,
                        analysis=EXCLUDED.analysis, suggestions=EXCLUDED.suggestions, error=EXCLUDED.error,
                        next_action=EXCLUDED.next_action
                    """,
                    (
                        task.task_id, record.iteration, record.action,
                        psycopg2.extras.Json(record.contract.to_dict()) if record.contract else None,
                        record.strategy_name, record.strategy_version_id, record.strategy_code,
                        record.reasoning,
                        psycopg2.extras.Json(record.sandbox_report) if record.sandbox_report else None,
                        record.backtest_run_id,
                        psycopg2.extras.Json(record.backtest_metrics),
                        psycopg2.extras.Json(record.eval_scores.to_dict()) if record.eval_scores else None,
                        record.score, record.meets_goal, record.analysis,
                        psycopg2.extras.Json(record.suggestions), record.error, record.next_action,
                    ),
                )

    def _load_task(self, task_id: str) -> Optional[AgentTask]:
        row = self._row("SELECT * FROM agent_tasks WHERE id=%s", (task_id,))
        if not row:
            return None
        task = self._task_from_row(row)
        iterations = self._rows(
            "SELECT * FROM agent_iterations WHERE task_id=%s ORDER BY iteration", (task_id,)
        )
        task.iterations = [self._record_from_row(item) for item in iterations]
        return task

    def _task_from_row(self, row: Dict[str, Any]) -> AgentTask:
        return AgentTask(
            task_id=str(row["id"]),
            name=str(row.get("name") or ""),
            status=str(row.get("status") or "pending"),
            stage=str(row.get("stage") or "planner"),
            stage_label=str(row.get("stage_label") or ""),
            goal=GoalCriteria.from_dict(row.get("goal") or {}),
            research_config=dict(row.get("research_config") or {}),
            strategy_spec=StrategySpec.from_dict(row.get("strategy_spec") or {}) if row.get("strategy_spec") else None,
            max_iterations=int(row.get("max_iterations") or 6),
            current_iteration=int(row.get("current_iteration") or 0),
            best_iteration=int(row["best_iteration"]) if row.get("best_iteration") is not None else None,
            user_prompt=str(row.get("user_prompt") or ""),
            llm_model=str(row.get("llm_model") or ""),
            promoted_strategy_version_id=str(row["promoted_strategy_version_id"]) if row.get("promoted_strategy_version_id") else None,
            error_message=str(row.get("error_message") or ""),
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
        )

    @staticmethod
    def _record_from_row(row: Dict[str, Any]) -> IterationRecord:
        return IterationRecord(
            iteration=int(row.get("iteration") or 0),
            strategy_name=str(row.get("strategy_name") or ""),
            strategy_code=str(row.get("strategy_code") or ""),
            reasoning=str(row.get("reasoning") or ""),
            strategy_version_id=str(row["strategy_version_id"]) if row.get("strategy_version_id") else None,
            sandbox_report=dict(row["sandbox_report"]) if row.get("sandbox_report") else None,
            backtest_run_id=str(row["backtest_run_id"]) if row.get("backtest_run_id") else None,
            backtest_metrics=dict(row.get("backtest_metrics") or {}),
            eval_scores=EvalScores.from_dict(row.get("eval_scores") or {}) if row.get("eval_scores") else None,
            analysis=str(row.get("analysis") or ""),
            suggestions=list(row.get("suggestions") or []),
            score=float(row.get("score") or 0.0),
            meets_goal=bool(row.get("meets_goal")),
            error=str(row.get("error") or ""),
            created_at=str(row.get("created_at") or ""),
            contract=SprintContract.from_dict(row.get("contract") or {}) if row.get("contract") else None,
            action=str(row.get("action") or "new"),
            next_action=str(row.get("next_action") or "refine"),
        )

    @staticmethod
    def _serialize_version(version: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(version["id"]),
            "name": version.get("name"),
            "version": version.get("version"),
            "validation_status": version.get("validation_status"),
            "content_hash": version.get("content_hash"),
        }

    def _row(self, query: str, params: Any = ()) -> Optional[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()
                return dict(row) if row else None

    def _rows(self, query: str, params: Any = ()) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [dict(item) for item in cursor.fetchall()]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _float_or_none(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
