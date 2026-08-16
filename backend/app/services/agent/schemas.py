"""AI 策略研发数据模型：目标准则、评分、合约、规格书、迭代记录与任务。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GoalCriteria:
    """用户设定的策略绩效目标（硬性阈值，映射 StockPro 回测指标码）。"""

    min_sharpe: float = 0.5
    max_drawdown: float = 0.15
    min_win_rate: float = 0.40
    min_return: float = 0.02
    min_trades: int = 5
    min_profit_loss_ratio: float = 1.0

    def check(self, metrics: Dict[str, Any]) -> bool:
        def value(code: str) -> Optional[float]:
            raw = metrics.get(code)
            return float(raw) if raw is not None else None

        sharpe = value("sharpe")
        drawdown = value("maximum_drawdown")
        win_rate = value("win_rate")
        total_return = value("strategy_return")
        trades = value("completed_trades")
        profit_loss = value("profit_loss_ratio")
        return bool(
            sharpe is not None and sharpe >= self.min_sharpe
            and drawdown is not None and drawdown <= self.max_drawdown
            and win_rate is not None and win_rate >= self.min_win_rate
            and total_return is not None and total_return >= self.min_return
            and trades is not None and trades >= self.min_trades
            and profit_loss is not None and profit_loss >= self.min_profit_loss_ratio
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_sharpe": self.min_sharpe,
            "max_drawdown": self.max_drawdown,
            "min_win_rate": self.min_win_rate,
            "min_return": self.min_return,
            "min_trades": self.min_trades,
            "min_profit_loss_ratio": self.min_profit_loss_ratio,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GoalCriteria":
        defaults = cls()
        merged: Dict[str, Any] = {}
        for key, value in (data or {}).items():
            if key not in defaults.__dataclass_fields__:
                continue
            try:
                merged[key] = float(value) if key != "min_trades" else int(value)
            except (TypeError, ValueError):
                continue
        return cls(**merged)


@dataclass
class EvalScores:
    """Evaluator 多维度评分（0-100，加权汇总）。"""

    risk_control: float = 0.0
    profitability: float = 0.0
    robustness: float = 0.0
    strategy_logic: float = 0.0
    originality: float = 0.0

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
            "risk_control": round(self.risk_control, 1),
            "profitability": round(self.profitability, 1),
            "robustness": round(self.robustness, 1),
            "strategy_logic": round(self.strategy_logic, 1),
            "originality": round(self.originality, 1),
            "total_score": self.total_score,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvalScores":
        scores = {}
        for key in ("risk_control", "profitability", "robustness", "strategy_logic", "originality"):
            raw = (data or {}).get(key)
            if raw is None:
                continue
            try:
                scores[key] = max(0.0, min(100.0, float(raw)))
            except (TypeError, ValueError):
                continue
        return cls(**scores)


@dataclass
class SprintContract:
    """每轮迭代前协商的验收合约（方向、逻辑与验收标准）。"""

    strategy_direction: str = ""
    key_indicators: List[str] = field(default_factory=list)
    entry_logic_desc: str = ""
    exit_logic_desc: str = ""
    risk_management_desc: str = ""
    acceptance_criteria: List[str] = field(default_factory=list)
    action: str = "new"

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
    def from_dict(cls, data: Dict[str, Any]) -> "SprintContract":
        return cls(**{k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__})


@dataclass
class StrategySpec:
    """Planner 生成的策略规格书（高层设计，不含实现）。"""

    market_analysis: str = ""
    strategy_candidates: List[Dict[str, str]] = field(default_factory=list)
    recommended_approach: str = ""
    risk_considerations: str = ""
    iteration_plan: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_analysis": self.market_analysis,
            "strategy_candidates": self.strategy_candidates,
            "recommended_approach": self.recommended_approach,
            "risk_considerations": self.risk_considerations,
            "iteration_plan": self.iteration_plan,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategySpec":
        return cls(**{k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__})


@dataclass
class IterationRecord:
    """一轮迭代的完整记录。"""

    iteration: int
    strategy_name: str = ""
    strategy_code: str = ""
    reasoning: str = ""
    strategy_version_id: Optional[str] = None
    sandbox_report: Optional[Dict[str, Any]] = None
    backtest_run_id: Optional[str] = None
    backtest_metrics: Dict[str, Any] = field(default_factory=dict)
    eval_scores: Optional[EvalScores] = None
    analysis: str = ""
    suggestions: List[str] = field(default_factory=list)
    score: float = 0.0
    meets_goal: bool = False
    error: str = ""
    created_at: str = ""
    contract: Optional[SprintContract] = None
    action: str = "new"
    next_action: str = "refine"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration": self.iteration,
            "strategy_name": self.strategy_name,
            "strategy_code": self.strategy_code,
            "reasoning": self.reasoning,
            "strategy_version_id": self.strategy_version_id,
            "sandbox_report": self.sandbox_report,
            "backtest_run_id": self.backtest_run_id,
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
            "next_action": self.next_action,
        }


@dataclass
class AgentTask:
    """一个 AI 策略研发任务。"""

    task_id: str
    name: str = ""
    status: str = "pending"
    stage: str = "planner"
    stage_label: str = "等待 Planner 生成规格书"
    goal: GoalCriteria = field(default_factory=GoalCriteria)
    research_config: Dict[str, Any] = field(default_factory=dict)
    strategy_spec: Optional[StrategySpec] = None
    max_iterations: int = 6
    current_iteration: int = 0
    iterations: List[IterationRecord] = field(default_factory=list)
    best_iteration: Optional[int] = None
    user_prompt: str = ""
    llm_model: str = ""
    promoted_strategy_version_id: Optional[str] = None
    error_message: str = ""
    created_at: str = ""
    updated_at: str = ""

    @property
    def best_record(self) -> Optional[IterationRecord]:
        if self.best_iteration is not None and 0 <= self.best_iteration < len(self.iterations):
            return self.iterations[self.best_iteration]
        return None
