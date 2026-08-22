"""Shared models and deterministic helpers for the live API endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import BadRequestError
from app.exchange import exchange_manager
from app.services import live_account_service
from app.services.binance_usdm_contract_broker import resolve_binance_usdm_market
from app.services.contract_paper_account import load_contract_instruments, normalize_contract_symbol
from app.services.strategy_engine import strategy_engine

logger = logging.getLogger(__name__)

_SUPERPNL_STRATEGY_KEY = "superpnl_15m_low_turnover"

_SUPERPNL_DEFAULT_SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "DOGE/USDT",
    "SOL/USDT",
    "XRP/USDT",
    "PEPE/USDT",
    "TRX/USDT",
    "XAUT/USDT",
    "BIO/USDT",
    "PENGU/USDT",
    "PI/USDT",
    "ZKJ/USDT",
    "TRUMP/USDT",
    "SUI/USDT",
    "FIL/USDT",
    "ADA/USDT",
    "APE/USDT",
    "CHZ/USDT",
    "LINK/USDT",
    "LTC/USDT",
]

class LiveConfigureBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    exchange: str = "okx"
    strategy_type: str = Field(..., description="策略 ID（与前端 selectedStrategy 一致）")
    symbol: Optional[str] = None
    initial_equity: float = 1000
    dry_run: bool = True
    loop_interval: Optional[int] = None
    risk_config: Optional[Dict[str, Any]] = None

class PreFlightBody(BaseModel):
    strategy: str
    exchange: str = "okx"
    symbol: Optional[str] = None
    dry_run: bool = True
    capital_pct: Optional[float] = None
    total_capital: Optional[float] = None

class TelegramTestBody(BaseModel):
    message: str = "BitPro test"

class LiveInstanceBody(BaseModel):
    """可选 body：显式指定策略实例 ID，供多实例控制台调用。

    `instance_id` 与 `strategy_type` 都可以指定目标策略（历史上 configure/start
    用 `strategy_type`，stop/pause/resume 用 `instance_id`，字段不一致容易误操作
    到「当前活跃策略」）；两者同时提供时以 `instance_id` 为准。
    """

    model_config = ConfigDict(populate_by_name=True)
    instance_id: Optional[int] = None
    strategy_type: Optional[str] = None
    clear_metrics: bool = False

class PaperPositionCloseBody(BaseModel):
    """模拟盘持仓平仓请求；只允许作用于 paper broker。"""

    model_config = ConfigDict(populate_by_name=True)
    instance_id: Optional[int] = None
    symbol: str
    side: Optional[str] = None
    market_type: Optional[str] = None

class PromoteToLiveBody(BaseModel):
    """模拟转实盘请求；/promote 保持旧克隆兼容，/live-real 使用订阅执行。"""

    model_config = ConfigDict(populate_by_name=True)

    source_strategy_id: int = Field(..., ge=1)
    account_id: Optional[str] = "default"
    exchange: str = "okx"
    initial_equity: Optional[float] = Field(None, gt=0)
    loop_interval: int = Field(60, ge=5)
    start_immediately: bool = True
    confirm_paper_reviewed: bool = False
    confirm_live_risk: bool = False
    risk_config: Optional[Dict[str, Any]] = None

class LiveStrategySettingBody(BaseModel):
    """实盘工作台中间列表设置；加入不会触发真实下单。"""

    model_config = ConfigDict(populate_by_name=True)

    added: Optional[bool] = True
    account_id: Optional[str] = "default"
    bind_account: Optional[bool] = None
    risk_config: Optional[Dict[str, Any]] = None

class LiveStrategyPreflightBody(BaseModel):
    """实盘工作台预检配置。"""

    model_config = ConfigDict(populate_by_name=True)

    account_id: Optional[str] = "default"
    exchange: str = "okx"
    initial_equity: Optional[float] = Field(None, gt=0)
    loop_interval: int = Field(60, ge=5)
    start_immediately: bool = True
    risk_config: Optional[Dict[str, Any]] = None

class LiveStrategyDeployBody(LiveStrategyPreflightBody):
    """实盘工作台部署配置。"""

    confirm_paper_reviewed: bool = False
    confirm_live_risk: bool = False

class LiveStrategySubscriptionControlBody(BaseModel):
    """实盘订阅控制配置；只影响实盘分发，不影响源模拟策略。"""

    model_config = ConfigDict(populate_by_name=True)
    account_id: Optional[str] = "default"

class LiveAccountCreateBody(BaseModel):
    """新增 OKX 或 Binance USD-M 实盘账户。密钥只保存于服务端。"""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    exchange: str = "okx"
    api_key: str
    api_secret: str
    passphrase: Optional[str] = None
    testnet: bool = False

class LivePositionCloseBody(BaseModel):
    """实盘持仓平仓请求。"""

    model_config = ConfigDict(populate_by_name=True)

    symbol: Optional[str] = None
    side: Optional[str] = None
    close_all: bool = False
    confirm_live_risk: bool = False

def _parse_strategy_id(raw: str) -> int:
    s = str(raw).strip()
    if not s.isdigit():
        raise BadRequestError("strategy_type / strategy 必须是数字策略 ID")
    return int(s)

def _is_superpnl_strategy(row: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    strategy_key = str(
        cfg.get("strategy_key")
        or row.get("strategy_key")
        or ""
    ).strip()
    name = str(row.get("name") or "")
    return strategy_key == _SUPERPNL_STRATEGY_KEY or "SuperPnL" in name

def _row_symbols(row: Dict[str, Any]) -> List[str]:
    raw = row.get("symbols") or []
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = [raw]
        raw = parsed
    if not isinstance(raw, list):
        return []
    return [str(s).strip() for s in raw if str(s).strip()]

def _config_symbols(cfg: Dict[str, Any]) -> List[str]:
    for key in ("symbols", "strategy_symbols"):
        symbols = _row_symbols({"symbols": cfg.get(key)})
        if symbols:
            return symbols
    return []

def _defined_symbols(
    row: Dict[str, Any],
    cfg: Dict[str, Any],
    fallback_symbol: Optional[str] = None,
) -> List[str]:
    symbols = _row_symbols(row)
    if not symbols:
        symbols = _config_symbols(cfg)
    if _is_superpnl_strategy(row, cfg) and len(symbols) < 2:
        symbols = list(_SUPERPNL_DEFAULT_SYMBOLS)
    if not symbols and fallback_symbol:
        symbols = [str(fallback_symbol).strip()]
    return [s for s in symbols if s]

def _runtime_strategy_symbols(strategy_cls: Any, exchange_name: str, cfg: Dict[str, Any]) -> List[str]:
    resolver = getattr(strategy_cls, "resolve_runtime_symbols", None)
    if not callable(resolver):
        return []
    try:
        raw = resolver(exchange_name, cfg)
    except Exception as exc:
        logger.warning("动态策略运行币池解析失败 %s: %s", getattr(strategy_cls, "__name__", strategy_cls), exc)
        return []
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, (list, tuple, set)):
        values = list(raw)
    else:
        return []
    return _row_symbols({"symbols": values})

def _configured_symbols(
    row: Dict[str, Any],
    cfg: Dict[str, Any],
    selected_symbol: Optional[str] = None,
) -> List[str]:
    symbols = _defined_symbols(row, cfg, selected_symbol)
    if not symbols:
        symbols = ["BTC/USDT"]
    cfg.pop("selected_symbol", None)
    cfg["symbol_scope"] = (
        "superpnl_top20_universe" if _is_superpnl_strategy(row, cfg) else "strategy_symbols"
    )
    return symbols

def _strategy_defined_timeframe(
    row: Optional[Dict[str, Any]],
    cfg: Optional[Dict[str, Any]] = None,
    *,
    fallback: str = "1m",
) -> str:
    """Resolve execution timeframe from the strategy definition, never from launch UI input."""
    source_cfg: Dict[str, Any] = {}
    if isinstance(cfg, dict):
        source_cfg = cfg
    elif row:
        raw_cfg = row.get("config") or {}
        if isinstance(raw_cfg, str):
            try:
                raw_cfg = json.loads(raw_cfg)
            except Exception:
                raw_cfg = {}
        if isinstance(raw_cfg, dict):
            source_cfg = raw_cfg

    raw = source_cfg.get("timeframe") if isinstance(source_cfg, dict) else None
    if not raw and row:
        raw = row.get("timeframe")
    value = str(raw or fallback).strip()
    return value or fallback

def _uptime_str(started_at: Optional[str]) -> str:
    if not started_at:
        return "-"
    try:
        dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return _format_duration_seconds(int(delta.total_seconds()))
    except Exception:
        return "-"

def _format_duration_seconds(seconds: int) -> str:
    seconds = max(0, int(seconds))
    total_minutes = seconds // 60
    hours, minute = divmod(total_minutes, 60)
    days, hour = divmod(hours, 24)
    if days:
        return f"{days}D {hour}H {minute}M"
    if hour:
        return f"{hour}H {minute}M"
    return f"{minute}M"

def _paper_positions_from_status(st: Optional[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], float]:
    """从引擎 PaperBroker 状态得到持仓列表与浮动盈亏合计。"""
    if not st:
        return [], 0.0
    unrealized_total = float(st.get("unrealized_pnl") or 0)
    raw = st.get("positions") or {}
    if not isinstance(raw, dict):
        return [], unrealized_total
    out: List[Dict[str, Any]] = []
    for psym, pos in raw.items():
        if not isinstance(pos, dict):
            continue
        try:
            contracts = float(pos.get("contracts") or 0)
        except (TypeError, ValueError):
            contracts = 0.0
        try:
            base_qty = float(pos.get("base_qty") or 0)
        except (TypeError, ValueError):
            base_qty = 0.0
        try:
            sz = float(pos.get("size") or base_qty or contracts or 0)
        except (TypeError, ValueError):
            sz = 0.0
        if max(sz, contracts, base_qty) <= 1e-12:
            continue
        upnl = float(pos.get("unrealized_pnl") or 0)
        out.append(
            {
                "symbol": str(pos.get("symbol") or psym),
                "side": str(pos.get("side") or "long"),
                "pos_side": pos.get("pos_side"),
                "size": sz,
                "contracts": contracts,
                "base_qty": base_qty,
                "notional_usdt": pos.get("notional_usdt"),
                "margin": pos.get("margin"),
                "leverage": pos.get("leverage"),
                "liq_price": pos.get("liq_price"),
                "funding_fee": pos.get("funding_fee"),
                "realized_pnl": pos.get("realized_pnl"),
                "entry_price": float(pos.get("entry_price") or 0),
                "mark_price": float(pos.get("mark_price") or 0),
                "unrealized_pnl": upnl,
                "unrealized_pnl_pct": None,
            }
        )
    return out, unrealized_total

def _normalize_ccxt_positions(positions: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], float]:
    """将 CCXT fetch_positions 结果转为统一结构，并汇总未实现盈亏。"""
    out: List[Dict[str, Any]] = []
    total_upnl = 0.0
    for p in positions:
        if not p:
            continue
        try:
            contracts = p.get("contracts")
            if contracts is None:
                contracts = p.get("contractsSize")
            c = float(contracts or 0)
        except (TypeError, ValueError):
            c = 0.0
        if abs(c) < 1e-12:
            continue
        side = str(p.get("side") or "").lower()
        if side not in ("long", "short"):
            side = "long" if c >= 0 else "short"
        sym = str(p.get("symbol") or "")
        try:
            entry = float(p.get("entryPrice") or p.get("entry_price") or 0)
        except (TypeError, ValueError):
            entry = 0.0
        try:
            mark = float(p.get("markPrice") or p.get("mark_price") or entry)
        except (TypeError, ValueError):
            mark = entry
        try:
            upnl = float(p.get("unrealizedPnl") or p.get("unrealized_pnl") or 0)
        except (TypeError, ValueError):
            upnl = 0.0
        total_upnl += upnl
        pct_raw = p.get("percentage")
        try:
            pct_f = float(pct_raw) if pct_raw is not None else None
        except (TypeError, ValueError):
            pct_f = None
        out.append(
            {
                "symbol": sym,
                "side": side,
                "size": abs(c),
                "entry_price": entry,
                "mark_price": mark,
                "unrealized_pnl": upnl,
                "unrealized_pnl_pct": pct_f,
            }
        )
    return out, total_upnl

def _spot_positions_from_balances(
    balances: List[Dict[str, Any]],
    *,
    exchange_name: str,
    symbol: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Represent non-USDT spot balances as read-only live account holdings."""
    requested_base = ""
    if symbol:
        requested_base = str(symbol).replace("-", "/").split("/", 1)[0].strip().upper()

    out: List[Dict[str, Any]] = []
    for row in balances or []:
        currency = str(row.get("currency") or "").strip().upper()
        if not currency or currency == "USDT":
            continue
        if requested_base and requested_base != currency:
            continue
        total = _float_value(row.get("total"), 0.0)
        free = _float_value(row.get("free"), 0.0)
        used = _float_value(row.get("used"), 0.0)
        if max(abs(total), abs(free), abs(used)) <= 1e-12:
            continue
        notional = _float_value(
            row.get("notional_usdt")
            or row.get("notional")
            or row.get("equity_usd")
            or row.get("usd_value"),
            0.0,
        )
        out.append(
            {
                "exchange": exchange_name,
                "symbol": f"{currency}/USDT",
                "currency": currency,
                "asset_type": "spot",
                "side": "spot",
                "pos_side": "spot",
                "amount": total,
                "free": free,
                "used": used,
                "notional_usdt": notional if notional > 0 else None,
                "unrealized_pnl": None,
            }
        )
    return out

