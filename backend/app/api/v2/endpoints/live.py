"""
Live trading orchestration — v2 `/live/*` used by LiveTrading.tsx.

与单策略引擎 `strategy_engine` 对齐：configure 写入 strategies 表后 start 启动对应 ID。
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import APIRouter, Body, Query

from app.core.contracts import ok
from app.core.errors import BadRequestError, NotFoundError
from app.db.local_db import db_instance as db
from app.domain.funding import funding_domain_service
from app.domain.market import market_domain_service
from app.exchange import exchange_manager
from app.services.strategy_engine import LiveContractBroker, strategy_engine
from app.services.binance_usdm_contract_broker import BinanceUsdmContractBroker
from app.services.strategy_diagnostic_presentation import compose_strategy_diagnostic_events
from app.services.strategy_log_store import strategy_log_store
from app.services.feishu_notifier import feishu_notifier
from app.services import live_account_service
from app.services.live_signal_execution_service import live_signal_execution_service
from app.services.strategy_exit_protection import audit_strategy_exit_protection
from app.services.contract_paper_account import normalize_contract_symbol
from app.services.dynamic_pool_presentation import normalize_dynamic_pool_view
from app.services.paper_performance_metrics import equity_curve_risk_metrics
from app.services.paper_observability import (
    PAPER_OBSERVABILITY_CONTRACT_VERSION,
    equity_curve_summary,
    equity_curve_version,
    paper_config_version,
    paper_evidence,
    strategy_version,
    utc_now_iso,
)
from app.services.strategy_registry import resolve_unified_base_strategy_class
from app.services.telegram_notifier import telegram_notifier
from app.services.trading_service import trading_service
# 兼容原有测试与内部调用：拆分后的模型和辅助函数继续从 live 模块导出。
from app.api.v2.endpoints.live_support import (  # noqa: F401
    _SUPERPNL_DEFAULT_SYMBOLS,
    _SUPERPNL_STRATEGY_KEY,
    LiveAccountCreateBody,
    LiveConfigureBody,
    LiveInstanceBody,
    LivePositionCloseBody,
    LiveStrategyDeployBody,
    LiveStrategyPreflightBody,
    LiveStrategySettingBody,
    LiveStrategySubscriptionControlBody,
    PaperPositionCloseBody,
    PreFlightBody,
    PromoteToLiveBody,
    TelegramTestBody,
    _account_equity,
    _apply_dynamic_live_symbol_filter,
    _apply_live_account_equity,
    _asset_prefix_for_config,
    _binance_usdm_position_mode_from_response,
    _build_promoted_live_config,
    _call_okx_public_method,
    _cap_fraction,
    _config_symbols,
    _config_trade_symbols,
    _configured_initial_capital,
    _configured_min_order_notional,
    _configured_order_quote,
    _configured_symbols,
    _defined_symbols,
    _dynamic_preflight_min_symbols,
    _extract_okx_rows,
    _first_live_order_float,
    _first_live_order_text,
    _float_value,
    _format_duration_seconds,
    _git_commit_ref,
    _has_explicit_order_quote,
    _is_contract_live_candidate,
    _is_superpnl_strategy,
    _kline_timestamp_ms,
    _live_account_exchange_alias,
    _live_account_trade_permission_check,
    _live_contract_account_precheck,
    _live_contract_position_targets,
    _live_contract_symbols,
    _live_deployment_is_stopped,
    _live_execution_body_to_promote,
    _live_open_position_symbols,
    _live_order_dict,
    _live_order_finite_float,
    _live_position_side,
    _live_position_size,
    _live_position_symbol,
    _market_rules_check,
    _merge_live_order_history,
    _normalize_ccxt_positions,
    _normalize_live_order_financial_fields,
    _normalize_watch_symbol,
    _okx_basis_points,
    _okx_inst_id,
    _okx_long_short_ratio_points,
    _okx_open_interest_points,
    _okx_position_mode_from_response,
    _okx_public_api,
    _okx_taker_volume_points,
    _optional_float,
    _order_book_liquidity_check,
    _order_history_sort_ms,
    _paper_positions_from_status,
    _parse_strategy_id,
    _point,
    _position_info,
    _position_symbols_from_status,
    _preview_symbols,
    _promoted_live_strategy_name,
    _promotion_account_id_from_config,
    _promotion_account_sizing_checks,
    _promotion_plan,
    _row_symbols,
    _runtime_strategy_symbols,
    _spot_positions_from_balances,
    _strategy_defined_timeframe,
    _strip_asset_prefix,
    _timeframe_seconds,
    _venue_contract_symbol_pairs,
    _timeframe_to_okx_period,
    _uptime_str,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# 最近一次 Live 配置对应的策略 ID（configure / start 成功后会设置）
_active_strategy_id: Optional[int] = None

# 权益曲线采样：strategy_id -> 时间序列
_equity_curve_samples: Dict[int, List[Dict[str, Any]]] = {}
_EQUITY_MAX = 400

_LIVE_PRIVATE_READ_CACHE_TTL_SEC = 3.0
_LIVE_ASSET_PRIVATE_READ_CACHE_TTL_SEC = 60.0
_live_private_read_cache: Dict[tuple[Any, ...], tuple[float, Any]] = {}
_live_private_read_inflight: Dict[tuple[Any, ...], asyncio.Task[Any]] = {}
_LIVE_WORKSPACE_CANDIDATE_CACHE_MAX = 1024
_live_workspace_candidate_cache: Dict[str, bool] = {}
_live_workspace_candidate_cache_lock = threading.Lock()


def _clone_live_private_read(value: Any) -> Any:
    return copy.deepcopy(value)


def _clear_live_private_read_cache(exchange: Optional[str] = None) -> None:
    if not exchange:
        _live_private_read_cache.clear()
        return
    for key in list(_live_private_read_cache):
        if len(key) > 1 and key[1] == exchange:
            _live_private_read_cache.pop(key, None)


async def _cached_live_private_read(
    key: tuple[Any, ...],
    loader: Callable[[], Awaitable[Any]],
    *,
    ttl_sec: float = _LIVE_PRIVATE_READ_CACHE_TTL_SEC,
) -> Any:
    now = time.monotonic()
    cached = _live_private_read_cache.get(key)
    if cached is not None:
        cached_at, value = cached
        if now - cached_at <= ttl_sec:
            return _clone_live_private_read(value)
        _live_private_read_cache.pop(key, None)

    inflight = _live_private_read_inflight.get(key)
    if inflight is not None and not inflight.done():
        return _clone_live_private_read(await inflight)

    task = asyncio.create_task(loader())
    _live_private_read_inflight[key] = task
    try:
        value = await task
    finally:
        if _live_private_read_inflight.get(key) is task:
            _live_private_read_inflight.pop(key, None)
    if len(_live_private_read_cache) > 128:
        _live_private_read_cache.clear()
    _live_private_read_cache[key] = (time.monotonic(), _clone_live_private_read(value))
    return _clone_live_private_read(value)


async def _cached_live_positions(exchange: str, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    return await _cached_live_private_read(
        ("positions", exchange, symbol or ""),
        lambda: trading_service.get_positions(exchange, symbol),
    )


async def _cached_live_balance(exchange: str) -> List[Dict[str, Any]]:
    return await _cached_live_private_read(
        ("balance", exchange),
        lambda: trading_service.get_balance(exchange),
        ttl_sec=_LIVE_ASSET_PRIVATE_READ_CACHE_TTL_SEC,
    )


async def _cached_live_balance_detail(exchange: str) -> Dict[str, Any]:
    return await _cached_live_private_read(
        ("balance_detail", exchange),
        lambda: trading_service.get_balance_detail(exchange),
        ttl_sec=_LIVE_ASSET_PRIVATE_READ_CACHE_TTL_SEC,
    )


async def _cached_live_return_rates(exchange: str) -> Dict[str, Any]:
    return await _cached_live_private_read(
        ("return_rates", exchange),
        lambda: trading_service.get_account_return_rates(exchange),
        ttl_sec=_LIVE_ASSET_PRIVATE_READ_CACHE_TTL_SEC,
    )


async def _cached_live_open_orders(exchange: str, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    return await _cached_live_private_read(
        ("open_orders", exchange, symbol or ""),
        lambda: trading_service.get_open_orders(exchange, symbol),
    )


async def _cached_live_order_history(
    exchange: str,
    symbol: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    return await _cached_live_private_read(
        ("order_history", exchange, symbol or "", int(limit)),
        lambda: trading_service.get_order_history(exchange, symbol, limit),
    )


async def _cached_live_account_order_history(
    *,
    account_id: str,
    exchange: str,
    symbol: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Read account history, expanding Binance USD-M into symbol queries.

    Binance's USD-M user-trades API requires one contract symbol, while OKX
    supports an account-wide history request.  For the account-wide Binance
    view, use open positions first and then the most recent BitPro execution
    symbols.  Keep the candidate set bounded because the watch page refreshes
    this private endpoint periodically.
    """
    if symbol or str(exchange).split(":", 1)[0].lower() != "binanceusdm":
        return await _cached_live_order_history(exchange, symbol, limit)

    positions = await _cached_live_positions(exchange)
    candidates: List[str] = []
    seen_symbols: set[str] = set()

    def append_symbol(value: Any) -> None:
        normalized = normalize_contract_symbol(str(value or ""))
        if not normalized or normalized in seen_symbols:
            return
        seen_symbols.add(normalized)
        candidates.append(normalized)

    for position in positions:
        if abs(_live_position_size(position)) > 1e-12:
            append_symbol(_live_position_symbol(position))

    for item in live_signal_execution_service.list_watchlist_items(
        account_id=account_id,
        limit=20,
    ):
        append_symbol(item.get("symbol"))
        if len(candidates) >= 20:
            break

    candidates = candidates[:20]
    if not candidates:
        return []

    histories = await asyncio.gather(
        *[
            _cached_live_order_history(exchange, candidate, limit)
            for candidate in candidates
        ]
    )
    orders = [order for history in histories for order in history]
    orders.sort(key=_order_history_sort_ms, reverse=True)
    return orders[: int(max(1, limit))]


def _resolve_target_strategy_id() -> Optional[int]:
    if _active_strategy_id is not None:
        return _active_strategy_id
    ids = strategy_engine.list_running_or_paused_ids()
    return ids[0] if ids else None


def _resolve_instance_sid(
    body: Optional[LiveInstanceBody],
    *,
    query_id: Optional[int] = None,
) -> Optional[int]:
    if query_id is not None:
        return int(query_id)
    if body is not None and body.instance_id is not None:
        return int(body.instance_id)
    if body is not None and body.strategy_type is not None and str(body.strategy_type).strip():
        return _parse_strategy_id(body.strategy_type)
    return _resolve_target_strategy_id()


def _refresh_paper_marks(strategy_id: int, exchange_name: str, symbols: List[str]) -> None:
    """模拟盘展示前用最新 ticker 刷新持仓标记价。"""
    if not symbols:
        return
    ex = exchange_manager.get_exchange(exchange_name or "okx")
    if not ex:
        return
    prices: Dict[str, float] = {}
    for sym in symbols:
        try:
            ticker = ex.fetch_ticker(sym)
            px = float(ticker.get("last") or 0)
        except Exception as e:
            logger.debug("refresh paper mark failed: %s %s", sym, e)
            continue
        if px > 0:
            prices[sym] = px
    if prices:
        strategy_engine.refresh_paper_marks(strategy_id, prices)


def _feishu_dashboard_slice() -> Dict[str, Any]:
    return {
        "enabled": bool(feishu_notifier.is_ready()),
        "webhook_configured": bool(feishu_notifier.has_webhook()),
        "messages_sent": len(getattr(feishu_notifier, "_history", []) or []),
    }


def _append_equity_sample(strategy_id: int, ts: float, equity: float) -> None:
    if equity <= 0:
        return
    ts_ms = int(ts * 1000)
    try:
        if hasattr(db, "insert_strategy_equity_sample"):
            db.insert_strategy_equity_sample(
                strategy_id,
                ts_ms,
                equity,
                source="dashboard",
            )
    except Exception as exc:
        logger.debug("Persist equity sample failed for %s: %s", strategy_id, exc)
    seq = _equity_curve_samples.setdefault(strategy_id, [])
    sample = {
        "timestamp": ts_ms,
        "equity": equity,
        "time": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(),
    }
    if seq and int(seq[-1].get("timestamp") or 0) == ts_ms:
        seq[-1] = sample
    else:
        seq.append(sample)
    if len(seq) > _EQUITY_MAX:
        del seq[: len(seq) - _EQUITY_MAX]


def _load_persisted_equity_samples(strategy_id: int) -> List[Dict[str, Any]]:
    if not hasattr(db, "get_strategy_equity_samples"):
        return _equity_curve_samples.get(strategy_id, [])
    try:
        rows = db.get_strategy_equity_samples(strategy_id, _EQUITY_MAX)
    except Exception as exc:
        logger.debug("Load persisted equity samples failed for %s: %s", strategy_id, exc)
        return _equity_curve_samples.get(strategy_id, [])
    if rows:
        _equity_curve_samples[strategy_id] = _restore_equity_sample_trade_metrics(
            strategy_id,
            list(rows),
        )
        return _equity_curve_samples[strategy_id]
    return _equity_curve_samples.get(strategy_id, [])


