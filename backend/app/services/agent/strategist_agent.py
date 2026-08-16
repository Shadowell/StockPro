"""Strategist：按 Sprint 合约生成符合 Strategy API v1 的策略代码。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.services.agent.llm_client import QwenClient
from app.services.agent.prompts import build_strategist_messages
from app.services.agent.schemas import SprintContract

logger = logging.getLogger(__name__)


def strip_code_fences(code: str) -> str:
    text = str(code or "").strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


class StrategistAgent:
    def generate(
        self,
        task: Any,
        client: QwenClient,
        contract: Optional[SprintContract] = None,
        handoff_context: str = "",
        repair_issues: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        data = client.chat_json(
            build_strategist_messages(task, contract, handoff_context, repair_issues),
            temperature=0.35,
            max_tokens=4096,
        )
        code = strip_code_fences(str(data.get("strategy_code") or ""))
        return {
            "strategy_name": str(data.get("strategy_name") or "").strip()[:40] or "AI策略",
            "strategy_code": code,
            "reasoning": str(data.get("reasoning") or "")[:1200],
        }
