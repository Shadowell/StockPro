"""
Evaluator Agent — 独立策略评估者 (v2)

借鉴 Anthropic 文章核心设计:
1. 评估者独立于生成者 — 分离消除了自我评估偏见
2. 多维度量化评分 — 将主观判断转化为具体可打分的标准
3. 合约验收 — 对照 Sprint 合约逐条检查
4. Pivot/Refine 决策 — 根据趋势判断下一步方向
"""
import json
import inspect
import logging
from typing import Any, Dict, List, Optional

from app.services.agent.prompts import (
    EVALUATOR_SYSTEM,
    CONTRACT_NEGOTIATION_SYSTEM,
    build_evaluator_prompt,
    build_contract_review_prompt,
    format_goal_description,
    format_iteration_history,
)
from app.services.agent.providers import get_research_provider_client
from app.services.agent.providers.contracts import (
    ProviderCapabilities,
    ProviderError,
    ProviderExecutionError,
    ProviderRunRequest,
)
from app.services.agent.providers.http_client import _strip_json_fence, _validate_json_schema
from app.services.agent.schemas import (
    AgentTask, EvalScores, SprintContract, IterationRecord,
)

logger = logging.getLogger(__name__)

EVALUATE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "risk_control": {"type": "number"},
        "profitability": {"type": "number"},
        "robustness": {"type": "number"},
        "strategy_logic": {"type": "number"},
        "originality": {"type": "number"},
        "meets_goal": {"type": "boolean"},
        "analysis": {"type": "string"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "suggestions": {"type": "array", "items": {"type": "string"}},
        "contract_verdict": {"type": "array", "items": {"type": "string"}},
        "next_action": {"type": "string", "enum": ["refine", "pivot"]},
    },
    "required": [
        "risk_control",
        "profitability",
        "robustness",
        "strategy_logic",
        "originality",
        "meets_goal",
        "analysis",
        "issues",
        "suggestions",
        "contract_verdict",
        "next_action",
    ],
    "additionalProperties": False,
}

REVIEW_CONTRACT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["approved", "revision_needed"]},
        "added_criteria": {"type": "array", "items": {"type": "string"}},
        "feedback": {"type": "string"},
    },
    "required": ["verdict", "added_criteria", "feedback"],
    "additionalProperties": False,
}


def _decode_provider_json(result: Any, response_schema: Dict[str, Any], provider_key: str) -> Dict[str, Any]:
    structured = getattr(result, "structured", None)
    try:
        if isinstance(structured, dict):
            payload = structured
        else:
            text = _strip_json_fence(str(getattr(result, "text", "") or "").strip())
            payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("Provider 返回的 Evaluator 内容必须是 JSON 对象")
        _validate_json_schema(payload, response_schema)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ProviderExecutionError(
            f"Provider {provider_key} 返回的 Evaluator 结构化内容无效",
            provider_key=provider_key,
            error_code="provider_structured_output_invalid",
        ) from exc
    return payload


async def _chat_json(
    task: AgentTask,
    messages: list[dict[str, str]],
    *,
    response_schema: Dict[str, Any],
    temperature: float,
    max_tokens: int,
) -> Dict[str, Any]:
    execution = task.provider_execution_config()
    client = None
    try:
        client = get_research_provider_client(
            execution,
            capabilities_override=ProviderCapabilities.model_validate(task.llm_provider_snapshot),
        )
        result = await client.run(
            ProviderRunRequest(
                messages=messages,
                execution=execution,
                response_schema=response_schema,
                max_output_tokens=max_tokens,
            )
        )
        return _decode_provider_json(result, response_schema, execution.provider_key)
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderExecutionError(
            f"Provider {execution.provider_key} 执行失败",
            provider_key=execution.provider_key,
            error_code="provider_execution_failed",
        ) from exc
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                result = close()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.warning("Evaluator Provider client close failed", exc_info=True)


