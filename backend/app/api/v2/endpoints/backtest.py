"""
回测 API
==============================
- POST /run_sync, /run       : 按 strategy_id 回测（BaseStrategy，与实盘同构）
- POST /run_new              : 按 strategy_name 回测（注册表键名）
- GET  /strategies           : 已注册的 strategy_key 列表
- GET  /results, /result/id  : 历史回测结果
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Request, Body
from typing import List, Optional, Dict, Any, Type, Set, Literal
from pydantic import BaseModel
from datetime import datetime, date, timedelta
import asyncio
import json
import logging
import numpy as np
import os
import sqlite3
import sys
import time
import uuid
import threading
from dataclasses import asdict
from pathlib import Path

from app.db.local_db import db_instance as db
from app.services.backtrader_engine import backtrader_engine, BacktestReport, BacktestCancelled
from app.services.strategy_registry import (
    get_strategy_for_id,
    list_backtestable_registry_keys,
    get_base_strategy_registry,
)
from app.core.execution.base_strategy import BaseStrategy
from app.services.auth_service import AuthError, auth_service
from app.services.exchange_fee_model import default_fee_schedule

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_BACKTEST_SLIPPAGE_BPS = 1.0
_CANCELLABLE_BACKTEST_STATUSES = {"pending", "running", "cancelling"}
_TERMINAL_BACKTEST_STATUSES = {"completed", "failed", "interrupted", "cancelled"}
_RESUMABLE_BACKTEST_STATUSES = {"pending", "running", "cancelling", "failed", "interrupted"}
_BACKTEST_CANCEL_REQUESTS: Set[str] = set()
_BACKTEST_CANCEL_LOCK = threading.Lock()
_ACTIVE_BACKTEST_JOBS: Set[str] = set()
_ACTIVE_BACKTEST_LOCK = threading.Lock()
_BATCH_BACKTEST_CONCURRENCY = 2
_BATCH_BACKTEST_SEMAPHORE = asyncio.Semaphore(_BATCH_BACKTEST_CONCURRENCY)
_SCHEDULED_BACKTEST_TASKS: Set[asyncio.Task[None]] = set()
_BACKEND_DIR = Path(__file__).resolve().parents[4]
_BACKTEST_WORKER_MODULE = "app.workers.backtest_job_worker"


def _request_backtest_cancel(job_id: str) -> None:
    with _BACKTEST_CANCEL_LOCK:
        _BACKTEST_CANCEL_REQUESTS.add(job_id)


def _clear_backtest_cancel(job_id: str) -> None:
    with _BACKTEST_CANCEL_LOCK:
        _BACKTEST_CANCEL_REQUESTS.discard(job_id)


def _is_backtest_cancel_requested(job_id: str) -> bool:
    with _BACKTEST_CANCEL_LOCK:
        if job_id in _BACKTEST_CANCEL_REQUESTS:
            return True
    return _read_backtest_job_status(job_id) == "cancelling"


def _read_backtest_job_status(job_id: str) -> Optional[str]:
    try:
        conn = db.get_connection()
        row = conn.execute(
            "SELECT status FROM backtest_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        conn.close()
    except Exception:
        logger.debug("read backtest job status failed for %s", job_id, exc_info=True)
        return None
    if not row:
        return None
    return str(row["status"] or "")


def _try_mark_backtest_active(job_id: str) -> bool:
    with _ACTIVE_BACKTEST_LOCK:
        if job_id in _ACTIVE_BACKTEST_JOBS:
            return False
        _ACTIVE_BACKTEST_JOBS.add(job_id)
        return True


def _clear_backtest_active(job_id: str) -> None:
    with _ACTIVE_BACKTEST_LOCK:
        _ACTIVE_BACKTEST_JOBS.discard(job_id)


def _is_backtest_active(job_id: str) -> bool:
    with _ACTIVE_BACKTEST_LOCK:
        return job_id in _ACTIVE_BACKTEST_JOBS


# ============================================
# 新架构策略注册表（BaseStrategy 子类）
# ============================================

_NEW_STRATEGY_REGISTRY: Dict[str, Type[BaseStrategy]] = {}


def _ensure_new_registry():
    """延迟加载，避免循环导入；与 strategy_registry.get_base_strategy_registry 同步。"""
    global _NEW_STRATEGY_REGISTRY
    if _NEW_STRATEGY_REGISTRY:
        return
    from app.services.strategy_registry import get_base_strategy_registry

    _NEW_STRATEGY_REGISTRY.update(get_base_strategy_registry())


# ============================================
# 请求 / 响应 模型
# ============================================

class BacktestRequest(BaseModel):
    """回测请求"""
    strategy_id: int
    exchange: str = "okx"
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    timeframe_mode: str = "strategy"
    timeframes: Optional[List[str]] = None
    start_date: str
    end_date: str
    initial_capital: float = 10000
    # Legacy single-rate fields. New clients should submit *_bps fields below.
    commission: Optional[float] = None
    slippage: Optional[float] = None
    maker_fee_bps: Optional[float] = None
    taker_fee_bps: Optional[float] = None
    slippage_bps: Optional[float] = None
    stop_loss: Optional[float] = None       # e.g. 0.05 = 5%
    take_profit: Optional[float] = None
    trailing_stop: Optional[float] = None


class RunningStrategiesBacktestRequest(BaseModel):
    """批量回测运行中模拟策略的便捷入口。"""
    exchange: str = "okx"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_capital: float = 100.0
    maker_fee_bps: Optional[float] = None
    taker_fee_bps: Optional[float] = None
    slippage_bps: Optional[float] = None


class BacktestResultResponse(BaseModel):
    """回测结果响应 — 前端使用"""
    strategy_id: int
    strategy_name: Optional[str] = None
    status: str
    timeframe: Optional[str] = None
    timeframe_mode: Optional[str] = None
    matrix_results: Optional[List[Dict[str, Any]]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_capital: float
    final_capital: Optional[float] = None
    total_return: Optional[float] = None
    annual_return: Optional[float] = None
    max_drawdown: Optional[float] = None
    max_drawdown_duration_days: Optional[int] = None
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    calmar_ratio: Optional[float] = None
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    total_trades: Optional[int] = None
    data_quality_status: Optional[str] = None
    data_quality_message: Optional[str] = None
    data_quality_checked_at: Optional[str] = None
    winning_trades: Optional[int] = None
    losing_trades: Optional[int] = None
    funding_fee: Optional[float] = None
    funding_events: Optional[int] = None
    avg_win_pct: Optional[float] = None
    avg_loss_pct: Optional[float] = None
    max_consecutive_wins: Optional[int] = None
    max_consecutive_losses: Optional[int] = None
    expectancy: Optional[float] = None
    total_fees: Optional[float] = None
    avg_holding_bars: Optional[float] = None
    total_bars: Optional[int] = None
    elapsed_seconds: Optional[float] = None
    monthly_returns: Optional[Dict[str, float]] = None
    equity_curve: Optional[List[dict]] = None
    trades: Optional[List[dict]] = None
    error_message: Optional[str] = None
    # 回测诊断：universe_size / skipped_symbols / 候选与池成员计数等。
    # total_trades=0 时用于向前端解释"为什么没交易"。
    diagnostics: Optional[Dict[str, Any]] = None


# ============================================
# 工具函数
# ============================================

def _safe_float(v) -> Optional[float]:
    """将 numpy 类型安全转为 Python float"""
    if v is None:
        return None
    if isinstance(v, (np.floating, np.integer)):
        val = float(v)
        if np.isnan(val) or np.isinf(val):
            return 0.0
        return val
    if isinstance(v, float):
        if np.isnan(v) or np.isinf(v):
            return 0.0
    return float(v)


def _validate_backtest_date_range(
    start_date: str,
    end_date: str,
    *,
    today: Optional[date] = None,
) -> tuple[date, date]:
    """Validate operator-supplied backtest date bounds before touching data stores."""
    try:
        start = date.fromisoformat(str(start_date))
        end = date.fromisoformat(str(end_date))
    except ValueError:
        raise HTTPException(status_code=400, detail="回测日期格式必须为 YYYY-MM-DD")

    if start > end:
        raise HTTPException(status_code=400, detail="回测开始日期不能晚于结束日期")

    current_day = today or datetime.now().date()
    if end > current_day:
        raise HTTPException(
            status_code=400,
            detail=f"回测结束日期不能晚于当前日期 {current_day.isoformat()}",
        )

    return start, end


def _one_year_ago(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return date(day.year - 1, 2, 28)


def _default_running_strategy_batch_dates() -> tuple[str, str]:
    current_day = datetime.now().date()
    return _one_year_ago(current_day).isoformat(), (current_day - timedelta(days=1)).isoformat()


def _explicit_false_like(value: Any) -> bool:
    if value is False:
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 0
    if isinstance(value, str):
        return value.strip().lower() in {"false", "0", "no", "live", "real"}
    return False


def _running_strategy_batch_skip_reason(strategy_row: Dict[str, Any]) -> Optional[str]:
    cfg = strategy_row.get("config") if isinstance(strategy_row.get("config"), dict) else {}
    name = str(strategy_row.get("name") or "")
    if "[实盘试运行]" in name or "[实盘]" in name or name.startswith("[实盘"):
        return "实盘策略不纳入批量回测入口"
    if (
        _explicit_false_like(cfg.get("is_paper_trading"))
        or _explicit_false_like(cfg.get("isPaperTrading"))
        or _explicit_false_like(cfg.get("dry_run"))
        or _explicit_false_like(cfg.get("dryRun"))
    ):
        return "策略未标记为模拟交易"
    mode = str(
        cfg.get("mode")
        or cfg.get("run_mode")
        or cfg.get("runMode")
        or cfg.get("execution_mode")
        or cfg.get("executionMode")
        or ""
    ).lower()
    if any(token in mode for token in ("live", "real", "production")):
        return "策略运行模式不是模拟交易"
    return None


def _batch_backtest_skip_item(strategy_row: Dict[str, Any], reason: str) -> Dict[str, Any]:
    return {
        "strategy_id": strategy_row.get("id"),
        "strategy_name": strategy_row.get("name"),
        "status": strategy_row.get("status"),
        "reason": reason,
    }


def _backtest_report_to_response(
    report: BacktestReport,
    strategy_id: int,
    strategy_name: str,
    request: BacktestRequest,
) -> BacktestResultResponse:
    """将 BaseStrategy/Backtrader 的 BacktestReport 转为前端 BacktestResultResponse。"""
    trades_list = []

    closed_by_exit: Dict[tuple[str, int], Dict[str, Any]] = {}
    for closed in report.trades or []:
        symbol = str(closed.get("symbol") or "")
        exit_time = int(closed.get("exit_time") or 0)
        if symbol and exit_time > 0:
            closed_by_exit[(symbol, exit_time)] = closed

    order_records = getattr(report, "orders", None) or []
    if order_records:
        for order in order_records:
            symbol = order.get("symbol")
            timestamp = int(order.get("timestamp") or 0)
            px = float(order.get("price") or 0.0)
            qty = float(order.get("size") or order.get("quantity") or 0.0)
            notional = float(order.get("notional_usdt") or order.get("notional") or abs(px * qty) or 0.0)
            leverage = _safe_float(order.get("leverage"))
            margin = _safe_float(order.get("margin"))
            if (margin is None or margin <= 0) and leverage and leverage > 0 and notional > 0:
                margin = notional / leverage
            matched = closed_by_exit.get((str(symbol or ""), timestamp))
            pnl_net = float((matched or {}).get("pnl_net") or order.get("pnl_net") or 0.0)
            pnl_pct = (pnl_net / notional * 100.0) if notional > 1e-12 else 0.0
            trades_list.append({
                "symbol": symbol,
                "timestamp": timestamp,
                "side": order.get("side") or "buy",
                "price": round(px, 8),
                "quantity": round(qty, 8),
                "notional_usdt": round(notional, 4),
                "leverage": round(leverage, 4) if leverage is not None else None,
                "margin": round(margin, 4) if margin is not None else None,
                "pnl": round(pnl_net, 4),
                "pnl_pct": round(pnl_pct, 4),
                "fee": round(float(order.get("commission") or 0.0), 4),
                "reason": order.get("reason") or "fill",
            })
    else:
        for t in report.trades or []:
            entry_px = float(t.get("entry_price") or 0)
            size = float(t.get("size") or 0)
            pnl_net = float(t.get("pnl_net") or t.get("pnl") or 0)
            notional = abs(entry_px * size) if entry_px and size else 0.0
            leverage = _safe_float(t.get("leverage"))
            margin = _safe_float(t.get("margin"))
            if (margin is None or margin <= 0) and leverage and leverage > 0 and notional > 0:
                margin = notional / leverage
            pnl_pct = (pnl_net / notional * 100.0) if notional > 1e-12 else 0.0
            trades_list.append({
                "symbol": t.get("symbol"),
                "timestamp": int(t.get("exit_time") or t.get("entry_time") or 0),
                "side": t.get("side") or "long",
                "price": round(entry_px, 4),
                "quantity": round(size, 6),
                "notional_usdt": round(notional, 4),
                "leverage": round(leverage, 4) if leverage is not None else None,
                "margin": round(margin, 4) if margin is not None else None,
                "pnl": round(pnl_net, 4),
                "pnl_pct": round(pnl_pct, 4),
                "fee": round(float(t.get("commission") or 0), 4),
                "reason": "close",
            })

    return BacktestResultResponse(
        strategy_id=strategy_id,
        strategy_name=strategy_name,
        status=report.status,
        timeframe=request.timeframe,
        timeframe_mode=_backtest_timeframe_mode(request),
        start_date=request.start_date,
        end_date=request.end_date,
        initial_capital=_safe_float(request.initial_capital),
        final_capital=_safe_float(report.final_capital),
        total_return=_safe_float(report.total_return_pct),
        annual_return=_safe_float(report.annual_return_pct),
        max_drawdown=_safe_float(report.max_drawdown_pct),
        max_drawdown_duration_days=int(report.max_drawdown_duration_days or 0),
        sharpe_ratio=_safe_float(report.sharpe_ratio),
        sortino_ratio=_safe_float(report.sortino_ratio),
        calmar_ratio=_safe_float(report.calmar_ratio),
        win_rate=_safe_float(report.win_rate_pct),
        profit_factor=_safe_float(report.profit_factor),
        total_trades=int(report.total_trades),
        winning_trades=int(report.winning_trades),
        losing_trades=int(report.losing_trades),
        avg_win_pct=None,
        avg_loss_pct=None,
        max_consecutive_wins=None,
        max_consecutive_losses=None,
        expectancy=None,
        total_fees=_safe_float(report.total_fees),
        funding_fee=_safe_float(getattr(report, "funding_fee", 0.0)),
        funding_events=int(getattr(report, "funding_events", 0) or 0),
        avg_holding_bars=_safe_float(report.avg_holding_bars),
        total_bars=int(report.total_bars),
        elapsed_seconds=_safe_float(report.elapsed_seconds),
        monthly_returns=report.monthly_returns or None,
        equity_curve=report.equity_curve or None,
        trades=trades_list,
        error_message=report.error_message if report.status == "failed" else None,
        diagnostics=(report.diagnostics or None) or None,
    )


def _clean_symbols(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = [raw]
        raw = parsed
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for item in raw:
        symbol = str(item or "").strip()
        if symbol and symbol not in out:
            out.append(symbol)
    return out


def _parse_base_quote_symbol(symbol: str) -> Optional[tuple[str, str]]:
    value = str(symbol or "").strip()
    if not value:
        return None

    upper_value = value.upper()
    if upper_value.endswith("-SWAP"):
        core = upper_value[:-5].strip("-")
        parts = [part for part in core.split("-") if part]
        if len(parts) >= 2:
            return "-".join(parts[:-1]), parts[-1]
        if len(parts) == 1:
            return parts[0], "USDT"

    pair = upper_value.split(":", 1)[0]
    if "/" in pair:
        base, quote = pair.split("/", 1)
        base = base.strip()
        quote = quote.strip()
        if base and quote:
            return base, quote

    return None


def _backtest_market_data_symbol(symbol: str, *, is_swap: bool) -> str:
    parsed = _parse_base_quote_symbol(symbol)
    if not parsed:
        return str(symbol or "").strip()
    base, quote = parsed
    if is_swap:
        return f"{base}/{quote}:{quote}"
    return f"{base}/{quote}"


def _normalize_backtest_market_data_symbols(symbols: List[str], *, is_swap: bool) -> List[str]:
    out: List[str] = []
    for symbol in symbols:
        normalized = _backtest_market_data_symbol(symbol, is_swap=is_swap)
        if normalized and normalized not in out:
            out.append(normalized)
    return out


def _strategy_symbols_for_backtest(strategy_info: Dict[str, Any], request: BacktestRequest) -> List[str]:
    """Backtest feed universe resolved to the strategy asset class market data."""
    cfg = strategy_info.get("db_config") or {}
    cfg = cfg if isinstance(cfg, dict) else {}
    is_swap = _is_swap_strategy_for_backtest(strategy_info)

    symbols: List[str] = []
    if is_swap:
        symbols.extend(_clean_symbols(cfg.get("trade_symbols")))
        symbols.extend(_clean_symbols(cfg.get("tradeSymbols")))
        symbols.extend(_clean_symbols(cfg.get("target_symbol")))

    symbols.extend(_clean_symbols(strategy_info.get("symbols")))
    if not symbols:
        symbols = _clean_symbols(cfg.get("symbols"))
    if not symbols:
        # 动态宇宙策略（如 Top60 动量池）：DB 行不固定 symbols，由策略类在运行时解析。
        # 回测路径此前缺失该解析，导致宇宙退化为单标的、候选池永远为空、回测静默 0 交易。
        resolver = getattr(strategy_info.get("strategy_class"), "resolve_runtime_symbols", None)
        if resolver is not None:
            try:
                symbols = _clean_symbols(resolver(str(request.exchange or "okx"), cfg))
            except Exception as exc:
                logger.warning(
                    "resolve_runtime_symbols 失败，回退默认标的: %s", exc,
                )
                symbols = []
    if not symbols:
        symbols = _clean_symbols(request.symbol)
    symbols = _normalize_backtest_market_data_symbols(symbols or ["BTC/USDT"], is_swap=is_swap)
    return symbols or ["BTC/USDT:USDT" if is_swap else "BTC/USDT"]


BACKTEST_TIMEFRAME_ALIASES = {
    "1M": "1m",
    "5M": "5m",
    "15M": "15m",
    "30M": "30m",
    "1H": "1h",
    "4H": "4h",
    "12H": "12h",
    "1D": "1d",
}
BACKTEST_ALLOWED_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h", "12h", "1d"}


def _normalize_backtest_timeframe(raw: Any) -> Optional[str]:
    value = str(raw or "").strip()
    if not value:
        return None
    value = BACKTEST_TIMEFRAME_ALIASES.get(value.upper(), value.lower())
    return value if value in BACKTEST_ALLOWED_TIMEFRAMES else None


def _strategy_defined_timeframe_for_backtest(strategy_info: Dict[str, Any]) -> Optional[str]:
    cfg = strategy_info.get("db_config") or {}
    candidates: List[Any] = []
    if isinstance(cfg, dict):
        candidates.extend([cfg.get("timeframe"), cfg.get("kline_timeframe")])
    candidates.append(strategy_info.get("timeframe"))
    for raw in candidates:
        timeframe = _normalize_backtest_timeframe(raw) or str(raw or "").strip()
        if timeframe:
            return timeframe
    return None


def _backtest_timeframe_mode(request: BacktestRequest) -> str:
    mode = str(request.timeframe_mode or "strategy").strip().lower()
    if mode in {"single", "matrix"}:
        return mode
    return "strategy"


def _strategy_timeframes_for_backtest(strategy_info: Dict[str, Any], request: BacktestRequest) -> List[str]:
    mode = _backtest_timeframe_mode(request)
    if mode == "matrix":
        values = request.timeframes or ([request.timeframe] if request.timeframe else [])
        resolved: List[str] = []
        for raw in values:
            timeframe = _normalize_backtest_timeframe(raw)
            if timeframe and timeframe not in resolved:
                resolved.append(timeframe)
        return resolved or [_strategy_timeframe_for_backtest(strategy_info, request)]
    return [_strategy_timeframe_for_backtest(strategy_info, request)]


def _strategy_timeframe_for_backtest(strategy_info: Dict[str, Any], request: BacktestRequest) -> str:
    """Backtest K-line timeframe; default to strategy config, explicit single mode may override it."""
    mode = _backtest_timeframe_mode(request)
    if mode == "single":
        explicit = _normalize_backtest_timeframe(request.timeframe)
        if explicit:
            return explicit

    if mode == "matrix":
        first = _normalize_backtest_timeframe((request.timeframes or [request.timeframe or ""])[0])
        if first:
            return first

    strategy_timeframe = _strategy_defined_timeframe_for_backtest(strategy_info)
    if strategy_timeframe:
        return strategy_timeframe
    legacy = _normalize_backtest_timeframe(request.timeframe)
    return legacy or "1h"


def _strategy_config_for_backtest(db_config: Any, timeframe: str) -> Dict[str, Any]:
    cfg = dict(db_config) if isinstance(db_config, dict) else {}
    cfg["timeframe"] = timeframe
    if "kline_timeframe" in cfg:
        cfg["kline_timeframe"] = timeframe
    if "klineTimeframe" in cfg:
        cfg["klineTimeframe"] = timeframe
    return cfg


def _float_or_none(raw: Any) -> Optional[float]:
    try:
        if raw is None or raw == "":
            return None
        value = float(raw)
        if not np.isfinite(value):
            return None
        return value
    except (TypeError, ValueError):
        return None


def _legacy_rate_or_percent_to_bps(raw: Any) -> Optional[float]:
    value = _float_or_none(raw)
    if value is None:
        return None
    # Older clients used "commission/slippage" as decimal rates, while the UI
    # label made operators enter percentages like 0.08 for 0.08%. Preserve both.
    if value > 0.02:
        return value * 100.0
    return value * 10_000.0


def _is_swap_strategy_for_backtest(strategy_info: Dict[str, Any]) -> bool:
    cfg = strategy_info.get("db_config") or {}
    name = str(strategy_info.get("name") or "")
    symbols = _clean_symbols(strategy_info.get("symbols"))
    if isinstance(cfg, dict):
        symbols.extend(_clean_symbols(cfg.get("symbols")))
        symbols.extend(_clean_symbols(cfg.get("trade_symbols")))
        symbols.extend(_clean_symbols(cfg.get("tradeSymbols")))
        market_type = str(cfg.get("market_type") or "").lower()
        inst_type = str(cfg.get("inst_type") or "").upper()
        if market_type in {"spot", "margin"} or inst_type in {"SPOT", "MARGIN"}:
            return False
        if market_type in {"swap", "future", "futures", "contract"} or inst_type == "SWAP":
            return True
    if name.startswith("[现货]"):
        return False
    if name.startswith("[合约]"):
        return True
    return any(":USDT" in s or s.endswith("-SWAP") for s in symbols)


def _strategy_cost_request_for_backtest(
    request: BacktestRequest,
    strategy_info: Dict[str, Any],
) -> BacktestRequest:
    cfg = strategy_info.get("db_config") or {}
    cfg = cfg if isinstance(cfg, dict) else {}
    is_swap = _is_swap_strategy_for_backtest(strategy_info)
    default_schedule = default_fee_schedule(request.exchange, "swap" if is_swap else "spot")
    default_maker = default_schedule.maker_fee_bps
    default_taker = default_schedule.taker_fee_bps

    cfg_maker_bps = _float_or_none(cfg.get("maker_fee_bps"))
    cfg_taker_bps = _float_or_none(cfg.get("taker_fee_bps"))
    cfg_fee_bps = _float_or_none(cfg.get("fee_bps"))
    cfg_commission_bps = _legacy_rate_or_percent_to_bps(cfg.get("commission_rate"))
    cfg_slippage_bps = _float_or_none(cfg.get("slippage_bps"))
    cfg_slippage_rate_bps = _legacy_rate_or_percent_to_bps(cfg.get("slippage_rate"))

    req_maker_bps = _float_or_none(request.maker_fee_bps)
    req_taker_bps = _float_or_none(request.taker_fee_bps)
    req_slippage_bps = _float_or_none(request.slippage_bps)
    req_commission_bps = _legacy_rate_or_percent_to_bps(request.commission)
    req_slippage_rate_bps = _legacy_rate_or_percent_to_bps(request.slippage)

    maker_fee_bps = (
        req_maker_bps
        if req_maker_bps is not None
        else cfg_maker_bps
        if cfg_maker_bps is not None
        else default_maker
    )
    taker_fee_bps = (
        req_taker_bps
        if req_taker_bps is not None
        else cfg_taker_bps
        if cfg_taker_bps is not None
        else cfg_fee_bps
        if cfg_fee_bps is not None
        else req_commission_bps
        if req_commission_bps is not None
        else cfg_commission_bps
        if cfg_commission_bps is not None
        else default_taker
    )
    slippage_bps = (
        req_slippage_bps
        if req_slippage_bps is not None
        else cfg_slippage_bps
        if cfg_slippage_bps is not None
        else req_slippage_rate_bps
        if req_slippage_rate_bps is not None
        else cfg_slippage_rate_bps
        if cfg_slippage_rate_bps is not None
        else DEFAULT_BACKTEST_SLIPPAGE_BPS
    )

    maker_fee_bps = max(0.0, float(maker_fee_bps))
    taker_fee_bps = max(0.0, float(taker_fee_bps))
    slippage_bps = max(0.0, float(slippage_bps))
    return request.model_copy(
        update={
            "maker_fee_bps": maker_fee_bps,
            "taker_fee_bps": taker_fee_bps,
            "slippage_bps": slippage_bps,
            # Backtrader market fills use the taker rate; maker is kept for
            # config fidelity and future limit-order backtest support.
            "commission": taker_fee_bps / 10_000.0,
            "slippage": slippage_bps / 10_000.0,
        }
    )


def _request_with_strategy_timeframe(
    request: BacktestRequest,
    strategy_info: Dict[str, Any],
) -> BacktestRequest:
    return request.model_copy(
        update={"timeframe": _strategy_timeframe_for_backtest(strategy_info, request)}
    )


def _backtest_date_range_ms(request: BacktestRequest) -> tuple[int, int]:
    start_ts = int(datetime.strptime(request.start_date, "%Y-%m-%d").timestamp() * 1000)
    end_ts = int(datetime.strptime(request.end_date, "%Y-%m-%d").timestamp() * 1000)
    return start_ts, end_ts


def _batch_backtest_data_skip_reason(
    strategy_info: Dict[str, Any],
    request: BacktestRequest,
) -> Optional[str]:
    """
    Batch creation should avoid creating jobs that are already known to lack local
    real K-line coverage. Single backtests still keep their existing fetch/fail path.
    """
    try:
        start_ts, end_ts = _backtest_date_range_ms(request)
    except Exception:
        return None

    missing: List[str] = []
    symbols = _strategy_symbols_for_backtest(strategy_info, request)
    timeframes = _strategy_timeframes_for_backtest(strategy_info, request)
    for timeframe in timeframes:
        for symbol in symbols:
            try:
                raw_df = backtrader_engine._read_cached_dataframe(
                    request.exchange,
                    symbol,
                    timeframe,
                    start_ts,
                    end_ts,
                )
                needs_fetch = backtrader_engine._needs_fetch_for_range(
                    raw_df,
                    start_ts,
                    end_ts,
                    timeframe,
                )
            except Exception as exc:
                logger.warning(
                    "批量回测数据预检失败: %s %s %s %s",
                    request.exchange,
                    symbol,
                    timeframe,
                    exc,
                )
                missing.append(f"{symbol} {timeframe}: 数据预检失败 {exc}")
                continue

            if not needs_fetch:
                continue

            try:
                first_ts, last_ts = backtrader_engine._dataframe_ts_range(raw_df)
                expected = backtrader_engine._expected_bar_count(start_ts, end_ts, timeframe)
                actual = len(raw_df)
                cached_range = (
                    f"{backtrader_engine._format_ts(first_ts)} ~ "
                    f"{backtrader_engine._format_ts(last_ts)}"
                )
            except Exception:
                expected = 0
                actual = len(raw_df) if raw_df is not None else 0
                cached_range = "未知"
            missing.append(
                f"{symbol} {timeframe}: 本地真实 K 线覆盖不足"
                f"（期望约 {expected} 根，实际 {actual} 根，缓存范围 {cached_range}）"
            )

    if not missing:
        return None
    preview = "；".join(missing[:3])
    if len(missing) > 3:
        preview = f"{preview}；另有 {len(missing) - 3} 个缺口"
    return f"批量回测跳过：{preview}。请先同步完整历史 K 线或缩短日期后单独回测。"


def _save_report_to_db(
    report: BacktestReport,
    strategy_id: int,
    trades_list: List[dict],
    start_date: str,
    end_date: str,
    initial_capital: float,
    *,
    timeframe: Optional[str] = None,
    timeframe_mode: Optional[str] = None,
    matrix_results: Optional[List[Dict[str, Any]]] = None,
    result_payload: Optional[Dict[str, Any]] = None,
):
    """BacktestReport 落库。"""
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        trades_json = json.dumps(trades_list, ensure_ascii=False)
        matrix_results_json = (
            json.dumps(matrix_results, ensure_ascii=False)
            if matrix_results
            else None
        )
        result_json = (
            json.dumps(result_payload, ensure_ascii=False)
            if result_payload
            else None
        )

        cursor.execute(
            """
            INSERT INTO backtest_results
            (strategy_id, start_date, end_date, initial_capital, final_capital,
             total_return, annual_return, max_drawdown, sharpe_ratio, win_rate,
             profit_factor, total_trades, trades_detail, timeframe, timeframe_mode,
             matrix_results_json, result_json, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                strategy_id,
                start_date,
                end_date,
                float(initial_capital),
                float(report.final_capital),
                float(report.total_return_pct),
                float(report.annual_return_pct),
                float(report.max_drawdown_pct),
                float(report.sharpe_ratio),
                float(report.win_rate_pct),
                float(report.profit_factor),
                int(report.total_trades),
                trades_json,
                timeframe,
                timeframe_mode,
                matrix_results_json,
                result_json,
                report.status,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error("保存 BaseStrategy 回测结果失败: %s", e)


def _insert_backtest_job(
    job_id: str,
    strategy_id: int,
    request: BacktestRequest,
    *,
    owner_role: str | None = None,
    owner_session_id: str | None = None,
    owner_guest_code_id: int | None = None,
) -> None:
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO backtest_jobs (
            job_id, strategy_id, request_json, status, current_bar, total_bars,
            owner_role, owner_session_id, owner_guest_code_id
        ) VALUES (?, ?, ?, 'pending', 0, 0, ?, ?, ?)
        """,
        (job_id, strategy_id, request.model_dump_json(), owner_role, owner_session_id, owner_guest_code_id),
    )
    conn.commit()
    conn.close()


def _auth_context(request: Request) -> Dict[str, Any]:
    return dict(getattr(request.state, "auth", None) or {})


def _auth_service_for_request(request: Request):
    return getattr(request.state, "auth_service", auth_service)


def _ensure_backtest_job_access(row: Any, auth: Dict[str, Any]) -> None:
    if auth.get("role") != "guest":
        return
    if row is None:
        return
    if str(row["owner_session_id"] or "") != str(auth.get("session_id") or ""):
        raise HTTPException(status_code=403, detail="访客只能查看或管理自己创建的回测任务")


_BACKTEST_PROGRESS_WRITE_INTERVAL_SEC = 1.0
_SQLITE_LOCK_RETRY_ATTEMPTS = 4
_SQLITE_LOCK_RETRY_BASE_DELAY_SEC = 0.2


def _execute_with_sqlite_lock_retry(operation, *, attempts: int = _SQLITE_LOCK_RETRY_ATTEMPTS, base_delay: float = _SQLITE_LOCK_RETRY_BASE_DELAY_SEC):
    """Run a SQLite write, retrying transient "database is locked" errors.

    Backtest worker subprocesses update job rows at high frequency while the
    main process keeps writing sessions/paper trades; under WAL those writers
    still serialize. Retrying with backoff turns spurious lock timeouts into
    successful writes instead of dropped progress updates (prod review 2026-08-24).
    """
    for attempt in range(attempts):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc).lower() or attempt == attempts - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))


class _ProgressWriter:
    """Throttle per-bar progress writes to at most one DB hit per interval."""

    def __init__(self, interval_sec: float = _BACKTEST_PROGRESS_WRITE_INTERVAL_SEC) -> None:
        self.interval_sec = float(interval_sec)
        self._last_write = float("-inf")

    def should_write(self, now: float, *, force: bool = False) -> bool:
        if force or (now - self._last_write) >= self.interval_sec:
            self._last_write = now
            return True
        return False


def _make_progress_hook(
    *,
    job_id: str,
    cancel_requested,
    completed_before,
    total_ref,
):
    """Build a throttled Backtrader progress hook for a backtest job."""
    writer = _ProgressWriter()

    def progress_hook(cur: int, total: int) -> None:
        cancelled = cancel_requested()
        # Cancellation and final-bar transitions must always be persisted;
        # intermediate running ticks are throttled to one write per interval.
        is_final = bool(total) and cur >= int(total)
        if not writer.should_write(time.monotonic(), force=cancelled or is_final):
            return
        try:
            if cancelled:
                _update_backtest_job(
                    job_id,
                    status="cancelling",
                    current_bar=completed_before() + cur,
                    total_bars=total_ref() or total,
                    message="用户请求停止回测，正在安全结束",
                )
                return
            _update_backtest_job(
                job_id,
                status="running",
                current_bar=completed_before() + cur,
                total_bars=total_ref() or total,
            )
        except Exception:
            pass

    return progress_hook


def _update_backtest_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return

    def _write() -> None:
        conn = db.get_connection()
        cursor = conn.cursor()
        cols = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values())
        vals.append(job_id)
        cursor.execute(
            f"UPDATE backtest_jobs SET {cols}, updated_at = datetime('now') WHERE job_id = ?",
            vals,
        )
        conn.commit()
        conn.close()

    _execute_with_sqlite_lock_retry(_write)


def _run_backtest_job_worker(job_id: str, payload: Dict[str, Any]) -> None:
    """执行回测并通过 progress_hook 写入 backtest_jobs。"""
    try:
        request = BacktestRequest(**payload)
        if _is_backtest_cancel_requested(job_id):
            raise BacktestCancelled("用户已停止回测")

        strategy_info = get_strategy_for_id(request.strategy_id)
        if not strategy_info:
            keys = sorted(get_base_strategy_registry().keys())
            _update_backtest_job(
                job_id,
                status="failed",
                error_message=(
                    f"策略 #{request.strategy_id} 无法解析为 BaseStrategy；"
                    f"已注册键: {keys}"
                ),
            )
            return

        strategy_name = strategy_info.get("name", "")
        strategy_class = strategy_info["strategy_class"]
        db_config = strategy_info.get("db_config") or {}
        requested_timeframes = _strategy_timeframes_for_backtest(strategy_info, request)
        request = _strategy_cost_request_for_backtest(request, strategy_info)
        symbols = _strategy_symbols_for_backtest(strategy_info, request)
        matrix_mode = _backtest_timeframe_mode(request) == "matrix" and len(requested_timeframes) > 1

        completed_bars_before_current_run = 0
        total_bars_across_runs = 0

        progress_hook = _make_progress_hook(
            job_id=job_id,
            cancel_requested=lambda: _is_backtest_cancel_requested(job_id),
            completed_before=lambda: completed_bars_before_current_run,
            total_ref=lambda: total_bars_across_runs,
        )

        _update_backtest_job(job_id, status="running", message=None)
        matrix_responses: List[Dict[str, Any]] = []
        primary_report: Optional[BacktestReport] = None
        primary_request: Optional[BacktestRequest] = None

        for timeframe in requested_timeframes:
            if _is_backtest_cancel_requested(job_id):
                raise BacktestCancelled("用户已停止回测")
            run_request = request.model_copy(
                update={
                    "timeframe": timeframe,
                    "timeframe_mode": "single" if not matrix_mode else "matrix",
                    "timeframes": requested_timeframes if matrix_mode else None,
                }
            )
            report = backtrader_engine.run_strategy(
                strategy_class=strategy_class,
                exchange=run_request.exchange,
                symbol=symbols[0],
                symbols=symbols,
                timeframe=timeframe,
                start_date=run_request.start_date,
                end_date=run_request.end_date,
                initial_capital=run_request.initial_capital,
                commission=run_request.commission,
                slippage=run_request.slippage,
                strategy_config=_strategy_config_for_backtest(db_config, timeframe),
                progress_hook=progress_hook,
                cancel_check=lambda: _is_backtest_cancel_requested(job_id),
            )
            completed_bars_before_current_run += int(report.total_bars or 0)
            total_bars_across_runs += int(report.total_bars or 0)
            response = _backtest_report_to_response(
                report, request.strategy_id, strategy_name, run_request
            )
            matrix_responses.append(response.model_dump(mode="json"))
            if primary_report is None or _safe_float(report.total_return_pct) >= _safe_float(primary_report.total_return_pct):
                primary_report = report
                primary_request = run_request
        if primary_report is None or primary_request is None:
            raise ValueError("没有可执行的回测周期")
        report = primary_report
        request = primary_request
    except ValueError as e:
        _update_backtest_job(
            job_id,
            status="failed",
            error_message=str(e),
        )
        return
    except BacktestCancelled:
        _update_backtest_job(
            job_id,
            status="cancelled",
            message="用户已停止回测",
            error_message=None,
        )
        return
    except Exception as e:
        logger.exception("backtest job %s failed", job_id)
        _update_backtest_job(
            job_id,
            status="failed",
            error_message=str(e),
        )
        return
    else:
        response = _backtest_report_to_response(
            report, request.strategy_id, strategy_name, request
        )
        if matrix_mode:
            response.timeframe_mode = "matrix"
            response.matrix_results = matrix_responses
        result_dict = response.model_dump(mode="json")

        # 零交易诊断：把"为什么没交易"写进 job message，避免静默空转（issue #707）。
        zero_trade_message: Optional[str] = None
        if not int(response.total_trades or 0):
            diagnostics = dict(response.diagnostics or {})
            if matrix_mode and matrix_responses:
                matrix_trades = sum(int(item.get("total_trades") or 0) for item in matrix_responses)
                if matrix_trades:
                    diagnostics = {}
            if diagnostics:
                parts = [
                    f"喂入标的 {diagnostics.get('universe_size', '?')} 个",
                    f"成功加载 {diagnostics.get('loaded_symbols', '?')} 个",
                ]
                skipped = diagnostics.get("skipped_symbols") or []
                if skipped:
                    parts.append(f"跳过缺数据 {len(skipped)} 个")
                if "candidate_count" in diagnostics:
                    parts.append(f"候选 {diagnostics.get('candidate_count', 0)} 个")
                if "pool_members" in diagnostics:
                    parts.append(f"池成员 {diagnostics.get('pool_members', 0)} 个")
                breaker = diagnostics.get("circuit_breaker") or {}
                if breaker.get("active"):
                    triggered_at = breaker.get("triggered_at")
                    if triggered_at:
                        try:
                            triggered_str = datetime.utcfromtimestamp(float(triggered_at)).strftime("%Y-%m-%d %H:%M UTC")
                        except (TypeError, ValueError):
                            triggered_str = "未知时间"
                    else:
                        triggered_str = "未知时间"
                    parts.append(
                        f"组合总回撤熔断（{breaker.get('reason', '')}）于 {triggered_str} 触发后停机，"
                        "剩余区间无交易"
                    )
                zero_trade_message = "回测完成但 0 笔交易：" + "、".join(parts)

        if report.status == "completed":
            _save_report_to_db(
                report,
                request.strategy_id,
                response.trades or [],
                request.start_date,
                request.end_date,
                request.initial_capital,
                timeframe=response.timeframe,
                timeframe_mode=response.timeframe_mode,
                matrix_results=response.matrix_results,
                result_payload=result_dict,
            )

        _update_backtest_job(
            job_id,
            status=report.status,
            current_bar=report.total_bars,
            total_bars=report.total_bars,
            result_json=json.dumps(result_dict, ensure_ascii=False),
            message=zero_trade_message,
            error_message=report.error_message if report.status == "failed" else None,
        )
    finally:
        _clear_backtest_cancel(job_id)
        _clear_backtest_active(job_id)


def _backtest_worker_env() -> Dict[str, str]:
    env = os.environ.copy()
    backend_path = str(_BACKEND_DIR)
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{backend_path}{os.pathsep}{pythonpath}" if pythonpath else backend_path
    return env


def _mark_backtest_job_failed_if_open(job_id: str, message: str) -> None:
    status = _read_backtest_job_status(job_id)
    if status not in _TERMINAL_BACKTEST_STATUSES:
        _update_backtest_job(job_id, status="failed", error_message=message)


async def _stop_backtest_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


async def _run_backtest_job_task(job_id: str, payload: Dict[str, Any]) -> None:
    payload_json = json.dumps(payload, ensure_ascii=False)
    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            _BACKTEST_WORKER_MODULE,
            job_id,
            payload_json,
            cwd=str(_BACKEND_DIR),
            env=_backtest_worker_env(),
        )
        returncode = await process.wait()
        if returncode != 0:
            message = f"回测工作进程异常退出（退出码 {returncode}）"
            logger.error("%s: %s", message, job_id)
            _mark_backtest_job_failed_if_open(job_id, message)
    except asyncio.CancelledError:
        if process is not None:
            await _stop_backtest_process(process)
        _update_backtest_job(
            job_id,
            status="interrupted",
            message="回测工作进程已随服务停止",
            error_message=None,
        )
        raise
    except Exception as exc:
        message = f"回测工作进程启动失败: {exc}"
        logger.exception("backtest job %s subprocess failed", job_id)
        _mark_backtest_job_failed_if_open(job_id, message)
    finally:
        _clear_backtest_cancel(job_id)
        _clear_backtest_active(job_id)


async def _run_scheduled_backtest_job_task(job_id: str, payload: Dict[str, Any]) -> None:
    try:
        async with _BATCH_BACKTEST_SEMAPHORE:
            await _run_backtest_job_task(job_id, payload)
    except asyncio.CancelledError:
        _update_backtest_job(
            job_id,
            status="interrupted",
            message="回测任务调度已中断",
            error_message=None,
        )
        _clear_backtest_cancel(job_id)
        _clear_backtest_active(job_id)
        raise
    except Exception as exc:
        logger.exception("scheduled backtest job %s failed before worker completed", job_id)
        _update_backtest_job(
            job_id,
            status="failed",
            error_message=str(exc),
        )
        _clear_backtest_cancel(job_id)
        _clear_backtest_active(job_id)
        raise


def _on_scheduled_backtest_job_done(task: asyncio.Task[None]) -> None:
    _SCHEDULED_BACKTEST_TASKS.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        logger.warning("scheduled backtest job task was cancelled")
    except Exception:
        logger.exception("scheduled backtest job task failed")


def _schedule_backtest_job_task(job_id: str, payload: Dict[str, Any]) -> None:
    task = asyncio.create_task(
        _run_scheduled_backtest_job_task(job_id, payload),
        name=f"backtest-job-{job_id}",
    )
    _SCHEDULED_BACKTEST_TASKS.add(task)
    task.add_done_callback(_on_scheduled_backtest_job_done)


def _job_row_to_response(row) -> Dict[str, Any]:
    d = {k: row[k] for k in row.keys()}
    request = None
    request_json = d.get("request_json")
    if request_json:
        try:
            request = json.loads(request_json)
        except json.JSONDecodeError:
            request = None
    tb = int(d.get("total_bars") or 0)
    cb = int(d.get("current_bar") or 0)
    pct = round(100.0 * min(cb, tb) / tb, 2) if tb > 0 else None
    status = str(d["status"] or "")
    resumable = status in _RESUMABLE_BACKTEST_STATUSES and not _is_backtest_active(str(d["job_id"]))
    response = {
        "job_id": d["job_id"],
        "strategy_id": d["strategy_id"],
        "status": status,
        "current_bar": cb,
        "total_bars": tb,
        "percent": pct,
        "message": d.get("message"),
        "request": request,
        "error_message": d.get("error_message"),
        "updated_at": str(d.get("updated_at")) if d.get("updated_at") is not None else None,
        "resumable": resumable,
    }
    if "result_json" in d:
        result = None
        rj = d.get("result_json")
        if rj:
            try:
                result = json.loads(rj)
            except json.JSONDecodeError:
                result = None
        response["result"] = result
    return response


_BACKTEST_MATRIX_LIST_FIELDS = {
    "timeframe",
    "status",
    "initial_capital",
    "final_capital",
    "total_return",
    "annual_return",
    "max_drawdown",
    "sharpe_ratio",
    "win_rate",
    "profit_factor",
    "total_trades",
}


def _backtest_matrix_result_list_summary(item: Any) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {key: item.get(key) for key in _BACKTEST_MATRIX_LIST_FIELDS if key in item}


def _backtest_result_row_to_response(row, *, include_matrix_detail: bool = True) -> Dict[str, Any]:
    result = dict(row)
    matrix_results_json = result.pop("matrix_results_json", None)
    result.pop("result_json", None)
    if matrix_results_json:
        try:
            matrix_results = json.loads(matrix_results_json)
        except json.JSONDecodeError:
            matrix_results = []
    else:
        matrix_results = []

    if include_matrix_detail:
        result["matrix_results"] = matrix_results
    else:
        result["matrix_results"] = [
            summary
            for item in matrix_results
            if (summary := _backtest_matrix_result_list_summary(item))
        ]
        if matrix_results and not result["matrix_results"]:
            result["matrix_results"] = [
                {"timeframe": item.get("timeframe")}
                for item in matrix_results
                if isinstance(item, dict) and item.get("timeframe")
            ]
    if not result.get("matrix_results"):
        result["matrix_results"] = []
    return result


def _backtest_results_order_sql(sort_by: str, sort_dir: str) -> str:
    direction = "ASC" if sort_dir == "asc" else "DESC"
    tie_direction = direction if sort_by == "created" else "DESC"
    if sort_by == "return":
        return f"br.total_return IS NULL ASC, br.total_return {direction}, br.created_at DESC, br.id DESC"
    if sort_by == "drawdown":
        return f"br.max_drawdown IS NULL ASC, br.max_drawdown {direction}, br.created_at DESC, br.id DESC"
    if sort_by == "win_rate":
        return f"br.win_rate IS NULL ASC, br.win_rate {direction}, br.created_at DESC, br.id DESC"
    return f"br.created_at {direction}, br.id {tie_direction}"


def _backtest_results_search_sql(search: str | None) -> tuple[list[str], list[Any]]:
    tokens = [token for token in (search or "").strip().lower().split() if token]
    if not tokens:
        return [], []
    fields = [
        "CAST(br.id AS TEXT)",
        "CAST(br.strategy_id AS TEXT)",
        "LOWER(COALESCE(br.start_date, ''))",
        "LOWER(COALESCE(br.end_date, ''))",
        "LOWER(COALESCE(br.timeframe, ''))",
        "LOWER(COALESCE(br.timeframe_mode, ''))",
        "LOWER(COALESCE(br.status, ''))",
        "LOWER(COALESCE(s.name, ''))",
        "LOWER(COALESCE(s.description, ''))",
        "LOWER(COALESCE(s.symbols, ''))",
        "LOWER(COALESCE(s.config, ''))",
    ]
    clauses: list[str] = []
    params: list[Any] = []
    for token in tokens:
        pattern = f"%{token}%"
        clauses.append(f"({' OR '.join(f'{field} LIKE ?' for field in fields)})")
        params.extend([pattern] * len(fields))
    return clauses, params


# ============================================
# API 端点
# ============================================

# ============================================
# 新架构 BaseStrategy 回测请求/响应
# ============================================

class NewBacktestRequest(BaseModel):
    """BaseStrategy 子类回测请求"""
    strategy_name: str = "kairos_30m_horizon_dca"
    exchange: str = "okx"
    symbol: str = "BTC/USDT"
    timeframe: str = "1m"
    start_date: str = "2026-03-01"
    end_date: str = "2026-04-20"
    initial_capital: float = 10000
    commission: float = 0.0004
    slippage: float = 0.0001
    config: Optional[Dict[str, Any]] = None


def _report_to_dict(report: BacktestReport) -> Dict[str, Any]:
    """将 BacktestReport dataclass 转为 JSON-friendly dict。"""
    d = asdict(report)
    for key in ("total_return_pct", "annual_return_pct", "max_drawdown_pct",
                "sharpe_ratio", "sortino_ratio", "calmar_ratio", "win_rate_pct",
                "profit_factor", "total_fees", "avg_holding_bars", "elapsed_seconds"):
        v = d.get(key)
        if v is not None and isinstance(v, float):
            if np.isnan(v) or np.isinf(v):
                d[key] = 0.0
    return d


@router.post("/run_new")
async def run_new_backtest(request: NewBacktestRequest):
    """
    运行新架构 BaseStrategy 子类回测。

    返回 JSON 报告，包含：
    - 基础指标（收益率/回撤/夏普/胜率等）
    - equity_curve 数组（前端可直接喂 ECharts）
    - trades 逐笔交易明细
    """
    _validate_backtest_date_range(request.start_date, request.end_date)
    _ensure_new_registry()

    strategy_class = _NEW_STRATEGY_REGISTRY.get(request.strategy_name)
    if not strategy_class:
        available = list(_NEW_STRATEGY_REGISTRY.keys())
        raise HTTPException(
            status_code=400,
            detail=f"策略 '{request.strategy_name}' 未注册。可用策略: {available}",
        )

    try:
        report = await asyncio.to_thread(
            backtrader_engine.run_strategy,
            strategy_class=strategy_class,
            exchange=request.exchange,
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            commission=request.commission,
            slippage=request.slippage,
            strategy_config=request.config,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("run_new_backtest failed")
        raise HTTPException(status_code=500, detail=f"回测执行异常: {e}")

    return _report_to_dict(report)


# ============================================
# 按 strategy_id 回测（与实盘同一 BaseStrategy 解析）
# ============================================

@router.post("/run_sync", response_model=BacktestResultResponse)
async def run_backtest_sync(request: BacktestRequest):
    """运行回测 (同步)，仅 BaseStrategy 路径。"""
    _validate_backtest_date_range(request.start_date, request.end_date)
    strategy_info = get_strategy_for_id(request.strategy_id)
    if not strategy_info:
        keys = sorted(get_base_strategy_registry().keys())
        raise HTTPException(
            status_code=400,
            detail=(
                f"策略 #{request.strategy_id} 无法解析为 BaseStrategy。"
                f"请补全 config.strategy_key、执行 python scripts/repair_strategy_keys.py，"
                f"或删除废弃行后重新导入 data/seed/strategies.json。"
                f" 已注册的键: {keys}。"
            ),
        )

    strategy_name = strategy_info.get("name", "")
    strategy_class = strategy_info["strategy_class"]
    db_config = strategy_info.get("db_config") or {}
    request = _request_with_strategy_timeframe(request, strategy_info)
    request = _strategy_cost_request_for_backtest(request, strategy_info)
    symbols = _strategy_symbols_for_backtest(strategy_info, request)
    strategy_config = _strategy_config_for_backtest(db_config, request.timeframe or "1h")
    try:
        report = await asyncio.to_thread(
            backtrader_engine.run_strategy,
            strategy_class=strategy_class,
            exchange=request.exchange,
            symbol=symbols[0],
            symbols=symbols,
            timeframe=request.timeframe,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            commission=request.commission,
            slippage=request.slippage,
            strategy_config=strategy_config,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    response = _backtest_report_to_response(
        report, request.strategy_id, strategy_name, request
    )
    result_dict = response.model_dump(mode="json")
    if report.status == "completed":
        _save_report_to_db(
            report,
            request.strategy_id,
            response.trades or [],
            request.start_date,
            request.end_date,
            request.initial_capital,
            timeframe=response.timeframe,
            timeframe_mode=response.timeframe_mode,
            matrix_results=response.matrix_results,
            result_payload=result_dict,
        )
    return response


@router.post("/run")
async def run_backtest(request: BacktestRequest):
    """
    运行回测 (异步) — 实际上 v2 引擎很快，直接同步返回
    """
    return await run_backtest_sync(request)


@router.post("/run_job")
async def start_backtest_job(
    request: Request,
    payload: BacktestRequest,
    background_tasks: BackgroundTasks,
):
    """
    异步回测：立即返回 job_id，进度写入 SQLite ``backtest_jobs``。
    前端可轮询 ``GET /backtest/job/{job_id}``；进程重启后运行中任务会标为 interrupted，
    仍可读取最后一次 current_bar / total_bars。
    """
    auth = _auth_context(request)
    try:
        _auth_service_for_request(request).check_guest_backtest_quota(
            auth,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    _validate_backtest_date_range(payload.start_date, payload.end_date)
    strategy_info = get_strategy_for_id(payload.strategy_id)
    if not strategy_info:
        keys = sorted(get_base_strategy_registry().keys())
        raise HTTPException(
            status_code=400,
            detail=(
                f"策略 #{payload.strategy_id} 无法解析为 BaseStrategy。"
                f"请补全 config.strategy_key、执行 python scripts/repair_strategy_keys.py，"
                f"或删除废弃行后重新导入 data/seed/strategies.json。"
                f" 已注册的键: {keys}。"
            ),
        )

    payload = _request_with_strategy_timeframe(payload, strategy_info)
    payload = _strategy_cost_request_for_backtest(payload, strategy_info)
    job_id = str(uuid.uuid4())
    _insert_backtest_job(
        job_id,
        payload.strategy_id,
        payload,
        owner_role=auth.get("role"),
        owner_session_id=auth.get("session_id"),
        owner_guest_code_id=auth.get("guest_code_id"),
    )
    _try_mark_backtest_active(job_id)
    background_tasks.add_task(_run_backtest_job_task, job_id, payload.model_dump())
    return {"job_id": job_id}


@router.post("/run_running_strategies")
async def start_running_strategies_backtest_jobs(
    request: Request,
    payload: Optional[RunningStrategiesBacktestRequest] = Body(default=None),
):
    """
    便捷批量入口：为当前运行中的模拟策略创建普通异步回测任务。

    默认回测区间为当前日期往前 1 年到昨日，默认资金 100U；实际回测执行、周期解析、
    手续费和滑点默认值继续复用单个回测任务的既有逻辑。
    """
    batch = payload or RunningStrategiesBacktestRequest()
    start_date, end_date = batch.start_date, batch.end_date
    default_start, default_end = _default_running_strategy_batch_dates()
    start_date = start_date or default_start
    end_date = end_date or default_end
    if batch.initial_capital <= 0:
        raise HTTPException(status_code=400, detail="批量回测初始资金必须大于 0")

    _validate_backtest_date_range(start_date, end_date)
    auth = _auth_context(request)
    running_rows = [
        row for row in db.get_strategies()
        if str(row.get("status") or "").strip().lower() == "running"
    ]
    jobs: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for row in running_rows:
        try:
            strategy_id = int(row.get("id"))
        except (TypeError, ValueError):
            skipped.append(_batch_backtest_skip_item(row, "策略 ID 无效"))
            continue

        skip_reason = _running_strategy_batch_skip_reason(row)
        if skip_reason:
            skipped.append(_batch_backtest_skip_item(row, skip_reason))
            continue

        strategy_info = get_strategy_for_id(strategy_id)
        if not strategy_info:
            skipped.append(_batch_backtest_skip_item(row, "策略无法解析为 BaseStrategy"))
            continue

        request_payload = BacktestRequest(
            strategy_id=strategy_id,
            exchange=batch.exchange,
            start_date=start_date,
            end_date=end_date,
            initial_capital=float(batch.initial_capital),
            timeframe_mode="strategy",
            maker_fee_bps=batch.maker_fee_bps,
            taker_fee_bps=batch.taker_fee_bps,
            slippage_bps=batch.slippage_bps,
        )
        try:
            _auth_service_for_request(request).check_guest_backtest_quota(
                auth,
                start_date=request_payload.start_date,
                end_date=request_payload.end_date,
            )
        except AuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

        request_payload = _request_with_strategy_timeframe(request_payload, strategy_info)
        request_payload = _strategy_cost_request_for_backtest(request_payload, strategy_info)
        data_skip_reason = _batch_backtest_data_skip_reason(strategy_info, request_payload)
        if data_skip_reason:
            skipped.append(_batch_backtest_skip_item(row, data_skip_reason))
            continue

        job_id = str(uuid.uuid4())
        _insert_backtest_job(
            job_id,
            strategy_id,
            request_payload,
            owner_role=auth.get("role"),
            owner_session_id=auth.get("session_id"),
            owner_guest_code_id=auth.get("guest_code_id"),
        )
        _try_mark_backtest_active(job_id)
        _schedule_backtest_job_task(job_id, request_payload.model_dump())
        jobs.append({
            "job_id": job_id,
            "strategy_id": strategy_id,
            "strategy_name": strategy_info.get("name") or row.get("name"),
            "status": "pending",
            "request": request_payload.model_dump(mode="json"),
        })

    return {
        "count": len(jobs),
        "skipped_count": len(skipped),
        "defaults": {
            "start_date": start_date,
            "end_date": end_date,
            "initial_capital": float(batch.initial_capital),
            "timeframe_mode": "strategy",
        },
        "jobs": jobs,
        "skipped": skipped,
    }


@router.get("/jobs")
async def get_backtest_jobs(
    request: Request,
    strategy_id: Optional[int] = Query(None, description="策略ID"),
    status: Optional[str] = Query(None, description="任务状态"),
    limit: int = Query(50, ge=1, le=200),
    include_result: bool = Query(False, description="是否返回完整任务结果"),
):
    conn = db.get_connection()
    cursor = conn.cursor()
    conditions: List[str] = []
    params: List[Any] = []
    if strategy_id is not None:
        conditions.append("strategy_id = ?")
        params.append(strategy_id)
    if status:
        statuses = [item.strip() for item in status.split(",") if item.strip()]
        if statuses:
            conditions.append(f"status IN ({','.join('?' for _ in statuses)})")
            params.extend(statuses)
    auth = _auth_context(request)
    if auth.get("role") == "guest":
        conditions.append("owner_session_id = ?")
        params.append(auth.get("session_id"))

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    result_column = ", result_json" if include_result else ""
    cursor.execute(
        f"""
        SELECT job_id, strategy_id, request_json, status, current_bar, total_bars,
               message, error_message, updated_at, owner_role, owner_session_id,
               owner_guest_code_id{result_column}
        FROM backtest_jobs
        {where_sql}
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        [*params, limit],
    )
    rows = cursor.fetchall()
    conn.close()
    return [_job_row_to_response(row) for row in rows]


