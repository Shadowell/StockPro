"""
Planner Agent — 策略规格书生成

借鉴 Anthropic 文章: Planner 接收简短 prompt 并扩展为完整产品规格书,
保持高层级设计视角, 不写具体实现代码。
"""
import json
import logging
import inspect
from typing import Dict, Any

from app.services.agent.factor_research import build_factor_research_context
from app.services.agent.prompts import (
    PLANNER_SYSTEM,
    build_planner_prompt,
    format_goal_description,
)
from app.services.agent.providers import get_research_provider_client
from app.services.agent.providers.contracts import (
    ProviderCapabilities,
    ProviderError,
    ProviderExecutionError,
    ProviderRunRequest,
)
from app.services.agent.providers.http_client import _strip_json_fence, _validate_json_schema
from app.services.agent.schemas import AgentTask, StrategySpec

logger = logging.getLogger(__name__)

PLANNER_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "market_analysis": {"type": "string"},
        "strategy_candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "factor_families": {"type": "array", "items": {"type": "string"}},
                    "description": {"type": "string"},
                    "pros": {"type": "string"},
                    "cons": {"type": "string"},
                    "test_plan": {"type": "string"},
                },
                "required": ["name", "factor_families", "description", "pros", "cons", "test_plan"],
                "additionalProperties": False,
            },
        },
        "recommended_approach": {"type": "string"},
        "risk_considerations": {"type": "string"},
        "iteration_plan": {"type": "string"},
    },
    "required": [
        "market_analysis",
        "strategy_candidates",
        "recommended_approach",
        "risk_considerations",
        "iteration_plan",
    ],
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
            raise ValueError("Provider 返回的 Planner 内容必须是 JSON 对象")
        _validate_json_schema(payload, response_schema)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ProviderExecutionError(
            f"Provider {provider_key} 返回的 Planner 结构化内容无效",
            provider_key=provider_key,
            error_code="provider_structured_output_invalid",
        ) from exc
    return payload


async def _chat_json(task: AgentTask, messages: list[dict[str, str]], *, temperature: float, max_tokens: int) -> Dict[str, Any]:
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
                response_schema=PLANNER_RESPONSE_SCHEMA,
                max_output_tokens=max_tokens,
            )
        )
        return _decode_provider_json(result, PLANNER_RESPONSE_SCHEMA, execution.provider_key)
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
                logger.warning("Planner Provider client close failed", exc_info=True)


class PlannerAgent:
    """
    规格书生成 Agent: 将用户简短需求扩展为完整的策略研发规格书。
    只在任务启动时运行一次。
    """

    async def plan(self, task: AgentTask) -> StrategySpec:
        goal_desc = format_goal_description(task.goal)
        factor_context = build_factor_research_context(
            symbol_scope=task.symbol,
            timeframe=task.timeframe,
            market_type=task.market_type,
        )

        user_prompt = build_planner_prompt(
            symbol=task.symbol,
            market_type=task.market_type,
            timeframe=task.timeframe,
            goal_desc=goal_desc,
            user_prompt=task.user_prompt,
            backtest_start=task.backtest_start,
            backtest_end=task.backtest_end,
            factor_context=factor_context,
        )

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]

        try:
            result = await _chat_json(task, messages, temperature=0.7, max_tokens=4096)
            spec = StrategySpec(
                market_analysis=result.get("market_analysis", ""),
                strategy_candidates=result.get("strategy_candidates", []),
                recommended_approach=result.get("recommended_approach", ""),
                risk_considerations=result.get("risk_considerations", ""),
                iteration_plan=result.get("iteration_plan", ""),
            )
            logger.info(
                "Planner 生成规格书: %d 个候选方向, 推荐: %s",
                len(spec.strategy_candidates),
                spec.recommended_approach[:60] if spec.recommended_approach else "无",
            )
            return spec

        except ProviderError:
            raise
        except Exception as e:
            logger.exception("Planner 规格书生成失败")
            raise ProviderExecutionError(
                "Planner Provider 执行失败",
                provider_key=task.llm_provider or None,
                error_code="provider_execution_failed",
            ) from e