class EvaluatorAgent:
    """
    独立评估 Agent: 多维度打分 + 合约验收 + 方向决策。
    关键区别于旧 Analyst: 这是一个 skeptical evaluator, 而非策略的 co-creator。
    """

    async def evaluate(
        self,
        task: AgentTask,
        strategy_code: str,
        metrics: Dict[str, Any],
        contract: Optional[SprintContract] = None,
    ) -> Dict[str, Any]:
        """
        评估策略并返回多维度评分和建议。

        Returns:
            {
                "eval_scores": EvalScores,
                "meets_goal": bool,
                "score": float,          # 加权综合分
                "analysis": str,
                "issues": list[str],
                "suggestions": list[str],
                "contract_verdict": list[str],
                "next_action": "refine" | "pivot",
            }
        """
        goal_desc = format_goal_description(task.goal)
        history_text = format_iteration_history(task.iterations)

        contract_text = ""
        if contract:
            contract_text = json.dumps(contract.to_dict(), ensure_ascii=False, indent=2)

        user_prompt = build_evaluator_prompt(
            goal_desc=goal_desc,
            strategy_code=strategy_code,
            metrics=metrics,
            contract=contract_text,
            iteration_history=history_text,
        )

        messages = [
            {"role": "system", "content": EVALUATOR_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]

        try:
            result = await _chat_json(
                task,
                messages,
                response_schema=EVALUATE_RESPONSE_SCHEMA,
                temperature=0.3,
                max_tokens=4096,
            )

            eval_scores = EvalScores(
                risk_control=self._safe_score(result.get("risk_control", 50)),
                profitability=self._safe_score(result.get("profitability", 50)),
                robustness=self._safe_score(result.get("robustness", 50)),
                strategy_logic=self._safe_score(result.get("strategy_logic", 50)),
                originality=self._safe_score(result.get("originality", 30)),
            )

            meets_goal_llm = result.get("meets_goal", False)
            meets_goal_hard = task.goal.check(metrics)
            meets_goal = meets_goal_llm and meets_goal_hard

            eval_scores, score_cap = self._apply_metric_caps(eval_scores, metrics, task)
            total_score = min(eval_scores.total_score, score_cap)

            next_action = result.get("next_action", "refine")
            if next_action not in ("refine", "pivot"):
                next_action = "refine"
            if not meets_goal and self._metric_float(metrics, "total_return_pct") <= 0 and len(task.iterations) >= 1:
                next_action = "pivot"

            logger.info(
                "Evaluator 评分: 风控=%.0f 盈利=%.0f 稳健=%.0f 逻辑=%.0f 原创=%.0f → 综合=%.1f | 达标=%s | 下一步=%s",
                eval_scores.risk_control, eval_scores.profitability,
                eval_scores.robustness, eval_scores.strategy_logic,
                eval_scores.originality, total_score, meets_goal, next_action,
            )

            return {
                "eval_scores": eval_scores,
                "meets_goal": meets_goal,
                "score": total_score,
                "analysis": result.get("analysis", ""),
                "issues": result.get("issues", []),
                "suggestions": result.get("suggestions", []),
                "contract_verdict": result.get("contract_verdict", []),
                "next_action": next_action,
            }

        except ProviderError:
            raise
        except Exception as e:
            logger.exception("Evaluator 评估失败")
            hard_check = task.goal.check(metrics)
            return {
                "eval_scores": EvalScores(
                    risk_control=50, profitability=50, robustness=50,
                    strategy_logic=50, originality=30,
                ),
                "meets_goal": hard_check,
                "score": 46.0 if hard_check else 25.0,
                "analysis": f"LLM 评估失败 ({e})，仅使用硬性指标判断",
                "issues": ["LLM 评估不可用"],
                "suggestions": ["请检查 DASHSCOPE_API_KEY 配置"],
                "contract_verdict": [],
                "next_action": "refine",
            }

    async def review_contract(
        self,
        contract_proposal: Dict[str, Any],
        task: AgentTask,
    ) -> Dict[str, Any]:
        """
        审查 Strategist 提出的 Sprint 合约提案。

        Returns:
            {
                "verdict": "approved" | "revision_needed",
                "added_criteria": list[str],
                "feedback": str,
            }
        """
        goal_desc = format_goal_description(task.goal)
        proposal_text = json.dumps(contract_proposal, ensure_ascii=False, indent=2)

        user_prompt = build_contract_review_prompt(
            contract_proposal=proposal_text,
            goal_desc=goal_desc,
        )

        messages = [
            {"role": "system", "content": CONTRACT_NEGOTIATION_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]

        try:
            result = await _chat_json(
                task,
                messages,
                response_schema=REVIEW_CONTRACT_RESPONSE_SCHEMA,
                temperature=0.3,
                max_tokens=2048,
            )
            logger.info("Evaluator 合约审查: %s", result.get("verdict", "unknown"))
            return {
                "verdict": result.get("verdict", "approved"),
                "added_criteria": result.get("added_criteria", []),
                "feedback": result.get("feedback", ""),
            }
        except ProviderError:
            raise
        except Exception as e:
            logger.warning("Evaluator 合约审查失败: %s", e)
            return {
                "verdict": "approved",
                "added_criteria": [],
                "feedback": f"审查失败 ({e})，默认接受",
            }

    @staticmethod
    def _safe_score(v) -> float:
        try:
            s = float(v)
            return max(0.0, min(100.0, s))
        except (TypeError, ValueError):
            return 50.0

    @staticmethod
    def _metric_float(metrics: Dict[str, Any], key: str, default: float = 0.0) -> float:
        try:
            return float(metrics.get(key, default))
        except (TypeError, ValueError):
            return default

    @classmethod
    def _apply_metric_caps(
        cls,
        eval_scores: EvalScores,
        metrics: Dict[str, Any],
        task: AgentTask,
    ) -> tuple[EvalScores, float]:
        """Clamp subjective LLM scores with hard backtest facts.

        The Evaluator can still value clean logic, but a strategy with negative
        return or negative Sharpe must not surface as a save-worthy candidate.
        """
        total_return = cls._metric_float(metrics, "total_return_pct")
        annual_return = cls._metric_float(metrics, "annual_return_pct")
        sharpe = cls._metric_float(metrics, "sharpe_ratio")
        drawdown = cls._metric_float(metrics, "max_drawdown_pct", 100.0)
        trades = cls._metric_float(metrics, "total_trades")
        profit_factor = cls._metric_float(metrics, "profit_factor")

        score_cap = 100.0

        if total_return <= 0 or annual_return <= 0:
            eval_scores.profitability = min(eval_scores.profitability, 15.0)
            eval_scores.robustness = min(eval_scores.robustness, 40.0)
            eval_scores.strategy_logic = min(eval_scores.strategy_logic, 60.0)
            eval_scores.originality = min(eval_scores.originality, 60.0)
            score_cap = min(score_cap, 38.0)

        if sharpe <= 0:
            eval_scores.profitability = min(eval_scores.profitability, 20.0)
            eval_scores.robustness = min(eval_scores.robustness, 45.0)
            score_cap = min(score_cap, 42.0)
        elif sharpe < task.goal.min_sharpe_ratio:
            eval_scores.profitability = min(eval_scores.profitability, 55.0)
            score_cap = min(score_cap, 68.0)

        if profit_factor < 1.0:
            eval_scores.profitability = min(eval_scores.profitability, 25.0)
            score_cap = min(score_cap, 48.0)

        drawdown_limit = max(task.goal.max_drawdown_pct * 3.0, 15.0)
        if drawdown > drawdown_limit:
            eval_scores.risk_control = min(eval_scores.risk_control, 35.0)
            eval_scores.robustness = min(eval_scores.robustness, 45.0)
            score_cap = min(score_cap, 50.0)

        if trades < task.goal.min_total_trades:
            eval_scores.robustness = min(eval_scores.robustness, 45.0)
            score_cap = min(score_cap, 65.0)

        return eval_scores, score_cap