@router.get("/job/{job_id}")
async def get_backtest_job_status(job_id: str, request: Request):
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT job_id, strategy_id, status, current_bar, total_bars, message,
               result_json, error_message, updated_at, owner_role, owner_session_id,
               owner_guest_code_id
        FROM backtest_jobs WHERE job_id = ?
        """,
        (job_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="回测任务不存在")
    _ensure_backtest_job_access(row, _auth_context(request))
    return _job_row_to_response(row)


@router.post("/job/{job_id}/cancel")
async def cancel_backtest_job(job_id: str, request: Request):
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT job_id, strategy_id, status, current_bar, total_bars, message,
               result_json, error_message, updated_at, owner_role, owner_session_id,
               owner_guest_code_id
        FROM backtest_jobs WHERE job_id = ?
        """,
        (job_id,),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="回测任务不存在")
    _ensure_backtest_job_access(row, _auth_context(request))

    status = str(row["status"] or "")
    if status in _TERMINAL_BACKTEST_STATUSES:
        conn.close()
        _clear_backtest_cancel(job_id)
        return _job_row_to_response(row)
    if status not in _CANCELLABLE_BACKTEST_STATUSES:
        conn.close()
        raise HTTPException(status_code=409, detail=f"当前回测状态不可停止: {status}")

    _request_backtest_cancel(job_id)
    cursor.execute(
        """
        UPDATE backtest_jobs
        SET status = 'cancelling',
            message = '用户请求停止回测，正在安全结束',
            updated_at = datetime('now')
        WHERE job_id = ?
        """,
        (job_id,),
    )
    conn.commit()
    cursor.execute(
        """
        SELECT job_id, strategy_id, status, current_bar, total_bars, message,
               result_json, error_message, updated_at, owner_role, owner_session_id,
               owner_guest_code_id
        FROM backtest_jobs WHERE job_id = ?
        """,
        (job_id,),
    )
    updated = cursor.fetchone()
    conn.close()
    return _job_row_to_response(updated)