def _position_symbols_from_status(st: Optional[Dict[str, Any]]) -> List[str]:
    if not st:
        return []
    raw = st.get("positions") or {}
    if not isinstance(raw, dict):
        return []
    out: List[str] = []
    for sym, pos in raw.items():
        if not isinstance(pos, dict):
            continue
        try:
            size = float(pos.get("size") or 0)
        except (TypeError, ValueError):
            size = 0.0
        symbol = str(pos.get("symbol") or sym).strip()
        if abs(size) > 1e-12 and symbol:
            out.append(symbol)
    return out

def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out

def _timeframe_seconds(timeframe: str) -> int:
    value = str(timeframe or "").strip().lower()
    if not value:
        return 60
    unit = value[-1]
    amount = _float_value(value[:-1], 1.0)
    if amount <= 0:
        amount = 1.0
    if unit == "m":
        return int(amount * 60)
    if unit == "h":
        return int(amount * 3600)
    if unit == "d":
        return int(amount * 86400)
    return int(amount)

def _kline_timestamp_ms(bar: Any) -> Optional[int]:
    raw: Any = None
    if isinstance(bar, dict):
        raw = bar.get("timestamp")
    elif isinstance(bar, (list, tuple)) and bar:
        raw = bar[0]
    ts = _float_value(raw, 0.0)
    if ts <= 0:
        return None
    if ts < 1_000_000_000_000:
        ts *= 1000
    return int(ts)