def _restore_equity_sample_trade_metrics(
    strategy_id: int,
    samples: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Rebuild legacy curve metrics from persisted closing trades after restarts."""
    if not samples or not hasattr(db, "get_strategy_trades_since"):
        return samples

    since_ms = min(int(row.get("timestamp") or 0) for row in samples)
    try:
        strategy = db.get_strategy_by_id(strategy_id) if hasattr(db, "get_strategy_by_id") else None
        run_started_at = (strategy or {}).get("run_started_at")
        if run_started_at:
            started_at = datetime.fromisoformat(str(run_started_at).replace("Z", "+00:00"))
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            since_ms = int(started_at.timestamp() * 1000)
        trades = db.get_strategy_trades_since(strategy_id, since_ms)
    except Exception as exc:
        logger.debug("Restore equity trade metrics failed for %s: %s", strategy_id, exc)
        return samples

    closing_trades: List[Dict[str, Any]] = []
    for trade in trades:
        side = str(trade.get("side") or "").strip().lower()
        if side in {"sell", "spot_sell", "close_long", "close_short"}:
            closing_trades.append(trade)
    if not closing_trades:
        return samples
    closing_trades.sort(key=lambda row: int(row.get("timestamp") or 0))

    restored: List[Dict[str, Any]] = []
    trade_index = 0
    closed_count = 0
    winning_count = 0
    gross_profit = 0.0
    gross_loss = 0.0
    for original in sorted(samples, key=lambda row: int(row.get("timestamp") or 0)):
        sample = dict(original)
        sample_ts = int(sample.get("timestamp") or 0)
        while trade_index < len(closing_trades):
            trade = closing_trades[trade_index]
            if int(trade.get("timestamp") or 0) > sample_ts:
                break
            trade_index += 1
            closed_count += 1
            try:
                pnl = float(trade.get("pnl") or 0.0)
            except (TypeError, ValueError):
                pnl = 0.0
            if pnl > 0:
                winning_count += 1
                gross_profit += pnl
            elif pnl < 0:
                gross_loss += abs(pnl)

        if closed_count > 0:
            sample["win_rate"] = round(winning_count / closed_count * 100, 4)
        else:
            sample.pop("win_rate", None)
        if gross_loss > 0:
            sample["profit_factor"] = round(gross_profit / gross_loss, 4)
        else:
            sample.pop("profit_factor", None)
        restored.append(sample)
    return restored


def _unique_strategy_name(base_name: str) -> str:
    existing_names = {str(item.get("name") or "") for item in db.get_strategies()}
    if base_name not in existing_names:
        return base_name
    suffix = 2
    while f"{base_name} #{suffix}" in existing_names:
        suffix += 1
    return f"{base_name} #{suffix}"


def _live_promotion_conflicts(
    source_strategy_id: int,
    *,
    account_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    normalized_account = (
        live_account_service.normalize_account_id(account_id)
        if account_id is not None
        else None
    )
    conflicts: List[Dict[str, Any]] = []
    for item in db.get_strategies():
        try:
            sid = int(item.get("id") or 0)
        except (TypeError, ValueError):
            sid = 0
        cfg = item.get("config") or {}
        if not isinstance(cfg, dict) or cfg.get("is_paper_trading") is not False:
            continue
        promotion = cfg.get("promotion")
        if not isinstance(promotion, dict):
            continue
        try:
            promoted_from = int(promotion.get("source_strategy_id") or 0)
        except (TypeError, ValueError):
            promoted_from = 0
        if promoted_from != int(source_strategy_id):
            continue
        if normalized_account is not None and _promotion_account_id_from_config(cfg) != normalized_account:
            continue
        status = str(item.get("status") or "").lower()
        engine_status = strategy_engine.get_strategy_status(sid) if sid > 0 else None
        engine_state = str((engine_status or {}).get("status") or "").lower()
        active_states = {"running", "paused", "starting", "stopping"}
        if status in active_states or engine_state in active_states:
            conflicts.append(
                {
                    "id": sid,
                    "name": item.get("name") or "",
                    "status": status or engine_state or "unknown",
                }
            )
    return conflicts


def _ensure_live_strategy_settings_table() -> None:
    live_signal_execution_service.ensure_schema()
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS live_strategy_settings (
            strategy_id INTEGER PRIMARY KEY,
            added INTEGER NOT NULL DEFAULT 0,
            account_id TEXT DEFAULT 'default',
            deployment_strategy_id INTEGER,
            status TEXT DEFAULT 'added',
            risk_config TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (strategy_id) REFERENCES strategies(id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS live_strategy_account_bindings (
            strategy_id INTEGER NOT NULL,
            account_id TEXT NOT NULL,
            added INTEGER NOT NULL DEFAULT 1,
            deployment_strategy_id INTEGER,
            status TEXT DEFAULT 'added',
            risk_config TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (strategy_id, account_id),
            FOREIGN KEY (strategy_id) REFERENCES strategies(id)
        )
        """
    )
    conn.commit()
    conn.close()


def _live_strategy_settings_by_id() -> Dict[int, Dict[str, Any]]:
    _ensure_live_strategy_settings_table()
    conn = db.get_connection()
    rows = conn.execute(
        """
        SELECT strategy_id, added, account_id, deployment_strategy_id, status,
               risk_config, created_at, updated_at
        FROM live_strategy_settings
        """
    ).fetchall()
    conn.close()
    settings: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        try:
            item["strategy_id"] = int(item["strategy_id"])
        except (TypeError, ValueError):
            continue
        item["added"] = bool(int(item.get("added") or 0))
        item["risk_config"] = _json_dict(item.get("risk_config"))
        settings[int(item["strategy_id"])] = item
    return settings


def _live_strategy_setting(strategy_id: int) -> Optional[Dict[str, Any]]:
    return _live_strategy_settings_by_id().get(int(strategy_id))


def _live_strategy_account_bindings_by_strategy(
    settings: Optional[Dict[int, Dict[str, Any]]] = None,
) -> Dict[int, Dict[str, Dict[str, Any]]]:
    _ensure_live_strategy_settings_table()
    conn = db.get_connection()
    rows = conn.execute(
        """
        SELECT strategy_id, account_id, added, deployment_strategy_id, status,
               risk_config, created_at, updated_at
        FROM live_strategy_account_bindings
        """
    ).fetchall()
    conn.close()
    out: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for row in rows:
        item = dict(row)
        try:
            strategy_id = int(item.get("strategy_id") or 0)
        except (TypeError, ValueError):
            continue
        account_id = live_account_service.normalize_account_id(item.get("account_id"))
        item["strategy_id"] = strategy_id
        item["account_id"] = account_id
        item["added"] = bool(int(item.get("added") or 0))
        item["risk_config"] = _json_dict(item.get("risk_config"))
        out.setdefault(strategy_id, {})[account_id] = item

    settings = settings if settings is not None else _live_strategy_settings_by_id()
    for strategy_id, setting in settings.items():
        if not setting.get("added"):
            continue
        if str(setting.get("status") or "").lower() in {"workspace_added", "preflight_failed_unbound"}:
            continue
        account_id = live_account_service.normalize_account_id(setting.get("account_id"))
        bindings = out.setdefault(strategy_id, {})
        if account_id not in bindings:
            bindings[account_id] = {
                "strategy_id": strategy_id,
                "account_id": account_id,
                "added": True,
                "deployment_strategy_id": setting.get("deployment_strategy_id"),
                "status": setting.get("status") or "added",
                "risk_config": setting.get("risk_config") or {},
                "created_at": setting.get("created_at"),
                "updated_at": setting.get("updated_at"),
            }
    return out