@router.post("/job/{job_id}/resume")
async def resume_backtest_job(job_id: str, request: Request, background_tasks: BackgroundTasks):
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT job_id, strategy_id, request_json, status, current_bar, total_bars,
               message, result_json, error_message, updated_at, owner_role,
               owner_session_id, owner_guest_code_id
        FROM backtest_jobs WHERE job_id = ?
        """,
        (job_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="回测任务不存在")
    _ensure_backtest_job_access(row, _auth_context(request))

    status = str(row["status"] or "")
    if _is_backtest_active(job_id):
        return _job_row_to_response(row)
    if status == "completed":
        raise HTTPException(status_code=409, detail="回测任务已完成，无需继续")
    if status == "cancelled":
        raise HTTPException(status_code=409, detail="回测任务已停止，请重新创建回测")
    if status not in _RESUMABLE_BACKTEST_STATUSES:
        raise HTTPException(status_code=409, detail=f"当前回测状态不可继续: {status}")

    try:
        payload = json.loads(row["request_json"] or "{}")
        request = BacktestRequest(**payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"回测任务参数损坏，无法继续: {exc}") from exc

    _validate_backtest_date_range(request.start_date, request.end_date)
    if not _try_mark_backtest_active(job_id):
        return _job_row_to_response(row)

    _clear_backtest_cancel(job_id)
    _update_backtest_job(
        job_id,
        status="pending",
        current_bar=0,
        total_bars=0,
        message="已继续回测，正在重新排队执行",
        result_json=None,
        error_message=None,
    )
    background_tasks.add_task(_run_backtest_job_task, job_id, request.model_dump())

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT job_id, strategy_id, status, current_bar, total_bars, message,
               result_json, error_message, updated_at, owner_role, owner_session_id,
               owner_guest_code_id
        FROM backtest_jobs WHERE job_id = ?
        """,
        (job_id,),
    )
    updated = cursor.fetchone()
    conn.close()
    return _job_row_to_response(updated)