def _configured_initial_capital(cfg: Dict[str, Any]) -> float:
    for key in ("initial_capital", "initialCapital", "initial_equity", "initialEquity"):
        value = _float_value(cfg.get(key), 0.0)
        if value > 0:
            return value
    return 10000.0

def _git_commit_ref() -> str:
    return (
        os.getenv("GITHUB_SHA")
        or os.getenv("BITPRO_BUILD_COMMIT")
        or os.getenv("COMMIT_SHA")
        or "unknown"
    )

def _cap_fraction(value: Any, default: float, cap: float) -> float:
    raw = _float_value(value, default)
    if raw > 1:
        raw = raw / 100.0
    if raw <= 0:
        raw = default
    return max(0.0, min(raw, cap))

def _build_promoted_live_config(
    source_row: Dict[str, Any],
    *,
    initial_equity: float,
    loop_interval: int,
    risk_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    source_cfg = source_row.get("config") or {}
    if not isinstance(source_cfg, dict):
        source_cfg = {}
    cfg = dict(source_cfg)
    risk = risk_config or {}
    now = datetime.now(timezone.utc).isoformat()
    cfg["is_paper_trading"] = False
    cfg["initial_capital"] = float(initial_equity)
    cfg["loop_interval_sec"] = int(loop_interval)
    cfg["risk_per_trade_pct"] = _cap_fraction(risk.get("risk_per_trade_pct"), 0.005, 0.01)
    cfg["max_daily_loss_pct"] = _cap_fraction(risk.get("max_daily_loss_pct"), 0.01, 0.02)
    cfg["max_total_loss_pct"] = _cap_fraction(risk.get("max_total_loss_pct"), 0.03, 0.05)

    if "max_position_pct" in cfg:
        cfg["max_position_pct"] = _cap_fraction(cfg.get("max_position_pct"), 0.02, 0.03)
    if "max_total_position_pct" in cfg:
        cfg["max_total_position_pct"] = _cap_fraction(cfg.get("max_total_position_pct"), 0.05, 0.08)
    if "max_position_per_symbol" in cfg:
        cfg["max_position_per_symbol"] = _cap_fraction(cfg.get("max_position_per_symbol"), 0.02, 0.03)
    if "max_total_position" in cfg:
        cfg["max_total_position"] = _cap_fraction(cfg.get("max_total_position"), 0.05, 0.08)
    if "entry_equity_pct" in cfg:
        cfg["entry_equity_pct"] = _cap_fraction(cfg.get("entry_equity_pct"), 0.01, 0.02)
    if "entry_quote_usdt" in cfg:
        cfg["entry_quote_usdt"] = min(_float_value(cfg.get("entry_quote_usdt"), 10.0), max(5.0, initial_equity * 0.02))
    if "quote_per_order" in cfg:
        cfg["quote_per_order"] = min(_float_value(cfg.get("quote_per_order"), 10.0), max(5.0, initial_equity * 0.02))

    cfg["promotion"] = {
        "type": "paper_to_live_trial",
        "source_strategy_id": int(source_row.get("id") or 0),
        "source_strategy_name": source_row.get("name") or "",
        "promoted_at": now,
        "code_commit": _git_commit_ref(),
        "trial": True,
        "trial_initial_equity": float(initial_equity),
        "operator_confirmed_paper_review": True,
        "operator_confirmed_live_risk": True,
    }
    return cfg

def _config_trade_symbols(cfg: Dict[str, Any]) -> List[str]:
    for key in ("trade_symbols", "tradeSymbols"):
        symbols = _row_symbols({"symbols": cfg.get(key)})
        if symbols:
            return symbols
    return []

def _is_contract_live_candidate(cfg: Dict[str, Any], symbols: List[str]) -> bool:
    market_type = str((cfg or {}).get("market_type") or "spot").strip().lower()
    contract_markets = {"swap", "future", "futures", "perp", "perpetual", "contract", "derivative", "derivatives"}
    if market_type in contract_markets:
        return True
    symbol_candidates = list(symbols)
    for key in ("trade_symbols", "tradeSymbols", "contract_trade_symbols", "contractTradeSymbols"):
        symbol_candidates.extend(_row_symbols({"symbols": cfg.get(key)}))
    return any(":USDT" in str(sym).upper() or str(sym).upper().endswith("-SWAP") for sym in symbol_candidates)

def _preview_symbols(symbols: List[str], *, max_items: int = 6) -> str:
    if not symbols:
        return "未定义"
    shown = ", ".join(symbols[:max_items])
    return shown if len(symbols) <= max_items else f"{shown} 等 {len(symbols)} 个"

def _promotion_account_id_from_config(cfg: Dict[str, Any]) -> str:
    promotion = cfg.get("promotion")
    account_id = cfg.get("live_account_id")
    if not account_id and isinstance(promotion, dict):
        account_id = promotion.get("account_id")
    return live_account_service.normalize_account_id(str(account_id or "default"))

def _live_deployment_is_stopped(row: Dict[str, Any]) -> bool:
    try:
        sid = int(row.get("id") or 0)
    except (TypeError, ValueError):
        sid = 0
    status = str(row.get("status") or "").lower()
    try:
        engine_status = strategy_engine.get_strategy_status(sid) if sid > 0 else None
    except Exception:
        engine_status = None
    engine_state = str((engine_status or {}).get("status") or "").lower()
    active_states = {"running", "paused", "starting", "stopping"}
    if engine_state in active_states:
        return False
    return status == "stopped"

def _live_execution_body_to_promote(
    strategy_id: int,
    body: LiveStrategyPreflightBody,
    *,
    confirm_paper_reviewed: bool = False,
    confirm_live_risk: bool = False,
) -> PromoteToLiveBody:
    account_id = live_account_service.validate_live_deployable_account_id(body.account_id or "default")
    return PromoteToLiveBody(
        source_strategy_id=int(strategy_id),
        account_id=account_id,
        exchange=live_account_service.exchange_alias_for_account(account_id),
        initial_equity=body.initial_equity,
        loop_interval=body.loop_interval,
        start_immediately=body.start_immediately,
        confirm_paper_reviewed=confirm_paper_reviewed,
        confirm_live_risk=confirm_live_risk,
        risk_config=body.risk_config,
    )

def _account_equity(account: Optional[Dict[str, Any]]) -> float:
    if not isinstance(account, dict):
        return 0.0
    free = _float_value(account.get("free_usdt"), 0.0)
    return free if free > 0 else 0.0

def _apply_live_account_equity(
    prepared: Dict[str, Any],
    account: Optional[Dict[str, Any]],
) -> None:
    equity = _account_equity(account)
    if equity <= 0:
        return
    live_cfg = prepared["live_cfg"]
    live_cfg["initial_capital"] = equity
    live_cfg["initial_capital_source"] = "live_account_free_usdt"
    live_cfg["detected_live_account"] = account
    promotion = live_cfg.get("promotion")
    if isinstance(promotion, dict):
        promotion["trial_initial_equity"] = equity
        promotion["trial_initial_equity_source"] = "live_account_free_usdt"
        promotion["detected_live_account"] = account
    prepared["account"] = account

def _configured_min_order_notional(cfg: Dict[str, Any]) -> float:
    candidates = [
        _float_value(cfg.get("min_order_notional_usdt"), 0.0),
        _float_value(cfg.get("min_order_value"), 0.0),
        10.0,
    ]
    return max(v for v in candidates if v > 0)

def _configured_order_quote(cfg: Dict[str, Any], equity: float) -> float:
    explicit: List[float] = []
    for key in ("entry_quote_usdt", "quote_per_order", "order_quote_usdt"):
        value = _float_value(cfg.get(key), 0.0)
        if value > 0:
            explicit.append(value)
    for key in ("entry_equity_pct", "entry_balance_pct"):
        pct = _float_value(cfg.get(key), 0.0)
        if pct > 1:
            pct /= 100.0
        if pct > 0 and equity > 0:
            explicit.append(equity * pct)
    if explicit:
        return min(explicit)
    if equity > 0:
        return min(equity, max(5.0, equity * 0.02))
    return 0.0

def _has_explicit_order_quote(cfg: Dict[str, Any]) -> bool:
    for key in ("entry_quote_usdt", "quote_per_order", "order_quote_usdt"):
        if _float_value(cfg.get(key), 0.0) > 0:
            return True
    for key in ("entry_equity_pct", "entry_balance_pct"):
        if _float_value(cfg.get(key), 0.0) > 0:
            return True
    return False

def _promotion_account_sizing_checks(prepared: Dict[str, Any]) -> List[Dict[str, Any]]:
    live_cfg = prepared["live_cfg"]
    account = prepared.get("account")
    equity = _account_equity(account)
    min_notional = _configured_min_order_notional(live_cfg)
    planned_quote = _configured_order_quote(live_cfg, equity)
    has_explicit_quote = _has_explicit_order_quote(live_cfg)
    if equity <= 0:
        return [
            {
                "item": "订单名义金额可执行",
                "passed": False,
                "detail": "未读取到可用 USDT，无法确认最小下单资金和单笔名义金额",
            }
        ]

    passed = equity >= min_notional and (not has_explicit_quote or planned_quote >= min_notional)
    if not has_explicit_quote:
        detail = (
            f"可用资金 {equity:.2f} USDT，满足最小可执行名义 {min_notional:.2f} USDT；"
            "策略未显式配置单笔名义，实际下单仍由策略逻辑和风控引擎校验"
            if passed
            else f"可用资金 {equity:.2f} USDT，低于最小可执行名义 {min_notional:.2f} USDT"
        )
    else:
        detail = (
            f"可用资金 {equity:.2f} USDT；计划单笔名义约 {planned_quote:.2f} USDT；"
            f"最小可执行名义 {min_notional:.2f} USDT"
            if passed
            else (
                f"可用资金 {equity:.2f} USDT；计划单笔名义约 {planned_quote:.2f} USDT，"
                f"低于最小可执行名义 {min_notional:.2f} USDT；请提高实盘可用资金或调低试运行限制后重审"
            )
        )
    return [
        {
            "item": "订单名义金额可执行",
            "passed": passed,
            "detail": detail,
        }
    ]

def _market_rules_check(exchange: Any, symbols: List[str]) -> Dict[str, Any]:
    if not hasattr(exchange, "load_markets") or not getattr(exchange, "exchange", None):
        return {
            "item": "交易规则与市场状态",
            "passed": True,
            "detail": "交易所封装未暴露市场元数据，已由行情和 K 线检查兜底",
        }
    try:
        exchange.load_markets()
        markets = getattr(exchange.exchange, "markets", {}) or {}
        missing: List[str] = []
        inactive: List[str] = []
        min_costs: List[float] = []
        for sym in symbols:
            market = markets.get(sym)
            if not market:
                missing.append(sym)
                continue
            if market.get("active") is False:
                inactive.append(sym)
            limits = market.get("limits") if isinstance(market, dict) else {}
            cost = (limits or {}).get("cost") if isinstance(limits, dict) else {}
            min_cost = _float_value((cost or {}).get("min") if isinstance(cost, dict) else None, 0.0)
            if min_cost > 0:
                min_costs.append(min_cost)
        passed = not missing and not inactive
        detail = (
            "交易对均存在且处于 active"
            if passed
            else (
                (f"缺失市场：{_preview_symbols(missing)}" if missing else "")
                + ("；" if missing and inactive else "")
                + (f"非 active：{_preview_symbols(inactive)}" if inactive else "")
            )
        )
        if min_costs and passed:
            detail += f"；交易所最小名义约 {max(min_costs):.2f} USDT"
        return {"item": "交易规则与市场状态", "passed": passed, "detail": detail}
    except Exception as e:
        return {"item": "交易规则与市场状态", "passed": False, "detail": f"市场规则读取失败：{e}"}

def _venue_contract_symbol_pairs(exchange: Any, symbols: List[str]) -> List[tuple[str, str]]:
    """Return source-to-venue symbols without changing strategy signal identifiers."""
    source_symbols = [str(symbol).strip() for symbol in symbols]
    native = getattr(exchange, "exchange", None)
    venue = str(
        getattr(exchange, "name", "")
        or getattr(native, "id", "")
        or getattr(native, "name", "")
    ).lower()
    if "binance" not in venue:
        return list(zip(source_symbols, source_symbols))

    exchange.load_markets()
    markets = getattr(native, "markets", {}) or {}
    pairs: List[tuple[str, str]] = []
    for source_symbol in source_symbols:
        venue_symbol, _, _ = resolve_binance_usdm_market(markets, source_symbol)
        pairs.append((normalize_contract_symbol(source_symbol), venue_symbol))
    return pairs

def _dynamic_preflight_min_symbols(cfg: Dict[str, Any], total: int) -> int:
    if total <= 0:
        return 0
    configured = int(_float_value((cfg or {}).get("live_preflight_min_symbols"), 0.0))
    if configured > 0:
        return max(1, min(configured, total))
    return max(1, min(10, total))

async def _order_book_liquidity_check(
    exchange: Any,
    symbols: List[str],
    *,
    allow_dynamic_filter: bool = False,
    min_remaining_symbols: int = 0,
) -> Dict[str, Any]:
    if not hasattr(exchange, "fetch_order_book"):
        return {
            "item": "订单簿点差与深度",
            "passed": True,
            "detail": "交易所封装未暴露订单簿接口，已由行情和 K 线检查兜底",
            "eligible_symbols": symbols,
            "excluded_symbols": [],
        }
    max_spread_pct = 0.005
    min_top_depth_usdt = 20.0
    failed: List[str] = []
    failed_symbols: List[str] = []
    checked = symbols if allow_dynamic_filter else symbols[:8]
    markets: Dict[str, Any] = {}
    try:
        if hasattr(exchange, "load_markets"):
            exchange.load_markets()
        markets = getattr(getattr(exchange, "exchange", None), "markets", {}) or {}
    except Exception:
        markets = {}
    for sym in checked:
        try:
            book = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda s=sym: exchange.fetch_order_book(s, limit=5),
            )
            bids = book.get("bids") if isinstance(book, dict) else []
            asks = book.get("asks") if isinstance(book, dict) else []
            if not bids or not asks:
                failed.append(f"{sym}: 买卖盘为空")
                failed_symbols.append(sym)
                continue
            best_bid = _float_value(bids[0][0] if bids[0] else None, 0.0)
            best_ask = _float_value(asks[0][0] if asks[0] else None, 0.0)
            mid = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else 0.0
            spread = (best_ask - best_bid) / mid if mid > 0 else 1.0
            market = markets.get(sym) if isinstance(markets, dict) else None
            contract_size = max(
                _float_value((market or {}).get("contractSize") if isinstance(market, dict) else None, 1.0),
                1e-12,
            )
            bid_depth = sum(
                _float_value(level[0] if level else None, 0.0)
                * _float_value(level[1] if len(level) > 1 else None, 0.0)
                * contract_size
                for level in bids[:5]
            )
            ask_depth = sum(
                _float_value(level[0] if level else None, 0.0)
                * _float_value(level[1] if len(level) > 1 else None, 0.0)
                * contract_size
                for level in asks[:5]
            )
            if spread > max_spread_pct:
                failed.append(f"{sym}: 点差 {spread:.2%}")
                failed_symbols.append(sym)
            elif min(bid_depth, ask_depth) < min_top_depth_usdt:
                failed.append(f"{sym}: 前5档深度不足 {min_top_depth_usdt:.0f} USDT")
                failed_symbols.append(sym)
        except Exception as e:
            failed.append(f"{sym}: {e}")
            failed_symbols.append(sym)
    excluded_set = set(failed_symbols)
    eligible_symbols = [sym for sym in symbols if sym not in excluded_set]
    min_remaining = max(0, int(min_remaining_symbols or 0))
    if allow_dynamic_filter and failed:
        passed = len(eligible_symbols) >= min_remaining
    else:
        passed = not failed
    detail = (
        f"已抽检 {_preview_symbols(checked)}，点差<=0.50% 且前5档深度充足"
        if passed and not failed
        else (
            f"已剔除 {len(failed_symbols)} 个低流动性标的：{_preview_symbols(failed_symbols)}；"
            f"剩余 {len(eligible_symbols)}/{len(symbols)} 个标的通过，最低要求 {min_remaining} 个"
            if allow_dynamic_filter and passed
            else "；".join(failed[:5]) + (f"；另有 {len(failed) - 5} 个失败" if len(failed) > 5 else "")
        )
    )
    return {
        "item": "订单簿点差与深度",
        "passed": passed,
        "detail": detail,
        "eligible_symbols": eligible_symbols if passed else [],
        "excluded_symbols": failed_symbols,
    }

