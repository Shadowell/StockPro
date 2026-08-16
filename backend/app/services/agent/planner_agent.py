"""Planner：任务启动时把用户目标扩展为策略规格书（仅一次）。"""
from __future__ import annotations

import logging
from typing import Any

from app.services.agent.llm_client import QwenClient
from app.services.agent.prompts import build_planner_messages
from app.services.agent.schemas import StrategySpec

logger = logging.getLogger(__name__)


class PlannerAgent:
    def plan(self, task: Any, client: QwenClient) -> StrategySpec:
        data = client.chat_json(build_planner_messages(task), temperature=0.4, max_tokens=2400)
        candidates = []
        raw_candidates = data.get("strategy_candidates")
        if isinstance(raw_candidates, list):
            for item in raw_candidates:
                if isinstance(item, dict):
                    candidates.append({
                        "name": str(item.get("name") or "")[:60],
                        "description": str(item.get("description") or "")[:500],
                        "fit_reason": str(item.get("fit_reason") or "")[:300],
                    })
        spec = StrategySpec(
            market_analysis=str(data.get("market_analysis") or "")[:2000],
            strategy_candidates=candidates[:5],
            recommended_approach=str(data.get("recommended_approach") or "")[:800],
            risk_considerations=str(data.get("risk_considerations") or "")[:800],
            iteration_plan=str(data.get("iteration_plan") or "")[:800],
        )
        logger.info("Planner 完成: 推荐方向=%s, 候选=%d", spec.recommended_approach[:50], len(spec.strategy_candidates))
        return spec