@router.get("/strategies")
async def get_available_strategies():
    """已注册的 BaseStrategy strategy_key 列表。"""
    return list_backtestable_registry_keys()


@router.get("/results")
async def get_backtest_results(
    strategy_id: int = Query(None, description="策略ID"),
    q: str = Query("", description="按策略名、标的、周期、状态、日期模糊搜索"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, description="分页偏移"),
    include_matrix_summary: bool = Query(True, description="是否返回矩阵回测摘要"),
    sort_by: Literal["created", "return", "drawdown", "win_rate"] = Query("created", description="排序字段"),
    sort_dir: Literal["asc", "desc"] = Query("desc", description="排序方向"),
):
    """获取回测结果列表 (从数据库)"""
    conn = db.get_connection()
    cursor = conn.cursor()

    matrix_column = "matrix_results_json" if include_matrix_summary else "NULL AS matrix_results_json"
    order_sql = _backtest_results_order_sql(sort_by, sort_dir)
    where_clauses: list[str] = []
    params: list[Any] = []
    if strategy_id:
        where_clauses.append("br.strategy_id = ?")
        params.append(strategy_id)
    search_clauses, search_params = _backtest_results_search_sql(q)
    where_clauses.extend(search_clauses)
    params.extend(search_params)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    cursor.execute(f'''
        SELECT br.id, br.strategy_id, s.name AS strategy_name, br.start_date, br.end_date, br.initial_capital, br.final_capital,
               br.total_return, br.annual_return, br.max_drawdown, br.sharpe_ratio, br.win_rate,
               br.profit_factor, br.total_trades, br.timeframe, br.timeframe_mode,
               {matrix_column}, br.data_quality_status, br.data_quality_message,
               br.data_quality_checked_at, br.status, br.created_at
        FROM backtest_results br
        LEFT JOIN strategies s ON s.id = br.strategy_id
        {where_sql}
        ORDER BY {order_sql} LIMIT ? OFFSET ?
    ''', (*params, limit, offset))

    rows = cursor.fetchall()
    conn.close()
    return [_backtest_result_row_to_response(row, include_matrix_detail=False) for row in rows]