def _apply_dynamic_live_symbol_filter(
    prepared: Dict[str, Any],
    runtime: Dict[str, Any],
) -> None:
    if prepared.get("symbol_scope") != "dynamic_runtime_symbols":
        return
    eligible = runtime.get("eligible_symbols")
    if not isinstance(eligible, list) or not eligible:
        return
    excluded = runtime.get("excluded_symbols") if isinstance(runtime.get("excluded_symbols"), list) else []
    prepared["symbols"] = eligible
    prepared["filtered_live_symbols"] = eligible
    prepared["excluded_live_symbols"] = excluded
    prepared["candidate_row"]["symbols"] = eligible
    prepared["live_cfg"]["live_preflight_allowed_symbols"] = eligible
    prepared["live_cfg"]["live_preflight_excluded_symbols"] = excluded

def _promotion_plan(
    prepared: Dict[str, Any],
    *,
    body: PromoteToLiveBody,
) -> Dict[str, Any]:
    source = prepared["source"]
    live_cfg = prepared["live_cfg"]
    symbols = prepared["symbols"]
    return {
        "source_strategy_id": int(source.get("id") or body.source_strategy_id),
        "source_strategy_name": source.get("name") or "",
        "account_id": body.account_id or "default",
        "exchange": body.exchange,
        "mode": "live",
        "dry_run": False,
        "timeframe": prepared["timeframe"],
        "initial_equity": _float_value(live_cfg.get("initial_capital"), 0.0),
        "initial_equity_source": live_cfg.get("initial_capital_source") or "request",
        "loop_interval_sec": int(body.loop_interval),
        "symbols": symbols,
        "trade_symbols": _config_trade_symbols(live_cfg),
        "excluded_symbols": prepared.get("excluded_live_symbols") or [],
        "symbol_scope": prepared.get("symbol_scope") or "strategy_symbols",
        "start_immediately": bool(body.start_immediately),
        "account": prepared.get("account"),
    }

