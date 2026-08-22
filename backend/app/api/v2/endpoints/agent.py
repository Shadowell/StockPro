"""
Agent 系统 API 端点 (v2)
Multi-Agent 量化策略协同系统
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException
from pydantic import BaseModel, Field

from app.db.local_db import db_instance as db
from app.services.agent.schemas import (
    AgentTask, GoalCriteria, IterationRecord, StrategySpec,
    SprintContract, EvalScores,
    CreateTaskRequest, TaskStatusResponse, IterationResponse,
    default_agent_scope_for_market, normalize_agent_market_type,
    normalize_agent_symbol_scope,
)
from app.services.agent.orchestrator import orchestrator
from app.services.agent.llm_client import (
    describe_qwen_exception,
    get_llm_model_config,
    get_qwen_client,
    has_agent_api_key,
    validate_llm_model_name,
)
from app.services.agent.ai_strategy_assistant import (
    DEFAULT_AUTO_RESEARCH_SYMBOLS,
    AiStrategyAssistantCycle,
    AutoAgentBacktestScenario,
    AutoAgentClosedLoopConfig,
    MarketSnapshot,
    assistant_blueprint,
    collect_public_market_snapshots,
)
from app.services.backtrader_engine import backtrader_engine
from app.services.strategy_registry import get_base_strategy_registry
from app.services.agent.prompts import build_prompt_optimizer_messages
from app.services.contract_paper_account import normalize_contract_symbol
from app.services.strategy_engine import strategy_engine
from app.services.strategy_log_store import strategy_log_store
from app.services.strategy_optimizer_service import strategy_optimizer_service

logger = logging.getLogger(__name__)

router = APIRouter()
AUTONOMOUS_MAX_LEVERAGE_CAP = 20.0
AUTONOMOUS_MAX_TOTAL_EXPOSURE_PCT = 500.0
AUTONOMOUS_DEFAULT_MAX_SINGLE_POSITION_PCT = 60.0
AUTONOMOUS_DEFAULT_MAX_TOTAL_EXPOSURE_PCT = 360.0
AUTONOMOUS_DEFAULT_MAX_POSITIONS = 6
AUTONOMOUS_DEFAULT_MIN_ORDER_NOTIONAL_USDT = 50.0
AUTONOMOUS_DEFAULT_SYMBOLS = list(DEFAULT_AUTO_RESEARCH_SYMBOLS)
AUTONOMOUS_DEFAULT_SCOPE_LABEL = "Top30"
DEFAULT_PAPER_STRATEGY_INITIAL_CAPITAL = 100.0
AUTONOMOUS_DEFAULT_DECISION_LEVERAGE = 5.0
AUTO_AGENT_RESEARCH_RUNS_KEY = "auto_agent_research_runs"
AUTO_AGENT_RESEARCH_SCHEDULER_KEY = "auto_agent_research_scheduler"
AUTO_AGENT_RESEARCH_MAX_STORED = 30
AUTONOMOUS_HERMES_MODEL = "gpt-5.5"
AUTONOMOUS_HERMES_DISPLAY_NAME = "Hermes/Codex"
AUTONOMOUS_DEFAULT_OPERATOR_PROMPT = "\n".join(
    [
        "通过 Hermes 调用 Codex，只做 OKX USDT 永续合约模拟盘，禁止实盘、禁止真实账户、禁止任何真实下单建议。",
        "目标是在严格 paper 风控内提升模拟盘净收益：允许 open_long/open_short/close_long/close_short/close_all/hold，多空双向选择，不固定 K 线周期，由模型根据行情强弱、波动和流动性决定观察窗口。",
        "优先从系统 Top30 候选中选择强弱分化清晰、成交活跃、盘口和成交量足够、波动率能覆盖手续费与滑点的标的；避开流动性差、价差大、方向混乱、连续假突破或消息噪音过强的标的。",
        "无持仓且候选信号有优势时，不要长期观望；杠杆必须在 5-10x 默认范围内由 AI 自主决定杠杆，仓位比例也由 AI 根据信号强度、波动、止损空间和流动性自行决定：弱信号小仓位试单，强信号可接近系统单笔上限，并严格遵守系统 max_leverage、max_single_position_pct、max_total_exposure_pct、max_positions、max_trades_per_hour 和 min_order_notional_usdt；默认最多 6 个持仓，最小开仓名义 50U。",
        "做多优先选择相对强势、上行动量、突破后回踩确认或空头衰竭的标的；做空优先选择相对弱势、下行动量、跌破支撑、反弹失败或多头衰竭的标的。",
        "持仓后主动管理：优势消失、反向信号、波动失控或亏损扩大时及时减仓/平仓；盈利后保护浮盈，不为了追涨杀跌扩大仓位。",
        "每次决策必须用中文 reason 说明标的选择、方向、观察窗口、风险和下一次检查间隔。",
    ]
)
AUTONOMOUS_HERMES_PROVIDER_ALIASES = {
    "hermes",
    "grok",
    "codex",
    "xai",
    "xai-oauth",
    "xai_oauth",
    "openai-codex",
    "openai_codex",
    "hermes-codex",
    "hermes/codex",
    "hermes-grok",
    "hermes/grok",
}
AUTONOMOUS_LLM_PROVIDERS = {"dashscope", "qwen", *AUTONOMOUS_HERMES_PROVIDER_ALIASES}
AUTONOMOUS_TRADE_DIRECTIONS = {"long_short", "long-short", "both", "short_only", "short-only", "short"}
AUTO_AGENT_BUILTIN_OBJECTIVE = (
    "自动定时扫描 OKX 高流动性永续合约市场，先用公开行情识别值得研究的 15m/30m 策略级机会，"
    f"允许多空双向候选，再调用服务器 {AUTONOMOUS_HERMES_DISPLAY_NAME} 继续研究并运行安全回测矩阵。严格边界：只允许 research/backtest/paper-simulation，"
    "不得连接 OKX 私有接口，不得自动实盘下单，不得根据缺失行情编造机会；若数据不足，输出等待/跳过。"
)
_auto_agent_research_runners: Dict[str, asyncio.Task] = {}


def _run_auto_agent_backtest_scenario(
    scenario: AutoAgentBacktestScenario,
    cfg: AutoAgentClosedLoopConfig,
) -> Dict[str, Any]:
    """Run one safe BaseStrategy backtest for the auto-agent closed-loop report."""

    registry = get_base_strategy_registry()
    strategy_class = registry.get(scenario.strategy_key)
    if strategy_class is None:
        raise ValueError(f"策略 {scenario.strategy_key} 未注册，不能进入候选报告")
    report = backtrader_engine.run_strategy(
        strategy_class=strategy_class,
        exchange="okx",
        symbol=scenario.symbol,
        timeframe=scenario.timeframe,
        start_date=scenario.start_date,
        end_date=scenario.end_date,
        initial_capital=cfg.initial_capital,
        commission=cfg.commission,
        slippage=cfg.slippage,
        strategy_config=scenario.config,
    )
    return {
        "total_return_pct": report.total_return_pct,
        "max_drawdown_pct": report.max_drawdown_pct,
        "sharpe_ratio": report.sharpe_ratio,
        "win_rate_pct": report.win_rate_pct,
        "profit_factor": report.profit_factor,
        "total_trades": report.total_trades,
    }


class StrategyOptimizerConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    interval_hours: Optional[float] = None
    low_return_pct: Optional[float] = None
    trial_hours: Optional[float] = None
    trial_success_return_pct: Optional[float] = None
    llm_model: Optional[str] = None


class PromptOptimizeRequest(BaseModel):
    manual_prompt: str = ""
    current_prompt: str = ""
    market_type: str = "spot"
    llm_model: Optional[str] = None
    goal: Optional[Dict[str, Any]] = None


class StrategyOptimizerRunNowRequest(BaseModel):
    llm_model: Optional[str] = None


class StrategyAssistantSnapshotRequest(BaseModel):
    symbol: str
    quote_volume_24h: float = 0.0
    spread_bps: float = 999.0
    depth_usdt: float = 0.0
    change_1h_pct: float = 0.0
    change_4h_pct: float = 0.0
    atr_pct: float = 0.0
    adx: float = 0.0
    ema_gap_bps: float = 0.0
    funding_rate: float = 0.0


class StrategyAssistantRunRequest(BaseModel):
    objective: str = "寻找 OKX 高流动性交易机会，先完成 paper/simulation 验证"
    snapshots: List[StrategyAssistantSnapshotRequest] = Field(default_factory=list)
    max_candidates: int = 5
    use_hermes_agent: bool = False
    auto_collect_market: bool = False
    symbols: List[str] = Field(default_factory=list)
    preferred_direction: str = "auto"


class AutoAgentSchedulerConfigRequest(BaseModel):
    enabled: bool = True
    interval_minutes: int = 60
    symbols: List[str] = Field(default_factory=list)
    use_hermes_agent: bool = True
    max_candidates: int = 5
    preferred_direction: str = "auto"


class OrbitAutoPostConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    account_id: Optional[str] = None
    interval_minutes: Optional[int] = None
    min_margin_roi_pct: Optional[float] = None
    max_posts_per_run: Optional[int] = None
    cooldown_hours: Optional[float] = None
    max_posts_per_day: Optional[int] = None
    copy_style: Optional[str] = None
    llm_model: Optional[str] = None


class OrbitAutoPostPublishRequest(BaseModel):
    candidate: Dict[str, Any]


class AutonomousTraderStartRequest(BaseModel):
    symbols: List[str] = Field(default_factory=lambda: list(AUTONOMOUS_DEFAULT_SYMBOLS))
    restrict_symbols: bool = False
    operator_prompt: Optional[str] = None
    llm_provider: str = "hermes"
    llm_model: Optional[str] = None
    trade_direction: str = "long_short"
    max_leverage_cap: float = 10.0
    max_single_position_pct: float = AUTONOMOUS_DEFAULT_MAX_SINGLE_POSITION_PCT
    max_total_exposure_pct: float = AUTONOMOUS_DEFAULT_MAX_TOTAL_EXPOSURE_PCT
    max_positions: int = AUTONOMOUS_DEFAULT_MAX_POSITIONS
    min_decision_interval_sec: float = 30.0
    max_decision_interval_sec: Optional[float] = None
    max_trades_per_hour: int = 6
    probe_size_pct: Optional[float] = None
    initial_capital: float = DEFAULT_PAPER_STRATEGY_INITIAL_CAPITAL


class AutonomousTraderConfigUpdateRequest(BaseModel):
    symbols: Optional[List[str]] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    trade_direction: Optional[str] = None
    operator_prompt: Optional[str] = None
    restrict_symbols: Optional[bool] = None
    max_leverage_cap: Optional[float] = None
    min_decision_leverage: Optional[float] = None
    default_decision_leverage: Optional[float] = None
    max_single_position_pct: Optional[float] = None
    max_total_exposure_pct: Optional[float] = None
    max_positions: Optional[int] = None
    min_decision_interval_sec: Optional[float] = None
    max_decision_interval_sec: Optional[float] = None
    max_trades_per_hour: Optional[int] = None
    probe_size_pct: Optional[float] = None
    initial_capital: Optional[float] = None


def _select_llm_model(model: Optional[str] = None) -> str:
    if model:
        try:
            return validate_llm_model_name(model)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return str(get_llm_model_config().get("model") or "").strip()


def _normalize_autonomous_llm_provider(raw: Any) -> str:
    normalized = str(raw or "dashscope").strip().lower().replace("_", "-")
    if normalized not in AUTONOMOUS_LLM_PROVIDERS:
        raise HTTPException(400, "AI模型提供方只支持 dashscope 或 hermes")
    return "hermes" if normalized in AUTONOMOUS_HERMES_PROVIDER_ALIASES else "dashscope"


def _normalize_autonomous_trade_direction(raw: Any) -> str:
    normalized = str(raw or "long_short").strip().lower().replace("-", "_")
    if normalized not in {item.replace("-", "_") for item in AUTONOMOUS_TRADE_DIRECTIONS}:
        raise HTTPException(400, "交易方向只支持 long_short 或 short_only")
    return "short_only" if normalized in {"short_only", "short"} else "long_short"


def _normalize_auto_agent_preferred_direction(raw: Any) -> str:
    normalized = str(raw or "auto").strip().lower().replace("-", "_")
    if normalized in {"long", "short"}:
        return normalized
    return "auto"


# ============================================
# 持久化回调
# ============================================

async def _persist_iteration(task: AgentTask, record: IterationRecord):
    try:
        _save_agent_task_state(task)
        db.save_agent_iteration(task.task_id, record.to_dict())
    except Exception as e:
        logger.warning("Agent 持久化失败: %s", e)


orchestrator.set_on_iteration(_persist_iteration)
orchestrator.set_on_task_update(lambda task: asyncio.to_thread(_save_agent_task_state, task))


def _save_agent_task_state(task: AgentTask):
    db.save_agent_task(_agent_task_payload(task))


def _agent_task_payload(task: AgentTask) -> Dict[str, Any]:
    return {
        "id": task.task_id,
        "status": task.status,
        "stage": task.stage,
        "stage_label": task.stage_label,
        "goal_criteria": task.goal.to_dict(),
        "market_type": task.market_type,
        "symbol": task.symbol,
        "timeframe": task.timeframe,
        "backtest_start": task.backtest_start,
        "backtest_end": task.backtest_end,
        "max_iterations": task.max_iterations,
        "current_iteration": task.current_iteration,
        "best_iteration": task.best_iteration,
        "user_prompt": task.user_prompt,
        "llm_model": task.llm_model,
        "strategy_spec": task.strategy_spec.to_dict() if task.strategy_spec else None,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


# ============================================
# 后台任务执行
# ============================================

async def _run_task_background(task_id: str):
    try:
        task = await orchestrator.run_task(task_id)
        _save_agent_task_state(task)
        logger.info("Agent 任务 %s 已完成, 状态: %s", task_id, task.status)
    except asyncio.CancelledError:
        task = orchestrator.get_task(task_id)
        if task:
            task.status = "stopped"
            _save_agent_task_state(task)
        logger.info("Agent 任务 %s 已被用户停止", task_id)
    except Exception as e:
        logger.exception("Agent 任务 %s 执行失败", task_id)
        task = orchestrator.get_task(task_id)
        if task:
            task.status = "failed"
            _save_agent_task_state(task)
    finally:
        orchestrator.clear_runner(task_id)


def _resume_persisted_task(db_task: Dict[str, Any], stage_label: str) -> Dict[str, Any]:
    task = _task_from_db(db_task)
    existing = orchestrator.get_task(task.task_id)
    if existing and existing.status in {"pending", "running"}:
        return {"task_id": task.task_id, "status": existing.status, "message": "任务已在运行中"}

    if len(task.iterations) >= task.max_iterations:
        task.status = "completed"
        task.stage = "completed"
        task.stage_label = "策略研发已完成"
        task.updated_at = datetime.now().isoformat()
        _save_agent_task_state(task)
        return {"task_id": task.task_id, "status": "completed", "message": "任务已完成，无需继续"}

    task.status = "pending"
    task.stage = "planner_done" if task.strategy_spec else "planner"
    task.stage_label = stage_label
    task.updated_at = datetime.now().isoformat()
    orchestrator.register_task(task)
    _save_agent_task_state(task)

    runner = asyncio.create_task(_run_task_background(task.task_id))
    orchestrator.attach_runner(task.task_id, runner)

    return {
        "task_id": task.task_id,
        "status": task.status,
        "message": f"任务已从第 {len(task.iterations) + 1} 轮继续研发",
    }


async def auto_resume_interrupted_agent_tasks(updated_at: str, limit: int = 20) -> int:
    """Auto-resume only the Agent tasks that were interrupted during this startup."""
    if not has_agent_api_key():
        logger.warning("AI Lab 自动续跑跳过：DASHSCOPE_API_KEY 未配置")
        return 0

    resumed = 0
    for db_task in db.get_interrupted_agent_tasks(updated_at=updated_at, limit=limit):
        task_id = str(db_task.get("id") or db_task.get("task_id") or "")
        if not task_id:
            continue
        try:
            result = _resume_persisted_task(db_task, "服务重启后自动恢复，等待继续研发")
            if result.get("status") in {"pending", "running"}:
                resumed += 1
        except Exception as e:
            logger.exception("AI Lab 任务 %s 自动续跑失败: %s", task_id, e)
    if resumed:
        logger.info("Auto-resumed %d AI Lab task(s) after restart", resumed)
    return resumed


def _record_from_db(row: Dict[str, Any]) -> IterationRecord:
    eval_scores = row.get("eval_scores")
    contract = row.get("contract")
    return IterationRecord(
        iteration=int(row.get("iteration", 0)),
        strategy_name=str(row.get("strategy_name") or ""),
        strategy_code=str(row.get("strategy_code") or ""),
        reasoning=str(row.get("reasoning") or ""),
        backtest_metrics=row.get("backtest_metrics") or {},
        eval_scores=EvalScores.from_dict(eval_scores) if isinstance(eval_scores, dict) else None,
        analysis=str(row.get("analysis") or ""),
        suggestions=list(row.get("suggestions") or []),
        score=float(row.get("score") or 0),
        meets_goal=bool(row.get("meets_goal")),
        error=str(row.get("error") or ""),
        created_at=str(row.get("created_at") or ""),
        contract=SprintContract.from_dict(contract) if isinstance(contract, dict) else None,
        action=str(row.get("action") or "new"),
    )


def _task_from_db(row: Dict[str, Any]) -> AgentTask:
    task_id = str(row.get("id") or row.get("task_id") or "")
    spec = row.get("strategy_spec")
    market_type = normalize_agent_market_type(row.get("market_type"))
    task = AgentTask(
        task_id=task_id,
        status=str(row.get("status") or "pending"),
        stage=str(row.get("stage") or "planner"),
        stage_label=str(row.get("stage_label") or _agent_status_label(str(row.get("status") or ""))),
        goal=GoalCriteria.from_dict(row.get("goal_criteria") or row.get("goal") or {}),
        market_type=market_type,
        symbol=str(row.get("symbol") or default_agent_scope_for_market(market_type)),
        timeframe=str(row.get("timeframe") or "15m"),
        backtest_start=str(row.get("backtest_start") or ""),
        backtest_end=str(row.get("backtest_end") or ""),
        max_iterations=int(row.get("max_iterations") or 0),
        current_iteration=int(row.get("current_iteration") or 0),
        best_iteration=row.get("best_iteration"),
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or ""),
        user_prompt=str(row.get("user_prompt") or ""),
        llm_model=str(row.get("llm_model") or ""),
        strategy_spec=StrategySpec.from_dict(spec) if isinstance(spec, dict) else None,
    )
    records = [_record_from_db(item) for item in db.get_agent_iterations(task_id)]
    task.iterations = records
    stored_best = next(
        (r for r in records if task.best_iteration is not None and r.iteration == int(task.best_iteration)),
        None,
    )
    if task.best_iteration is None or not stored_best or not orchestrator._is_basic_candidate(stored_best):
        task.best_iteration = _best_iteration_from_records([r.to_dict() for r in records])
    return task


def _best_iteration_from_records(records: List[Dict[str, Any]]) -> Optional[int]:
    valid = [
        r for r in records
        if str(r.get("strategy_code") or "").strip()
        and not str(r.get("error") or "").strip()
        and not _candidate_quality_issues({}, r, strict_drawdown=False, strict_trades=False)
    ]
    if not valid:
        return None
    best = max(valid, key=lambda r: float(r.get("score") or 0))
    return int(best.get("iteration", 0))


def _record_dict_for_iteration(task_id: str, iteration: int) -> tuple[Dict[str, Any], Dict[str, Any]]:
    task_info = db.get_agent_task(task_id) or {}
    if not task_info:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    records = db.get_agent_iterations(task_id)
    record_data = next((r for r in records if int(r.get("iteration", -1)) == iteration), None)
    if not record_data:
        raise HTTPException(404, f"任务 {task_id} 第 {iteration + 1} 轮不存在")
    return task_info, record_data


def _save_iteration_strategy(
    task_id: str,
    iteration: int,
    task_info: Dict[str, Any],
    record_data: Dict[str, Any],
    name_prefix: str = "[AI猎手]",
    allow_low_quality: bool = False,
) -> Dict[str, Any]:
    strategy_code = str(record_data.get("strategy_code") or "")
    strategy_name = str(record_data.get("strategy_name") or f"AI策略第{iteration + 1}轮")
    if not strategy_code.strip():
        raise HTTPException(400, "该迭代没有可保存的策略代码")
    quality_issues = _candidate_quality_issues(task_info, record_data)
    if quality_issues and not allow_low_quality:
        raise HTTPException(400, f"候选策略未通过保存门槛: {'; '.join(quality_issues)}")
    quality_warning = ""
    if quality_issues:
        quality_warning = "\n保存风险: 未通过质量门槛: " + "; ".join(quality_issues)

    eval_scores = record_data.get("eval_scores")
    scores_text = ""
    if isinstance(eval_scores, dict):
        scores_text = (
            f"\n维度评分: 风控={float(eval_scores.get('risk_control', 0)):.0f} "
            f"盈利={float(eval_scores.get('profitability', 0)):.0f} "
            f"稳健={float(eval_scores.get('robustness', 0)):.0f} "
            f"逻辑={float(eval_scores.get('strategy_logic', 0)):.0f} "
            f"原创={float(eval_scores.get('originality', 0)):.0f}"
        )

    market_type = normalize_agent_market_type(task_info.get("market_type"))
    symbol = str(task_info.get("symbol") or default_agent_scope_for_market(market_type))
    symbols = normalize_agent_symbol_scope(symbol, market_type=market_type)
    timeframe = str(task_info.get("timeframe") or "")
    asset_prefix = _asset_prefix_for_market(market_type)
    saved_name = f"{asset_prefix} {name_prefix} {_strip_asset_prefix(strategy_name)} ({task_id}-{iteration + 1})"
    strategy_config = {
        "agent_task_id": task_id,
        "agent_iteration": iteration,
        "backtest_metrics": record_data.get("backtest_metrics") or {},
        "eval_scores": eval_scores,
        "timeframe": timeframe,
        "market_type": market_type,
        "is_paper_trading": True,
        "initial_capital": DEFAULT_PAPER_STRATEGY_INITIAL_CAPITAL,
        "ai_hunter_candidate": True,
        "low_quality_saved": bool(quality_issues),
        "quality_issues": quality_issues,
        "script_content_source": "db",
    }
    if market_type == "swap":
        strategy_config.update({
            "inst_type": "SWAP",
            "td_mode": "isolated",
            "position_mode": "long_short_mode",
            "settle_ccy": "USDT",
            "max_leverage": 5,
        })
    strategy_id = db.save_strategy(
        name=saved_name,
        description=(
            f"由 AI 策略猎手保存的候选策略 (任务 {task_id}, 第 {iteration + 1} 轮)\n"
            f"综合评分: {float(record_data.get('score') or 0):.0f}/100{scores_text}\n"
            f"{quality_warning}\n"
            f"设计思路: {record_data.get('reasoning') or ''}"
        ),
        script_content=strategy_code,
        config=strategy_config,
        exchange="okx",
        symbols=symbols,
    )

    return {
        "message": "候选策略已保存到数据库",
        "strategy_id": strategy_id,
        "strategy_name": saved_name,
    }


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _asset_prefix_for_market(market_type: str | None = None) -> str:
    return "[合约]" if normalize_agent_market_type(market_type) == "swap" else "[现货]"


def _strip_asset_prefix(name: str) -> str:
    value = str(name or "").strip()
    for prefix in ("[现货]", "[合约]"):
        if value.startswith(prefix):
            return value[len(prefix):].strip()
    return value


def _candidate_quality_issues(
    task_info: Dict[str, Any],
    record_data: Dict[str, Any],
    *,
    strict_drawdown: bool = True,
    strict_trades: bool = True,
) -> List[str]:
    metrics = record_data.get("backtest_metrics") or {}
    goal = GoalCriteria.from_dict(task_info.get("goal_criteria") or task_info.get("goal") or {})
    issues: List[str] = []

    if str(record_data.get("error") or "").strip():
        issues.append("回测或评估存在错误")
    if not str(record_data.get("strategy_code") or "").strip():
        issues.append("缺少可保存策略代码")

    total_return = _to_float(metrics.get("total_return_pct"))
    sharpe = _to_float(metrics.get("sharpe_ratio"))
    profit_factor = _to_float(metrics.get("profit_factor"))
    score = _to_float(record_data.get("score"))
    drawdown = _to_float(metrics.get("max_drawdown_pct"), 100.0)
    trades = _to_float(metrics.get("total_trades"))

    if total_return <= 0:
        issues.append("收益率未转正")
    if sharpe <= 0:
        issues.append("夏普比率未转正")
    if profit_factor < 1:
        issues.append("盈亏比低于1")
    if score < 50:
        issues.append("评分低于50")
    if strict_trades and trades < goal.min_total_trades:
        issues.append(f"交易数少于{goal.min_total_trades:g}")
    drawdown_limit = max(goal.max_drawdown_pct * 3.0, 15.0)
    if strict_drawdown and drawdown > drawdown_limit:
        issues.append(f"最大回撤超过{drawdown_limit:.1f}%")

    return issues


# ============================================
# API 端点
# ============================================

@router.post("/tasks", summary="创建 Agent 任务")
async def create_task(req: CreateTaskRequest):
    if not has_agent_api_key():
        raise HTTPException(400, "DASHSCOPE_API_KEY 未配置，请在 .env 中设置")

    req.llm_model = _select_llm_model(req.llm_model)
    task = orchestrator.create_task(req)

    _save_agent_task_state(task)

    runner = asyncio.create_task(_run_task_background(task.task_id))
    orchestrator.attach_runner(task.task_id, runner)

    return {
        "task_id": task.task_id,
        "status": task.status,
        "message": f"任务已创建并启动 (v2 多Agent架构)，最多迭代 {task.max_iterations} 轮",
    }


@router.get("/strategy-assistant/blueprint", summary="读取 AI 策略助手五 Agent 闭环蓝图")
async def get_strategy_assistant_blueprint():
    return {"success": True, "data": assistant_blueprint()}


@router.post("/strategy-assistant/run-local-cycle", summary="本地运行 AI 策略助手五 Agent 纸面闭环")
async def run_strategy_assistant_local_cycle(req: StrategyAssistantRunRequest):
    snapshots = [MarketSnapshot.from_dict(item.model_dump()) for item in req.snapshots]
    collected_symbols: List[str] = []
    if req.auto_collect_market and not snapshots:
        requested_symbols = [str(item or "").strip() for item in req.symbols if str(item or "").strip()]
        if not requested_symbols:
            requested_symbols = list(DEFAULT_AUTO_RESEARCH_SYMBOLS)
        snapshots = await collect_public_market_snapshots(requested_symbols)
        collected_symbols = [item.symbol for item in snapshots]
    result = AiStrategyAssistantCycle(backtest_runner=_run_auto_agent_backtest_scenario).run(
        objective=req.objective,
        snapshots=snapshots,
        max_candidates=max(1, min(int(req.max_candidates or 5), 20)),
        use_hermes_agent=bool(req.use_hermes_agent),
        preferred_direction=req.preferred_direction,
        run_closed_loop=True,
    )
    result["market_data_source"] = {
        "auto_collect_market": bool(req.auto_collect_market),
        "requested_symbols": [str(item or "").strip() for item in req.symbols if str(item or "").strip()],
        "collected_symbols": collected_symbols,
        "snapshots_count": len(snapshots),
    }
    return {"success": True, "data": result}




def _load_auto_agent_research_runs() -> Dict[str, Dict[str, Any]]:
    raw = db.get_app_setting(AUTO_AGENT_RESEARCH_RUNS_KEY, "{}") or "{}"
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _save_auto_agent_research_runs(runs: Dict[str, Dict[str, Any]]) -> None:
    ordered = sorted(runs.items(), key=lambda item: str(item[1].get("created_at") or ""), reverse=True)
    compact = dict(ordered[:AUTO_AGENT_RESEARCH_MAX_STORED])
    db.set_app_setting(AUTO_AGENT_RESEARCH_RUNS_KEY, json.dumps(compact, ensure_ascii=False))


def _save_auto_agent_research_run(run: Dict[str, Any]) -> Dict[str, Any]:
    runs = _load_auto_agent_research_runs()
    runs[str(run["run_id"])] = run
    _save_auto_agent_research_runs(runs)
    return run


def _default_auto_agent_scheduler_config() -> Dict[str, Any]:
    return {
        "enabled": False,
        "interval_minutes": 60,
        "symbols": list(DEFAULT_AUTO_RESEARCH_SYMBOLS),
        "use_hermes_agent": True,
        "max_candidates": 5,
        "preferred_direction": "auto",
        "last_run_at": None,
        "last_run_id": None,
        "last_error": "",
        "builtin_objective": AUTO_AGENT_BUILTIN_OBJECTIVE,
    }


def _load_auto_agent_scheduler_config() -> Dict[str, Any]:
    cfg = _default_auto_agent_scheduler_config()
    raw = db.get_app_setting(AUTO_AGENT_RESEARCH_SCHEDULER_KEY, "{}") or "{}"
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {}
    if isinstance(parsed, dict):
        cfg.update(parsed)
    cfg["enabled"] = bool(cfg.get("enabled"))
    cfg["interval_minutes"] = max(15, min(int(cfg.get("interval_minutes") or 60), 24 * 60))
    symbols = [str(item or "").strip() for item in (cfg.get("symbols") or []) if str(item or "").strip()]
    cfg["symbols"] = symbols or list(DEFAULT_AUTO_RESEARCH_SYMBOLS)
    cfg["use_hermes_agent"] = bool(cfg.get("use_hermes_agent", True))
    cfg["max_candidates"] = max(1, min(int(cfg.get("max_candidates") or 5), 20))
    cfg["preferred_direction"] = _normalize_auto_agent_preferred_direction(cfg.get("preferred_direction"))
    cfg["builtin_objective"] = AUTO_AGENT_BUILTIN_OBJECTIVE
    return cfg


def _save_auto_agent_scheduler_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _default_auto_agent_scheduler_config()
    normalized.update(cfg or {})
    normalized["enabled"] = bool(normalized.get("enabled"))
    normalized["interval_minutes"] = max(15, min(int(normalized.get("interval_minutes") or 60), 24 * 60))
    normalized["symbols"] = [str(item or "").strip() for item in (normalized.get("symbols") or []) if str(item or "").strip()] or list(DEFAULT_AUTO_RESEARCH_SYMBOLS)
    normalized["use_hermes_agent"] = bool(normalized.get("use_hermes_agent", True))
    normalized["max_candidates"] = max(1, min(int(normalized.get("max_candidates") or 5), 20))
    normalized["preferred_direction"] = _normalize_auto_agent_preferred_direction(normalized.get("preferred_direction"))
    normalized["builtin_objective"] = AUTO_AGENT_BUILTIN_OBJECTIVE
    db.set_app_setting(AUTO_AGENT_RESEARCH_SCHEDULER_KEY, json.dumps(normalized, ensure_ascii=False))
    return normalized


def _create_auto_agent_research_run(
    payload: Dict[str, Any],
    *,
    source: str = "manual",
    schedule_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not payload.get("objective"):
        payload["objective"] = AUTO_AGENT_BUILTIN_OBJECTIVE
    if not payload.get("auto_collect_market") and not payload.get("snapshots"):
        payload["auto_collect_market"] = True
    if not payload.get("symbols"):
        payload["symbols"] = list(DEFAULT_AUTO_RESEARCH_SYMBOLS)
    payload["use_hermes_agent"] = True if payload.get("use_hermes_agent") is None else bool(payload.get("use_hermes_agent"))
    run_id = f"auto-agent-{uuid.uuid4().hex[:10]}"
    now = datetime.now().isoformat()
    run = {
        "run_id": run_id,
        "status": "pending",
        "stage": "queued",
        "stage_label": "自动研发已入队；服务重启后会自动续跑",
        "request": payload,
        "result": None,
        "error": "",
        "source": source,
        "schedule_config": schedule_config,
        "created_at": now,
        "updated_at": now,
    }
    _save_auto_agent_research_run(run)
    _schedule_auto_agent_research_run(run_id)
    return run


def _get_auto_agent_research_run(run_id: str) -> Optional[Dict[str, Any]]:
    return _load_auto_agent_research_runs().get(str(run_id))


async def _execute_auto_agent_research_run(run_id: str) -> None:
    run = _get_auto_agent_research_run(run_id)
    if not run:
        return
    now = datetime.now().isoformat()
    run.update({"status": "running", "stage": "collecting_market", "stage_label": "正在采集公开行情并启动 Hermes 研发", "updated_at": now, "error": ""})
    _save_auto_agent_research_run(run)
    try:
        request = StrategyAssistantRunRequest(**(run.get("request") or {}))
        snapshots = [MarketSnapshot.from_dict(item.model_dump()) for item in request.snapshots]
        collected_symbols: List[str] = []
        if request.auto_collect_market and not snapshots:
            requested_symbols = [str(item or "").strip() for item in request.symbols if str(item or "").strip()]
            if not requested_symbols:
                requested_symbols = list(DEFAULT_AUTO_RESEARCH_SYMBOLS)
            snapshots = await collect_public_market_snapshots(requested_symbols)
            collected_symbols = [item.symbol for item in snapshots]
        run.update({"stage": "hermes_research", "stage_label": "正在调用服务器 Hermes Agent 继续研发", "updated_at": datetime.now().isoformat()})
        _save_auto_agent_research_run(run)
        run.update({"stage": "backtest_matrix", "stage_label": "正在运行安全回测矩阵并生成候选策略报告", "updated_at": datetime.now().isoformat()})
        _save_auto_agent_research_run(run)
        result = AiStrategyAssistantCycle(backtest_runner=_run_auto_agent_backtest_scenario).run(
            objective=request.objective,
            snapshots=snapshots,
            max_candidates=max(1, min(int(request.max_candidates or 5), 20)),
            use_hermes_agent=bool(request.use_hermes_agent),
            preferred_direction=request.preferred_direction,
            run_closed_loop=True,
        )
        result["market_data_source"] = {
            "auto_collect_market": bool(request.auto_collect_market),
            "requested_symbols": [str(item or "").strip() for item in request.symbols if str(item or "").strip()],
            "collected_symbols": collected_symbols,
            "snapshots_count": len(snapshots),
        }
        run.update({
            "status": "completed",
            "stage": "completed",
            "stage_label": "自动研发已完成，结果已持久化",
            "result": result,
            "updated_at": datetime.now().isoformat(),
            "completed_at": datetime.now().isoformat(),
        })
        _save_auto_agent_research_run(run)
    except Exception as e:
        logger.exception("自动交易Agent研发 run %s 执行失败", run_id)
        run.update({
            "status": "failed",
            "stage": "failed",
            "stage_label": "自动研发失败，可点击重新开始",
            "error": str(e),
            "updated_at": datetime.now().isoformat(),
        })
        _save_auto_agent_research_run(run)
    finally:
        _auto_agent_research_runners.pop(run_id, None)


def _schedule_auto_agent_research_run(run_id: str) -> bool:
    runner = _auto_agent_research_runners.get(run_id)
    if runner and not runner.done():
        return False
    task = asyncio.create_task(_execute_auto_agent_research_run(run_id))
    _auto_agent_research_runners[run_id] = task
    return True


async def auto_resume_auto_agent_research_runs(limit: int = 10) -> int:
    runs = _load_auto_agent_research_runs()
    resumed = 0
    for run_id, run in sorted(runs.items(), key=lambda item: str(item[1].get("updated_at") or ""), reverse=True):
        if resumed >= limit:
            break
        if run.get("status") in {"pending", "running"}:
            run.update({
                "status": "pending",
                "stage": "resume_queued",
                "stage_label": "服务重启后自动续跑，等待重新进入 Hermes 研发",
                "updated_at": datetime.now().isoformat(),
            })
            _save_auto_agent_research_run(run)
            _schedule_auto_agent_research_run(run_id)
            resumed += 1
    if resumed:
        logger.info("Auto-resumed %d auto-agent research run(s) after restart", resumed)
    return resumed


async def run_auto_agent_scheduled_scan_once(*, force: bool = False) -> Dict[str, Any]:
    cfg = _load_auto_agent_scheduler_config()
    now = datetime.now()
    if not cfg.get("enabled") and not force:
        return {"skipped": "disabled", "config": cfg}
    active = [task for task in _auto_agent_research_runners.values() if task and not task.done()]
    if active:
        return {"skipped": "research_already_running", "active_runs": len(active), "config": cfg}
    last_run_at = cfg.get("last_run_at")
    if last_run_at and not force:
        try:
            due_at = datetime.fromisoformat(str(last_run_at)) + timedelta(minutes=int(cfg["interval_minutes"]))
            if now < due_at:
                return {"skipped": "not_due", "next_run_at": due_at.isoformat(), "config": cfg}
        except Exception:
            pass
    payload = StrategyAssistantRunRequest(
        objective=AUTO_AGENT_BUILTIN_OBJECTIVE,
        snapshots=[],
        max_candidates=int(cfg.get("max_candidates") or 5),
        use_hermes_agent=bool(cfg.get("use_hermes_agent", True)),
        auto_collect_market=True,
        symbols=list(cfg.get("symbols") or DEFAULT_AUTO_RESEARCH_SYMBOLS),
        preferred_direction=str(cfg.get("preferred_direction") or "auto"),
    ).model_dump()
    run = _create_auto_agent_research_run(payload, source="scheduled", schedule_config=cfg)
    cfg.update({"last_run_at": now.isoformat(), "last_run_id": run["run_id"], "last_error": ""})
    _save_auto_agent_scheduler_config(cfg)
    return {"scheduled": True, "run_id": run["run_id"], "config": cfg}


@router.get("/strategy-assistant/scheduler", summary="读取自动交易Agent定时扫描配置")
async def get_strategy_assistant_scheduler_config():
    return {"success": True, "data": _load_auto_agent_scheduler_config()}


@router.put("/strategy-assistant/scheduler", summary="更新自动交易Agent定时扫描配置")
async def update_strategy_assistant_scheduler_config(req: AutoAgentSchedulerConfigRequest):
    cfg = _save_auto_agent_scheduler_config(req.model_dump())
    return {"success": True, "data": cfg}


@router.post("/strategy-assistant/scheduler/run-now", summary="立即触发一次自动交易Agent内置扫描")
async def run_strategy_assistant_scheduler_now():
    result = await run_auto_agent_scheduled_scan_once(force=True)
    return {"success": True, "data": result}


@router.get("/orbit-auto-post/config", summary="读取 OKX 星球自动发帖配置")
async def get_orbit_auto_post_config():
    from app.services.orbit_auto_post_service import orbit_auto_post_service

    return {"success": True, "data": orbit_auto_post_service.get_config()}


@router.put("/orbit-auto-post/config", summary="更新 OKX 星球自动发帖配置")
async def update_orbit_auto_post_config(req: OrbitAutoPostConfigRequest):
    from app.services.orbit_auto_post_service import orbit_auto_post_service

    cfg = orbit_auto_post_service.update_config(req.model_dump(exclude_unset=True))
    return {"success": True, "data": cfg}


@router.get("/orbit-auto-post/login-status", summary="读取 OKX Orbit Web 登录状态")
async def get_orbit_auto_post_login_status():
    from app.services.orbit_auto_post_service import orbit_auto_post_service

    return {"success": True, "data": await orbit_auto_post_service.login_status()}


@router.get("/orbit-auto-post/candidates", summary="预览可自动发布的实盘合约单")
async def list_orbit_auto_post_candidates():
    from app.services.orbit_auto_post_service import orbit_auto_post_service

    return {
        "success": True,
        "data": {
            "config": orbit_auto_post_service.get_config(),
            "candidates": await orbit_auto_post_service.preview_candidates(),
            "history": orbit_auto_post_service.list_history(limit=20),
        },
    }


@router.post("/orbit-auto-post/run-now", summary="立即执行一次 OKX 星球自动发帖扫描")
async def run_orbit_auto_post_now():
    from app.services.orbit_auto_post_service import orbit_auto_post_service

    return {"success": True, "data": await orbit_auto_post_service.run_once(force=True)}


@router.post("/orbit-auto-post/publish", summary="手动发布一个 OKX 星球候选合约单")
async def publish_orbit_auto_post_candidate(req: OrbitAutoPostPublishRequest):
    from app.services.orbit_auto_post_service import orbit_auto_post_service

    return {"success": True, "data": await orbit_auto_post_service.publish_candidate(req.candidate)}


@router.post("/strategy-assistant/research-runs", summary="启动可恢复的自动交易Agent研发任务")
async def start_strategy_assistant_research_run(req: StrategyAssistantRunRequest):
    run = _create_auto_agent_research_run(req.model_dump(), source="manual")
    return {"success": True, "data": run}


@router.get("/strategy-assistant/research-runs/{run_id}", summary="查看自动交易Agent研发任务状态")
async def get_strategy_assistant_research_run(run_id: str):
    run = _get_auto_agent_research_run(run_id)
    if not run:
        raise HTTPException(404, f"自动研发任务 {run_id} 不存在")
    runner = _auto_agent_research_runners.get(run_id)
    if runner and not runner.done() and run.get("status") not in {"completed", "failed"}:
        run = dict(run)
        run["runtime_active"] = True
    else:
        run = dict(run)
        run["runtime_active"] = False
    return {"success": True, "data": run}


@router.post("/strategy-assistant/research-runs/{run_id}/resume", summary="继续自动交易Agent研发任务")
async def resume_strategy_assistant_research_run(run_id: str):
    run = _get_auto_agent_research_run(run_id)
    if not run:
        raise HTTPException(404, f"自动研发任务 {run_id} 不存在")
    if run.get("status") in {"completed", "running", "pending"}:
        return {"success": True, "data": run}
    run.update({
        "status": "pending",
        "stage": "resume_queued",
        "stage_label": "已重新入队，等待自动续跑",
        "updated_at": datetime.now().isoformat(),
        "error": "",
    })
    _save_auto_agent_research_run(run)
    _schedule_auto_agent_research_run(run_id)
    return {"success": True, "data": run}


@router.post("/prompt/optimize", summary="AI 优化新策略研发提示词")
async def optimize_research_prompt(req: PromptOptimizeRequest):
    if not has_agent_api_key():
        raise HTTPException(400, "DASHSCOPE_API_KEY 未配置，请在 .env 中设置")

    manual_prompt = (req.manual_prompt or "").strip()
    current_prompt = (req.current_prompt or "").strip()
    if not manual_prompt and not current_prompt:
        raise HTTPException(400, "请输入人工提示词后再生成最终提示词")

    messages = build_prompt_optimizer_messages(
        manual_prompt=manual_prompt or current_prompt,
        current_prompt=current_prompt,
        market_type=req.market_type,
        goal=req.goal or {},
    )
    llm_model = _select_llm_model(req.llm_model)
    try:
        result = await get_qwen_client(llm_model).chat_json(
            messages,
            temperature=0.2,
            max_tokens=1800,
        )
    except Exception as e:
        logger.warning("AI Lab 提示词优化失败: %s", describe_qwen_exception(e))
        raise HTTPException(502, f"提示词优化失败: {describe_qwen_exception(e)}")

    optimized_prompt = str(
        result.get("optimized_prompt")
        or result.get("final_prompt")
        or result.get("prompt")
        or ""
    ).strip()
    if not optimized_prompt:
        raise HTTPException(502, "提示词优化失败: 模型未返回 optimized_prompt")

    return {
        "manual_prompt": manual_prompt,
        "optimized_prompt": optimized_prompt[:12000],
        "summary": str(result.get("summary") or "").strip(),
        "model": llm_model,
    }


def _normalize_autonomous_symbols(raw: List[str]) -> List[str]:
    items: List[str] = []
    seen = set()
    for item in raw or []:
        symbol = normalize_contract_symbol(str(item or "").strip())
        if not symbol:
            continue
        if symbol in seen:
            continue
        items.append(symbol)
        seen.add(symbol)
    return items or list(AUTONOMOUS_DEFAULT_SYMBOLS)


def _autonomous_symbol_scope_label(symbols: List[str], restrict_symbols: bool) -> str:
    if not restrict_symbols and symbols == AUTONOMOUS_DEFAULT_SYMBOLS:
        return AUTONOMOUS_DEFAULT_SCOPE_LABEL
    bases = [symbol.split("/", 1)[0] for symbol in symbols if symbol]
    if 0 < len(bases) <= 3:
        return "/".join(bases)
    return f"自选{len(bases)}"


def _has_autonomous_symbol_input(raw: List[str]) -> bool:
    return any(str(item or "").strip() for item in raw or [])


def _as_autonomous_fraction(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number > 1:
        number = number / 100.0
    return max(0.0, number)


def _validate_autonomous_request(req: AutonomousTraderStartRequest) -> None:
    llm_provider = _normalize_autonomous_llm_provider(req.llm_provider)
    _normalize_autonomous_trade_direction(req.trade_direction)
    if llm_provider != "hermes" and not has_agent_api_key():
        raise HTTPException(400, "DASHSCOPE_API_KEY 未配置，AI自主交易无法调用大模型")
    if req.llm_model:
        try:
            validate_llm_model_name(req.llm_model)
        except ValueError as e:
            raise HTTPException(400, str(e))
    if req.restrict_symbols and not _has_autonomous_symbol_input(req.symbols):
        raise HTTPException(400, "开启限制标的后必须填写合约标的池")
    if req.operator_prompt and len(req.operator_prompt.strip()) > 4000:
        raise HTTPException(400, "提示词不能超过 4000 字")
    if req.max_leverage_cap < 1 or req.max_leverage_cap > AUTONOMOUS_MAX_LEVERAGE_CAP:
        raise HTTPException(400, f"最大杠杆上限必须在 1x 到 {AUTONOMOUS_MAX_LEVERAGE_CAP:g}x 之间")
    if req.max_single_position_pct <= 0 or req.max_single_position_pct > 100:
        raise HTTPException(400, "单笔最大仓位上限必须在 0% 到 100% 之间")
    if req.max_total_exposure_pct <= 0 or req.max_total_exposure_pct > AUTONOMOUS_MAX_TOTAL_EXPOSURE_PCT:
        raise HTTPException(400, f"总风险敞口上限必须在 0% 到 {AUTONOMOUS_MAX_TOTAL_EXPOSURE_PCT:g}% 之间")
    if req.max_positions < 1 or req.max_positions > 20:
        raise HTTPException(400, "最多持仓数必须在 1 到 20 之间")
    if req.min_decision_interval_sec < 30:
        raise HTTPException(400, "最短决策间隔不能小于 30 秒")
    if req.max_decision_interval_sec is not None and req.max_decision_interval_sec < req.min_decision_interval_sec:
        raise HTTPException(400, "最长等待时间不能小于最短决策间隔")
    if req.max_trades_per_hour < 1 or req.max_trades_per_hour > 120:
        raise HTTPException(400, "每小时最大交易次数必须在 1 到 120 之间")
    if req.probe_size_pct is not None:
        probe_fraction = _as_autonomous_fraction(req.probe_size_pct, 0.08)
        single_fraction = _as_autonomous_fraction(
            req.max_single_position_pct,
            AUTONOMOUS_DEFAULT_MAX_SINGLE_POSITION_PCT / 100.0,
        )
        if probe_fraction <= 0:
            raise HTTPException(400, "试单仓位必须大于 0")
        if probe_fraction > single_fraction:
            raise HTTPException(400, "试单仓位不能超过单笔最大仓位上限")
    if req.initial_capital <= 0:
        raise HTTPException(400, "模拟盘初始资金必须大于 0")


def _validate_autonomous_config_update(
    row: Dict[str, Any],
    req: AutonomousTraderConfigUpdateRequest,
) -> tuple[Dict[str, Any], bool]:
    raw_updates = {
        key: value
        for key, value in req.model_dump(exclude_unset=True).items()
        if value is not None
    }
    if not raw_updates:
        raise HTTPException(400, "没有可更新的 AI自主交易配置")

    engine_status = strategy_engine.get_strategy_status(int(row["id"])) or {}
    runtime_status = str(engine_status.get("status") or row.get("status") or "").lower()
    active_runtime = runtime_status in {"pending", "running", "paused"}
    if "initial_capital" in raw_updates and active_runtime:
        raise HTTPException(400, "运行中的 AI自主交易实例不能修改初始资金，请先停止实例")

    config = dict(row.get("config") or {})
    if "llm_model" in raw_updates:
        model = str(raw_updates["llm_model"] or "").strip()
        if not model:
            raise HTTPException(400, "AI模型不能为空")
        try:
            config["llm_model"] = validate_llm_model_name(model)
        except ValueError as e:
            raise HTTPException(400, str(e))

    if "llm_provider" in raw_updates:
        config["llm_provider"] = _normalize_autonomous_llm_provider(raw_updates["llm_provider"])
        config["ai_provider"] = config["llm_provider"]

    if "trade_direction" in raw_updates:
        trade_direction = _normalize_autonomous_trade_direction(raw_updates["trade_direction"])
        config["trade_direction"] = trade_direction
        config["allow_long"] = trade_direction != "short_only"
        config["allow_short"] = True

    if "operator_prompt" in raw_updates:
        operator_prompt = str(raw_updates["operator_prompt"] or "").strip()
        if len(operator_prompt) > 4000:
            raise HTTPException(400, "提示词不能超过 4000 字")
        config["operator_prompt"] = operator_prompt

    if "restrict_symbols" in raw_updates:
        config["restrict_symbols"] = bool(raw_updates["restrict_symbols"])

    if "symbols" in raw_updates:
        raw_symbols = raw_updates["symbols"] or []
        if not _has_autonomous_symbol_input(raw_symbols) and bool(config.get("restrict_symbols")):
            raise HTTPException(400, "开启限制标的后必须填写合约标的池")
        symbols = _normalize_autonomous_symbols(raw_symbols) if _has_autonomous_symbol_input(raw_symbols) else list(AUTONOMOUS_DEFAULT_SYMBOLS)
        config["symbols"] = symbols
        config["trade_symbols"] = symbols
        config["contract_trade_symbols"] = symbols
    elif "restrict_symbols" in raw_updates and not bool(config.get("restrict_symbols")):
        symbols = list(AUTONOMOUS_DEFAULT_SYMBOLS)
        config["symbols"] = symbols
        config["trade_symbols"] = symbols
        config["contract_trade_symbols"] = symbols

    if "max_leverage_cap" in raw_updates:
        value = float(raw_updates["max_leverage_cap"])
        if value < 1 or value > AUTONOMOUS_MAX_LEVERAGE_CAP:
            raise HTTPException(400, f"最大杠杆上限必须在 1x 到 {AUTONOMOUS_MAX_LEVERAGE_CAP:g}x 之间")
        config["max_leverage_cap"] = value
        config["max_leverage"] = value

    if "min_decision_leverage" in raw_updates:
        value = float(raw_updates["min_decision_leverage"])
        if value < 1 or value > AUTONOMOUS_MAX_LEVERAGE_CAP:
            raise HTTPException(400, f"AI 决策杠杆下限必须在 1x 到 {AUTONOMOUS_MAX_LEVERAGE_CAP:g}x 之间")
        config["min_decision_leverage"] = value

    if "default_decision_leverage" in raw_updates:
        value = float(raw_updates["default_decision_leverage"])
        if value < 1 or value > AUTONOMOUS_MAX_LEVERAGE_CAP:
            raise HTTPException(400, f"AI 默认开仓杠杆必须在 1x 到 {AUTONOMOUS_MAX_LEVERAGE_CAP:g}x 之间")
        config["default_decision_leverage"] = value

    if "max_single_position_pct" in raw_updates:
        value = float(raw_updates["max_single_position_pct"])
        if value <= 0 or value > 100:
            raise HTTPException(400, "单笔最大仓位上限必须在 0% 到 100% 之间")
        config["max_single_position_pct"] = value

    if "max_total_exposure_pct" in raw_updates:
        value = float(raw_updates["max_total_exposure_pct"])
        if value <= 0 or value > AUTONOMOUS_MAX_TOTAL_EXPOSURE_PCT:
            raise HTTPException(400, f"总风险敞口上限必须在 0% 到 {AUTONOMOUS_MAX_TOTAL_EXPOSURE_PCT:g}% 之间")
        config["max_total_exposure_pct"] = value

    if "max_positions" in raw_updates:
        value = int(raw_updates["max_positions"])
        if value < 1 or value > 20:
            raise HTTPException(400, "最多持仓数必须在 1 到 20 之间")
        config["max_positions"] = value

    if "min_decision_interval_sec" in raw_updates:
        value = float(raw_updates["min_decision_interval_sec"])
        if value < 30:
            raise HTTPException(400, "最短决策间隔不能小于 30 秒")
        config["min_decision_interval_sec"] = value

    if "max_decision_interval_sec" in raw_updates:
        value = float(raw_updates["max_decision_interval_sec"])
        config["max_decision_interval_sec"] = value

    min_interval = float(config.get("min_decision_interval_sec") or 30.0)
    max_interval = float(config.get("max_decision_interval_sec") or max(min_interval, 90.0))
    if max_interval < min_interval:
        raise HTTPException(400, "最长等待时间不能小于最短决策间隔")
    config["max_decision_interval_sec"] = max_interval

    if "max_trades_per_hour" in raw_updates:
        value = int(raw_updates["max_trades_per_hour"])
        if value < 1 or value > 120:
            raise HTTPException(400, "每小时最大交易次数必须在 1 到 120 之间")
        config["max_trades_per_hour"] = value

    if "probe_size_pct" in raw_updates:
        probe_fraction = _as_autonomous_fraction(raw_updates["probe_size_pct"], 0.08)
        if probe_fraction <= 0:
            raise HTTPException(400, "试单仓位必须大于 0")
        config["probe_size_pct"] = probe_fraction

    if "initial_capital" in raw_updates:
        value = float(raw_updates["initial_capital"])
        if value <= 0:
            raise HTTPException(400, "模拟盘初始资金必须大于 0")
        config["initial_capital"] = value

    single_fraction = _as_autonomous_fraction(
        config.get("max_single_position_pct"),
        AUTONOMOUS_DEFAULT_MAX_SINGLE_POSITION_PCT / 100.0,
    )
    probe_fraction = _as_autonomous_fraction(config.get("probe_size_pct"), 0.08)
    if probe_fraction > single_fraction:
        config["probe_size_pct"] = single_fraction
    leverage_cap = max(1.0, min(AUTONOMOUS_MAX_LEVERAGE_CAP, float(config.get("max_leverage_cap") or config.get("max_leverage") or 10.0)))
    min_decision_leverage = max(
        1.0,
        min(leverage_cap, float(config.get("min_decision_leverage") or AUTONOMOUS_DEFAULT_DECISION_LEVERAGE)),
    )
    default_decision_leverage = max(
        min_decision_leverage,
        min(leverage_cap, float(config.get("default_decision_leverage") or min_decision_leverage)),
    )
    config["max_leverage_cap"] = leverage_cap
    config["max_leverage"] = leverage_cap
    config["min_decision_leverage"] = min_decision_leverage
    config["default_decision_leverage"] = default_decision_leverage

    config.update({
        "strategy_key": "ai_autonomous_trader",
        "market_type": "swap",
        "inst_type": "SWAP",
        "is_paper_trading": True,
        "paper_only": True,
        "exchange": "okx",
        "market_observation_mode": "ai_decides",
        "ai_autonomous_trader": True,
    })
    llm_provider = _normalize_autonomous_llm_provider(config.get("llm_provider") or config.get("ai_provider"))
    trade_direction = _normalize_autonomous_trade_direction(config.get("trade_direction"))
    config["llm_provider"] = llm_provider
    config["ai_provider"] = llm_provider
    config["trade_direction"] = trade_direction
    config["allow_long"] = trade_direction != "short_only"
    config["allow_short"] = True
    symbols = _normalize_autonomous_symbols(
        config.get("contract_trade_symbols")
        or config.get("trade_symbols")
        or config.get("symbols")
        or row.get("symbols")
        or []
    )
    config["symbols"] = symbols
    config["trade_symbols"] = symbols
    config["contract_trade_symbols"] = symbols
    if llm_provider == "hermes" and not str(config.get("llm_model") or "").strip():
        config["llm_model"] = AUTONOMOUS_HERMES_MODEL
    return config, active_runtime


def _autonomous_trade_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row)
    meta = item.get("meta")
    if isinstance(meta, str) and meta.strip():
        try:
            item["meta"] = json.loads(meta)
        except Exception:
            item["meta"] = {"raw": meta}
    return item


def _autonomous_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _autonomous_trade_side(row: Dict[str, Any]) -> str:
    return str(row.get("side") or "").strip().lower().replace("-", "_").replace(" ", "_")


def _autonomous_trade_meta(row: Dict[str, Any]) -> Dict[str, Any]:
    meta = row.get("meta")
    if isinstance(meta, str) and meta.strip():
        try:
            parsed = json.loads(meta)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return meta if isinstance(meta, dict) else {}


def _autonomous_run_started_ms(row: Dict[str, Any]) -> Optional[int]:
    raw = row.get("run_started_at")
    if not raw:
        return None
    value = str(raw).strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    try:
        return int(datetime.fromisoformat(value).timestamp() * 1000)
    except ValueError:
        return None


def _autonomous_persisted_trades(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    strategy_id = int(row["id"])
    since_ms = _autonomous_run_started_ms(row)
    if since_ms is not None and hasattr(db, "get_strategy_trades_since"):
        try:
            return list(db.get_strategy_trades_since(strategy_id, since_ms))
        except Exception:
            logger.warning("读取 AI自主交易本轮成交失败: strategy_id=%s", strategy_id)
    try:
        return list(reversed(db.get_strategy_trades(strategy_id, 5000)))
    except Exception:
        logger.warning("读取 AI自主交易成交失败: strategy_id=%s", strategy_id)
        return []


def _autonomous_persisted_dashboard(
    row: Dict[str, Any],
    engine_status: Dict[str, Any],
) -> Dict[str, Any]:
    """Paused/stopped autonomous instances lose the in-memory broker; keep card metrics from persisted fills."""
    dashboard = dict(engine_status or {})
    config = row.get("config") or {}
    initial = (
        _autonomous_float(dashboard.get("initial_capital"), 0.0)
        or _autonomous_float(config.get("initial_capital"), DEFAULT_PAPER_STRATEGY_INITIAL_CAPITAL)
    )
    trades = _autonomous_persisted_trades(row)

    status_equity = _autonomous_float(dashboard.get("equity"), 0.0)
    if status_equity > 0:
        if "total_trades" not in dashboard:
            dashboard["total_trades"] = len(trades)
        return dashboard

    closing_sides = {"sell", "spot_sell", "close_long", "close_short", "liquidation_long", "liquidation_short"}
    open_sides = {"buy", "spot_buy", "open_long", "open_short"}
    closing_trades = 0
    winning_trades = 0
    gross_profit = 0.0
    gross_loss = 0.0
    realized_pnl = 0.0
    opening_fees = 0.0
    for trade in trades:
        side = _autonomous_trade_side(trade)
        meta = _autonomous_trade_meta(trade)
        action = str(meta.get("action") or "").strip().lower()
        pnl = _autonomous_float(trade.get("pnl"), 0.0)
        fee = _autonomous_float(trade.get("fee"), 0.0)
        realized_pnl += pnl
        if side in open_sides or action == "open":
            opening_fees += fee
        if side in closing_sides or action in {"close", "liquidation"}:
            closing_trades += 1
            if pnl > 0:
                winning_trades += 1
                gross_profit += pnl
            elif pnl < 0:
                gross_loss += abs(pnl)

    equity = initial + realized_pnl - opening_fees
    return_pct = ((equity - initial) / initial * 100) if initial > 0 else 0.0
    win_rate = (winning_trades / closing_trades * 100) if closing_trades else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0
    dashboard.update({
        "equity": round(equity, 6),
        "initial_capital": initial,
        "balance": round(equity, 6),
        "pnl": round(equity - initial, 6),
        "return_pct": round(return_pct, 6),
        "total_trades": len(trades),
        "closing_trades": closing_trades,
        "winning_trades": winning_trades,
        "win_rate": round(win_rate, 4),
        "gross_profit": round(gross_profit, 6),
        "gross_loss": round(gross_loss, 6),
        "profit_factor": round(profit_factor, 4),
        "unrealized_pnl": _autonomous_float(dashboard.get("unrealized_pnl"), 0.0),
        "positions": dashboard.get("positions") or {},
    })
    return dashboard


def _autonomous_strategy_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    strategy_id = int(row["id"])
    engine_status = strategy_engine.get_strategy_status(strategy_id) or {}
    dashboard = _autonomous_persisted_dashboard(row, engine_status)
    config = dict(row.get("config") or {})
    is_ai_autonomous = config.get("strategy_key") == "ai_autonomous_trader" or config.get("ai_autonomous_trader")
    symbols = (
        config.get("contract_trade_symbols")
        or config.get("trade_symbols")
        or config.get("symbols")
        or dashboard.get("symbols")
        or row.get("symbols")
        or []
    ) if is_ai_autonomous else (
        dashboard.get("symbols")
        or config.get("contract_trade_symbols")
        or config.get("trade_symbols")
        or config.get("symbols")
        or row.get("symbols")
        or []
    )
    symbols = _normalize_autonomous_symbols(symbols if isinstance(symbols, list) else [str(symbols)])
    if is_ai_autonomous:
        config["symbols"] = symbols
        config["trade_symbols"] = symbols
        config["contract_trade_symbols"] = symbols
    return {
        "strategy_id": strategy_id,
        "name": row.get("name"),
        "status": dashboard.get("status") or row.get("status"),
        "config": config,
        "symbols": symbols,
        "dashboard": dashboard,
        "recent_trades": [
            _autonomous_trade_payload(item)
            for item in db.get_strategy_trades(strategy_id, 20)
        ],
        "events": strategy_log_store.get(strategy_id, 30),
        "updated_at": row.get("updated_at"),
        "created_at": row.get("created_at"),
    }


def _get_autonomous_strategy_row(strategy_id: int) -> Dict[str, Any]:
    row = db.get_strategy_by_id(strategy_id)
    if not row:
        raise HTTPException(404, f"策略 #{strategy_id} 不存在")
    cfg = row.get("config") or {}
    if cfg.get("strategy_key") != "ai_autonomous_trader" and not cfg.get("ai_autonomous_trader"):
        raise HTTPException(400, "该策略不是 AI自主交易实例")
    is_paper = cfg.get("is_paper_trading") is True or cfg.get("isPaperTrading") is True
    paper_only = cfg.get("paper_only") is True or cfg.get("paperOnly") is True
    if not is_paper or not paper_only:
        raise HTTPException(400, "AI自主交易实例只能操作模拟盘配置")
    return row


@router.post("/autonomous-trader/start", summary="启动 AI 自主交易模拟盘")
async def start_autonomous_trader(req: AutonomousTraderStartRequest):
    _validate_autonomous_request(req)
    symbols = _normalize_autonomous_symbols(req.symbols) if req.restrict_symbols else list(AUTONOMOUS_DEFAULT_SYMBOLS)
    llm_provider = _normalize_autonomous_llm_provider(req.llm_provider)
    trade_direction = _normalize_autonomous_trade_direction(req.trade_direction)
    llm_model = (
        validate_llm_model_name(req.llm_model)
        if req.llm_model
        else AUTONOMOUS_HERMES_MODEL if llm_provider == "hermes"
        else str(get_llm_model_config().get("model") or "").strip()
    )
    operator_prompt = str(req.operator_prompt or AUTONOMOUS_DEFAULT_OPERATOR_PROMPT).strip()
    max_decision_interval = max(
        float(req.min_decision_interval_sec),
        float(req.max_decision_interval_sec) if req.max_decision_interval_sec is not None else 90.0,
    )
    default_decision_leverage = min(AUTONOMOUS_DEFAULT_DECISION_LEVERAGE, float(req.max_leverage_cap))
    single_position_fraction = _as_autonomous_fraction(
        req.max_single_position_pct,
        AUTONOMOUS_DEFAULT_MAX_SINGLE_POSITION_PCT / 100.0,
    )
    probe_size_fraction = (
        _as_autonomous_fraction(req.probe_size_pct, 0.08)
        if req.probe_size_pct is not None
        else min(0.08, max(0.01, single_position_fraction))
    )
    created_label = datetime.now().strftime("%Y%m%d%H%M%S")
    capital_label = f"{int(req.initial_capital) if float(req.initial_capital).is_integer() else req.initial_capital:g}U"
    scope_label = _autonomous_symbol_scope_label(symbols, bool(req.restrict_symbols))
    if llm_provider == "hermes":
        method_label = f"{AUTONOMOUS_HERMES_DISPLAY_NAME}自主做空" if trade_direction == "short_only" else f"{AUTONOMOUS_HERMES_DISPLAY_NAME}自主交易"
    else:
        method_label = "AI自主做空" if trade_direction == "short_only" else "AI自主交易员"
    strategy_name = f"[合约][AI][AI] {scope_label} · {method_label} · {capital_label}"
    config = {
        "strategy_key": "ai_autonomous_trader",
        "market_type": "swap",
        "inst_type": "SWAP",
        "td_mode": "isolated",
        "position_mode": "long_short_mode",
        "settle_ccy": "USDT",
        "is_paper_trading": True,
        "paper_only": True,
        "exchange": "okx",
        "market_observation_mode": "ai_decides",
        "restrict_symbols": bool(req.restrict_symbols),
        "operator_prompt": operator_prompt,
        "loop_interval_sec": 60,
        "initial_capital": float(req.initial_capital),
        "symbols": symbols,
        "trade_symbols": symbols,
        "contract_trade_symbols": symbols,
        "llm_provider": llm_provider,
        "ai_provider": llm_provider,
        "llm_model": llm_model,
        "trade_direction": trade_direction,
        "allow_long": trade_direction != "short_only",
        "allow_short": True,
        "max_leverage": float(req.max_leverage_cap),
        "max_leverage_cap": float(req.max_leverage_cap),
        "max_single_position_pct": float(req.max_single_position_pct),
        "max_total_exposure_pct": float(req.max_total_exposure_pct),
        "max_positions": int(req.max_positions),
        "min_decision_interval_sec": float(req.min_decision_interval_sec),
        "max_decision_interval_sec": max_decision_interval,
        "max_trades_per_hour": int(req.max_trades_per_hour),
        "min_order_notional_usdt": AUTONOMOUS_DEFAULT_MIN_ORDER_NOTIONAL_USDT,
        "context_bars": 12,
        "model_temperature": 0.35,
        "activity_bias": "active_paper_research",
        "active_after_holds": 2,
        "probe_size_pct": min(probe_size_fraction, single_position_fraction),
        "min_decision_leverage": default_decision_leverage,
        "default_decision_leverage": default_decision_leverage,
        "ai_autonomous_trader": True,
    }
    strategy_id = db.save_strategy(
        name=strategy_name,
        description=(
            f"AI 自主交易模拟盘。{AUTONOMOUS_HERMES_DISPLAY_NAME} 或 DashScope 可以建议交易频率、方向、仓位和杠杆，"
            "但系统会强制执行人工配置的硬性风控上限；禁止实盘下单。"
        ),
        script_content="# Built-in strategy_key=ai_autonomous_trader; runtime class is registered in strategy_registry.\n",
        config=config,
        exchange="okx",
        symbols=symbols,
    )
    started = await strategy_engine.start_strategy(strategy_id)
    if not started:
        raise HTTPException(500, "AI自主交易模拟盘启动失败，请查看策略日志")
    row = db.get_strategy_by_id(strategy_id) or {}
    return {
        "message": "AI自主交易模拟盘已启动",
        "strategy": _autonomous_strategy_summary(row),
    }


@router.get("/autonomous-trader/instances", summary="列出 AI 自主交易模拟盘实例")
async def list_autonomous_trader_instances(limit: int = 20):
    rows = []
    for row in db.get_strategies():
        cfg = row.get("config") or {}
        if cfg.get("strategy_key") == "ai_autonomous_trader" or cfg.get("ai_autonomous_trader"):
            rows.append(row)
    rows = rows[: max(1, min(int(limit), 100))]
    return [_autonomous_strategy_summary(row) for row in rows]


@router.put("/autonomous-trader/{strategy_id}/config", summary="更新 AI 自主交易模拟盘配置")
async def update_autonomous_trader_config(strategy_id: int, req: AutonomousTraderConfigUpdateRequest):
    row = _get_autonomous_strategy_row(strategy_id)
    next_config, active_runtime = _validate_autonomous_config_update(row, req)

    if not db.update_strategy_config(strategy_id, next_config):
        raise HTTPException(404, f"策略 #{strategy_id} 不存在")

    runtime_update = strategy_engine.update_cached_config(strategy_id, next_config)
    row = db.get_strategy_by_id(strategy_id) or row
    return {
        "message": "AI自主交易配置已更新",
        "active_runtime": active_runtime,
        "runtime_applied": bool(runtime_update.get("runtime_applied")),
        "strategy": _autonomous_strategy_summary(row),
    }


@router.post("/autonomous-trader/{strategy_id}/pause", summary="暂停 AI 自主交易模拟盘")
async def pause_autonomous_trader(strategy_id: int):
    row = _get_autonomous_strategy_row(strategy_id)
    paused = await strategy_engine.pause_strategy(strategy_id)
    if not paused:
        raise HTTPException(500, "暂停 AI自主交易失败")
    row = db.get_strategy_by_id(strategy_id) or row
    return {"message": "AI自主交易模拟盘已暂停，指标已保留，可继续运行", "strategy": _autonomous_strategy_summary(row)}


@router.post("/autonomous-trader/{strategy_id}/resume", summary="继续 AI 自主交易模拟盘")
async def resume_autonomous_trader(strategy_id: int):
    row = _get_autonomous_strategy_row(strategy_id)
    resumed = await strategy_engine.start_strategy(strategy_id)
    if not resumed:
        raise HTTPException(500, "继续 AI自主交易失败，请查看策略日志")
    row = db.get_strategy_by_id(strategy_id) or row
    return {"message": "AI自主交易模拟盘已继续运行", "strategy": _autonomous_strategy_summary(row)}


@router.post("/autonomous-trader/{strategy_id}/stop", summary="停止 AI 自主交易模拟盘")
async def stop_autonomous_trader(strategy_id: int):
    row = _get_autonomous_strategy_row(strategy_id)
    stopped = await strategy_engine.stop_strategy(strategy_id, clear_metrics=False)
    if not stopped:
        raise HTTPException(500, "停止 AI自主交易失败")
    row = db.get_strategy_by_id(strategy_id) or row
    return {"message": "AI自主交易模拟盘已停止", "strategy": _autonomous_strategy_summary(row)}


@router.delete("/autonomous-trader/{strategy_id}", summary="删除 AI 自主交易模拟盘实例")
async def delete_autonomous_trader(strategy_id: int):
    row = _get_autonomous_strategy_row(strategy_id)
    status = (row.get("status") or "").lower()
    engine_status = strategy_engine.get_strategy_status(strategy_id) or {}
    runtime_status = (engine_status.get("status") or status).lower()
    if runtime_status in {"pending", "running", "paused"}:
        stopped = await strategy_engine.stop_strategy(strategy_id, clear_metrics=False)
        if not stopped:
            raise HTTPException(500, "删除前停止 AI自主交易失败")
    deleted = db.delete_strategy(strategy_id)
    if not deleted:
        raise HTTPException(404, f"策略 #{strategy_id} 不存在")
    try:
        strategy_log_store.clear(strategy_id)
    except Exception:
        logger.warning("清理 AI自主交易日志失败: strategy_id=%s", strategy_id)
    return {
        "message": "AI自主交易模拟盘实例已删除",
        "deleted": True,
        "strategy_id": strategy_id,
    }


def _optimizer_config_with_scheduler() -> Dict[str, Any]:
    cfg = dict(strategy_optimizer_service.get_config())
    cfg["running"] = bool(cfg.get("running")) or strategy_optimizer_service.is_running
    cfg["next_run_at"] = None
    try:
        from app.services.scheduler_service import scheduler_service

        for job in scheduler_service.get_jobs():
            if job.get("id") == "ai_strategy_optimizer_4h":
                cfg["next_run_at"] = job.get("next_run")
                break
    except Exception:
        pass
    return cfg


@router.get("/strategy-optimizer/config", summary="读取现有策略自动优化配置")
async def get_strategy_optimizer_config():
    return _optimizer_config_with_scheduler()


@router.put("/strategy-optimizer/config", summary="更新现有策略自动优化配置")
async def update_strategy_optimizer_config(req: StrategyOptimizerConfigRequest):
    updates = req.model_dump(exclude_unset=True)
    for key in ("interval_hours", "trial_hours"):
        if key in updates and updates[key] is not None and float(updates[key]) <= 0:
            raise HTTPException(400, f"{key} 必须大于 0")
    if updates.get("llm_model"):
        updates["llm_model"] = _select_llm_model(str(updates["llm_model"]))
    cfg = strategy_optimizer_service.update_config(updates)
    cfg.update(_optimizer_config_with_scheduler())
    return cfg


@router.post("/strategy-optimizer/run-now", summary="立即执行一次现有策略自动优化扫描")
async def run_strategy_optimizer_now(req: Optional[StrategyOptimizerRunNowRequest] = Body(default=None)):
    if strategy_optimizer_service.is_running:
        return {"started": False, "running": True, "message": "自动优化周期正在运行"}
    req = req or StrategyOptimizerRunNowRequest()
    if req.llm_model:
        strategy_optimizer_service.update_config({"llm_model": _select_llm_model(req.llm_model)})

    async def _run():
        try:
            await strategy_optimizer_service.run_once(force=True)
        except Exception as e:
            logger.exception("手动触发策略自动优化失败: %s", e)

    asyncio.create_task(_run())
    return {"started": True, "running": True, "message": "已触发自动优化扫描"}


@router.post("/strategy-optimizer/stop", summary="停止现有策略自动优化")
async def stop_strategy_optimizer():
    return await strategy_optimizer_service.stop_current()


@router.get("/strategy-optimizer/runs", summary="列出现有策略自动优化记录")
async def list_strategy_optimizer_runs(limit: int = 50):
    return strategy_optimizer_service.list_runs(limit=max(1, min(int(limit), 200)))


@router.get("/strategy-optimizer/runs/{run_id}", summary="查看现有策略自动优化详情")
async def get_strategy_optimizer_run(run_id: str):
    run = strategy_optimizer_service.get_run(run_id)
    if not run:
        raise HTTPException(404, f"优化任务 {run_id} 不存在")
    return run


@router.post("/strategy-optimizer/runs/{run_id}/cancel", summary="取消现有策略自动优化任务")
async def cancel_strategy_optimizer_run(run_id: str):
    try:
        return await strategy_optimizer_service.cancel_run(run_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete("/strategy-optimizer/runs/{run_id}", summary="删除现有策略自动优化记录")
async def delete_strategy_optimizer_run(run_id: str):
    try:
        return strategy_optimizer_service.delete_run(run_id)
    except ValueError as e:
        message = str(e)
        if "不存在" in message:
            raise HTTPException(404, message)
        raise HTTPException(400, message)
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.get("/tasks", summary="列出所有 Agent 任务")
async def list_tasks():
    in_memory = {_task.task_id: _task_to_status(_task) for _task in orchestrator.list_tasks()}
    db_tasks = db.get_agent_tasks(limit=50)
    for db_task in db_tasks:
        task_id = str(db_task.get("id") or db_task.get("task_id") or "")
        if task_id and task_id not in in_memory:
            in_memory[task_id] = _db_task_to_status(db_task)
    return list(in_memory.values())


@router.get("/tasks/{task_id}", summary="查询任务状态")
async def get_task(task_id: str):
    task = orchestrator.get_task(task_id)
    if task:
        return _task_to_status(task)
    db_task = db.get_agent_task(task_id)
    if not db_task:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    return _db_task_to_status(db_task)


@router.get("/tasks/{task_id}/iterations", summary="查看迭代记录")
async def get_iterations(task_id: str):
    task = orchestrator.get_task(task_id)
    if task:
        return [rec.to_dict() for rec in task.iterations]
    db_iterations = db.get_agent_iterations(task_id)
    if not db_iterations:
        db_task = db.get_agent_task(task_id)
        if not db_task:
            raise HTTPException(404, f"任务 {task_id} 不存在")
    return db_iterations


@router.post("/tasks/{task_id}/stop", summary="停止任务")
async def stop_task(task_id: str):
    if orchestrator.stop_task(task_id):
        task = orchestrator.get_task(task_id)
        if task:
            _save_agent_task_state(task)
        return {"message": f"任务 {task_id} 已停止"}
    db_task = db.get_agent_task(task_id)
    if db_task and db_task.get("status") in {"pending", "running"}:
        db.update_agent_task_status(task_id, "stopped", datetime.now().isoformat())
        return {"message": f"任务 {task_id} 已停止"}
    if db_task and db_task.get("status") == "stopped":
        return {"message": f"任务 {task_id} 已停止"}
    raise HTTPException(400, f"任务 {task_id} 不在运行中或不存在")


@router.delete("/tasks/{task_id}", summary="删除 Agent 任务记录")
async def delete_task(task_id: str):
    task = orchestrator.get_task(task_id)
    if task and task.status in {"pending", "running"}:
        raise HTTPException(400, "任务仍在运行中，请先停止后再删除记录")

    db_task = db.get_agent_task(task_id)
    if not task and not db_task:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    if db_task and db_task.get("status") in {"pending", "running"}:
        raise HTTPException(400, "任务仍在运行中，请先停止后再删除记录")

    if not orchestrator.delete_task(task_id):
        raise HTTPException(400, "任务仍在运行中，请先停止后再删除记录")

    deleted = db.delete_agent_task(task_id)
    if deleted.get("task_deleted", 0) <= 0 and db_task:
        raise HTTPException(500, "任务记录删除失败")
    return {
        "deleted": True,
        "task_id": task_id,
        "iterations_deleted": deleted.get("iterations_deleted", 0),
    }


@router.post("/tasks/{task_id}/resume", summary="从已保存进度继续 Agent 任务")
async def resume_task(task_id: str):
    task = orchestrator.get_task(task_id)
    if task and task.status in {"pending", "running"}:
        return {"task_id": task_id, "status": task.status, "message": "任务已在运行中"}

    db_task = db.get_agent_task(task_id)
    if not db_task:
        raise HTTPException(404, f"任务 {task_id} 不存在")

    return _resume_persisted_task(db_task, "已从持久化记录恢复，等待继续研发")


@router.post("/tasks/{task_id}/accept", summary="接受最佳策略")
async def accept_best_strategy(task_id: str):
    task = orchestrator.get_task(task_id)
    if task and task.best_record:
        record_data = task.best_record.to_dict()
        task_info = {
            "market_type": task.market_type,
            "symbol": task.symbol,
            "timeframe": task.timeframe,
            "goal_criteria": task.goal.to_dict(),
        }
        return _save_iteration_strategy(
            task_id,
            task.best_record.iteration,
            task_info,
            record_data,
            name_prefix="[AI]",
        )

    task_info = db.get_agent_task(task_id) or {}
    if not task_info:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    records = db.get_agent_iterations(task_id)
    best_iteration = task_info.get("best_iteration")
    if best_iteration is None:
        best_iteration = _best_iteration_from_records(records)
    if best_iteration is None:
        raise HTTPException(400, "没有可接受的策略 (无有效迭代记录)")
    record_data = next((r for r in records if int(r.get("iteration", -1)) == int(best_iteration)), None)
    if not record_data:
        raise HTTPException(400, "最佳迭代记录缺失，无法保存策略")
    return _save_iteration_strategy(
        task_id,
        int(best_iteration),
        task_info,
        record_data,
        name_prefix="[AI]",
    )


@router.post("/tasks/{task_id}/iterations/{iteration}/accept", summary="接受指定迭代策略")
async def accept_iteration_strategy(task_id: str, iteration: int, allow_low_quality: bool = False):
    """
    保存某一轮候选策略到策略库。

    与 /accept 不同，这个接口可以接受候选池中的任意一轮；若任务已不在内存中，
    也会从 SQLite 的 agent_iterations 读取策略代码后保存。
    """
    task = orchestrator.get_task(task_id)
    if task:
        record = next((r for r in task.iterations if r.iteration == iteration), None)
        if not record:
            raise HTTPException(404, f"任务 {task_id} 第 {iteration + 1} 轮不存在")
        task_info: Dict[str, Any] = {
            "market_type": task.market_type,
            "symbol": task.symbol,
            "timeframe": task.timeframe,
            "goal_criteria": task.goal.to_dict(),
        }
        record_data = record.to_dict()
    else:
        task_info, record_data = _record_dict_for_iteration(task_id, iteration)

    return _save_iteration_strategy(
        task_id,
        iteration,
        task_info,
        record_data,
        allow_low_quality=allow_low_quality,
    )


# ============================================
# 一键用嘴写策略
# ============================================

class GenerateStrategyRequest(BaseModel):
    """用自然语言描述你想要的策略"""
    prompt: str  # 例: "写一个布林带均值回归策略，跌破下轨买入"
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"


@router.post("/generate_strategy", summary="一键用嘴写策略")
async def generate_strategy(req: GenerateStrategyRequest):
    """
    接收自然语言需求，调用 LLM 生成合规 BaseStrategy 代码，
    以数据库 script_content 为运行源保存策略。
    """
    if not has_agent_api_key():
        raise HTTPException(400, "DASHSCOPE_API_KEY 未配置，请在 .env 中设置")

    from app.services.agent.llm_client import get_qwen_client
    client = get_qwen_client()

    system_prompt = """你是一个专业量化策略开发工程师。请根据用户需求，生成一个完整的、可直接运行的 Python 策略类。

