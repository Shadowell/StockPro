"""
Agent A: Strategist (Generator) — 策略生成师 (v2)

增强:
1. 支持 Sprint 合约 — 先协商再生成
2. 支持 Context Reset — 通过结构化交接文档接收上下文
3. 支持 Pivot/Refine 决策 — 由 Evaluator 驱动方向选择
"""
import json
import inspect
import logging
from typing import Dict, Any, Optional

from app.services.agent.factor_research import build_factor_research_context
from app.services.agent.prompts import (
    STRATEGIST_SYSTEM,
    build_strategist_prompt,
    build_contract_proposal_prompt,
    format_goal_description,
    format_iteration_history,
    format_spec_summary,
)
from app.services.agent.providers import get_research_provider_client
from app.services.agent.providers.contracts import (
    ProviderCapabilities,
    ProviderError,
    ProviderExecutionError,
    ProviderRunRequest,
)
from app.services.agent.providers.http_client import _strip_json_fence, _validate_json_schema
from app.services.agent.schemas import AgentTask, SprintContract
from app.services.agent.code_sandbox import (
    CodeSafetyError,
    validate_base_strategy_contract,
    validate_strategy_runtime_smoke,
)

logger = logging.getLogger(__name__)

CONTRACT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["new", "refine", "pivot"]},
        "strategy_direction": {"type": "string"},
        "key_indicators": {"type": "array", "items": {"type": "string"}},
        "entry_logic_desc": {"type": "string"},
        "exit_logic_desc": {"type": "string"},
        "risk_management_desc": {"type": "string"},
        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "action",
        "strategy_direction",
        "key_indicators",
        "entry_logic_desc",
        "exit_logic_desc",
        "risk_management_desc",
        "acceptance_criteria",
    ],
    "additionalProperties": False,
}

STRATEGY_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "strategy_name": {"type": "string"},
        "strategy_class_code": {"type": "string"},
        "stop_loss": {"type": ["number", "null"]},
        "timeframe": {"type": "string"},
        "reasoning": {"type": "string"},
    },
    "required": ["strategy_name", "strategy_class_code", "stop_loss", "timeframe", "reasoning"],
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
            raise ValueError("Provider 返回的 Strategist 内容必须是 JSON 对象")
        _validate_json_schema(payload, response_schema)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ProviderExecutionError(
            f"Provider {provider_key} 返回的 Strategist 结构化内容无效",
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
                logger.warning("Strategist Provider client close failed", exc_info=True)


class StrategistAgent:
    """
    策略生成 Agent: 先提出 Sprint 合约, 再生成代码。
    """

    async def propose_contract(
        self,
        task: AgentTask,
        evaluator_feedback: str = "",
    ) -> Dict[str, Any]:
        """
        提出 Sprint 合约提案。

        Returns:
            {
                "action": "new" | "refine" | "pivot",
                "strategy_direction": str,
                "key_indicators": list,
                "entry_logic_desc": str,
                "exit_logic_desc": str,
                "risk_management_desc": str,
                "acceptance_criteria": list[str],
            }
        """
        goal_desc = format_goal_description(task.goal)
        spec_text = format_spec_summary(task.strategy_spec)
        history_text = format_iteration_history(task.iterations)
        factor_context = build_factor_research_context(
            symbol_scope=task.symbol,
            timeframe=task.timeframe,
            market_type=task.market_type,
        )

        user_prompt = build_contract_proposal_prompt(
            strategy_spec=spec_text,
            goal_desc=goal_desc,
            iteration=len(task.iterations),
            history_summary=history_text,
            evaluator_feedback=evaluator_feedback,
            factor_context=factor_context,
        )

        messages = [
            {"role": "system", "content": STRATEGIST_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]

        try:
            result = await _chat_json(
                task,
                messages,
                response_schema=CONTRACT_RESPONSE_SCHEMA,
                temperature=0.7,
                max_tokens=2048,
            )
            action = result.get("action", "new")
            if action not in ("new", "refine", "pivot"):
                action = "new"
            if not task.iterations:
                action = "new"
            result["action"] = action
            logger.info(
                "Strategist 合约提案: %s | 方向: %s",
                action, result.get("strategy_direction", "unknown")[:50],
            )
            return result
        except ProviderError:
            raise
        except Exception as e:
            logger.warning("Strategist 合约提案失败: %s", e)
            return {
                "action": "new",
                "strategy_direction": "默认多指标组合策略",
                "key_indicators": ["sma", "rsi", "atr"],
                "entry_logic_desc": "多指标共振信号买入",
                "exit_logic_desc": "趋势反转或止损出场",
                "risk_management_desc": "动态止损 + 仓位控制",
                "acceptance_criteria": ["夏普比率达标", "回撤可控"],
            }

    async def generate(
        self,
        task: AgentTask,
        previous_feedback: str = "",
        contract: Optional[SprintContract] = None,
    ) -> Dict[str, Any]:
        """
        生成或改进策略代码。

        Returns:
            {
                "strategy_name": str,
                "strategy_class_code": str,
                "stop_loss": float,
                "timeframe": str,
                "reasoning": str,
            }
        """
        goal_desc = format_goal_description(task.goal)
        factor_context = build_factor_research_context(
            symbol_scope=task.symbol,
            timeframe=task.timeframe,
            market_type=task.market_type,
        )

        contract_text = ""
        if contract:
            contract_text = json.dumps(contract.to_dict(), ensure_ascii=False, indent=2)

        user_prompt = build_strategist_prompt(
            goal_desc=goal_desc,
            symbol=task.symbol,
            market_type=task.market_type,
            timeframe=task.timeframe,
            user_prompt=task.user_prompt,
            previous_feedback=previous_feedback,
            contract=contract_text,
            factor_context=factor_context,
        )

        messages = [
            {"role": "system", "content": STRATEGIST_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]

        max_code_retries = 3
        last_error = ""

        for attempt in range(max_code_retries):
            try:
                if attempt > 0 and last_error:
                    messages.append({
                        "role": "user",
                        "content": (
                            f"上一次生成的代码有问题:\n{last_error}\n"
                            "请修复并重新输出完整 JSON。"
                        ),
                    })

                result = await _chat_json(
                    task,
                    messages,
                    response_schema=STRATEGY_RESPONSE_SCHEMA,
                    temperature=0.7,
                    max_tokens=4096,
                )

                strategy_code = result.get("strategy_class_code", "")

                if not strategy_code:
                    last_error = "strategy_class_code 字段为空"
                    continue

                validate_base_strategy_contract(strategy_code)
                await validate_strategy_runtime_smoke(
                    strategy_code,
                    symbols=task.symbol,
                    market_type=task.market_type,
                    timeframe=task.timeframe,
                )

                logger.info(
                    "Strategist 生成策略: %s (第 %d 次尝试)",
                    result.get("strategy_name", "unknown"),
                    attempt + 1,
                )
                result["strategy_class_code"] = strategy_code
                return result

            except ProviderError:
                raise
            except CodeSafetyError as e:
                last_error = str(e)
                logger.warning("Strategist 代码安全检查失败 (attempt %d): %s", attempt + 1, e)
            except Exception as e:
                last_error = str(e)
                logger.warning("Strategist 生成失败 (attempt %d): %s", attempt + 1, e)

        raise RuntimeError(f"Strategist 在 {max_code_retries} 次尝试后仍无法生成安全的策略代码: {last_error}")