def _live_contract_symbols(cfg: Dict[str, Any], symbols: List[str]) -> List[str]:
    if not _is_contract_live_candidate(cfg, symbols):
        return []
    raw: List[str] = []
    for key in ("contract_trade_symbols", "contractTradeSymbols", "trade_symbols", "tradeSymbols"):
        values = _row_symbols({"symbols": (cfg or {}).get(key)})
        if values:
            raw.extend(values)
            break
    if not raw:
        raw.extend(symbols)
    out: List[str] = []
    seen: set[str] = set()
    for symbol in raw:
        normalized = normalize_contract_symbol(str(symbol))
        if not normalized or normalized in seen:
            continue
        out.append(normalized)
        seen.add(normalized)
    return out

def _okx_position_mode_from_response(response: Any) -> str:
    data = response.get("data") if isinstance(response, dict) else None
    first = data[0] if isinstance(data, list) and data else {}
    raw = str(first.get("posMode") or first.get("positionMode") or "").strip().lower()
    if raw in {"long_short_mode", "longshort", "hedge", "hedge_mode"}:
        return "long_short_mode"
    if raw in {"net", "net_mode"}:
        return "net_mode"
    raise ValueError(f"无法识别 OKX 持仓模式：{raw or response}")

def _binance_usdm_position_mode_from_response(response: Any) -> str:
    raw = response.get("dualSidePosition") if isinstance(response, dict) else None
    if isinstance(raw, str):
        raw = raw.strip().lower() == "true"
    return "long_short_mode" if bool(raw) else "net_mode"