你必须严格遵守以下规范：
1. 策略类必须继承 `BaseStrategy`（从 `app.core.execution.base_strategy` 导入）
2. 必须实现 `async def on_init(self)` 和 `async def on_bar(self, bar: BarData)` 方法
3. 使用 `self.config.get(key, default)` 读取可配置参数
4. 使用 `collections.deque(maxlen=N)` 管理历史数据，不要用无限增长 list
5. 使用 `await self.buy(symbol, amount)` / `await self.sell(symbol, amount)` / `await self.close_position(symbol)` 交易
6. 通过 `self.broker.get_position_size(symbol)` 获取当前持仓
7. 所有方法必须是 async def，不要用 time.sleep，用 asyncio

返回 JSON 格式：
{
    "class_name": "MyStrategy",
    "file_name": "my_strategy",
    "description": "策略简要描述",
    "code": "完整的 Python 代码（包含所有 import）"
}"""

    user_msg = f"""请为以下需求生成策略代码：

需求：{req.prompt}
交易对：{req.symbol}
K线周期：{req.timeframe}

请生成完整可运行的 BaseStrategy 子类代码。"""

    try:
        result = await client.chat_json(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.5,
            max_tokens=4096,
        )
    except Exception as e:
        raise HTTPException(500, f"LLM 调用失败: {e}")

    class_name = result.get("class_name", "AutoGenStrategy")
    file_name = result.get("file_name", "auto_gen_strategy")
    description = result.get("description", req.prompt[:100])
    code = result.get("code", "")

    if not code or "BaseStrategy" not in code:
        raise HTTPException(500, "LLM 生成的代码不合规（未包含 BaseStrategy）")

    from app.services.agent.code_sandbox import validate_base_strategy_contract

    try:
        validate_base_strategy_contract(code)
    except Exception as e:
        raise HTTPException(500, f"LLM 生成的代码不合规: {e}")

    # 生成策略以数据库 script_content 为唯一运行源。部署会用 GitHub Actions 同步代码目录，
    # 因此不能依赖运行时写入 backend/app/strategies 的临时文件。
    strategy_id = db.save_strategy(
        name=f"[现货] [AI] {_strip_asset_prefix(class_name)}",
        description=f"AI 自动生成 — {description}",
        script_content=code,
        config={
            "class_name": class_name,
            "timeframe": req.timeframe,
            "is_paper_trading": True,
            "initial_capital": DEFAULT_PAPER_STRATEGY_INITIAL_CAPITAL,
            "ai_generated": True,
            "user_prompt": req.prompt,
            "script_content_source": "db",
        },
        exchange="okx",
        symbols=[req.symbol],
    )

    return {
        "strategy_id": strategy_id,
        "class_name": class_name,
        "file_name": "",
        "file_path": "",
        "description": description,
        "module_path": "",
        "message": f"策略 [{class_name}] 已生成并保存到数据库，可立即回测或启动",
    }


def _task_to_status(task: AgentTask) -> dict:
    best_score = None
    best_metrics = None
    best_eval_scores = None
    if task.best_record:
        best_score = task.best_record.score
        best_metrics = task.best_record.backtest_metrics
        if task.best_record.eval_scores:
            best_eval_scores = task.best_record.eval_scores.to_dict()

    return {
        "task_id": task.task_id,
        "status": task.status,
        "stage": task.stage,
        "stage_label": task.stage_label,
        "market_type": task.market_type,
        "symbol": task.symbol,
        "timeframe": task.timeframe,
        "backtest_start": task.backtest_start,
        "backtest_end": task.backtest_end,
        "current_iteration": task.current_iteration,
        "max_iterations": task.max_iterations,
        "best_iteration": task.best_iteration,
        "best_score": best_score,
        "best_metrics": best_metrics,
        "best_eval_scores": best_eval_scores,
        "goal": task.goal.to_dict(),
        "user_prompt": task.user_prompt,
        "llm_model": task.llm_model,
        "strategy_spec": task.strategy_spec.to_dict() if task.strategy_spec else None,
        "iterations_count": len(task.iterations),
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _db_task_to_status(task: dict) -> dict:
    task_id = str(task.get("id") or task.get("task_id") or "")
    status = task.get("status") or "unknown"
    goal = task.get("goal") or task.get("goal_criteria") or {}
    iterations = db.get_agent_iterations(task_id) if task_id else []
    best_iteration = task.get("best_iteration")
    if best_iteration is not None:
        stored_best = next(
            (r for r in iterations if int(r.get("iteration", -1)) == int(best_iteration)),
            None,
        )
        if not stored_best or _candidate_quality_issues(task, stored_best, strict_drawdown=False, strict_trades=False):
            best_iteration = _best_iteration_from_records(iterations)
    else:
        best_iteration = _best_iteration_from_records(iterations)
    best_record = None
    if best_iteration is not None:
        best_record = next(
            (r for r in iterations if int(r.get("iteration", -1)) == int(best_iteration)),
            None,
        )
    return {
        "task_id": task_id,
        "id": task_id,
        "status": status,
        "stage": task.get("stage") or status,
        "stage_label": task.get("stage_label") or _agent_status_label(status),
        "market_type": normalize_agent_market_type(task.get("market_type")),
        "symbol": task.get("symbol") or default_agent_scope_for_market(task.get("market_type")),
        "timeframe": task.get("timeframe") or "15m",
        "backtest_start": task.get("backtest_start") or "",
        "backtest_end": task.get("backtest_end") or "",
        "current_iteration": task.get("current_iteration") or 0,
        "max_iterations": task.get("max_iterations") or 0,
        "best_iteration": best_iteration,
        "best_score": best_record.get("score") if best_record else None,
        "best_metrics": best_record.get("backtest_metrics") if best_record else None,
        "best_eval_scores": best_record.get("eval_scores") if best_record else None,
        "goal": goal,
        "user_prompt": task.get("user_prompt") or "",
        "llm_model": task.get("llm_model") or "",
        "strategy_spec": task.get("strategy_spec"),
        "iterations_count": len(iterations),
        "created_at": task.get("created_at") or "",
        "updated_at": task.get("updated_at") or "",
    }


def _agent_status_label(status: str) -> str:
    return {
        "pending": "等待启动",
        "running": "运行中",
        "completed": "已完成",
        "stopped": "任务已停止",
        "failed": "已失败",
        "interrupted": "服务重启已中断",
    }.get(status, status or "未知状态")
