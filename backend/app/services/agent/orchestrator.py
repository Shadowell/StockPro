"""
Orchestrator v2 — 编排器 (GAN-inspired multi-agent)

四 Agent 闭环架构 (借鉴 Anthropic 文章):
  Planner → [Sprint Contract 协商 → Strategist → Backtester → Evaluator] × N

核心改进:
1. Planner: 任务启动时生成策略规格书
2. Sprint Contract: 每轮迭代前 Strategist 提案 + Evaluator 审查
3. Context Reset: 每轮用结构化交接文档传递状态 (非累积对话)
4. Pivot/Refine: Evaluator 决定下一步方向, Strategist 执行
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from app.services.agent.schemas import (
    AgentTask, GoalCriteria, IterationRecord, SprintContract, EvalScores,
    CreateTaskRequest, AI_RESEARCH_MARKET_SCOPE, normalize_agent_market_type,
    normalize_agent_symbol_scope,
)
from app.services.agent.planner_agent import PlannerAgent
from app.services.agent.strategist_agent import StrategistAgent
from app.services.agent.backtester_agent import BacktesterAgent
from app.services.agent.evaluator_agent import EvaluatorAgent
from app.services.agent.factor_research import default_factor_key_indicators
from app.services.agent.prompts import (
    format_goal_description, format_iteration_history, build_handoff_context,
)

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """
    Agent 编排器 v2。
    管理任务生命周期，驱动 Planner → [Contract → Strategist → Backtester → Evaluator] 闭环。
    """

    def __init__(self):
        self.tasks: Dict[str, AgentTask] = {}
        self._planner = PlannerAgent()
        self._strategist = StrategistAgent()
        self._backtester = BacktesterAgent()
        self._evaluator = EvaluatorAgent()
        self._on_iteration_cb: Optional[Callable] = None
        self._on_task_update_cb: Optional[Callable] = None
        self._runner_tasks: Dict[str, asyncio.Task] = {}

    def set_on_iteration(self, callback: Callable):
        self._on_iteration_cb = callback

    def set_on_task_update(self, callback: Callable):
        self._on_task_update_cb = callback

    def create_task(self, req: CreateTaskRequest) -> AgentTask:
        task_id = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()
        goal = GoalCriteria.from_dict(req.goal) if req.goal else GoalCriteria()

        market_type = normalize_agent_market_type(req.market_type)
        request_symbol = req.symbol
        if (
            market_type == "swap"
            and not req.symbols
            and str(request_symbol or "").strip() in {"", AI_RESEARCH_MARKET_SCOPE}
        ):
            request_symbol = ""
        symbol_scope = ",".join(normalize_agent_symbol_scope(request_symbol, req.symbols, market_type))

        task = AgentTask(
            task_id=task_id,
            status="pending",
            stage="planner",
            stage_label="等待 Planner 生成规格书",
            goal=goal,
            market_type=market_type,
            symbol=symbol_scope,
            timeframe=req.timeframe,
            backtest_start=req.backtest_start,
            backtest_end=req.backtest_end,
            max_iterations=req.max_iterations,
            user_prompt=req.user_prompt,
            llm_model=str(req.llm_model or "").strip(),
            created_at=now,
            updated_at=now,
        )
        self.tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> Optional[AgentTask]:
        return self.tasks.get(task_id)

    def list_tasks(self):
        return list(self.tasks.values())

    def register_task(self, task: AgentTask) -> AgentTask:
        """Register a task reconstructed from SQLite so it can continue running."""
        self.tasks[task.task_id] = task
        return task

    def attach_runner(self, task_id: str, runner: asyncio.Task) -> None:
        self._runner_tasks[task_id] = runner

    def clear_runner(self, task_id: str) -> None:
        self._runner_tasks.pop(task_id, None)

    def stop_task(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        if task and task.status in {"pending", "running"}:
            task.status = "stopped"
            self._set_stage(task, "stopped", "任务已停止")
            task.updated_at = datetime.now().isoformat()
            runner = self._runner_tasks.get(task_id)
            if runner and not runner.done():
                runner.cancel()
            return True
        return False

    def delete_task(self, task_id: str) -> bool:
        """Remove a non-running task from in-memory history."""
        task = self.tasks.get(task_id)
        runner = self._runner_tasks.get(task_id)
        if (task and task.status in {"pending", "running"}) or (runner and not runner.done()):
            return False
        self.tasks.pop(task_id, None)
        self._runner_tasks.pop(task_id, None)
        return True

    async def run_task(self, task_id: str) -> AgentTask:
        """
        执行完整的 Agent 闭环迭代。

        流程:
        Phase 0: Planner 生成策略规格书 (仅一次)
        Phase 1-N: 迭代循环
            Step 1: Sprint 合约协商 (Strategist 提案 → Evaluator 审查)
            Step 2: Strategist 生成策略代码
            Step 3: Backtester 执行回测
            Step 4: Evaluator 独立评估 (多维度打分 + 方向决策)
            Step 5: Context Reset — 构建结构化交接文档
        """
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        if task.status == "stopped":
            return task
        if len(task.iterations) >= task.max_iterations:
            task.status = "completed"
            self._set_stage(task, "completed", "策略研发已完成")
            task.updated_at = datetime.now().isoformat()
            await self._persist_task_state(task)
            return task

        task.status = "running"
        if task.strategy_spec:
            next_iteration = min(len(task.iterations) + 1, task.max_iterations)
            self._set_stage(task, "planner_done", f"Planner 已完成，准备第 {next_iteration} 轮策略生成")
        else:
            self._set_stage(task, "planner", "Planner 正在生成策略规格书")
        task.updated_at = datetime.now().isoformat()
        await self._persist_task_state(task)

        try:
            # ========================
            # Phase 0: Planner
            # ========================
            if task.strategy_spec:
                logger.info("=== Task %s: Phase 0 — 复用已持久化 Planner 规格书 ===", task_id)
            else:
                logger.info("=== Task %s: Phase 0 — Planner 生成规格书 ===", task_id)
                task.strategy_spec = await self._planner.plan(task)
            next_iteration = min(len(task.iterations) + 1, task.max_iterations)
            self._set_stage(task, "planner_done", f"Planner 已完成，准备第 {next_iteration} 轮策略生成")
            task.updated_at = datetime.now().isoformat()
            await self._persist_task_state(task)
            if task.status == "stopped":
                logger.info("Task %s stopped after planner phase", task_id)
                return task

            # ========================
            # Phase 1-N: 迭代循环
            # ========================
            start_iteration = len(task.iterations)
            for iteration in range(start_iteration, task.max_iterations):
                if task.status == "stopped":
                    logger.info("Task %s stopped by user at iteration %d", task_id, iteration)
                    break

                task.current_iteration = iteration
                task.updated_at = datetime.now().isoformat()
                await self._persist_task_state(task)
                logger.info("=== Task %s: 第 %d/%d 轮 ===", task_id, iteration + 1, task.max_iterations)

                record = IterationRecord(
                    iteration=iteration,
                    created_at=datetime.now().isoformat(),
                )

                # --- Step 1: Sprint 合约协商 ---
                handoff_context = ""
                if task.iterations:
                    last = task.iterations[-1]
                    handoff_context = build_handoff_context(task, last)

                self._set_stage(
                    task,
                    "contract",
                    f"第 {iteration + 1} 轮：准备策略合约",
                )
                await self._persist_task_state(task)
                contract = await self._negotiate_contract(task, handoff_context)
                record.contract = contract
                record.action = contract.action if contract else "new"

                # --- Step 2: Strategist 生成策略 ---
                try:
                    self._set_stage(
                        task,
                        "strategist",
                        f"第 {iteration + 1} 轮：正在生成策略代码",
                    )
                    await self._persist_task_state(task)
                    strategy_result = await self._strategist.generate(
                        task=task,
                        previous_feedback=handoff_context,
                        contract=contract,
                    )
                    record.strategy_name = strategy_result.get("strategy_name", f"策略_v{iteration+1}")
                    record.strategy_code = strategy_result.get("strategy_class_code", "")
                    record.reasoning = strategy_result.get("reasoning", "")

                    stop_loss = strategy_result.get("stop_loss")
                except Exception as e:
                    record.error = f"策略生成失败: {e}"
                    logger.exception("Strategist failed at iteration %d", iteration)
                    task.iterations.append(record)
                    await self._persist_iteration(task, record)
                    continue

                # --- Step 3: Backtester 执行回测 ---
                try:
                    self._set_stage(
                        task,
                        "backtester",
                        f"第 {iteration + 1} 轮：正在执行回测",
                    )
                    await self._persist_task_state(task)
                    bt_result = await self._backtester.run(
                        strategy_code=record.strategy_code,
                        symbol=task.symbol,
                        market_type=task.market_type,
                        timeframe=task.timeframe,
                        start_date=task.backtest_start,
                        end_date=task.backtest_end,
                        stop_loss=stop_loss,
                    )
                    record.backtest_metrics = bt_result.get("metrics", {})

                    if bt_result.get("error"):
                        record.error = bt_result["error"]
                        logger.warning("Backtester error at iteration %d: %s", iteration, record.error)
                        task.iterations.append(record)
                        await self._persist_iteration(task, record)
                        continue

                except Exception as e:
                    record.error = f"回测执行失败: {e}"
                    logger.exception("Backtester failed at iteration %d", iteration)
                    task.iterations.append(record)
                    await self._persist_iteration(task, record)
                    continue

                # --- Step 4: Evaluator 独立评估 ---
                try:
                    self._set_stage(
                        task,
                        "evaluator",
                        f"第 {iteration + 1} 轮：正在评分",
                    )
                    await self._persist_task_state(task)
                    eval_result = await self._evaluator.evaluate(
                        task=task,
                        strategy_code=record.strategy_code,
                        metrics=record.backtest_metrics,
                        contract=contract,
                    )
                    record.eval_scores = eval_result.get("eval_scores")
                    record.meets_goal = eval_result.get("meets_goal", False)
                    record.score = eval_result.get("score", 0)
                    record.analysis = eval_result.get("analysis", "")
                    record.suggestions = eval_result.get("suggestions", [])

                except Exception as e:
                    record.analysis = f"评估失败: {e}"
                    record.meets_goal = task.goal.check(record.backtest_metrics)
                    record.score = 50.0 if record.meets_goal else 20.0
                    logger.exception("Evaluator failed at iteration %d", iteration)

                # --- 更新最佳记录 ---
                task.iterations.append(record)
                self._update_best(task)
                await self._persist_iteration(task, record)

                scores_text = ""
                if record.eval_scores:
                    s = record.eval_scores
                    scores_text = (
                        f" | 风控={s.risk_control:.0f} 盈利={s.profitability:.0f} "
                        f"稳健={s.robustness:.0f} 逻辑={s.strategy_logic:.0f} 原创={s.originality:.0f}"
                    )
                logger.info(
                    "第 %d 轮完成: %s | 综合=%.1f | 达标=%s | 收益=%.1f%% | 夏普=%.2f%s | 行动=%s",
                    iteration + 1,
                    record.strategy_name,
                    record.score,
                    record.meets_goal,
                    record.backtest_metrics.get("total_return_pct", 0),
                    record.backtest_metrics.get("sharpe_ratio", 0),
                    scores_text,
                    record.action,
                )

                if record.meets_goal:
                    logger.info("Task %s 在第 %d 轮达标!", task_id, iteration + 1)
                    task.status = "completed"
                    self._set_stage(task, "completed", f"第 {iteration + 1} 轮已达标")
                    task.updated_at = datetime.now().isoformat()
                    await self._persist_task_state(task)
                    return task

            if task.status == "running":
                task.status = "completed"
                self._set_stage(task, "completed", "策略研发已完成")
            task.updated_at = datetime.now().isoformat()
            await self._persist_task_state(task)
            return task

        except Exception as e:
            task.status = "failed"
            self._set_stage(task, "failed", f"任务失败：{e}")
            task.updated_at = datetime.now().isoformat()
            await self._persist_task_state(task)
            logger.exception("Task %s failed", task_id)
            raise

    async def _negotiate_contract(
        self, task: AgentTask, evaluator_feedback: str = "",
    ) -> Optional[SprintContract]:
        """
        Sprint 合约协商: Strategist 提案 → Evaluator 审查 (最多 2 轮)
        """
        try:
            if not task.iterations and task.strategy_spec:
                contract = self._build_initial_contract_from_spec(task)
                logger.info(
                    "首轮使用 Planner 规格书生成本地合约，跳过额外 LLM 合约协商: direction=%s",
                    contract.strategy_direction[:50],
                )
                return contract

            proposal = await self._strategist.propose_contract(
                task=task,
                evaluator_feedback=evaluator_feedback,
            )

            review = await self._evaluator.review_contract(
                contract_proposal=proposal,
                task=task,
            )

            criteria = proposal.get("acceptance_criteria", [])
            added = review.get("added_criteria", [])
            if added:
                criteria.extend(added)

            contract = SprintContract(
                strategy_direction=proposal.get("strategy_direction", ""),
                key_indicators=proposal.get("key_indicators", []),
                entry_logic_desc=proposal.get("entry_logic_desc", ""),
                exit_logic_desc=proposal.get("exit_logic_desc", ""),
                risk_management_desc=proposal.get("risk_management_desc", ""),
                acceptance_criteria=criteria,
                action=proposal.get("action", "new"),
            )

            logger.info(
                "合约协商完成: action=%s, direction=%s, criteria=%d条",
                contract.action, contract.strategy_direction[:30], len(criteria),
            )
            return contract

        except Exception as e:
            logger.warning("合约协商失败, 跳过: %s", e)
            return None

    def _build_initial_contract_from_spec(self, task: AgentTask) -> SprintContract:
        spec = task.strategy_spec
        candidates = spec.strategy_candidates if spec else []
        first_candidate = candidates[0] if candidates else {}
        direction = (
            (spec.recommended_approach if spec else "")
            or first_candidate.get("name")
            or first_candidate.get("description")
            or "基于 K 线趋势、波动率和成交量过滤的策略"
        )
        return SprintContract(
            strategy_direction=str(direction),
            key_indicators=default_factor_key_indicators(),
            entry_logic_desc=(
                first_candidate.get("description")
                or "按 Planner 推荐方向构建入场条件，结合主流因子库中的趋势、截面、波动率和成交量代理。"
            ),
            exit_logic_desc="按趋势失效、止损、止盈或风控条件退出。",
            risk_management_desc=(
                (spec.risk_considerations if spec else "")
                or "控制最大回撤、仓位大小和交易频率，避免过拟合。"
            ),
            acceptance_criteria=[
                f"夏普比率 >= {task.goal.min_sharpe_ratio}",
                f"最大回撤 <= {task.goal.max_drawdown_pct}%",
                f"胜率 >= {task.goal.min_win_rate_pct}%",
                f"总收益率 >= {task.goal.min_total_return_pct}%",
                f"盈亏比 >= {task.goal.min_profit_factor}",
                f"交易次数 >= {task.goal.min_total_trades}",
            ],
            action="new",
        )

    @staticmethod
    def _set_stage(task: AgentTask, stage: str, label: str) -> None:
        task.stage = stage
        task.stage_label = label

    def _update_best(self, task: AgentTask):
        best_idx = None
        best_score = -1
        for i, rec in enumerate(task.iterations):
            if rec.score > best_score and not rec.error and self._is_basic_candidate(rec):
                best_score = rec.score
                best_idx = i
        task.best_iteration = best_idx

    @staticmethod
    def _is_basic_candidate(record: IterationRecord) -> bool:
        metrics = record.backtest_metrics or {}
        try:
            total_return = float(metrics.get("total_return_pct", 0))
            sharpe = float(metrics.get("sharpe_ratio", 0))
            profit_factor = float(metrics.get("profit_factor", 0))
        except (TypeError, ValueError):
            return False
        return (
            bool(record.strategy_code.strip())
            and total_return > 0
            and sharpe > 0
            and profit_factor >= 1
            and record.score >= 50
        )

    async def _persist_iteration(self, task: AgentTask, record: IterationRecord):
        if self._on_iteration_cb:
            try:
                await self._on_iteration_cb(task, record)
            except Exception as e:
                logger.warning("Failed to persist iteration: %s", e)

    async def _persist_task_state(self, task: AgentTask):
        if self._on_task_update_cb:
            try:
                await self._on_task_update_cb(task)
            except Exception as e:
                logger.warning("Failed to persist task state: %s", e)


orchestrator = AgentOrchestrator()