async def _live_contract_account_precheck(
    *,
    exchange: str,
    live_cfg: Dict[str, Any],
    symbols: List[str],
) -> Dict[str, Any]:
    contract_symbols = _live_contract_symbols(live_cfg, symbols)
    if not contract_symbols:
        return {
            "item": "账户合约交易能力",
            "passed": True,
            "detail": "非合约策略，跳过 OKX SWAP 账户预检查",
        }

    venue = str(exchange or "").split(":", 1)[0].lower()
    td_mode = str(live_cfg.get("td_mode") or live_cfg.get("mgn_mode") or "isolated").lower()
    if td_mode not in {"cross", "isolated"}:
        td_mode = "isolated"

    def probe() -> Dict[str, Any]:
        ex = exchange_manager.get_exchange(exchange)
        if not ex or not getattr(ex, "exchange", None):
            raise ValueError(f"交易所实例不可用：{exchange}")
        native = ex.exchange
        if venue == "binanceusdm":
            position_mode_endpoint = getattr(native, "fapiPrivateGetPositionSideDual", None)
            if not callable(position_mode_endpoint):
                raise ValueError("Binance USD-M position mode endpoint unavailable")
            position_mode = _binance_usdm_position_mode_from_response(position_mode_endpoint({}))
            ex.load_markets()
            markets = getattr(native, "markets", {}) or {}
            venue_symbol, market, _ = resolve_binance_usdm_market(markets, contract_symbols[0])
            if not market.get("swap") or not market.get("linear"):
                raise ValueError(f"Binance USD-M 合约元数据不可用：{venue_symbol}")
            if market.get("active") is False:
                raise ValueError(f"Binance USD-M 合约未激活：{venue_symbol}")
            amount_limits = ((market.get("limits") or {}).get("amount") or {})
            min_amount = _float_value(amount_limits.get("min"), 0.0)
            if min_amount <= 0:
                raise ValueError(f"Binance USD-M 合约最小数量不可用：{contract_symbols[0]}")
            cost_limits = ((market.get("limits") or {}).get("cost") or {})
            min_cost = _float_value(cost_limits.get("min"), 0.0)
            test_quantity = min_amount
            if min_cost > 0:
                ticker = ex.fetch_ticker(venue_symbol)
                mark_price = _float_value((ticker or {}).get("last"), 0.0)
                contract_size = max(_float_value(market.get("contractSize"), 1.0), 1e-12)
                if mark_price <= 0:
                    raise ValueError(f"Binance USD-M 合约价格不可用：{venue_symbol}")
                precision = market.get("precision") if isinstance(market.get("precision"), dict) else {}
                amount_step = _float_value(precision.get("amount"), min_amount)
                if amount_step <= 0:
                    amount_step = min_amount
                # order/test 仍校验最小名义金额。留出 5% 价格波动缓冲，
                # 避免获取 ticker 后市场轻微下跌造成非成交预检误报。
                required = min_cost * 1.05 / (mark_price * contract_size)
                test_quantity = max(
                    min_amount,
                    math.ceil((required / amount_step) - 1e-12) * amount_step,
                )
            payload: Dict[str, Any] = {
                "symbol": str(market.get("id") or ""),
                "side": "BUY",
                "type": "MARKET",
                "quantity": str(test_quantity),
            }
            if position_mode == "long_short_mode":
                payload["positionSide"] = "LONG"
            order_test = getattr(native, "fapiPrivatePostOrderTest", None)
            if not callable(order_test):
                raise ValueError("Binance USD-M order/test endpoint unavailable")
            order_test(payload)
            return {
                "venue": "binanceusdm",
                "position_mode": position_mode,
                "inst_id": str(market.get("id") or contract_symbols[0]),
                "precheck_available": True,
            }
        if not hasattr(native, "privateGetAccountConfig"):
            raise ValueError("OKX account config endpoint unavailable")
        account_config = native.privateGetAccountConfig({})
        position_mode = _okx_position_mode_from_response(account_config)
        instruments = load_contract_instruments(exchange, contract_symbols[:1], live_cfg)
        inst = instruments[contract_symbols[0]]
        payload: Dict[str, Any] = {
            "instId": inst.inst_id,
            "tdMode": td_mode,
            "side": "buy",
            "ordType": "market",
            "sz": str(inst.min_sz),
        }
        if position_mode == "long_short_mode":
            payload["posSide"] = "long"

        response: Optional[Dict[str, Any]] = None
        if hasattr(native, "privatePostTradeOrderPrecheck"):
            response = native.privatePostTradeOrderPrecheck(payload)
        elif hasattr(native, "request"):
            response = native.request("trade/order-precheck", "private", "POST", payload)

        if response is None:
            return {
                "position_mode": position_mode,
                "inst_id": inst.inst_id,
                "precheck_available": False,
            }
        code = str(response.get("code") or "0") if isinstance(response, dict) else "0"
        data = response.get("data") if isinstance(response, dict) and isinstance(response.get("data"), list) else []
        first = data[0] if data else {}
        sub_code = str(first.get("sCode") or "0")
        if code not in {"", "0"} or sub_code not in {"", "0"}:
            raise ValueError(first.get("sMsg") or response.get("msg") or str(response))
        return {
            "venue": "okx",
            "position_mode": position_mode,
            "inst_id": inst.inst_id,
            "precheck_available": True,
        }

    try:
        result = await asyncio.get_running_loop().run_in_executor(None, probe)
        mode = result.get("position_mode")
        mode_label = "双向持仓" if mode == "long_short_mode" else "单向持仓"
        if result.get("venue") == "binanceusdm":
            return {
                "item": "账户合约交易能力",
                "passed": True,
                "detail": f"Binance USD-M {mode_label}模式；{result.get('inst_id')} 最小数量非成交 order/test 通过",
            }
        if result.get("precheck_available"):
            detail = f"OKX {mode_label}模式；{result.get('inst_id')} 最小张数非成交 order-precheck 通过"
        else:
            detail = f"OKX {mode_label}模式；当前客户端未暴露 order-precheck，已完成账户配置检查"
        return {"item": "账户合约交易能力", "passed": True, "detail": detail}
    except Exception as exc:
        prefix = "Binance USD-M" if venue == "binanceusdm" else "OKX"
        return {
            "item": "账户合约交易能力",
            "passed": False,
            "detail": f"{prefix} 合约账户预检查失败：{exc}",
        }

async def _live_account_trade_permission_check(account_id: str) -> Dict[str, Any]:
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: live_account_service.validate_account_trade_permission(account_id),
        )
        can_trade = bool(result.get("can_trade"))
        return {
            "item": "账户交易权限",
            "passed": can_trade,
            "detail": (
                str(result.get("detail") or "读取权限和交易权限测试通过")
                if can_trade
                else "当前 API Key 未通过 Trade 权限测试"
            ),
        }
    except Exception as exc:
        return {
            "item": "账户交易权限",
            "passed": False,
            "detail": str(exc),
        }