@router.get("/result/{backtest_id}")
async def get_backtest_result(backtest_id: int):
    """获取回测结果详情"""
    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT br.id, br.strategy_id, s.name AS strategy_name, br.start_date, br.end_date, br.initial_capital, br.final_capital,
               br.total_return, br.annual_return, br.max_drawdown, br.sharpe_ratio, br.win_rate,
               br.profit_factor, br.total_trades, br.trades_detail, br.timeframe, br.timeframe_mode,
               br.matrix_results_json, br.result_json, br.data_quality_status, br.data_quality_message,
               br.data_quality_checked_at, br.status, br.created_at
        FROM backtest_results br
        LEFT JOIN strategies s ON s.id = br.strategy_id
        WHERE br.id = ?
    ''', (backtest_id,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Backtest result not found")

    row_dict = dict(row)
    result_json = row_dict.get("result_json")
    result = _backtest_result_row_to_response(row)
    if result_json:
        try:
            full_result = json.loads(result_json)
        except json.JSONDecodeError:
            full_result = None
        if isinstance(full_result, dict):
            full_result["id"] = result.get("id")
            full_result["created_at"] = result.get("created_at")
            full_result["status"] = result.get("status") or full_result.get("status")
            full_result["timeframe"] = result.get("timeframe") or full_result.get("timeframe")
            full_result["timeframe_mode"] = result.get("timeframe_mode") or full_result.get("timeframe_mode")
            full_result["data_quality_status"] = result.get("data_quality_status")
            full_result["data_quality_message"] = result.get("data_quality_message")
            full_result["data_quality_checked_at"] = result.get("data_quality_checked_at")
            if not full_result.get("strategy_name"):
                full_result["strategy_name"] = result.get("strategy_name")
            if not full_result.get("matrix_results"):
                full_result["matrix_results"] = result.get("matrix_results", [])
            return full_result

    if result.get('trades_detail'):
        result['trades'] = json.loads(result['trades_detail'])
        del result['trades_detail']

    return result


@router.delete("/result/{backtest_id}")
async def delete_backtest_result(backtest_id: int):
    """删除一条已落库回测历史；不影响策略、K 线缓存或回测 job。"""
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM backtest_results WHERE id = ?", (backtest_id,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()

    if deleted <= 0:
        raise HTTPException(status_code=404, detail="Backtest result not found")
    return {"deleted": True, "id": backtest_id}
