"""
Agent 系统数据模型 (v2 — GAN-inspired multi-agent)

基于 Anthropic 文章指导思想重构:
- Planner: 扩展用户 prompt 为完整策略规格书
- Strategist (Generator): 生成策略代码
- Backtester: 执行回测 (无 LLM)
- Evaluator: 独立于 Generator 的评估者, 多维度量化打分
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# ============================================
# AI 研发默认市场范围
# ============================================

AI_RESEARCH_SPOT_SYMBOLS: List[str] = [
    "BTC/USDT",
    "ETH/USDT",
    "DOGE/USDT",
    "SOL/USDT",
    "XRP/USDT",
    "PEPE/USDT",
    "TRX/USDT",
    "PENGU/USDT",
    "PI/USDT",
    "SUI/USDT",
    "FIL/USDT",
    "ADA/USDT",
    "APE/USDT",
    "LINK/USDT",
    "LTC/USDT",
]
AI_RESEARCH_LIQUID_SYMBOLS = AI_RESEARCH_SPOT_SYMBOLS

AI_RESEARCH_SWAP_SYMBOLS: List[str] = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "DOGE/USDT:USDT",
    "SOL/USDT:USDT",
    "XRP/USDT:USDT",
    "PEPE/USDT:USDT",
    "TRX/USDT:USDT",
    "PENGU/USDT:USDT",
    "PI/USDT:USDT",
    "SUI/USDT:USDT",
    "FIL/USDT:USDT",
    "ADA/USDT:USDT",
    "APE/USDT:USDT",
    "LINK/USDT:USDT",
    "LTC/USDT:USDT",
]

AI_RESEARCH_MARKET_SCOPE = ",".join(AI_RESEARCH_SPOT_SYMBOLS)
AI_RESEARCH_SWAP_MARKET_SCOPE = ",".join(AI_RESEARCH_SWAP_SYMBOLS)


def normalize_agent_market_type(market_type: str | None = None) -> str:
    """Normalize AI Lab research market type."""
    value = str(market_type or "spot").strip().lower()
    if value in {"swap", "contract", "futures", "perpetual", "perp"}:
        return "swap"
    return "spot"


def default_agent_symbols_for_market(market_type: str | None = None) -> List[str]:
    return list(AI_RESEARCH_SWAP_SYMBOLS if normalize_agent_market_type(market_type) == "swap" else AI_RESEARCH_SPOT_SYMBOLS)


def default_agent_scope_for_market(market_type: str | None = None) -> str:
    return ",".join(default_agent_symbols_for_market(market_type))


def normalize_agent_symbol_scope(
    symbol: str | None = None,
    symbols: Optional[List[str]] = None,
    market_type: str | None = None,
) -> List[str]:
    """Normalize an AI research market scope into an ordered unique symbol list."""
    out: List[str] = []
    raw_items: List[str] = []
    if symbols:
        raw_items.extend(str(s) for s in symbols)
    if symbol:
        raw_items.extend(str(symbol).split(","))

    for raw in raw_items:
        item = str(raw or "").strip()
        if item and item not in out:
            out.append(item)
    return out or default_agent_symbols_for_market(market_type)


# ============================================
# 目标准则
# ============================================

@dataclass
class GoalCriteria:
    """用户设定的策略绩效目标 (硬性阈值)"""
    min_sharpe_ratio: float = 1.2
    max_drawdown_pct: float = 5.0
    min_win_rate_pct: float = 55.0
    min_total_return_pct: float = 30.0
    min_total_trades: int = 30
    min_profit_factor: float = 1.25

    def check(self, metrics: Dict[str, Any]) -> bool:
        return (
            metrics.get("sharpe_ratio", 0) >= self.min_sharpe_ratio
            and metrics.get("max_drawdown_pct", 100) <= self.max_drawdown_pct
            and metrics.get("win_rate_pct", 0) >= self.min_win_rate_pct
            and metrics.get("total_return_pct", 0) >= self.min_total_return_pct
            and metrics.get("total_trades", 0) >= self.min_total_trades
            and metrics.get("profit_factor", 0) >= self.min_profit_factor
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_sharpe_ratio": self.min_sharpe_ratio,
            "max_drawdown_pct": self.max_drawdown_pct,
            "min_win_rate_pct": self.min_win_rate_pct,
            "min_total_return_pct": self.min_total_return_pct,
            "min_total_trades": self.min_total_trades,
            "min_profit_factor": self.min_profit_factor,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GoalCriteria":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ============================================
# Evaluator 多维度评分
# ============================================

@dataclass
class EvalScores:
    """
    独立 Evaluator 的多维度评分体系 (借鉴 Anthropic 前端设计评分维度)
    每个维度 0-100 分, 加权汇总为 total_score
    """
    risk_control: float = 0.0       # 风控质量: 回撤控制、止损逻辑、仓位管理
    profitability: float = 0.0      # 盈利能力: 收益率、夏普比率、盈亏比
    robustness: float = 0.0         # 稳健性: 胜率、连续亏损、收益曲线平滑度
    strategy_logic: float = 0.0     # 策略逻辑: 代码质量、信号合理性、过拟合风险
    originality: float = 0.0        # 原创性: 避免简单均线交叉等"AI 模板策略"

    # 权重分配 (文章强调: 重点权重放在差异化维度上)
    WEIGHTS = {
        "risk_control": 0.25,
        "profitability": 0.25,
        "robustness": 0.20,
        "strategy_logic": 0.15,
        "originality": 0.15,
    }

    @property
    def total_score(self) -> float:
        return round(
            self.risk_control * self.WEIGHTS["risk_control"]
            + self.profitability * self.WEIGHTS["profitability"]
            + self.robustness * self.WEIGHTS["robustness"]
            + self.strategy_logic * self.WEIGHTS["strategy_logic"]
            + self.originality * self.WEIGHTS["originality"],
            1,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_control": self.risk_control,
            "profitability": self.profitability,
            "robustness": self.robustness,
            "strategy_logic": self.strategy_logic,
            "originality": self.originality,
            "total_score": self.total_score,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvalScores":
        return cls(**{
            k: d[k] for k in ("risk_control", "profitability", "robustness",
                               "strategy_logic", "originality")
            if k in d
        })


# ============================================
# Sprint 合约
# ============================================

@dataclass
class SprintContract:
    """
    Sprint 合约: Strategist 和 Evaluator 在生成前协商的验收标准
    借鉴文章中 "generator 和 evaluator 协商 sprint contract" 机制
    """
    strategy_direction: str = ""      # 策略方向: 如 "动量突破", "均值回归"
    key_indicators: List[str] = field(default_factory=list)
    entry_logic_desc: str = ""        # 进场逻辑描述
    exit_logic_desc: str = ""         # 出场逻辑描述
    risk_management_desc: str = ""    # 风控描述
    acceptance_criteria: List[str] = field(default_factory=list)
    action: str = "new"               # "new" | "refine" | "pivot"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_direction": self.strategy_direction,
            "key_indicators": self.key_indicators,
            "entry_logic_desc": self.entry_logic_desc,
            "exit_logic_desc": self.exit_logic_desc,
            "risk_management_desc": self.risk_management_desc,
            "acceptance_criteria": self.acceptance_criteria,
            "action": self.action,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SprintContract":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ============================================
# Planner 输出: 策略规格书
# ============================================

@dataclass
class StrategySpec:
    """Planner 生成的策略规格书 (高层设计, 不含具体实现)"""
    market_analysis: str = ""         # 市场环境分析
    strategy_candidates: List[Dict[str, str]] = field(default_factory=list)
    recommended_approach: str = ""    # 推荐的策略方向
    risk_considerations: str = ""     # 风险注意事项
    iteration_plan: str = ""          # 迭代计划建议

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_analysis": self.market_analysis,
            "strategy_candidates": self.strategy_candidates,
            "recommended_approach": self.recommended_approach,
            "risk_considerations": self.risk_considerations,
            "iteration_plan": self.iteration_plan,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "StrategySpec":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ============================================
# 单轮迭代记录 (v2 — 增加合约和多维评分)
# ============================================

@dataclass
class IterationRecord:
    """一轮 Agent 迭代的完整记录"""
    iteration: int
    strategy_name: str = ""
    strategy_code: str = ""
    reasoning: str = ""
    backtest_metrics: Dict[str, Any] = field(default_factory=dict)
    # v2: 独立 Evaluator 多维评分
    eval_scores: Optional[EvalScores] = None
    analysis: str = ""
    suggestions: List[str] = field(default_factory=list)
    score: float = 0.0
    meets_goal: bool = False
    error: str = ""
    created_at: str = ""
    # v2: Sprint 合约 + 方向决策
    contract: Optional[SprintContract] = None
    action: str = "new"               # "new" | "refine" | "pivot"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration": self.iteration,
            "strategy_name": self.strategy_name,
            "strategy_code": self.strategy_code,
            "reasoning": self.reasoning,
            "backtest_metrics": self.backtest_metrics,
            "eval_scores": self.eval_scores.to_dict() if self.eval_scores else None,
            "analysis": self.analysis,
            "suggestions": self.suggestions,
            "score": self.score,
            "meets_goal": self.meets_goal,
            "error": self.error,
            "created_at": self.created_at,
            "contract": self.contract.to_dict() if self.contract else None,
            "action": self.action,
        }


# ============================================
# Agent 任务 (v2 — 增加 Planner 规格书)
# ============================================

@dataclass
class AgentTask:
    """一个 Agent 协同任务"""
    task_id: str
    status: str = "pending"
    stage: str = "planner"
    stage_label: str = "等待 Planner 生成规格书"
    goal: GoalCriteria = field(default_factory=GoalCriteria)
    market_type: str = "spot"
    symbol: str = AI_RESEARCH_MARKET_SCOPE
    timeframe: str = "15m"
    backtest_start: str = "2024-01-01"
    backtest_end: str = "2025-12-31"
    max_iterations: int = 10
    current_iteration: int = 0
    iterations: List[IterationRecord] = field(default_factory=list)
    best_iteration: Optional[int] = None
    created_at: str = ""
    updated_at: str = ""
    user_prompt: str = ""
    llm_model: str = ""
    # v2: Planner 输出
    strategy_spec: Optional[StrategySpec] = None

    @property
    def best_record(self) -> Optional[IterationRecord]:
        if self.best_iteration is not None and self.best_iteration < len(self.iterations):
            return self.iterations[self.best_iteration]
        return None


# ============================================
# API 请求/响应模型 (Pydantic)
# ============================================

class CreateTaskRequest(BaseModel):
    market_type: str = "spot"
    symbol: str = ""
    symbols: Optional[List[str]] = None
    timeframe: str = "15m"
    backtest_start: str = "2024-01-01"
    backtest_end: str = "2025-12-31"
    max_iterations: int = 10
    user_prompt: str = ""
    llm_model: Optional[str] = None
    goal: Optional[Dict[str, Any]] = None


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    stage: str = ""
    stage_label: str = ""
    market_type: str = "spot"
    symbol: str
    timeframe: str
    current_iteration: int
    max_iterations: int
    best_iteration: Optional[int] = None
    best_score: Optional[float] = None
    best_metrics: Optional[Dict[str, Any]] = None
    llm_model: str = ""
    strategy_spec: Optional[Dict[str, Any]] = None
    created_at: str
    updated_at: str


class IterationResponse(BaseModel):
    iteration: int
    strategy_name: str
    strategy_code: str
    reasoning: str
    backtest_metrics: Dict[str, Any]
    eval_scores: Optional[Dict[str, Any]] = None
    analysis: str
    suggestions: List[str]
    score: float
    meets_goal: bool
    error: str = ""
    created_at: str
    contract: Optional[Dict[str, Any]] = None
    action: str = "new"