def _asset_prefix_for_config(config: Dict[str, Any] | None) -> str:
    market_type = str((config or {}).get("market_type") or "spot").strip().lower()
    contract_markets = {"swap", "future", "futures", "perp", "perpetual", "contract", "derivative", "derivatives"}
    return "[合约]" if market_type in contract_markets else "[现货]"

def _strip_asset_prefix(name: str) -> str:
    value = str(name or "").strip()
    for prefix in ("[现货]", "[合约]"):
        if value.startswith(prefix):
            return value[len(prefix):].strip()
    return value

def _promoted_live_strategy_name(source_row: Dict[str, Any]) -> str:
    raw_name = str(source_row.get("name") or source_row.get("id") or "策略")
    prefix = "[合约]" if raw_name.strip().startswith("[合约]") else _asset_prefix_for_config(source_row.get("config") or {})
    base_name = _strip_asset_prefix(raw_name)
    return f"{prefix} [实盘试运行] {base_name}"

def _live_account_exchange_alias(account_id: str) -> tuple[str, str]:
    normalized = live_account_service.validate_live_deployable_account_id(account_id)
    return normalized, live_account_service.exchange_alias_for_account(normalized)

def _optional_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None

def _normalize_watch_symbol(symbol: str) -> str:
    normalized = normalize_contract_symbol(str(symbol or "").strip())
    if not normalized:
        raise BadRequestError("symbol 不能为空")
    return normalized

def _okx_inst_id(symbol: str) -> str:
    normalized = _normalize_watch_symbol(symbol)
    base = normalized.split("/", 1)[0]
    return f"{base}-USDT-SWAP"

def _point(ts: Any, value: Any, **extra: Any) -> Dict[str, Any]:
    return {"timestamp": int(_float_value(ts, 0.0)), "value": _optional_float(value), **extra}

def _okx_public_api(exchange_name: str) -> Any:
    try:
        ex = exchange_manager.get_exchange(exchange_name) or exchange_manager.get_exchange("okx")
        return getattr(ex, "exchange", ex)
    except Exception:
        return None

def _extract_okx_rows(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, dict):
        data = raw.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        return [raw]
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    return []

def _timeframe_to_okx_period(timeframe: str) -> str:
    value = str(timeframe or "15m").strip().lower()
    return {
        "5m": "5m",
        "15m": "15m",
        "1h": "1H",
        "4h": "4H",
        "1d": "1D",
        "1m": "1m",
    }.get(value, "15m")

async def _call_okx_public_method(exchange_name: str, names: List[str], params: Dict[str, Any]) -> Optional[Any]:
    api = _okx_public_api(exchange_name)
    if api is None:
        return None
    for name in names:
        method = getattr(api, name, None)
        if not callable(method):
            continue
        try:
            return await asyncio.to_thread(method, params)
        except Exception as exc:
            logger.debug("OKX public stat method %s unavailable: %s", name, exc)
    return None

async def _okx_open_interest_points(exchange_name: str, symbol: str, timeframe: str, limit: int) -> Optional[List[Dict[str, Any]]]:
    raw = await _call_okx_public_method(
        exchange_name,
        [
            "publicGetRubikStatContractsOpenInterestVolume",
            "public_get_rubik_stat_contracts_open_interest_volume",
        ],
        {
            "ccy": symbol.split("/", 1)[0],
            "instType": "SWAP",
            "period": _timeframe_to_okx_period(timeframe),
            "limit": str(limit),
        },
    )
    rows = _extract_okx_rows(raw)
    if not rows:
        return None
    points = [
        _point(
            row.get("ts") or row.get("timestamp"),
            row.get("oi") or row.get("openInterest") or row.get("open_interest"),
            volume=_optional_float(row.get("vol") or row.get("volume")),
        )
        for row in rows
    ]
    return [p for p in points if p["timestamp"]]

async def _okx_long_short_ratio_points(exchange_name: str, symbol: str, timeframe: str, limit: int) -> Optional[List[Dict[str, Any]]]:
    raw = await _call_okx_public_method(
        exchange_name,
        [
            "publicGetRubikStatContractsLongShortAccountRatio",
            "public_get_rubik_stat_contracts_long_short_account_ratio",
        ],
        {
            "ccy": symbol.split("/", 1)[0],
            "period": _timeframe_to_okx_period(timeframe),
            "limit": str(limit),
        },
    )
    rows = _extract_okx_rows(raw)
    if not rows:
        return None
    points = [
        _point(
            row.get("ts") or row.get("timestamp"),
            row.get("longShortRatio") or row.get("ratio") or row.get("value"),
            long_account_ratio=_optional_float(row.get("longAccount") or row.get("longAccountRatio")),
            short_account_ratio=_optional_float(row.get("shortAccount") or row.get("shortAccountRatio")),
        )
        for row in rows
    ]
    return [p for p in points if p["timestamp"]]

async def _okx_taker_volume_points(exchange_name: str, symbol: str, timeframe: str, limit: int) -> Optional[List[Dict[str, Any]]]:
    raw = await _call_okx_public_method(
        exchange_name,
        [
            "publicGetRubikStatTakerVolume",
            "public_get_rubik_stat_taker_volume",
            "publicGetRubikStatContractsTakerVolume",
        ],
        {
            "ccy": symbol.split("/", 1)[0],
            "instType": "SWAP",
            "period": _timeframe_to_okx_period(timeframe),
            "limit": str(limit),
        },
    )
    rows = _extract_okx_rows(raw)
    if not rows:
        return None
    points = []
    for row in rows:
        buy = _optional_float(row.get("buyVol") or row.get("buyVolume") or row.get("takerBuyVolume"))
        sell = _optional_float(row.get("sellVol") or row.get("sellVolume") or row.get("takerSellVolume"))
        points.append(
            _point(
                row.get("ts") or row.get("timestamp"),
                (buy or 0.0) - (sell or 0.0) if buy is not None or sell is not None else None,
                buy=buy,
                sell=sell,
            )
        )
    return [p for p in points if p["timestamp"]]

async def _okx_basis_points(exchange_name: str, symbol: str, timeframe: str, limit: int) -> Optional[List[Dict[str, Any]]]:
    inst_id = _okx_inst_id(symbol)
    raw = await _call_okx_public_method(
        exchange_name,
        [
            "publicGetRubikStatContractsBasis",
            "public_get_rubik_stat_contracts_basis",
            "publicGetMarketIndexComponents",
        ],
        {
            "instId": inst_id,
            "period": _timeframe_to_okx_period(timeframe),
            "limit": str(limit),
        },
    )
    rows = _extract_okx_rows(raw)
    if not rows:
        return None
    points = []
    for row in rows:
        basis = _optional_float(row.get("basis") or row.get("premium"))
        index_price = _optional_float(row.get("indexPx") or row.get("index_price"))
        contract_price = _optional_float(row.get("contractPx") or row.get("markPx") or row.get("mark_price"))
        if basis is None and contract_price is not None and index_price is not None:
            basis = contract_price - index_price
        basis_rate = _optional_float(row.get("basisRate") or row.get("rate"))
        if basis_rate is None and basis is not None and index_price:
            basis_rate = basis / index_price
        points.append(
            _point(
                row.get("ts") or row.get("timestamp"),
                basis,
                basis_rate=basis_rate,
                index_price=index_price,
                contract_price=contract_price,
            )
        )
    return [p for p in points if p["timestamp"]]