def _upsert_live_strategy_account_binding(
    strategy_id: int,
    *,
    account_id: str,
    added: bool = True,
    risk_config: Optional[Dict[str, Any]] = None,
    deployment_strategy_id: Optional[int] = None,
    clear_deployment_strategy_id: bool = False,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    if not db.get_strategy_by_id(int(strategy_id)):
        raise NotFoundError("Strategy not found")
    _ensure_live_strategy_settings_table()
    normalized_account = (
        live_account_service.validate_live_deployable_account_id(account_id)
        if added
        else live_account_service.validate_account_id(account_id)
    )
    now = datetime.now(timezone.utc).isoformat()
    existing = _live_strategy_account_bindings_by_strategy().get(int(strategy_id), {}).get(normalized_account) or {}
    if clear_deployment_strategy_id:
        next_deployment_id = None
    elif deployment_strategy_id is not None:
        next_deployment_id = int(deployment_strategy_id)
    else:
        next_deployment_id = existing.get("deployment_strategy_id")
    next_status = status or ("added" if added else "removed")
    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO live_strategy_account_bindings (
            strategy_id, account_id, added, deployment_strategy_id, status,
            risk_config, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(strategy_id, account_id) DO UPDATE SET
            added = excluded.added,
            deployment_strategy_id = COALESCE(excluded.deployment_strategy_id, live_strategy_account_bindings.deployment_strategy_id),
            status = excluded.status,
            risk_config = excluded.risk_config,
            updated_at = excluded.updated_at
        """,
        (
            int(strategy_id),
            normalized_account,
            1 if added else 0,
            next_deployment_id,
            next_status,
            json.dumps(risk_config or existing.get("risk_config") or {}, ensure_ascii=False),
            existing.get("created_at") or now,
            now,
        ),
    )
    conn.commit()
    if clear_deployment_strategy_id:
        conn.execute(
            """
            UPDATE live_strategy_account_bindings
            SET deployment_strategy_id = NULL,
                updated_at = ?
            WHERE strategy_id = ? AND account_id = ?
            """,
            (now, int(strategy_id), normalized_account),
        )
        conn.commit()
    conn.close()
    return _live_strategy_account_bindings_by_strategy().get(int(strategy_id), {}).get(normalized_account) or {}


def _mark_live_strategy_account_bindings_removed(strategy_id: int) -> None:
    _ensure_live_strategy_settings_table()
    conn = db.get_connection()
    conn.execute(
        """
        UPDATE live_strategy_account_bindings
        SET added = 0, status = 'removed', updated_at = ?
        WHERE strategy_id = ?
        """,
        (datetime.now(timezone.utc).isoformat(), int(strategy_id)),
    )
    conn.commit()
    conn.close()


def _clear_live_execution_deployment(live_strategy_id: int) -> None:
    _ensure_live_strategy_settings_table()
    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_connection()
    conn.execute(
        """
        UPDATE live_strategy_account_bindings
        SET deployment_strategy_id = NULL,
            status = CASE WHEN added = 1 THEN 'added' ELSE 'removed' END,
            updated_at = ?
        WHERE deployment_strategy_id = ?
        """,
        (now, int(live_strategy_id)),
    )
    conn.execute(
        """
        UPDATE live_strategy_settings
        SET deployment_strategy_id = NULL,
            status = CASE WHEN added = 1 THEN 'added' ELSE 'removed' END,
            updated_at = ?
        WHERE deployment_strategy_id = ?
        """,
        (now, int(live_strategy_id)),
    )
    conn.commit()
    conn.close()


def _json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _upsert_live_strategy_setting(
    strategy_id: int,
    *,
    added: bool,
    account_id: str = "default",
    risk_config: Optional[Dict[str, Any]] = None,
    deployment_strategy_id: Optional[int] = None,
    clear_deployment_strategy_id: bool = False,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    if not db.get_strategy_by_id(int(strategy_id)):
        raise NotFoundError("Strategy not found")
    _ensure_live_strategy_settings_table()
    now = datetime.now(timezone.utc).isoformat()
    setting = _live_strategy_setting(int(strategy_id)) or {}
    next_status = status or ("added" if added else "removed")
    if clear_deployment_strategy_id:
        next_deployment_id = None
    elif deployment_strategy_id is not None:
        next_deployment_id = int(deployment_strategy_id)
    else:
        next_deployment_id = setting.get("deployment_strategy_id")
    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO live_strategy_settings (
            strategy_id, added, account_id, deployment_strategy_id, status,
            risk_config, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(strategy_id) DO UPDATE SET
            added = excluded.added,
            account_id = excluded.account_id,
            deployment_strategy_id = COALESCE(excluded.deployment_strategy_id, live_strategy_settings.deployment_strategy_id),
            status = excluded.status,
            risk_config = excluded.risk_config,
            updated_at = excluded.updated_at
        """,
        (
            int(strategy_id),
            1 if added else 0,
            (account_id or "default").strip() or "default",
            next_deployment_id,
            next_status,
            json.dumps(risk_config or {}, ensure_ascii=False),
            setting.get("created_at") or now,
            now,
        ),
    )
    conn.commit()
    if clear_deployment_strategy_id:
        conn.execute(
            """
            UPDATE live_strategy_settings
            SET deployment_strategy_id = NULL,
                updated_at = ?
            WHERE strategy_id = ?
            """,
            (now, int(strategy_id)),
        )
        conn.commit()
    conn.close()
    if not added:
        _mark_live_strategy_account_bindings_removed(int(strategy_id))
    return _live_strategy_setting(int(strategy_id)) or {}


def _deployed_live_strategy_for_source(
    source_strategy_id: int,
    *,
    account_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    normalized_account = (
        live_account_service.normalize_account_id(account_id)
        if account_id is not None
        else None
    )
    if normalized_account is not None:
        binding = _live_strategy_account_bindings_by_strategy().get(int(source_strategy_id), {}).get(normalized_account)
        if binding and binding.get("deployment_strategy_id"):
            deployed = db.get_strategy_by_id(int(binding["deployment_strategy_id"]))
            if deployed and not _live_deployment_is_stopped(deployed):
                return deployed
    setting = _live_strategy_setting(int(source_strategy_id))
    setting_account = live_account_service.normalize_account_id((setting or {}).get("account_id"))
    if (
        setting
        and setting.get("deployment_strategy_id")
        and (normalized_account is None or setting_account == normalized_account)
    ):
        deployed = db.get_strategy_by_id(int(setting["deployment_strategy_id"]))
        if deployed and not _live_deployment_is_stopped(deployed):
            return deployed
    conflicts = _live_promotion_conflicts(int(source_strategy_id), account_id=normalized_account)
    if conflicts:
        return db.get_strategy_by_id(int(conflicts[0]["id"]))
    return None


def _live_subscription_for_source(
    source_strategy_id: int,
    *,
    account_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    statuses = sorted(live_signal_execution_service.DEPLOYED_STATUSES)
    if account_id is not None:
        subscription = live_signal_execution_service.get_subscription(
            int(source_strategy_id),
            live_account_service.normalize_account_id(account_id),
        )
        if subscription and str(subscription.get("status") or "").lower() in statuses:
            return subscription
        return None
    subscriptions = live_signal_execution_service.list_subscriptions(
        source_strategy_id=int(source_strategy_id),
        statuses=statuses,
    )
    return subscriptions[0] if subscriptions else None


def _blocking_live_subscriptions_for_workspace_remove(source_strategy_id: int) -> List[Dict[str, Any]]:
    return live_signal_execution_service.list_subscriptions(
        source_strategy_id=int(source_strategy_id),
        statuses=sorted(live_signal_execution_service.DEPLOYED_STATUSES),
    )


def _running_live_subscriptions_for_source_strategy(source_strategy_id: int) -> List[Dict[str, Any]]:
    return live_signal_execution_service.list_subscriptions(
        source_strategy_id=int(source_strategy_id),
        statuses=sorted(live_signal_execution_service.ACTIVE_STATUSES),
    )


def _raise_if_paper_lifecycle_blocked_by_running_live(source_strategy_id: int, action_label: str) -> None:
    subscriptions = _running_live_subscriptions_for_source_strategy(int(source_strategy_id))
    if not subscriptions:
        return
    raise BadRequestError(
        f"该模拟策略正在驱动运行中的实盘订阅，请先在「实盘」右侧面板停止实盘订阅，"
        f"再{action_label}模拟交易。"
    )


def _raise_if_live_workspace_remove_blocked(source_strategy_id: int) -> None:
    subscriptions = _blocking_live_subscriptions_for_workspace_remove(int(source_strategy_id))
    if not subscriptions:
        return
    statuses = {str(item.get("status") or "").lower() for item in subscriptions}
    if statuses & live_signal_execution_service.ACTIVE_STATUSES:
        raise BadRequestError("实盘订阅正在运行，请先在右侧实盘面板停止后再移出实盘策略列表")
    if "paused" in statuses:
        raise BadRequestError("实盘订阅已暂停，需要先在右侧实盘面板停止后才能移出实盘策略列表")
    raise BadRequestError("该策略仍存在实盘订阅，请先停止后再移出实盘策略列表")


def _is_live_workspace_source(row: Dict[str, Any]) -> bool:
    cfg = row.get("config") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    if cfg.get("is_paper_trading") is False:
        return False
    name = str(row.get("name") or "")
    if "[实盘" in name or "实盘试运行" in name:
        return False
    return True


def _is_live_workspace_candidate(row: Dict[str, Any]) -> bool:
    if not _is_live_workspace_source(row):
        return False
    revision = json.dumps(
        {
            "db": id(db),
            "id": row.get("id"),
            "updated_at": row.get("updated_at"),
            "strategy_key": row.get("strategy_key"),
            "script_content": row.get("script_content"),
            "config": row.get("config"),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    cache_key = hashlib.sha256(revision).hexdigest()
    with _live_workspace_candidate_cache_lock:
        cached = _live_workspace_candidate_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            resolved = resolve_unified_base_strategy_class(row)
        except Exception:
            resolved = None
        deployable = resolved is not None
        if len(_live_workspace_candidate_cache) >= _LIVE_WORKSPACE_CANDIDATE_CACHE_MAX:
            _live_workspace_candidate_cache.clear()
        _live_workspace_candidate_cache[cache_key] = deployable
        return deployable


def _live_execution_batch_context(
    rows: List[Dict[str, Any]],
    settings: Dict[int, Dict[str, Any]],
    bindings_by_strategy: Dict[int, Dict[str, Dict[str, Any]]],
) -> Dict[str, Any]:
    rows_by_id = {
        int(row.get("id") or 0): row
        for row in rows
        if int(row.get("id") or 0) > 0
    }
    accounts_by_id = {
        str(account.get("account_id")): account
        for account in live_account_service.list_accounts()
    }
    subscriptions = live_signal_execution_service.list_subscriptions(
        statuses=sorted(live_signal_execution_service.DEPLOYED_STATUSES),
    )
    subscriptions_by_source: Dict[int, List[Dict[str, Any]]] = {}
    subscriptions_by_source_account: Dict[tuple[int, str], Dict[str, Any]] = {}
    for subscription in subscriptions:
        source_id = int(subscription.get("source_strategy_id") or 0)
        account_id = live_account_service.normalize_account_id(subscription.get("account_id"))
        subscriptions_by_source.setdefault(source_id, []).append(subscription)
        subscriptions_by_source_account.setdefault((source_id, account_id), subscription)

    deployed_by_source_account: Dict[tuple[int, Optional[str]], Dict[str, Any]] = {}
    active_states = {"running", "paused", "starting", "stopping"}
    for row in rows:
        cfg = row.get("config") or {}
        if not isinstance(cfg, dict) or cfg.get("is_paper_trading") is not False:
            continue
        promotion = cfg.get("promotion")
        if not isinstance(promotion, dict):
            continue
        source_id = int(promotion.get("source_strategy_id") or 0)
        strategy_id = int(row.get("id") or 0)
        status = str(row.get("status") or "").lower()
        engine_status = strategy_engine.get_strategy_status(strategy_id) if strategy_id > 0 else None
        engine_state = str((engine_status or {}).get("status") or "").lower()
        if source_id <= 0 or (status not in active_states and engine_state not in active_states):
            continue
        account_id = _promotion_account_id_from_config(cfg)
        deployed_by_source_account.setdefault((source_id, account_id), row)
        deployed_by_source_account.setdefault((source_id, None), row)

    for source_id, setting in settings.items():
        deployed = rows_by_id.get(int(setting.get("deployment_strategy_id") or 0))
        if not deployed or _live_deployment_is_stopped(deployed):
            continue
        account_id = live_account_service.normalize_account_id(setting.get("account_id"))
        deployed_by_source_account[(source_id, account_id)] = deployed
        deployed_by_source_account[(source_id, None)] = deployed

    for source_id, bindings in bindings_by_strategy.items():
        for account_id, binding in bindings.items():
            deployed = rows_by_id.get(int(binding.get("deployment_strategy_id") or 0))
            if deployed and not _live_deployment_is_stopped(deployed):
                deployed_by_source_account[(source_id, account_id)] = deployed

    return {
        "accounts_by_id": accounts_by_id,
        "subscriptions_by_source": subscriptions_by_source,
        "subscriptions_by_source_account": subscriptions_by_source_account,
        "deployed_by_source_account": deployed_by_source_account,
    }


def _has_live_workspace_state(
    strategy_id: int,
    settings: Dict[int, Dict[str, Any]],
    bindings_by_strategy: Dict[int, Dict[str, Dict[str, Any]]],
) -> bool:
    setting = settings.get(int(strategy_id)) or {}
    if setting.get("added") or setting.get("deployment_strategy_id"):
        return True
    bindings = bindings_by_strategy.get(int(strategy_id), {})
    return any(
        bool(binding.get("added")) or bool(binding.get("deployment_strategy_id"))
        for binding in bindings.values()
    )


def _runtime_strategy_metrics(strategy_id: int) -> Dict[str, Optional[float]]:
    try:
        status = strategy_engine.get_strategy_status(int(strategy_id))
    except Exception:
        status = None
    if not isinstance(status, dict):
        return {"total_pnl": None, "return_pct": None}
    return {
        "total_pnl": _float_value(status.get("pnl"), None),
        "return_pct": _float_value(status.get("return_pct"), None),
    }


def _live_execution_strategy_payload(
    row: Dict[str, Any],
    settings: Optional[Dict[int, Dict[str, Any]]] = None,
    bindings_by_strategy: Optional[Dict[int, Dict[str, Dict[str, Any]]]] = None,
    *,
    accounts_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
    subscriptions_by_source: Optional[Dict[int, List[Dict[str, Any]]]] = None,
    subscriptions_by_source_account: Optional[Dict[tuple[int, str], Dict[str, Any]]] = None,
    deployed_by_source_account: Optional[Dict[tuple[int, Optional[str]], Dict[str, Any]]] = None,
    deployable: Optional[bool] = None,
) -> Dict[str, Any]:
    settings = settings if settings is not None else _live_strategy_settings_by_id()
    bindings_by_strategy = (
        bindings_by_strategy
        if bindings_by_strategy is not None
        else _live_strategy_account_bindings_by_strategy()
    )
    strategy_id = int(row.get("id") or 0)
    setting = settings.get(strategy_id) or {}
    account_meta = accounts_by_id if accounts_by_id is not None else {
        str(account.get("account_id")): account for account in live_account_service.list_accounts()
    }
    raw_bindings = bindings_by_strategy.get(strategy_id, {})
    cfg = row.get("config") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    account_bindings: List[Dict[str, Any]] = []
    for account_id, binding in sorted(raw_bindings.items(), key=lambda item: (item[0] != "default", item[0])):
        subscription_for_account = (
            subscriptions_by_source_account.get((strategy_id, account_id))
            if subscriptions_by_source_account is not None
            else _live_subscription_for_source(strategy_id, account_id=account_id)
        )
        deployed_for_account = None if subscription_for_account else (
            deployed_by_source_account.get((strategy_id, account_id))
            if deployed_by_source_account is not None
            else _deployed_live_strategy_for_source(strategy_id, account_id=account_id)
        )
        deployed_id = (
            int(deployed_for_account["id"]) if deployed_for_account else None
        )
        deployed_status = (
            str(subscription_for_account.get("status") or "")
            if subscription_for_account
            else str(deployed_for_account.get("status") or "") if deployed_for_account else None
        )
        meta = account_meta.get(account_id) or {}
        added_binding = bool(binding.get("added")) or deployed_for_account is not None or subscription_for_account is not None
        if not added_binding:
            continue
        is_deployed = subscription_for_account is not None or deployed_for_account is not None
        account_bindings.append(
            {
                "account_id": account_id,
                "account_name": meta.get("name") or account_id,
                "exchange": meta.get("exchange") or "okx",
                "exchange_alias": meta.get("exchange_alias") or live_account_service.exchange_alias_for_account(account_id),
                "masked_api_key": meta.get("masked_api_key"),
                "testnet": bool(meta.get("testnet")),
                "added": added_binding,
                "deployed": is_deployed,
                "live_subscription_id": int(subscription_for_account["id"]) if subscription_for_account else None,
                "deployment_strategy_id": deployed_id,
                "deployment_status": deployed_status,
                "status": binding.get("status") or ("deployed" if is_deployed else "added"),
                "risk_config": binding.get("risk_config") or {},
                "created_at": binding.get("created_at"),
                "updated_at": binding.get("updated_at"),
            }
        )

    account_ids = [item["account_id"] for item in account_bindings]
    subscription = (
        (subscriptions_by_source.get(strategy_id) or [None])[0]
        if subscriptions_by_source is not None
        else _live_subscription_for_source(strategy_id)
    )
    deployed = None if subscription else (
        deployed_by_source_account.get((strategy_id, None))
        if deployed_by_source_account is not None
        else _deployed_live_strategy_for_source(strategy_id)
    )
    deployed_id = int(deployed["id"]) if deployed else None
    deployed_status = (
        str(subscription.get("status") or "")
        if subscription
        else str(deployed.get("status") or "") if deployed else None
    )
    symbols = _defined_symbols(row, cfg, None)
    metrics = _runtime_strategy_metrics(strategy_id)
    has_deployment = subscription is not None or deployed is not None
    added = bool(setting.get("added")) or bool(account_bindings) or has_deployment
    status = str(setting.get("status") or ("deployed" if has_deployment else "added" if added else "available"))
    if has_deployment and status in {"available", "added"}:
        status = "deployed"
    primary_account_id = live_account_service.normalize_account_id(
        setting.get("account_id") or (account_ids[0] if account_ids else "default")
    )
    return {
        "strategy_id": strategy_id,
        "strategy_name": str(row.get("name") or f"策略 #{strategy_id}"),
        "added": added,
        "deployable": _is_live_workspace_candidate(row) if deployable is None else deployable,
        "deployed": has_deployment,
        "live_subscription_id": int(subscription["id"]) if subscription else None,
        "deployment_strategy_id": deployed_id,
        "deployment_strategy_name": None if subscription else deployed.get("name") if deployed else None,
        "deployment_status": deployed_status,
        "status": str(row.get("status") or ""),
        "workspace_status": status,
        "exchange": str(row.get("exchange") or "okx"),
        "account_id": primary_account_id,
        "account_ids": account_ids,
        "account_bindings": account_bindings,
        "symbols": symbols,
        "trade_symbols": _config_trade_symbols(cfg),
        "market_type": str(cfg.get("market_type") or "spot"),
        "risk_config": setting.get("risk_config") or {},
        "total_pnl": metrics["total_pnl"],
        "return_pct": metrics["return_pct"],
        "created_at": row.get("created_at"),
        "updated_at": setting.get("updated_at") or row.get("updated_at"),
    }


def _prepare_promoted_live_candidate(body: PromoteToLiveBody) -> Dict[str, Any]:
    account_id = live_account_service.validate_live_deployable_account_id(body.account_id or "default")
    body.account_id = account_id
    body.exchange = live_account_service.exchange_alias_for_account(account_id)
    source = db.get_strategy_by_id(int(body.source_strategy_id))
    if not source:
        raise NotFoundError("未找到来源模拟策略")

    source_cfg = source.get("config") or {}
    if not isinstance(source_cfg, dict):
        source_cfg = {}

    symbols = _defined_symbols(source, dict(source_cfg), None)
    symbol_scope = "strategy_symbols"
    requested_initial_equity = _float_value(body.initial_equity, 0.0)
    try:
        live_cfg = json.loads(json.dumps(source_cfg, ensure_ascii=False))
    except Exception:
        live_cfg = dict(source_cfg)
    live_cfg["is_paper_trading"] = False
    live_cfg["dry_run"] = False
    live_cfg["loop_interval_sec"] = int(body.loop_interval)
    if requested_initial_equity > 0:
        live_cfg["initial_capital"] = requested_initial_equity
        live_cfg["initial_capital_source"] = "request"
    if requested_initial_equity <= 0:
        live_cfg.setdefault("initial_capital", source_cfg.get("initial_capital", 1.0))
        live_cfg["initial_capital_source"] = "live_account_free_usdt"
    live_cfg["live_account_id"] = account_id
    live_cfg["exchange"] = body.exchange
    promotion = live_cfg.get("promotion")
    if not isinstance(promotion, dict):
        promotion = {}
        live_cfg["promotion"] = promotion
    promotion.update(
        {
            "mode": "live_signal_subscription",
            "source_strategy_id": int(body.source_strategy_id),
            "account_id": account_id,
            "exchange_alias": body.exchange,
            "loop_interval_sec": int(body.loop_interval),
        }
    )
    if isinstance(promotion, dict):
        if requested_initial_equity <= 0:
            promotion["trial_initial_equity"] = None
            promotion["trial_initial_equity_source"] = "live_account_free_usdt"
    candidate_row = {**source, "config": live_cfg, "symbols": symbols, "exchange": body.exchange}
    if not symbols:
        resolved = resolve_unified_base_strategy_class(candidate_row)
        if resolved:
            runtime_symbols = _runtime_strategy_symbols(resolved[0], body.exchange, live_cfg)
            if runtime_symbols:
                symbols = runtime_symbols
                symbol_scope = "dynamic_runtime_symbols"
                candidate_row["symbols"] = symbols
                live_cfg["symbol_scope"] = symbol_scope
    timeframe = str(live_cfg.get("timeframe") or source_cfg.get("timeframe") or "1m")

    return {
        "source": source,
        "source_cfg": source_cfg,
        "symbols": symbols,
        "symbol_scope": symbol_scope,
        "live_cfg": live_cfg,
        "candidate_row": candidate_row,
        "timeframe": timeframe,
        "requested_initial_equity": requested_initial_equity,
    }


def _promotion_matching_checks(prepared: Dict[str, Any]) -> List[Dict[str, Any]]:
    source = prepared["source"]
    source_cfg = prepared["source_cfg"]
    live_cfg = prepared["live_cfg"]
    symbols = prepared["symbols"]
    symbol_scope = prepared.get("symbol_scope") or "strategy_symbols"
    candidate_row = prepared["candidate_row"]
    trade_symbols = _config_trade_symbols(live_cfg)

    checks: List[Dict[str, Any]] = []
    source_is_paper = source_cfg.get("is_paper_trading") is not False
    checks.append(
        {
            "item": "来源策略为模拟盘",
            "passed": source_is_paper,
            "detail": (
                "来源模拟策略保持运行，实盘订阅复用同一份策略信号"
                if source_is_paper
                else "来源策略已是实盘模式，不能作为模拟转实盘来源"
            ),
        }
    )

    live_mode = live_cfg.get("is_paper_trading") is False
    checks.append(
        {
            "item": "真实交易路径配置",
            "passed": live_mode,
            "detail": (
                "候选配置为 is_paper_trading=false，将使用 LiveBroker 真实下单"
                if live_mode
                else "候选配置仍是模拟模式"
            ),
        }
    )

    is_contract_live = _is_contract_live_candidate(live_cfg, symbols)
    checks.append(
        {
            "item": "实盘合约执行支持",
            "passed": True,
            "detail": (
                (
                    "当前策略为 Binance USD-M 永续合约，将使用 BinanceUsdmContractBroker 通过 Futures API 执行"
                    if str(live_cfg.get("exchange") or "").split(":", 1)[0] == "binanceusdm"
                    else "当前策略为 OKX USDT 永续合约，将使用 LiveContractBroker 通过 OKX Trade API 执行"
                )
                if is_contract_live
                else "当前策略是现货实盘候选，当前引擎可继续预检"
            ),
        }
    )

    exit_audit = audit_strategy_exit_protection(source_cfg)
    checks.append(
        {
            "item": "止盈止损保护",
            "passed": (not is_contract_live) or exit_audit.passed,
            "detail": (
                exit_audit.detail
                if is_contract_live
                else "当前候选不是方向性合约策略，不适用合约止盈止损准入"
            ),
        }
    )

    missing_trade_symbols = [sym for sym in trade_symbols if sym not in symbols]
    symbols_match = bool(symbols) and not missing_trade_symbols
    checks.append(
        {
            "item": "策略交易对匹配",
            "passed": symbols_match,
            "detail": (
                f"策略币池：{_preview_symbols(symbols)}"
                + (
                    f"；交易子池：{_preview_symbols(trade_symbols)}"
                    if trade_symbols
                    else "；动态运行币池由策略解析" if symbol_scope == "dynamic_runtime_symbols" else "；未单独配置交易子池"
                )
                if symbols_match
                else (
                    "策略未定义可继承的交易对，不能隐式改用默认币种"
                    if not symbols
                    else f"交易子池不在策略币池内：{_preview_symbols(missing_trade_symbols)}"
                )
            ),
        }
    )

    resolved = resolve_unified_base_strategy_class(candidate_row)
    checks.append(
        {
            "item": "策略运行合约匹配",
            "passed": resolved is not None,
            "detail": (
                f"已解析为 {resolved[0].__name__}，可由当前实盘引擎加载"
                if resolved
                else "策略无法解析为 BaseStrategy，请补全 strategy_key、module_path/class_name 或 script_content"
            ),
        }
    )

    subscription_conflict = _live_subscription_for_source(
        int(source.get("id") or 0),
        account_id=live_cfg.get("live_account_id") or "default",
    )
    conflicts = [] if subscription_conflict else _live_promotion_conflicts(
        int(source.get("id") or 0),
        account_id=live_cfg.get("live_account_id") or "default",
    )
    checks.append(
        {
            "item": "重复实盘实例冲突",
            "passed": subscription_conflict is None and not conflicts,
            "detail": (
                "未发现同源同账户运行/暂停中的实盘订阅"
                if subscription_conflict is None and not conflicts
                else (
                    f"已有同源同账户实盘订阅：#{subscription_conflict['id']} ({subscription_conflict['status']})"
                    if subscription_conflict
                    else "已有同源实盘实例："
                    + "；".join(
                        f"#{item['id']} {item['name']} ({item['status']})" for item in conflicts[:5]
                    )
                )
            ),
        }
    )

    initial = _float_value(live_cfg.get("initial_capital"), 0.0)
    account_pending = live_cfg.get("initial_capital_source") == "live_account_free_usdt"
    risk_per_trade = _float_value(live_cfg.get("risk_per_trade_pct"), 0.0)
    max_daily_loss = _float_value(live_cfg.get("max_daily_loss_pct"), 0.0)
    max_total_loss = _float_value(live_cfg.get("max_total_loss_pct"), 0.0)
    risk_detail = (
        (
            "实盘订阅资金将按实盘 USDT 可用余额写入预检计划；"
            if account_pending
            else f"预检资金 {initial:.2f} USDT；"
        )
        + f"单笔风险 {risk_per_trade:.2%}；"
        f"日亏损上限 {max_daily_loss:.2%}；"
        f"总亏损上限 {max_total_loss:.2%}"
    )
    checks.append(
        {
            "item": "源策略参数完整继承",
            "passed": source_is_paper and (account_pending or initial > 0),
            "detail": (
                risk_detail
                if source_is_paper and (account_pending or initial > 0)
                else (
                    "实盘订阅必须来自有效模拟策略，并保留原策略交易逻辑/风控参数；"
                    "只覆盖 is_paper_trading=false、live_account_id 和交易所账户别名"
                )
            ),
        }
    )
    loop_interval = int(live_cfg.get("loop_interval_sec") or 0)
    min_interval = 60 if len(symbols) >= 10 else 15 if len(symbols) >= 5 else 5
    checks.append(
        {
            "item": "调度频率与币池规模",
            "passed": loop_interval >= min_interval,
            "detail": (
                f"{len(symbols)} 个策略交易对，轮询间隔 {loop_interval}s，满足上线前限频要求"
                if loop_interval >= min_interval
                else f"{len(symbols)} 个策略交易对至少需要 {min_interval}s 轮询间隔，当前 {loop_interval}s 过高频"
            ),
        }
    )
    return checks


async def _run_promote_preflight(
    body: PromoteToLiveBody,
    prepared: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if prepared is None:
        prepared = _prepare_promoted_live_candidate(body)
    checks = _promotion_matching_checks(prepared)
    if all(c["passed"] for c in checks):
        checks.append(await _live_account_trade_permission_check(body.account_id or "default"))
    if all(c["passed"] for c in checks):
        checks.append(
            await _live_contract_account_precheck(
                exchange=body.exchange,
                live_cfg=prepared["live_cfg"],
                symbols=prepared["symbols"],
            )
        )
    if all(c["passed"] for c in checks):
        runtime = await _run_preflight_checks(
            strategy_id=int(body.source_strategy_id),
            row=prepared["candidate_row"],
            exchange=body.exchange,
            timeframe=prepared["timeframe"],
            dry_run=False,
            symbol=None,
            symbol_scope=prepared.get("symbol_scope") or "strategy_symbols",
        )
        _apply_dynamic_live_symbol_filter(prepared, runtime)
        _apply_live_account_equity(prepared, runtime.get("account"))
        checks.extend(runtime["checks"])
        checks.extend(_promotion_account_sizing_checks(prepared))

    return {
        "all_passed": all(c["passed"] for c in checks),
        "checks": checks,
        "plan": _promotion_plan(prepared, body=body),
        "account": prepared.get("account"),
    }


def _insert_promoted_strategy(
    source_row: Dict[str, Any],
    *,
    exchange: str,
    symbols: List[str],
    config: Dict[str, Any],
) -> int:
    name = _unique_strategy_name(_promoted_live_strategy_name(source_row))
    description = (
        f"小资金实盘试运行克隆自模拟策略 #{source_row.get('id')}：{source_row.get('name') or ''}。"
        "该策略由模拟转实盘流程生成，独立于原模拟策略。"
    )
    conn = db.get_connection()
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cur.execute(
        """
        INSERT INTO strategies
        (name, description, script_content, config, status, exchange, symbols, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'stopped', ?, ?, ?, ?)
        """,
        (
            name,
            description,
            source_row.get("script_content") or "",
            json.dumps(config, ensure_ascii=False),
            exchange,
            json.dumps(symbols, ensure_ascii=False),
            now,
            now,
        ),
    )
    new_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return new_id


def _latest_positive_equity_sample(strategy_id: int) -> Optional[float]:
    for item in reversed(_equity_curve_samples.get(strategy_id, [])):
        value = _float_value(item.get("equity"), 0.0)
        if value > 0:
            return value
    if hasattr(db, "get_latest_strategy_equity_sample"):
        try:
            item = db.get_latest_strategy_equity_sample(strategy_id)
        except Exception as exc:
            logger.debug("Load latest persisted equity sample failed for %s: %s", strategy_id, exc)
            item = None
        if isinstance(item, dict):
            value = _float_value(item.get("equity"), 0.0)
            if value > 0:
                _load_persisted_equity_samples(strategy_id)
                return value
    return None


def _resolve_paper_snapshot_instance(
    *,
    strategy_id: Optional[int],
    instance_id: Optional[str],
) -> Dict[str, Any]:
    """Resolve one immutable paper session, never silently fall back to another strategy."""
    # 直接调用函数的单元测试不会经过 FastAPI 参数解析，Query 默认值应视为未提供。
    requested_instance_id = str(instance_id).strip() if isinstance(instance_id, str) else ""
    try:
        requested_strategy_id = int(strategy_id) if strategy_id is not None else None
    except (TypeError, ValueError):
        # 直接调用函数的单元测试不会经过 FastAPI 参数解析，保留 Query 默认值等同于未提供。
        requested_strategy_id = None
    if not requested_instance_id and requested_strategy_id is None:
        raise BadRequestError("paper_snapshot 必须提供 strategy_id 或 instance_id")

    instance: Optional[Dict[str, Any]] = None
    if requested_instance_id:
        instance = db.get_paper_instance(requested_instance_id)
        if not instance:
            raise NotFoundError("Paper instance not found")
        if requested_strategy_id is not None and int(instance["strategy_id"]) != requested_strategy_id:
            raise BadRequestError("strategy_id 与 instance_id 不属于同一纸面会话")
        return instance

    row = db.get_strategy_by_id(int(requested_strategy_id))
    if not row:
        raise NotFoundError("Strategy not found")
    config = row.get("config") if isinstance(row.get("config"), dict) else {}
    current_instance_id = str(config.get("paper_instance_id") or "").strip()
    if not current_instance_id:
        raise NotFoundError("该策略尚未通过 paper_configure 创建纸面会话")
    instance = db.get_paper_instance(current_instance_id)
    if not instance or int(instance["strategy_id"]) != int(requested_strategy_id):
        raise NotFoundError("当前策略的纸面会话映射不可用")
    return instance


def _paper_snapshot_payload(instance: Dict[str, Any]) -> Dict[str, Any]:
    strategy_id = int(instance["strategy_id"])
    row = db.get_strategy_by_id(strategy_id)
    if not row:
        raise NotFoundError("Strategy not found")
    current_config = row.get("config") if isinstance(row.get("config"), dict) else {}
    session_config = instance.get("config_snapshot") if isinstance(instance.get("config_snapshot"), dict) else {}
    initial_equity = _configured_initial_capital(session_config)
    samples = db.get_paper_instance_equity_samples(instance, limit=_EQUITY_MAX)
    metrics = equity_curve_risk_metrics(samples)
    session_start_ms = db._iso_to_epoch_ms(instance.get("started_at") or instance.get("configured_at"))
    session_end_ms = db._iso_to_epoch_ms(instance.get("ended_at")) or None
    try:
        rolling_max_drawdown = db.get_strategy_rolling_max_drawdown(
            strategy_id,
            window_days=30,
            as_of_ts_ms=session_end_ms,
            start_ts_ms=session_start_ms or None,
        )
    except Exception:
        rolling_max_drawdown = float(metrics["max_drawdown"])
    current_instance_id = str(current_config.get("paper_instance_id") or "").strip()
    # 已封存的历史会话绝不能读取策略当前运行时权益或状态，否则会把新一轮 paper 的数据混入旧证据。
    is_current_session = current_instance_id == str(instance["instance_id"])
    runtime = strategy_engine.get_strategy_status(strategy_id) if is_current_session else None
    runtime_equity = _float_value((runtime or {}).get("equity"), 0.0)
    sampled_equity = _float_value((samples[-1] if samples else {}).get("equity"), 0.0)
    equity = runtime_equity if runtime_equity > 0 else (sampled_equity if sampled_equity > 0 else initial_equity)
    cumulative_return_pct = ((equity - initial_equity) / initial_equity * 100) if initial_equity > 0 else 0.0
    event_summary = db.get_paper_instance_event_summary(instance["instance_id"])
    curve_version = equity_curve_version(samples)
    curve_summary = equity_curve_summary(samples)
    generated_at = utc_now_iso()
    evidence = paper_evidence(
        instance,
        row,
        equity_version=curve_version,
        generated_at=generated_at,
    )
    status = str((runtime or {}).get("status") or instance.get("status") or "stopped")
    symbols = row.get("symbols") or []
    if isinstance(symbols, str):
        symbols = [part.strip() for part in symbols.split(",") if part.strip()]
    session_start_at = instance.get("started_at") or instance.get("configured_at")

    return {
        "contract_version": PAPER_OBSERVABILITY_CONTRACT_VERSION,
        "instance_id": instance["instance_id"],
        "strategy_id": strategy_id,
        "strategy": {
            "strategy_id": strategy_id,
            "name": row.get("name"),
            "exchange": row.get("exchange"),
            "symbols": list(symbols),
        },
        "session": {
            "instance_id": instance["instance_id"],
            "configured_at": instance.get("configured_at"),
            "started_at": instance.get("started_at"),
            "ended_at": instance.get("ended_at"),
            "status": status,
        },
        "strategy_version": instance.get("strategy_version"),
        "config_version": instance.get("config_version"),
        "status": status,
        "equity": round(equity, 6),
        "pnl": round(equity - initial_equity, 6),
        "cumulative_return_pct": round(cumulative_return_pct, 6),
        "max_drawdown_pct": round(float(rolling_max_drawdown), 6),
        "max_drawdown_window_days": 30,
        "sharpe_ratio": round(float(metrics["sharpe_ratio"]), 6),
        "trade_count": db.get_paper_instance_trade_count(instance),
        "latest_event_at": event_summary["latest_event_at"],
        "latest_event": event_summary["latest_event"],
        "error_count": event_summary["error_count"],
        "equity_curve_version": curve_version,
        "equity_curve_summary": curve_summary,
        "data_coverage": {
            "session_start_at": session_start_at,
            "session_end_at": instance.get("ended_at"),
            "equity_first_at": curve_summary["first_at"],
            "equity_last_at": curve_summary["last_at"],
            "equity_sample_count": curve_summary["sample_count"],
            "timezone": "UTC",
        },
        "configured_at": instance.get("configured_at"),
        "started_at": instance.get("started_at"),
        "generated_at": generated_at,
        "evidence": evidence,
    }


def _performance_metrics(
    strategy_id: int,
    *,
    initial: float,
    equity_cur: float,
    total_trades: int,
    run_started_at: Optional[str],
) -> Dict[str, float | int]:
    """用本轮成交与权益采样计算实时监控指标，供详情页和实例卡片共用。"""
    total_pnl = equity_cur - initial
    total_pnl_pct = (total_pnl / initial * 100) if initial > 0 else 0.0

    closing_trades = 0
    winning_closes = 0
    gross_profit = 0.0
    gross_loss = 0.0
    since_ms = 0
    if run_started_at:
        try:
            dt = datetime.fromisoformat(str(run_started_at).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            since_ms = int(dt.timestamp() * 1000)
        except Exception:
            since_ms = 0
    try:
        rows = db.get_strategy_trades_since(strategy_id, since_ms) if since_ms > 0 else []
    except Exception:
        rows = []
    run_trade_count = len(rows) if rows else int(total_trades)
    for row in rows:
        side = str(row.get("side") or "").strip().lower().replace("-", "_").replace(" ", "_")
        if side not in {"sell", "spot_sell", "close_long", "close_short"}:
            continue
        closing_trades += 1
        try:
            pnl = float(row.get("pnl") or 0)
        except (TypeError, ValueError):
            pnl = 0.0
        if pnl > 0:
            winning_closes += 1
            gross_profit += pnl
        elif pnl < 0:
            gross_loss += abs(pnl)
    win_rate = (winning_closes / closing_trades * 100) if closing_trades > 0 else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0

    seq = _equity_curve_samples.get(strategy_id) or _load_persisted_equity_samples(strategy_id)
    equity_metrics = equity_curve_risk_metrics(seq)
    try:
        rolling_max_drawdown = db.get_strategy_rolling_max_drawdown(
            strategy_id,
            window_days=30,
            start_ts_ms=since_ms or None,
        )
    except Exception:
        rolling_max_drawdown = float(equity_metrics["max_drawdown"])

    return {
        "total_pnl": round(total_pnl, 6),
        "total_pnl_pct": round(total_pnl_pct, 6),
        "win_rate": round(win_rate, 4),
        "gross_profit": round(gross_profit, 6),
        "gross_loss": round(gross_loss, 6),
        "profit_factor": round(profit_factor, 4),
        "total_trades": int(run_trade_count),
        "max_drawdown": round(rolling_max_drawdown, 6),
        "max_drawdown_window_days": 30,
        "sharpe_ratio": round(equity_metrics["sharpe_ratio"], 6),
    }


def _dynamic_pool_view_payload(strategy_id: int) -> Optional[Dict[str, Any]]:
    """动态标的池页面快照：停止后仍可读取，并归一化为统一展示合同。"""
    try:
        raw = db.get_app_setting(f"strategy_runtime_state:{int(strategy_id)}", "")
        payload = json.loads(raw or "{}")
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    view = payload.get("_dynamic_pool_view")
    return normalize_dynamic_pool_view(view) if isinstance(view, dict) else None


def _build_dashboard(strategy_id: int) -> Dict[str, Any]:
    row = db.get_strategy_by_id(strategy_id)
    risk = strategy_engine.get_risk_status()

    cfg = (row or {}).get("config") or {}
    if not isinstance(cfg, dict):
        cfg = {}

    dry_run = bool(cfg.get("is_paper_trading", True))
    symbol = (row or {}).get("symbols") or ["BTC/USDT"]
    if isinstance(symbol, list) and symbol:
        sym = symbol[0]
        symbols_list = [str(s) for s in symbol if s]
    else:
        sym = str(symbol)
        symbols_list = [sym] if sym else []

    st = strategy_engine.get_strategy_status(strategy_id)
    if dry_run:
        # SuperPnL 会订阅 Top20，但标记价只需要刷新当前持仓，避免详情页首屏串行拉整池 ticker。
        mark_symbols = _position_symbols_from_status(st)
        if mark_symbols:
            _refresh_paper_marks(strategy_id, (row or {}).get("exchange") or "okx", mark_symbols)
            st = strategy_engine.get_strategy_status(strategy_id)

    if st:
        state = st.get("status") or "stopped"
        runtime_symbols = st.get("symbols")
        if isinstance(runtime_symbols, list) and runtime_symbols:
            symbols_list = [str(s) for s in runtime_symbols if s]
            sym = symbols_list[0] if symbols_list else sym
        elif isinstance(runtime_symbols, str) and runtime_symbols.strip():
            sym = runtime_symbols.strip()
            symbols_list = [sym]
        initial = (
            _float_value(st.get("initial_capital"), 0.0)
            or _configured_initial_capital(cfg)
        )
        status_equity = _float_value(st.get("equity"), 0.0)
        if status_equity > 0:
            equity_cur = status_equity
        else:
            # pause/stop 会取消任务并移除 PaperBroker；此时 context 仍在，
            # get_strategy_status() 只能返回默认 0。展示层应保留最近权益，
            # 没有采样时回退到初始资金，避免误显示账户归零。
            equity_cur = _latest_positive_equity_sample(strategy_id) or initial
        ret_pct = (
            _float_value(st.get("return_pct"), 0.0)
            if status_equity > 0
            else ((equity_cur - initial) / initial * 100 if initial > 0 else 0.0)
        )
        total_trades = int(st.get("total_trades", 0) or 0)
    else:
        state = (row or {}).get("status") or "stopped"
        initial = _configured_initial_capital(cfg)
        equity_cur = _latest_positive_equity_sample(strategy_id) or initial
        ret_pct = (equity_cur - initial) / initial * 100 if initial > 0 else 0.0
        total_trades = 0

    if dry_run:
        positions_list, unrealized_total = _paper_positions_from_status(st)
    else:
        positions_list, unrealized_total = [], 0.0

    # The global account circuit breaker is backed by real exchange equity. Do not
    # project that live-account state onto paper instances in the detail UI.
    effective_circuit = bool(risk.get("circuit_breaker")) and not dry_run

    if effective_circuit:
        ui_state = "circuit_breaker"
    else:
        ui_state = state
    perf = _performance_metrics(
        strategy_id,
        initial=initial,
        equity_cur=equity_cur,
        total_trades=total_trades,
        run_started_at=(row or {}).get("run_started_at"),
    )

    return {
        "system": {
            "state": ui_state,
            "uptime": _uptime_str(st.get("started_at") if st else None),
            "exchange": (row or {}).get("exchange") or "",
            "symbol": sym,
            "symbols": symbols_list,
            "timeframe": str(cfg.get("timeframe") or ""),
            "strategy": (row or {}).get("name") or str(strategy_id),
            "strategy_id": strategy_id,
            "dry_run": dry_run,
            "mode": "paper" if dry_run else "live",
        },
        "equity": {
            "initial": initial,
            "current": equity_cur,
            "peak": equity_cur,
            "change": equity_cur - initial,
            "change_pct": ret_pct,
        },
        "performance": {
            "total_pnl": perf["total_pnl"],
            "total_pnl_pct": perf["total_pnl_pct"] if initial > 0 else ret_pct,
            "win_rate": perf["win_rate"],
            "profit_factor": perf["profit_factor"],
            "gross_profit": perf["gross_profit"],
            "gross_loss": perf["gross_loss"],
            "total_trades": perf["total_trades"],
            "max_drawdown": perf["max_drawdown"],
            "sharpe_ratio": perf["sharpe_ratio"],
        },
        "risk": {
            "circuit_breaker": effective_circuit,
            "current_drawdown": (
                float(risk.get("current_drawdown") or 0) if effective_circuit else 0.0
            ),
            "daily_loss": 0.0,
        },
        "positions": positions_list,
        "account": {
            "unrealized_pnl": unrealized_total,
        },
        "recent_events": [],
        "feishu": _feishu_dashboard_slice(),
        "dynamic_pool": _dynamic_pool_view_payload(strategy_id) if dry_run else None,
    }


@router.post("/configure")
async def live_configure(body: LiveConfigureBody):
    global _active_strategy_id
    sid = _parse_strategy_id(body.strategy_type)
    existing = db.get_strategy_by_id(sid)
    if not existing:
        raise NotFoundError("Strategy not found")

    eng = strategy_engine.get_strategy_status(sid)
    if eng and eng.get("status") == "running":
        raise BadRequestError("策略运行中，请先停止后再修改配置")

    cfg = dict(existing.get("config") or {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg["timeframe"] = _strategy_defined_timeframe(existing, cfg)
    cfg["initial_capital"] = float(body.initial_equity)
    cfg["is_paper_trading"] = bool(body.dry_run)
    if body.loop_interval is not None:
        cfg["loop_interval_sec"] = int(body.loop_interval)
    rc = body.risk_config or {}
    if rc:
        cfg["risk_per_trade_pct"] = rc.get("risk_per_trade_pct")
        cfg["max_daily_loss_pct"] = rc.get("max_daily_loss_pct")
        cfg["max_total_loss_pct"] = rc.get("max_total_loss_pct")

    symbols = _configured_symbols(existing, cfg, body.symbol)
    paper_instance: Optional[Dict[str, Any]] = None
    reused_paper_instance = False
    reset_run_started_at = False
    if body.dry_run:
        configured_at = utc_now_iso()
        current_strategy_version = strategy_version(existing.get("script_content"))
        current_config_version = paper_config_version(
            cfg,
            exchange=body.exchange,
            symbols=symbols,
        )
        existing_instance_id = str(cfg.get("paper_instance_id") or "").strip()
        existing_instance = db.get_paper_instance(existing_instance_id) if existing_instance_id else None
        can_reuse = (
            existing_instance is not None
            and not existing_instance.get("ended_at")
            and existing_instance.get("strategy_version") == current_strategy_version
            and existing_instance.get("config_version") == current_config_version
        )
        if can_reuse:
            paper_instance = existing_instance
            reused_paper_instance = True
            cfg["paper_instance_id"] = paper_instance["instance_id"]
            cfg["paper_strategy_version"] = current_strategy_version
            cfg["paper_config_version"] = current_config_version
            cfg["paper_configured_at"] = paper_instance.get("configured_at") or configured_at
        else:
            # 配置或脚本变了才封存旧会话并开新实例；同配置重启必须复用原实例。
            db.close_open_paper_instances(sid, ended_at=configured_at)
            paper_instance = db.create_paper_instance(
                strategy_id=sid,
                strategy_version=current_strategy_version,
                config_version=current_config_version,
                config_snapshot=cfg,
                configured_at=configured_at,
            )
            cfg["paper_instance_id"] = paper_instance["instance_id"]
            cfg["paper_strategy_version"] = current_strategy_version
            cfg["paper_config_version"] = current_config_version
            cfg["paper_configured_at"] = configured_at
            reset_run_started_at = True
    conn = db.get_connection()
    cur = conn.cursor()
    if reset_run_started_at:
        cur.execute(
            """
            UPDATE strategies
            SET exchange = ?, symbols = ?, config = ?, run_started_at = NULL, updated_at = datetime('now')
            WHERE id = ?
            """,
            (body.exchange, json.dumps(symbols), json.dumps(cfg), sid),
        )
    else:
        cur.execute(
            """
            UPDATE strategies SET exchange = ?, symbols = ?, config = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (body.exchange, json.dumps(symbols), json.dumps(cfg), sid),
        )
    conn.commit()
    conn.close()

    strategy_engine.drop_cached_context(sid)
    _active_strategy_id = sid
    result: Dict[str, Any] = {"configured": True, "strategy_id": sid}
    if paper_instance:
        if not reused_paper_instance:
            db.insert_paper_instance_event(
                paper_instance["instance_id"],
                sid,
                "configured",
                "info",
                {"message": "纸面会话已配置", "strategy_id": sid},
            )
        result.update(
            {
                "instance_id": paper_instance["instance_id"],
                "strategy_version": paper_instance["strategy_version"],
                "config_version": paper_instance["config_version"],
                "configured_at": paper_instance["configured_at"],
                "started_at": paper_instance["started_at"],
            }
        )
    return ok(result)


@router.post("/start")
async def live_start(body: LiveInstanceBody = Body(default_factory=LiveInstanceBody)):
    sid = _resolve_instance_sid(body)
    if sid is None:
        raise BadRequestError("请先调用 /live/configure 或选择策略")
    started_ok = await strategy_engine.start_strategy(sid)
    if not started_ok:
        raise BadRequestError("策略启动失败（可能处于熔断或配置无效）")
    result: Dict[str, Any] = {"started": True, "strategy_id": sid}
    row = db.get_strategy_by_id(sid) or {}
    config = row.get("config") if isinstance(row.get("config"), dict) else {}
    instance_id = str(config.get("paper_instance_id") or "").strip()
    if instance_id:
        instance = db.get_paper_instance(instance_id)
        if instance:
            result.update({"instance_id": instance_id, "started_at": instance.get("started_at")})
    return ok(result)


@router.post("/stop")
async def live_stop(body: LiveInstanceBody = Body(default_factory=LiveInstanceBody)):
    sid = _resolve_instance_sid(body)
    global _active_strategy_id
    if sid is None:
        return ok({"stopped": False})
    _raise_if_paper_lifecycle_blocked_by_running_live(sid, "关闭")
    await strategy_engine.stop_strategy(sid, clear_metrics=bool(body.clear_metrics))
    _clear_live_execution_deployment(sid)
    if body.clear_metrics:
        _equity_curve_samples.pop(sid, None)
    if _active_strategy_id == sid:
        _active_strategy_id = None
    return ok({"stopped": True, "clear_metrics": bool(body.clear_metrics)})


@router.post("/pause")
async def live_pause(body: LiveInstanceBody = Body(default_factory=LiveInstanceBody)):
    sid = _resolve_instance_sid(body)
    if sid is None:
        raise BadRequestError("没有运行中的会话")
    _raise_if_paper_lifecycle_blocked_by_running_live(sid, "暂停")
    await strategy_engine.pause_strategy(sid)
    return ok({"paused": True})


@router.post("/resume")
async def live_resume(body: LiveInstanceBody = Body(default_factory=LiveInstanceBody)):
    sid = _resolve_instance_sid(body)
    if sid is None:
        raise BadRequestError("没有可恢复的会话")
    resumed_ok = await strategy_engine.start_strategy(sid)
    if not resumed_ok:
        raise BadRequestError("恢复运行失败")
    result: Dict[str, Any] = {"resumed": True, "strategy_id": sid}
    row = db.get_strategy_by_id(sid) or {}
    config = row.get("config") if isinstance(row.get("config"), dict) else {}
    instance_id = str(config.get("paper_instance_id") or "").strip()
    if instance_id:
        instance = db.get_paper_instance(instance_id)
        if instance:
            result.update({"instance_id": instance_id, "started_at": instance.get("started_at")})
    return ok(result)


@router.post("/positions/close")
async def live_close_paper_position(body: PaperPositionCloseBody):
    sid = body.instance_id if body.instance_id is not None else _resolve_target_strategy_id()
    if sid is None:
        raise BadRequestError("没有可操作的模拟盘实例")

    row = db.get_strategy_by_id(int(sid))
    if not row:
        raise NotFoundError("Strategy not found")
    cfg = row.get("config") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    if cfg.get("is_paper_trading") is False:
        raise BadRequestError("仅支持模拟盘持仓平仓；实盘持仓请使用实盘工作台")

    result = await strategy_engine.close_paper_position(
        int(sid),
        symbol=body.symbol,
        side=body.side,
        market_type=body.market_type,
    )
    status = str(result.get("status") or "").lower()
    closed_count = int(result.get("closed") or 0) if str(result.get("closed") or "").isdigit() else 0
    if status != "filled" and closed_count <= 0:
        reason = result.get("reason") or result.get("error") or "当前持仓无法平仓"
        if str(reason) == "no_position":
            return ok({
                "closed": False,
                "stale": True,
                "strategy_id": int(sid),
                "message": "当前持仓已不存在或已平仓，页面将刷新最新模拟仓位",
                "result": result,
            })
        raise BadRequestError(str(reason))

    return ok({"closed": True, "strategy_id": int(sid), "result": result})


@router.get("/dashboard")
async def live_dashboard(instance_id: Optional[int] = Query(None)):
    sid = _resolve_instance_sid(None, query_id=instance_id)
    if sid is None:
        return ok(
            {
                "system": {
                    "state": "idle",
                    "uptime": "-",
                    "exchange": "",
                    "symbol": "",
                    "symbols": [],
                    "timeframe": "",
                    "strategy": "",
                    "strategy_id": None,
                    "dry_run": True,
                    "mode": "paper",
                },
                "equity": {"initial": 0, "current": 0, "peak": 0, "change": 0, "change_pct": 0},
                "performance": {
                    "total_pnl": 0,
                    "total_pnl_pct": 0,
                    "win_rate": 0,
                    "profit_factor": 0,
                    "gross_profit": 0,
                    "gross_loss": 0,
                    "total_trades": 0,
                    "max_drawdown": 0,
                    "sharpe_ratio": 0,
                },
                "risk": {
                    "circuit_breaker": bool(
                        strategy_engine.get_risk_status().get("circuit_breaker")
                    ),
                    "current_drawdown": 0,
                    "daily_loss": 0,
                },
                "positions": [],
                "account": {"unrealized_pnl": 0.0},
                "recent_events": [],
                "feishu": _feishu_dashboard_slice(),
            }
        )
    data = _build_dashboard(sid)
    if not data["system"].get("dry_run"):
        ex = (data["system"].get("exchange") or "").strip()
        sym = (data["system"].get("symbol") or "").strip()
        if ex and sym:
            try:
                raw = await trading_service.get_positions(ex, sym)
                if not isinstance(raw, list):
                    raw = []
                norm, total_up = _normalize_ccxt_positions(raw)
                data["positions"] = norm
                data["account"]["unrealized_pnl"] = total_up
            except Exception as e:
                logger.warning("live_dashboard fetch positions failed: %s", e)
    return ok(data)


@router.get("/paper_snapshot")
async def paper_snapshot(
    strategy_id: Optional[int] = Query(None, ge=1),
    instance_id: Optional[str] = Query(None, min_length=1),
):
    """HyperTrade 纸面证据单快照：严格绑定一个不可变会话，不拼多个 dashboard 接口。"""
    instance = _resolve_paper_snapshot_instance(
        strategy_id=strategy_id,
        instance_id=instance_id,
    )
    return ok(_paper_snapshot_payload(instance))


@router.get("/events")
async def live_events(
    limit: int = 50,
    event_type: Optional[str] = None,
    instance_id: Optional[int] = Query(None),
):
    _ = event_type
    sid = _resolve_instance_sid(None, query_id=instance_id)
    if sid is None:
        return ok({"events": []})
    requested_limit = max(1, min(500, int(limit)))
    source_limit = min(500, max(50, requested_limit * 3))
    runtime_events = strategy_log_store.get(sid, source_limit)
    try:
        runtime_state = db.get_app_setting(f"strategy_runtime_state:{int(sid)}", "")
    except Exception:
        runtime_state = ""
    try:
        trades = db.get_strategy_trades(int(sid), source_limit)
    except Exception:
        trades = []
    events = compose_strategy_diagnostic_events(
        runtime_events=runtime_events,
        runtime_state=runtime_state,
        trades=trades,
        limit=requested_limit,
    )
    return ok({"events": events})


@router.get("/equity_curve")
async def live_equity_curve(instance_id: Optional[int] = Query(None)):
    sid = _resolve_instance_sid(None, query_id=instance_id)
    if sid is None:
        return ok([])
    return ok(_load_persisted_equity_samples(sid))


@router.get("/instances")
async def live_instances_probe():
    """兼容手工探测 / 旧脚本；当前与引擎会话一致时返回占位结构。"""
    ids = strategy_engine.list_running_or_paused_ids()
    return ok(
        {
            "instances": [
                {"id": str(i), "strategy_id": i, "status": "running"} for i in ids
            ]
        }
    )


@router.get("/strategies")
async def list_live_execution_strategies():
    return ok(await asyncio.to_thread(_list_live_execution_strategies))


def _list_live_execution_strategies() -> Dict[str, List[Dict[str, Any]]]:
    rows = db.get_strategies()
    settings = _live_strategy_settings_by_id()
    bindings_by_strategy = _live_strategy_account_bindings_by_strategy(settings)
    batch = _live_execution_batch_context(rows, settings, bindings_by_strategy)
    strategies: List[Dict[str, Any]] = []
    for row in rows:
        deployable = _is_live_workspace_candidate(row)
        if not deployable and not (
            _is_live_workspace_source(row)
            and _has_live_workspace_state(int(row.get("id") or 0), settings, bindings_by_strategy)
        ):
            continue
        strategies.append(
            _live_execution_strategy_payload(
                row,
                settings,
                bindings_by_strategy,
                deployable=deployable,
                **batch,
            )
        )
    strategies.sort(
        key=lambda item: (
            0 if item.get("added") else 1,
            -int(item.get("strategy_id") or 0),
        )
    )
    return {"strategies": strategies}


@router.patch("/strategies/{strategy_id}")
async def patch_live_execution_strategy(strategy_id: int, body: LiveStrategySettingBody):
    row = db.get_strategy_by_id(int(strategy_id))
    if not row:
        raise NotFoundError("Strategy not found")
    if body.added is False:
        if not _is_live_workspace_source(row):
            raise BadRequestError("该策略不是可移出实盘策略列表的模拟策略")
        _raise_if_live_workspace_remove_blocked(int(strategy_id))
        setting = _upsert_live_strategy_setting(
            int(strategy_id),
            added=False,
            account_id=body.account_id or "default",
            risk_config=body.risk_config or {},
            status="removed",
        )
        payload = _live_execution_strategy_payload(row, {int(strategy_id): setting})
        return ok({"strategy": payload})
    if not _is_live_workspace_candidate(row):
        raise BadRequestError("该策略不是可部署的模拟策略")
    if body.bind_account is not False and body.added is not False:
        account_id = live_account_service.validate_live_deployable_account_id(body.account_id or "default")
    else:
        account_id = live_account_service.validate_account_id(body.account_id or "default")
    workspace_only = (
        body.bind_account is False
        and body.added is True
        and "added" in body.model_fields_set
    )
    if workspace_only:
        setting = _upsert_live_strategy_setting(
            int(strategy_id),
            added=True,
            account_id=account_id,
            risk_config=body.risk_config or {},
            status="workspace_added",
        )
        return ok({"strategy": _live_execution_strategy_payload(row, {int(strategy_id): setting})})
    if body.bind_account is False:
        current_setting = _live_strategy_setting(int(strategy_id)) or {}
        _upsert_live_strategy_account_binding(
            int(strategy_id),
            account_id=account_id,
            added=False,
            risk_config=body.risk_config or {},
            status="removed",
        )
        bindings = _live_strategy_account_bindings_by_strategy().get(int(strategy_id), {})
        still_added = any(bool(item.get("added")) for item in bindings.values())
        keep_strategy_added = bool(current_setting.get("added"))
        next_account_id = next(
            (item.get("account_id") for item in bindings.values() if item.get("added")),
            account_id,
        )
        setting = _upsert_live_strategy_setting(
            int(strategy_id),
            added=keep_strategy_added or still_added,
            account_id=str(next_account_id or account_id),
            risk_config=body.risk_config or {},
            status="added" if (keep_strategy_added or still_added) else "removed",
        )
        return ok({"strategy": _live_execution_strategy_payload(row, {int(strategy_id): setting})})

    setting = _upsert_live_strategy_setting(
        int(strategy_id),
        added=bool(body.added),
        account_id=account_id,
        risk_config=body.risk_config or {},
    )
    if body.added is not False:
        _upsert_live_strategy_account_binding(
            int(strategy_id),
            account_id=account_id,
            added=True,
            risk_config=body.risk_config or {},
        )
    payload = _live_execution_strategy_payload(row, {int(strategy_id): setting})
    return ok({"strategy": payload})


def _require_added_live_strategy(strategy_id: int, account_id: Optional[str] = None) -> Dict[str, Any]:
    row = db.get_strategy_by_id(int(strategy_id))
    if not row:
        raise NotFoundError("Strategy not found")
    if not _is_live_workspace_candidate(row):
        raise BadRequestError("该策略不是可部署的模拟策略")
    setting = _live_strategy_setting(int(strategy_id))
    if not setting or not setting.get("added"):
        raise BadRequestError("请先将策略加入实盘策略列表")
    if account_id is not None:
        normalized_account = live_account_service.validate_account_id(account_id)
        binding = _live_strategy_account_bindings_by_strategy().get(int(strategy_id), {}).get(normalized_account)
        legacy_account = live_account_service.normalize_account_id(setting.get("account_id"))
        if not binding and legacy_account == normalized_account:
            binding = {
                "added": True,
                "account_id": normalized_account,
            }
        if not binding or not binding.get("added"):
            raise BadRequestError("请先将该账户绑定到当前实盘策略")
    return row


def _require_live_subscription_control(
    strategy_id: int,
    account_id: str,
    *,
    allow_stopped: bool = False,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    row = db.get_strategy_by_id(int(strategy_id))
    if not row:
        raise NotFoundError("Strategy not found")
    if not _is_live_workspace_source(row):
        raise BadRequestError("该策略不是可控制的模拟来源策略")
    subscription = live_signal_execution_service.get_subscription(int(strategy_id), account_id)
    if not subscription:
        raise BadRequestError("当前账户尚未部署该实盘订阅")
    if not allow_stopped and str(subscription.get("status") or "").lower() == "stopped":
        raise BadRequestError("当前账户尚未部署该实盘订阅")
    return row, subscription


@router.post("/strategies/{strategy_id}/preflight")
async def preflight_live_execution_strategy(strategy_id: int, body: LiveStrategyPreflightBody):
    live_account_service.validate_live_deployable_account_id(body.account_id or "default")
    row = _require_added_live_strategy(int(strategy_id))
    promote_body = _live_execution_body_to_promote(int(strategy_id), body)
    preflight = await _run_promote_preflight(promote_body)
    return ok({"strategy": _live_execution_strategy_payload(row), "preflight": preflight})


def _live_subscription_risk_config(
    *,
    body: LiveStrategyPreflightBody,
    prepared: Dict[str, Any],
    preflight: Dict[str, Any],
) -> Dict[str, Any]:
    subscription_risk_config = dict(body.risk_config or {})
    trial_initial = _float_value((prepared.get("live_cfg") or {}).get("initial_capital"), 0.0)
    if trial_initial > 0:
        subscription_risk_config["trial_initial_equity"] = trial_initial
        subscription_risk_config["trial_initial_equity_source"] = (
            (prepared.get("live_cfg") or {}).get("initial_capital_source") or "request"
        )
    plan = preflight.get("plan") if isinstance(preflight.get("plan"), dict) else {}
    if plan.get("symbol_scope") == "dynamic_runtime_symbols":
        allowed_symbols = plan.get("symbols") if isinstance(plan.get("symbols"), list) else []
        excluded_symbols = plan.get("excluded_symbols") if isinstance(plan.get("excluded_symbols"), list) else []
        if allowed_symbols:
            subscription_risk_config["allowed_live_symbols"] = allowed_symbols
        if excluded_symbols:
            subscription_risk_config["excluded_live_symbols"] = excluded_symbols
    return subscription_risk_config


def _activate_live_subscription(
    *,
    strategy_id: int,
    account_id: str,
    risk_config: Dict[str, Any],
    start_immediately: bool,
) -> Dict[str, Any]:
    subscription_status = "running" if start_immediately else "paused"
    subscription: Optional[Dict[str, Any]] = None
    previous_binding = _live_strategy_account_bindings_by_strategy().get(int(strategy_id), {}).get(
        live_account_service.normalize_account_id(account_id)
    )
    try:
        _upsert_live_strategy_account_binding(
            int(strategy_id), account_id=account_id, added=True, risk_config=risk_config, status="enabling"
        )
        subscription = live_signal_execution_service.upsert_subscription(
            source_strategy_id=int(strategy_id),
            account_id=account_id,
            status=subscription_status,
            risk_config=risk_config,
        )
        workspace_status = "deployed" if start_immediately else "paused"
        _upsert_live_strategy_setting(
            int(strategy_id),
            added=True,
            account_id=account_id,
            risk_config=risk_config,
            deployment_strategy_id=None,
            clear_deployment_strategy_id=True,
            status=workspace_status,
        )
        _upsert_live_strategy_account_binding(
            int(strategy_id),
            account_id=account_id,
            added=True,
            risk_config=risk_config,
            deployment_strategy_id=None,
            clear_deployment_strategy_id=True,
            status=workspace_status,
        )
        return subscription
    except Exception:
        if subscription is not None:
            try:
                live_signal_execution_service.set_subscription_status(
                    source_strategy_id=int(strategy_id), account_id=account_id, status="stopped"
                )
            except Exception:
                logger.exception("Failed to stop partially activated live subscription")
        try:
            if previous_binding and previous_binding.get("added"):
                _upsert_live_strategy_account_binding(
                    int(strategy_id),
                    account_id=account_id,
                    added=True,
                    risk_config=previous_binding.get("risk_config") or {},
                    deployment_strategy_id=previous_binding.get("deployment_strategy_id"),
                    clear_deployment_strategy_id=previous_binding.get("deployment_strategy_id") is None,
                    status=previous_binding.get("status") or "added",
                )
            else:
                _upsert_live_strategy_account_binding(
                    int(strategy_id), account_id=account_id, added=False, risk_config=risk_config, status="removed"
                )
        except Exception:
            logger.exception("Failed to restore live account binding after activation failure")
        try:
            _upsert_live_strategy_setting(
                int(strategy_id),
                added=True,
                account_id=account_id,
                risk_config=risk_config,
                status="preflight_failed_unbound",
            )
        except Exception:
            logger.exception("Failed to mark live workspace activation failure")
        raise


@router.post("/strategies/{strategy_id}/enable-account")
async def enable_live_execution_account(strategy_id: int, body: LiveStrategyDeployBody):
    """Run preflight, bind the account, and start signal execution as one confirmed action."""
    if not body.confirm_paper_reviewed or not body.confirm_live_risk:
        raise BadRequestError("绑定并启用下单需要确认已复核模拟盘表现，并确认真实资金风险")

    account_id = live_account_service.validate_live_deployable_account_id(body.account_id or "default")
    row = _require_added_live_strategy(int(strategy_id))
    existing_subscription = live_signal_execution_service.get_subscription(int(strategy_id), account_id)
    active_subscription_statuses = {"running", "active", "deployed", "paused"}
    if existing_subscription and str(existing_subscription.get("status") or "").lower() in active_subscription_statuses:
        raise BadRequestError("当前账户已经启用该策略；请使用暂停、继续或停止控制，不要重复启用")
    promote_body = _live_execution_body_to_promote(
        int(strategy_id),
        body,
        confirm_paper_reviewed=True,
        confirm_live_risk=True,
    )
    prepared = _prepare_promoted_live_candidate(promote_body)
    if prepared["source_cfg"].get("is_paper_trading") is False:
        raise BadRequestError("来源策略已经是实盘策略，不能再次启用")

    preflight = await _run_promote_preflight(promote_body, prepared=prepared)
    if not preflight["all_passed"]:
        _upsert_live_strategy_setting(
            int(strategy_id),
            added=True,
            account_id=account_id,
            risk_config=body.risk_config or {},
            status="preflight_failed_unbound",
        )
        return ok(
            {
                "deployed": False,
                "started": False,
                "source_strategy_id": int(strategy_id),
                "strategy": _live_execution_strategy_payload(row),
                "preflight": preflight,
            }
        )

    risk_config = _live_subscription_risk_config(body=body, prepared=prepared, preflight=preflight)
    subscription = _activate_live_subscription(
        strategy_id=int(strategy_id),
        account_id=account_id,
        risk_config=risk_config,
        start_immediately=True,
    )
    return ok(
        {
            "deployed": True,
            "started": True,
            "source_strategy_id": int(strategy_id),
            "live_strategy_id": None,
            "live_subscription_id": subscription["id"],
            "strategy": _live_execution_strategy_payload(row),
            "preflight": preflight,
        }
    )


@router.post("/strategies/{strategy_id}/deploy")
async def deploy_live_execution_strategy(strategy_id: int, body: LiveStrategyDeployBody):
    if not body.confirm_paper_reviewed or not body.confirm_live_risk:
        raise BadRequestError("部署实盘需要确认已复核模拟盘表现，并确认真实资金风险")

    account_id = live_account_service.validate_live_deployable_account_id(body.account_id or "default")
    row = _require_added_live_strategy(int(strategy_id), account_id)
    promote_body = _live_execution_body_to_promote(
        int(strategy_id),
        body,
        confirm_paper_reviewed=True,
        confirm_live_risk=True,
    )
    prepared = _prepare_promoted_live_candidate(promote_body)
    source_cfg = prepared["source_cfg"]
    if source_cfg.get("is_paper_trading") is False:
        raise BadRequestError("来源策略已经是实盘策略，不能再次部署")

    preflight = await _run_promote_preflight(promote_body, prepared=prepared)
    if not preflight["all_passed"]:
        _upsert_live_strategy_setting(
            int(strategy_id),
            added=True,
            account_id=promote_body.account_id or "default",
            risk_config=body.risk_config or {},
            status="preflight_failed",
        )
        _upsert_live_strategy_account_binding(
            int(strategy_id),
            account_id=promote_body.account_id or "default",
            added=True,
            risk_config=body.risk_config or {},
            status="preflight_failed",
        )
        return ok(
            {
                "deployed": False,
                "started": False,
                "source_strategy_id": int(strategy_id),
                "strategy": _live_execution_strategy_payload(row),
                "preflight": preflight,
            }
        )

    subscription_risk_config = _live_subscription_risk_config(body=body, prepared=prepared, preflight=preflight)
    subscription = _activate_live_subscription(
        strategy_id=int(strategy_id),
        account_id=promote_body.account_id or "default",
        risk_config=subscription_risk_config,
        start_immediately=body.start_immediately,
    )
    return ok(
        {
            "deployed": True,
            "started": body.start_immediately,
            "source_strategy_id": int(strategy_id),
            "live_strategy_id": None,
            "live_subscription_id": subscription["id"],
            "strategy": _live_execution_strategy_payload(row),
            "preflight": preflight,
        }
    )


@router.post("/strategies/{strategy_id}/pause")
async def pause_live_strategy_subscription(strategy_id: int, body: LiveStrategySubscriptionControlBody):
    account_id = live_account_service.validate_account_id(body.account_id or "default")
    row, _ = _require_live_subscription_control(int(strategy_id), account_id)
    subscription = live_signal_execution_service.set_subscription_status(
        source_strategy_id=int(strategy_id),
        account_id=account_id,
        status="paused",
    )
    _upsert_live_strategy_account_binding(
        int(strategy_id),
        account_id=account_id,
        added=True,
        risk_config=subscription.get("risk_config") or {},
        deployment_strategy_id=None,
        clear_deployment_strategy_id=True,
        status="deployed",
    )
    _upsert_live_strategy_setting(
        int(strategy_id),
        added=True,
        account_id=account_id,
        risk_config=subscription.get("risk_config") or {},
        deployment_strategy_id=None,
        clear_deployment_strategy_id=True,
        status="deployed",
    )
    return ok(
        {
            "paused": True,
            "source_strategy_id": int(strategy_id),
            "live_subscription_id": subscription["id"],
            "strategy": _live_execution_strategy_payload(row),
        }
    )


@router.post("/strategies/{strategy_id}/resume")
async def resume_live_strategy_subscription(strategy_id: int, body: LiveStrategySubscriptionControlBody):
    account_id = live_account_service.validate_account_id(body.account_id or "default")
    row, _ = _require_live_subscription_control(int(strategy_id), account_id)
    subscription = live_signal_execution_service.set_subscription_status(
        source_strategy_id=int(strategy_id),
        account_id=account_id,
        status="running",
    )
    _upsert_live_strategy_account_binding(
        int(strategy_id),
        account_id=account_id,
        added=True,
        risk_config=subscription.get("risk_config") or {},
        deployment_strategy_id=None,
        clear_deployment_strategy_id=True,
        status="deployed",
    )
    _upsert_live_strategy_setting(
        int(strategy_id),
        added=True,
        account_id=account_id,
        risk_config=subscription.get("risk_config") or {},
        deployment_strategy_id=None,
        clear_deployment_strategy_id=True,
        status="deployed",
    )
    return ok(
        {
            "resumed": True,
            "source_strategy_id": int(strategy_id),
            "live_subscription_id": subscription["id"],
            "strategy": _live_execution_strategy_payload(row),
        }
    )


def _live_subscription_stop_symbols(row: Dict[str, Any], subscription: Dict[str, Any]) -> set[str]:
    cfg = _json_dict(row.get("config") if row else {})
    risk_config = _json_dict(subscription.get("risk_config") if subscription else {})
    raw_symbols: List[str] = []
    for key in ("allowed_live_symbols", "live_preflight_allowed_symbols"):
        raw_symbols.extend(_row_symbols({"symbols": risk_config.get(key)}))
    if not raw_symbols:
        raw_symbols.extend(_config_trade_symbols(cfg))
        raw_symbols.extend(_defined_symbols(row, cfg, None))
    return {normalize_contract_symbol(symbol) for symbol in raw_symbols if str(symbol).strip()}


async def _ensure_live_subscription_positionless(
    *,
    row: Dict[str, Any],
    subscription: Dict[str, Any],
    account_id: str,
) -> None:
    symbols = _live_subscription_stop_symbols(row, subscription)
    if not symbols:
        return
    exchange = live_account_service.exchange_alias_for_account(account_id)
    ex = exchange_manager.get_exchange(exchange)
    if ex:
        try:
            symbols = {
                venue_symbol
                for _, venue_symbol in _venue_contract_symbol_pairs(ex, sorted(symbols))
            }
        except Exception as exc:
            logger.warning(
                "停止实盘订阅前解析交易所合约失败 account=%s symbols=%s: %s",
                account_id,
                sorted(symbols),
                exc,
            )
    try:
        positions = await trading_service.get_positions(exchange, None)
    except Exception as exc:
        logger.warning("停止实盘订阅前读取账户持仓失败 account=%s: %s", account_id, exc)
        raise BadRequestError("无法确认实盘账户是否仍有持仓，请稍后重试；停止前需要先完成平仓确认")
    targets = [
        target
        for target in _live_contract_position_targets(positions, None)
        if target.get("symbol") in symbols
    ]
    if not targets:
        return
    preview = "、".join(
        f"{target.get('symbol')} {target.get('side')}"
        for target in targets[:5]
        if target.get("symbol") and target.get("side")
    )
    suffix = f"：{preview}" if preview else ""
    raise BadRequestError(f"当前账户仍有该实盘策略相关持仓{suffix}，请先平仓后再停止订阅")


@router.post("/strategies/{strategy_id}/stop")
async def stop_live_strategy_subscription(strategy_id: int, body: LiveStrategySubscriptionControlBody):
    account_id = live_account_service.validate_account_id(body.account_id or "default")
    row, existing_subscription = _require_live_subscription_control(int(strategy_id), account_id, allow_stopped=True)
    await _ensure_live_subscription_positionless(
        row=row,
        subscription=existing_subscription,
        account_id=account_id,
    )
    subscription = live_signal_execution_service.set_subscription_status(
        source_strategy_id=int(strategy_id),
        account_id=account_id,
        status="stopped",
    )
    still_deployed = bool(
        live_signal_execution_service.list_subscriptions(
            source_strategy_id=int(strategy_id),
            statuses=sorted(live_signal_execution_service.DEPLOYED_STATUSES),
        )
    )
    _upsert_live_strategy_account_binding(
        int(strategy_id),
        account_id=account_id,
        added=True,
        risk_config=subscription.get("risk_config") or {},
        deployment_strategy_id=None,
        clear_deployment_strategy_id=True,
        status="added",
    )
    _upsert_live_strategy_setting(
        int(strategy_id),
        added=True,
        account_id=account_id,
        risk_config=subscription.get("risk_config") or {},
        deployment_strategy_id=None,
        clear_deployment_strategy_id=True,
        status="deployed" if still_deployed else "added",
    )
    return ok(
        {
            "stopped": True,
            "source_strategy_id": int(strategy_id),
            "live_subscription_id": subscription["id"],
            "strategy": _live_execution_strategy_payload(row),
        }
    )


@router.get("/accounts")
async def list_live_accounts():
    return ok({"accounts": live_account_service.list_accounts()})


@router.post("/accounts")
async def create_live_account(body: LiveAccountCreateBody):
    account = live_account_service.create_account(
        name=body.name,
        exchange=body.exchange,
        api_key=body.api_key,
        api_secret=body.api_secret,
        passphrase=body.passphrase,
        testnet=body.testnet,
    )
    return ok({"account": account})


def _live_contract_broker_for_exchange(exchange: str):
    return BinanceUsdmContractBroker if str(exchange).split(":", 1)[0].lower() == "binanceusdm" else LiveContractBroker


@router.get("/watchlist")
async def live_watchlist(
    account_id: str = Query("default", description="实盘账户 ID"),
    limit: int = Query(100, ge=1, le=500),
):
    normalized, exchange = _live_account_exchange_alias(account_id)
    candidate_limit = min(2000, max(int(limit) * 5, int(limit)))
    items = live_signal_execution_service.list_watchlist_items(account_id=normalized, limit=candidate_limit)
    positions = await _cached_live_positions(exchange)
    open_symbols = _live_open_position_symbols(positions)
    items = [
        item
        for item in items
        if normalize_contract_symbol(str(item.get("symbol") or "")) in open_symbols
    ][: int(limit)]
    return ok({"account_id": normalized, "exchange": exchange, "items": items})


@router.get("/watchlist/markers")
async def live_watch_markers(
    account_id: str = Query("default", description="实盘账户 ID"),
    symbol: str = Query(..., description="合约交易对"),
    start: Optional[int] = Query(None, description="开始时间戳 ms"),
    end: Optional[int] = Query(None, description="结束时间戳 ms"),
    limit: int = Query(500, ge=1, le=2000),
):
    normalized, exchange = _live_account_exchange_alias(account_id)
    markers = live_signal_execution_service.list_trade_markers(
        account_id=normalized,
        symbol=_normalize_watch_symbol(symbol),
        start=start,
        end=end,
        limit=limit,
    )
    return ok({"account_id": normalized, "exchange": exchange, "symbol": _normalize_watch_symbol(symbol), "markers": markers})


@router.get("/watchlist/market")
async def live_watch_market(
    account_id: str = Query("default", description="实盘账户 ID"),
    symbol: str = Query(..., description="合约交易对"),
    timeframe: str = Query("15m", description="K线周期"),
    limit: int = Query(240, ge=20, le=1000),
):
    normalized, exchange = _live_account_exchange_alias(account_id)
    normalized_symbol = _normalize_watch_symbol(symbol)
    public_exchange = str(exchange).split(":", 1)[0].strip().lower() or "okx"
    ticker, klines, orderbook, trades, positions = await asyncio.gather(
        market_domain_service.get_ticker(public_exchange, normalized_symbol),
        market_domain_service.get_klines(public_exchange, normalized_symbol, timeframe=timeframe, limit=limit),
        market_domain_service.get_orderbook(public_exchange, normalized_symbol, limit=20),
        market_domain_service.get_trades(public_exchange, normalized_symbol, limit=50),
        _cached_live_positions(exchange, normalized_symbol),
    )
    return ok(
        {
            "account_id": normalized,
            "exchange": exchange,
            "symbol": normalized_symbol,
            "timeframe": timeframe,
            "ticker": ticker,
            "klines": klines,
            "orderbook": orderbook,
            "recent_trades": trades,
            "positions": positions,
        }
    )


@router.get("/watchlist/derivatives-data")
async def live_watch_derivatives_data(
    account_id: str = Query("default", description="实盘账户 ID"),
    symbol: str = Query(..., description="合约交易对"),
    timeframe: str = Query("15m", description="统计周期"),
    limit: int = Query(120, ge=20, le=500),
):
    normalized, exchange = _live_account_exchange_alias(account_id)
    normalized_symbol = _normalize_watch_symbol(symbol)
    public_exchange = "okx"
    funding_history, open_interest, long_short_ratio, taker_volume, basis = await asyncio.gather(
        funding_domain_service.get_funding_history(public_exchange, normalized_symbol, limit=limit),
        _okx_open_interest_points(public_exchange, normalized_symbol, timeframe, limit),
        _okx_long_short_ratio_points(public_exchange, normalized_symbol, timeframe, limit),
        _okx_taker_volume_points(public_exchange, normalized_symbol, timeframe, limit),
        _okx_basis_points(public_exchange, normalized_symbol, timeframe, limit),
    )
    funding_points = [
        _point(
            row.get("timestamp") or row.get("funding_time") or row.get("fundingTime"),
            row.get("funding_rate") or row.get("rate") or row.get("current_rate"),
            mark_price=_optional_float(row.get("mark_price") or row.get("markPrice")),
        )
        for row in (funding_history or [])
        if isinstance(row, dict)
    ]
    return ok(
        {
            "account_id": normalized,
            "exchange": exchange,
            "symbol": normalized_symbol,
            "timeframe": timeframe,
            "open_interest": {"points": open_interest},
            "funding_rate": {"points": [p for p in funding_points if p["timestamp"]]},
            "long_short_ratio": {"points": long_short_ratio},
            "taker_volume": {"points": taker_volume},
            "basis": {"points": basis},
        }
    )


@router.get("/accounts/{account_id}/balance")
async def live_account_balance(account_id: str):
    normalized, exchange = _live_account_exchange_alias(account_id)
    balance = await _cached_live_balance(exchange)
    return ok({"account_id": normalized, "exchange": exchange, "balance": balance})


@router.get("/accounts/{account_id}/balance/detail")
async def live_account_balance_detail(account_id: str):
    normalized, exchange = _live_account_exchange_alias(account_id)
    detail, return_rates = await asyncio.gather(
        _cached_live_balance_detail(exchange),
        _cached_live_return_rates(exchange),
    )
    return ok({"account_id": normalized, "exchange": exchange, **detail, "return_rates": return_rates})


@router.get("/accounts/{account_id}/positions")
async def live_account_positions(
    account_id: str,
    symbol: Optional[str] = Query(None, description="交易对"),
):
    normalized, exchange = _live_account_exchange_alias(account_id)
    positions, balances = await asyncio.gather(
        _cached_live_positions(exchange, symbol),
        _cached_live_balance(exchange),
    )
    if not str(exchange).startswith("binanceusdm:"):
        positions = [
            *positions,
            *_spot_positions_from_balances(balances, exchange_name=exchange, symbol=symbol),
        ]
    return ok({"account_id": normalized, "exchange": exchange, "positions": positions})


@router.post("/accounts/{account_id}/positions/close")
async def live_account_close_position(account_id: str, body: LivePositionCloseBody):
    if not body.confirm_live_risk:
        raise BadRequestError("平仓需要二次确认 confirm_live_risk=true")
    normalized, exchange = _live_account_exchange_alias(account_id)
    symbol = normalize_contract_symbol(body.symbol) if body.symbol else ""

    if body.close_all:
        positions = await trading_service.get_positions(exchange, symbol or None)
        targets = _live_contract_position_targets(positions, symbol or None)
        if not targets:
            raise BadRequestError("当前账户没有可平的合约持仓")
    else:
        side = str(body.side or "").strip().lower()
        if not symbol or side not in {"long", "short"}:
            raise BadRequestError("平仓需要指定合约 symbol 和方向 side=long/short")
        targets = [{"symbol": symbol, "side": side}]

    broker = _live_contract_broker_for_exchange(exchange)(
        strategy_id=0,
        exchange_name=exchange,
        symbols=sorted({target["symbol"] for target in targets}),
        config={
            "is_paper_trading": False,
            "market_type": "swap",
            "live_order_type": "market",
        },
    )
    results: List[Dict[str, Any]] = []
    for target in targets:
        result = await broker.close_contract(target["symbol"], target["side"], ratio=1.0)
        results.append(dict(result))
    closed = sum(1 for result in results if str(result.get("status") or "").lower() in {"filled", "closed", "submitted", "open"})
    _clear_live_private_read_cache(exchange)
    return ok(
        {
            "account_id": normalized,
            "exchange": exchange,
            "closed": closed,
            "results": results,
        }
    )


@router.get("/accounts/{account_id}/orders/open")
async def live_account_open_orders(
    account_id: str,
    symbol: Optional[str] = Query(None, description="交易对"),
):
    normalized, exchange = _live_account_exchange_alias(account_id)
    orders = await _cached_live_open_orders(exchange, symbol)
    return ok({"account_id": normalized, "exchange": exchange, "orders": orders})


@router.get("/accounts/{account_id}/orders/history")
async def live_account_order_history(
    account_id: str,
    symbol: Optional[str] = Query(None, description="交易对"),
    limit: int = Query(50, ge=1, le=200),
):
    normalized, exchange = _live_account_exchange_alias(account_id)
    orders = await _cached_live_account_order_history(
        account_id=normalized,
        exchange=exchange,
        symbol=symbol,
        limit=limit,
    )
    orders = [_normalize_live_order_financial_fields(order) for order in orders]
    orders = live_signal_execution_service.enrich_orders_with_attribution(
        account_id=normalized,
        orders=orders,
    )
    failed_execution_orders = live_signal_execution_service.list_failed_execution_orders(
        account_id=normalized,
        symbol=symbol,
        limit=limit,
    )
    orders = _merge_live_order_history(orders, failed_execution_orders, limit)
    return ok({"account_id": normalized, "exchange": exchange, "orders": orders})


async def _run_preflight_checks(
    *,
    strategy_id: int,
    row: Optional[Dict[str, Any]],
    exchange: str,
    timeframe: str,
    dry_run: bool,
    symbol: Optional[str] = None,
    symbol_scope: str = "strategy_symbols",
) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    account: Optional[Dict[str, Any]] = None
    eligible_symbols: List[str] = []
    excluded_symbols: List[str] = []
    ex = exchange_manager.get_exchange(exchange)
    checks.append(
        {
            "item": "策略存在性",
            "passed": row is not None,
            "detail": None if row else f"未找到策略 #{strategy_id}",
        }
    )

    exchange_probe = ex is not None
    checks.append(
        {
            "item": f"行情连接 ({exchange})",
            "passed": exchange_probe,
            "detail": None if exchange_probe else "交易所实例不可用（请检查代理与 API）",
        }
    )

    if not dry_run:
        risk = strategy_engine.get_risk_status()
        circuit = bool(risk.get("circuit_breaker"))
        checks.append(
            {
                "item": "全局风控熔断状态",
                "passed": not circuit,
                "detail": (
                    "当前未触发全局熔断"
                    if not circuit
                    else f"全局熔断中：{risk.get('circuit_breaker_reason') or '未提供原因'}"
                ),
            }
        )

    probe_symbols: List[str] = []
    row_cfg: Dict[str, Any] = {}
    if row:
        row_cfg = row.get("config") or {}
        if not isinstance(row_cfg, dict):
            row_cfg = {}
        probe_symbols = _defined_symbols(row, row_cfg, symbol)
    if not probe_symbols:
        probe_symbols = [symbol or "BTC/USDT"]

    if ex:
        try:
            symbol_pairs = _venue_contract_symbol_pairs(ex, probe_symbols)
        except Exception:
            symbol_pairs = [(sym, sym) for sym in probe_symbols]
        venue_probe_symbols = [venue_symbol for _, venue_symbol in symbol_pairs]
        source_by_venue = {venue_symbol: source_symbol for source_symbol, venue_symbol in symbol_pairs}
        checks.append(
            await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: _market_rules_check(ex, venue_probe_symbols),
            )
        )
        failed: List[str] = []
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        max_stale_ms = max(_timeframe_seconds(timeframe) * 5 * 1000, 300_000)
        for sym in venue_probe_symbols:
            try:
                ohlcv = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda s=sym: ex.fetch_ohlcv(s, timeframe, limit=3),
                )
                if not ohlcv or len(ohlcv) < 1:
                    failed.append(f"{sym}: 无数据")
                    continue
                latest_ts = _kline_timestamp_ms(ohlcv[-1])
                if latest_ts is None:
                    failed.append(f"{sym}: K 线缺少时间戳")
                elif now_ms - latest_ts > max_stale_ms:
                    stale_min = (now_ms - latest_ts) / 60_000
                    failed.append(f"{sym}: 最新 K 线滞后 {stale_min:.0f} 分钟")
            except Exception as e:
                failed.append(f"{sym}: {e}")
        has_bar = not failed
        bar_err = "；".join(failed[:5])
        if len(failed) > 5:
            bar_err += f"；另有 {len(failed) - 5} 个失败"
        checks.append(
            {
                "item": f"K 线拉取（策略定义 {len(probe_symbols)} 个交易对）",
                "passed": has_bar,
                "detail": None if has_bar else (bar_err or "无数据"),
            }
        )
        if not dry_run:
            dynamic_filter = symbol_scope == "dynamic_runtime_symbols"
            order_book_check = await _order_book_liquidity_check(
                ex,
                venue_probe_symbols,
                allow_dynamic_filter=dynamic_filter,
                min_remaining_symbols=(
                    _dynamic_preflight_min_symbols(row_cfg, len(probe_symbols)) if dynamic_filter else 0
                ),
            )
            checks.append(order_book_check)
            if dynamic_filter and order_book_check.get("passed"):
                raw_eligible = order_book_check.get("eligible_symbols")
                raw_excluded = order_book_check.get("excluded_symbols")
                if isinstance(raw_eligible, list) and raw_eligible:
                    eligible_symbols = [
                        source_by_venue.get(str(sym), str(sym))
                        for sym in raw_eligible
                        if str(sym).strip()
                    ]
                    probe_symbols = eligible_symbols
                if isinstance(raw_excluded, list):
                    excluded_symbols = [
                        source_by_venue.get(str(sym), str(sym))
                        for sym in raw_excluded
                        if str(sym).strip()
                    ]
    else:
        checks.append({"item": "K 线拉取", "passed": False, "detail": "跳过（无交易所实例）"})

    if not dry_run:
        try:
            balances = await trading_service.get_balance(exchange)
            usdt = next(
                (
                    item
                    for item in balances
                    if isinstance(item, dict) and str(item.get("currency", "")).upper() == "USDT"
                ),
                None,
            )
            free_usdt = float((usdt or {}).get("free") or 0.0)
            total_usdt = float((usdt or {}).get("total") or 0.0)
            used_usdt = float((usdt or {}).get("used") or max(total_usdt - free_usdt, 0.0))
            account = {
                "exchange": exchange,
                "currency": "USDT",
                "free_usdt": free_usdt,
                "total_usdt": total_usdt,
                "used_usdt": used_usdt,
            }
            checks.append(
                {
                    "item": "实盘账户权限与 USDT 余额",
                    "passed": free_usdt > 0,
                    "detail": (
                        f"USDT 可用 {free_usdt:.2f} / 总额 {total_usdt:.2f}"
                        if free_usdt > 0
                        else "未读取到可用 USDT，请检查 OKX API Key、权限和账户资金"
                    ),
                    "account": account,
                }
            )
            min_cash = _configured_min_order_notional(row_cfg)
            checks.append(
                {
                    "item": "实盘最小下单资金",
                    "passed": free_usdt >= min_cash,
                    "detail": (
                        f"USDT 可用 {free_usdt:.2f}，满足最小下单资金 {min_cash:.2f}"
                        if free_usdt >= min_cash
                        else f"USDT 可用 {free_usdt:.2f}，低于最小下单资金 {min_cash:.2f}"
                    ),
                    "account": account,
                }
            )
        except Exception as e:
            checks.append(
                {
                    "item": "实盘账户权限与 USDT 余额",
                    "passed": False,
                    "detail": f"余额读取失败：{e}",
                }
            )
        try:
            conflicts: List[str] = []
            for sym in venue_probe_symbols:
                orders = await trading_service.get_open_orders(exchange, sym)
                active_orders = [
                    order
                    for order in (orders or [])
                    if isinstance(order, dict)
                    and str(order.get("status") or "open").lower()
                    not in {"closed", "canceled", "cancelled"}
                ]
                if active_orders:
                    conflicts.append(f"{sym}: {len(active_orders)} 个未成交挂单")
            checks.append(
                {
                    "item": "实盘未成交挂单冲突",
                    "passed": not conflicts,
                    "detail": (
                        "策略交易对当前无未成交挂单"
                        if not conflicts
                        else "；".join(conflicts[:5])
                        + (f"；另有 {len(conflicts) - 5} 个交易对存在挂单" if len(conflicts) > 5 else "")
                    ),
                }
            )
        except Exception as e:
            checks.append(
                {
                    "item": "实盘未成交挂单冲突",
                    "passed": False,
                    "detail": f"未成交挂单读取失败：{e}",
                }
            )

    all_passed = all(c["passed"] for c in checks)
    result: Dict[str, Any] = {"all_passed": all_passed, "checks": checks, "account": account}
    if eligible_symbols:
        result["eligible_symbols"] = eligible_symbols
    if excluded_symbols:
        result["excluded_symbols"] = excluded_symbols
    return result


@router.post("/pre_flight")
async def live_pre_flight(body: PreFlightBody):
    sid = _parse_strategy_id(body.strategy)
    row = db.get_strategy_by_id(sid)
    timeframe = _strategy_defined_timeframe(row)
    return ok(
        await _run_preflight_checks(
            strategy_id=sid,
            row=row,
            exchange=body.exchange,
            timeframe=timeframe,
            dry_run=body.dry_run,
            symbol=body.symbol,
        )
    )


@router.post("/promote/preflight")
async def promote_to_live_preflight(body: PromoteToLiveBody):
    return ok(await _run_promote_preflight(body))


@router.post("/promote")
async def promote_to_live(body: PromoteToLiveBody):
    if not body.confirm_paper_reviewed or not body.confirm_live_risk:
        raise BadRequestError("部署实盘需要确认已复核模拟盘表现，并确认真实资金风险")

    prepared = _prepare_promoted_live_candidate(body)
    source = prepared["source"]
    source_cfg = prepared["source_cfg"]
    if source_cfg.get("is_paper_trading") is False:
        raise BadRequestError("来源策略已经是实盘策略，不能再次部署")

    eng = strategy_engine.get_strategy_status(int(body.source_strategy_id))
    if eng and eng.get("status") == "running" and source.get("status") == "running":
        # 允许从正在运行的模拟盘复制；只是不复用该 row，不污染模拟盘。
        pass

    preflight = await _run_promote_preflight(body, prepared=prepared)
    if not preflight["all_passed"]:
        return ok(
            {
                "promoted": False,
                "started": False,
                "source_strategy_id": int(body.source_strategy_id),
                "preflight": preflight,
            }
        )

    symbols = prepared["symbols"]
    live_cfg = prepared["live_cfg"]
    live_id = _insert_promoted_strategy(
        source,
        exchange=body.exchange,
        symbols=symbols,
        config=live_cfg,
    )
    strategy_engine.drop_cached_context(live_id)
    started = False
    if body.start_immediately:
        started = await strategy_engine.start_strategy(live_id)
        if not started:
            db.update_strategy_status(live_id, "stopped")
            raise BadRequestError("小资金实盘试运行已创建，但启动失败（可能处于熔断或配置无效）")

    global _active_strategy_id
    _active_strategy_id = live_id
    return ok(
        {
            "promoted": True,
            "started": started,
            "source_strategy_id": int(body.source_strategy_id),
            "live_strategy_id": live_id,
            "preflight": preflight,
            "trial": {
                "initial_equity": _float_value(live_cfg.get("initial_capital"), 0.0),
                "initial_equity_source": live_cfg.get("initial_capital_source") or "request",
                "account": prepared.get("account"),
                "loop_interval_sec": int(body.loop_interval),
                "symbols": symbols,
            },
        }
    )


@router.post("/test_telegram")
async def live_test_telegram(body: TelegramTestBody):
    sent = await telegram_notifier.send_message(body.message)
    return ok({"sent": sent})
