"""
Planner Agent — 策略规格书生成

借鉴 Anthropic 文章: Planner 接收简短 prompt 并扩展为完整产品规格书,
保持高层级设计视角, 不写具体实现代码。
"""
import logging
from typing import Dict, Any

from app.services.agent.llm_client import get_qwen_client
from app.services.agent.factor_research import build_factor_research_context
from app.services.agent.prompts import (
    PLANNER_SYSTEM,
    build_planner_prompt,
    format_goal_description,
)
from app.services.agent.schemas import AgentTask, StrategySpec

logger = logging.getLogger(__name__)


class PlannerAgent:
    """
    规格书生成 Agent: 将用户简短需求扩展为完整的策略研发规格书。
    只在任务启动时运行一次。
    """

    async def plan(self, task: AgentTask) -> StrategySpec:
        client = get_qwen_client(task.llm_model)
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
            result = await client.chat_json(messages, temperature=0.7, max_tokens=4096)
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

        except Exception as e:
            logger.exception("Planner 规格书生成失败")
            return StrategySpec(
                market_analysis=f"规格书生成失败: {e}",
                recommended_approach="使用默认策略方向",
            )
