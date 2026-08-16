"""Evaluator：独立多维评分与方向决策；LLM 不可用时退化为确定性评分。"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, Optional

from app.services.agent.llm_client import QwenClient
from app.services.agent.prompts import build_evaluator_messages
from app.services.agent.schemas import EvalScores

logger = logging.getLogger(__name__)


class EvaluatorAgent:
    def evaluate(self, task: Any, record: Any, client: Optional[QwenClient], contract: Any) -> Dict[str, Any]:
        meets_goal = task.goal.check(record.backtest_metrics or {})
        if client is not None:
            try:
                data = client.chat_json(
                    build_evaluator_messages(task, record, contract), temperature=0.25, max_tokens=2400
                )
                scores = EvalScores.from_dict(data.get("eval_scores") or {})
                suggestions = [
                    str(item)[:300] for item in (data.get("suggestions") or []) if str(item).strip()
                ][:5]
                next_action = str(data.get("next_action") or "refine").strip().lower()
                return {
                    "eval_scores": scores,
                    "meets_goal": meets_goal,
                    "score": scores.total_score,
                    "analysis": str(data.get("analysis") or "")[:1500],
                    "suggestions": suggestions,
                    "next_action": next_action if next_action in {"refine", "pivot"} else "refine",
                }
            except Exception as exc:
                logger.warning("Evaluator LLM 评分失败，使用确定性评分: %s", exc)
        return self.deterministic_evaluate(task, record, meets_goal)

    @staticmethod
    def deterministic_evaluate(task: Any, record: Any, meets_goal: Optional[bool] = None) -> Dict[str, Any]:
        metrics = record.backtest_metrics or {}
        if meets_goal is None:
            meets_goal = task.goal.check(metrics)

        def ratio(value: Any, target: float) -> float:
            try:
                raw = float(value)
            except (TypeError, ValueError):
                return 0.0
            if not math.isfinite(raw) or target == 0:
                return 0.0
            return max(0.0, min(100.0, 100.0 * raw / target))

        sharpe = metrics.get("sharpe")
        drawdown = metrics.get("maximum_drawdown")
        win_rate = metrics.get("win_rate")
        total_return = metrics.get("strategy_return")
        profit_loss = metrics.get("profit_loss_ratio")
        trades = metrics.get("completed_trades")
        goal = task.goal
        profitability = (
            ratio(total_return, max(goal.min_return, 0.01)) * 0.5
            + ratio(sharpe, max(goal.min_sharpe, 0.1)) * 0.5
        )
        risk_control = ratio(-float(drawdown or 1.0), max(goal.max_drawdown, 0.05)) * 0.6 + ratio(
            profit_loss, max(goal.min_profit_loss_ratio, 0.1)
        ) * 0.4
        robustness = ratio(win_rate, max(goal.min_win_rate, 0.05)) * 0.6 + ratio(
            trades, max(goal.min_trades, 1)
        ) * 0.4
        strategy_logic = 55.0 if record.strategy_code and not record.error else 20.0
        originality = 50.0
        scores = EvalScores(
            risk_control=risk_control,
            profitability=profitability,
            robustness=robustness,
            strategy_logic=strategy_logic,
            originality=originality,
        )
        return {
            "eval_scores": scores,
            "meets_goal": meets_goal,
            "score": scores.total_score,
            "analysis": "（确定性评分：LLM 不可用，按回测指标与目标阈值计算）",
            "suggestions": ["配置 QWEN_API_KEY 后可获得逐轮改进建议"] if not record.error else [],
            "next_action": "refine",
        }