def _position_info(row: Dict[str, Any]) -> Dict[str, Any]:
    info = row.get("info")
    return info if isinstance(info, dict) else {}

def _live_position_symbol(row: Dict[str, Any]) -> str:
    info = _position_info(row)
    raw = (
        row.get("symbol")
        or row.get("instId")
        or row.get("instrument_id")
        or info.get("instId")
        or ""
    )
    return normalize_contract_symbol(str(raw)) if raw else ""

def _live_position_size(row: Dict[str, Any]) -> float:
    info = _position_info(row)
    for key in ("contracts", "size", "amount", "pos", "base_amount"):
        if key in row:
            size = _float_value(row.get(key), 0.0)
            if abs(size) > 1e-12:
                return size
    for key in ("pos", "availPos"):
        if key in info:
            size = _float_value(info.get(key), 0.0)
            if abs(size) > 1e-12:
                return size
    return 0.0

def _live_position_side(row: Dict[str, Any]) -> str:
    info = _position_info(row)
    raw_pos_side = (
        row.get("pos_side")
        or row.get("posSide")
        or row.get("position_side")
        or info.get("posSide")
        or ""
    )
    pos_side = str(raw_pos_side).strip().lower()
    raw_side = row.get("side") or info.get("side") or ""
    side = str(raw_side).strip().lower()
    if pos_side in {"long", "short"}:
        return pos_side
    if side in {"long", "short"}:
        return side
    if side == "buy":
        return "long"
    if side == "sell":
        return "short"
    if pos_side == "net":
        signed = _live_position_size(row)
        return "long" if signed > 0 else "short" if signed < 0 else ""
    signed = _live_position_size(row)
    if signed > 0:
        return "long"
    if signed < 0:
        return "short"
    return ""

def _live_contract_position_targets(
    positions: List[Dict[str, Any]],
    requested_symbol: Optional[str] = None,
) -> List[Dict[str, str]]:
    normalized_requested = normalize_contract_symbol(requested_symbol) if requested_symbol else None
    seen: set[tuple[str, str]] = set()
    targets: List[Dict[str, str]] = []
    for row in positions or []:
        symbol = _live_position_symbol(row)
        if not symbol:
            continue
        if normalized_requested and symbol != normalized_requested:
            continue
        if abs(_live_position_size(row)) <= 1e-12:
            continue
        side = _live_position_side(row)
        if side not in {"long", "short"}:
            continue
        key = (symbol, side)
        if key in seen:
            continue
        seen.add(key)
        targets.append({"symbol": symbol, "side": side})
    return targets

def _live_open_position_symbols(positions: List[Dict[str, Any]]) -> set[str]:
    symbols: set[str] = set()
    for row in positions or []:
        if abs(_live_position_size(row)) <= 1e-12:
            continue
        symbol = _live_position_symbol(row)
        if symbol:
            symbols.add(symbol)
    return symbols

def _order_history_sort_ms(order: Dict[str, Any]) -> int:
    for key in (
        "timestamp",
        "updated_timestamp",
        "created_timestamp",
        "fill_timestamp",
        "uTime",
        "cTime",
        "fillTime",
    ):
        value = order.get(key)
        try:
            if value is not None and value != "":
                return int(float(value))
        except (TypeError, ValueError):
            continue
    for key in ("updated_datetime", "created_datetime", "fill_datetime", "datetime"):
        value = order.get(key)
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp() * 1000)
        except ValueError:
            continue
    return 0

def _live_order_finite_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"none", "null", "nan", "--"}:
            return None
        value = text.replace(",", "")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None

def _first_live_order_float(*values: Any, prefer_non_zero: bool = False) -> Optional[float]:
    first: Optional[float] = None
    for value in values:
        number = _live_order_finite_float(value)
        if number is None:
            continue
        if first is None:
            first = number
        if not prefer_non_zero or abs(number) > 1e-12:
            return number
    return first

def _first_live_order_text(*values: Any) -> Optional[str]:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None

def _live_order_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}

def _normalize_live_order_financial_fields(order: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(order)
    info = _live_order_dict(normalized.get("info"))
    fee = normalized.get("fee")
    fee_row = _live_order_dict(fee)
    info_fee_row = _live_order_dict(info.get("fee"))
    fees = normalized.get("fees")
    first_fee = _live_order_dict(fees[0]) if isinstance(fees, list) and fees else {}

    realized_pnl = _first_live_order_float(
        normalized.get("pnl"),
        normalized.get("realized_pnl"),
        normalized.get("realizedPnl"),
        normalized.get("closed_pnl"),
        normalized.get("closedPnl"),
        normalized.get("fill_pnl"),
        normalized.get("fillPnl"),
        info.get("pnl"),
        info.get("realized_pnl"),
        info.get("realizedPnl"),
        info.get("closed_pnl"),
        info.get("closedPnl"),
        info.get("fill_pnl"),
        info.get("fillPnl"),
        prefer_non_zero=True,
    )
    if realized_pnl is not None:
        normalized["pnl"] = realized_pnl
        normalized["realized_pnl"] = realized_pnl

    fee_value = _first_live_order_float(
        None if isinstance(fee, (dict, list)) else fee,
        normalized.get("fee_cost"),
        normalized.get("feeCost"),
        fee_row.get("cost"),
        fee_row.get("fee"),
        first_fee.get("cost"),
        first_fee.get("fee"),
        None if isinstance(info.get("fee"), (dict, list)) else info.get("fee"),
        info_fee_row.get("cost"),
        info_fee_row.get("fee"),
        info.get("fee_cost"),
        info.get("feeCost"),
        info.get("fill_fee"),
        info.get("fillFee"),
    )
    if fee_value is not None:
        normalized["fee"] = fee_value

    fee_currency = _first_live_order_text(
        normalized.get("fee_currency"),
        normalized.get("feeCurrency"),
        normalized.get("fee_ccy"),
        normalized.get("feeCcy"),
        fee_row.get("currency"),
        fee_row.get("ccy"),
        first_fee.get("currency"),
        first_fee.get("ccy"),
        info.get("fee_currency"),
        info.get("feeCurrency"),
        info.get("fee_ccy"),
        info.get("feeCcy"),
        info_fee_row.get("currency"),
        info_fee_row.get("ccy"),
    )
    if fee_currency:
        normalized["fee_currency"] = fee_currency

    return normalized

def _merge_live_order_history(
    exchange_orders: List[Dict[str, Any]],
    execution_failure_orders: List[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    merged = [*exchange_orders, *execution_failure_orders]
    merged.sort(key=_order_history_sort_ms, reverse=True)
    return merged[: int(max(1, limit))]
