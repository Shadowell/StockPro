"""Stable paper-session evidence helpers shared by REST, MCP and backtests."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping


PAPER_OBSERVABILITY_CONTRACT_VERSION = "bitpro-paper-observability-v1"
_EPHEMERAL_CONFIG_KEYS = {
    "paper_instance_id",
    "paper_config_version",
    "paper_strategy_version",
    "paper_configured_at",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_version(value: Any) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def strategy_version(script_content: Any) -> str:
    return sha256_version({"script_content": str(script_content or "")})


def stable_paper_config(config: Mapping[str, Any] | None) -> Dict[str, Any]:
    raw = dict(config or {})
    return {key: value for key, value in raw.items() if key not in _EPHEMERAL_CONFIG_KEYS}


def paper_config_version(
    config: Mapping[str, Any] | None,
    *,
    exchange: Any,
    symbols: Any,
) -> str:
    return sha256_version(
        {
            "config": stable_paper_config(config),
            "exchange": str(exchange or ""),
            "symbols": list(symbols or []) if isinstance(symbols, (list, tuple, set)) else [str(symbols or "")],
        }
    )


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bps_from_rate(value: Any) -> float | None:
    number = _finite_number(value)
    return round(number * 10_000, 8) if number is not None else None


def evidence_assumptions(config: Mapping[str, Any] | None, *, overrides: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    cfg = dict(config or {})
    values = dict(overrides or {})

    maker_fee_bps = values.get("maker_fee_bps", cfg.get("maker_fee_bps"))
    taker_fee_bps = values.get("taker_fee_bps", cfg.get("taker_fee_bps", cfg.get("fee_bps")))
    commission_rate = values.get("commission_rate", cfg.get("commission_rate", cfg.get("commission")))
    if taker_fee_bps is None:
        taker_fee_bps = _bps_from_rate(commission_rate)

    slippage_bps = values.get("slippage_bps", cfg.get("slippage_bps"))
    slippage_rate = values.get("slippage_rate", cfg.get("slippage_rate", cfg.get("slippage")))
    if slippage_bps is None:
        slippage_bps = _bps_from_rate(slippage_rate)

    funding = values.get("funding")
    if funding is None:
        funding = {
            "mode": cfg.get("funding_mode") or "strategy_defined_or_not_modeled",
            "rate_assumption": cfg.get("funding_rate_assumption"),
            "interval_hours": cfg.get("funding_interval_hours"),
        }

    return {
        "fees": {
            "maker_fee_bps": _finite_number(maker_fee_bps),
            "taker_fee_bps": _finite_number(taker_fee_bps),
            "commission_rate": _finite_number(commission_rate),
        },
        "slippage": {
            "slippage_bps": _finite_number(slippage_bps),
            "slippage_rate": _finite_number(slippage_rate),
        },
        "funding": funding,
    }


def equity_curve_version(samples: Iterable[Mapping[str, Any]]) -> str:
    normalized = []
    for item in samples:
        timestamp = item.get("timestamp")
        equity = _finite_number(item.get("equity"))
        if timestamp is None or equity is None:
            continue
        normalized.append({"timestamp": int(timestamp), "equity": equity})
    return sha256_version({"equity_samples": normalized})


def _epoch_ms_to_utc_iso(value: Any) -> str | None:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).isoformat()


def equity_curve_summary(samples: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return compact, stable coverage facts without embedding the whole equity curve."""
    normalized = []
    for item in samples:
        try:
            timestamp = int(item.get("timestamp"))
        except (TypeError, ValueError):
            continue
        equity = _finite_number(item.get("equity"))
        if equity is None:
            continue
        normalized.append((timestamp, equity))
    normalized.sort(key=lambda item: item[0])
    if not normalized:
        return {
            "sample_count": 0,
            "first_at": None,
            "last_at": None,
            "first_equity": None,
            "last_equity": None,
            "peak_equity": None,
            "trough_equity": None,
        }
    equities = [item[1] for item in normalized]
    return {
        "sample_count": len(normalized),
        "first_at": _epoch_ms_to_utc_iso(normalized[0][0]),
        "last_at": _epoch_ms_to_utc_iso(normalized[-1][0]),
        "first_equity": normalized[0][1],
        "last_equity": normalized[-1][1],
        "peak_equity": max(equities),
        "trough_equity": min(equities),
    }


def paper_evidence(
    instance: Mapping[str, Any],
    strategy_row: Mapping[str, Any],
    *,
    equity_version: str,
    generated_at: str | None = None,
) -> Dict[str, Any]:
    generated = generated_at or utc_now_iso()
    config = instance.get("config_snapshot") or strategy_row.get("config") or {}
    data_window = {
        "start_at": instance.get("started_at") or instance.get("configured_at"),
        "end_at": instance.get("ended_at") or generated,
        "timezone": "UTC",
    }
    evidence = {
        "strategy_version": instance.get("strategy_version"),
        "script_hash": instance.get("strategy_version"),
        "config_version": instance.get("config_version"),
        "data_window": data_window,
        "assumptions": evidence_assumptions(config),
        "equity_curve_version": equity_version,
        "generated_at": generated,
        "timezone": "UTC",
    }
    evidence["evidence_version"] = sha256_version(evidence)
    return evidence


def backtest_evidence(
    strategy_row: Mapping[str, Any] | None,
    *,
    start_date: str,
    end_date: str,
    assumptions: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
) -> Dict[str, Any]:
    row = dict(strategy_row or {})
    generated = generated_at or utc_now_iso()
    config = row.get("config") or {}
    evidence = {
        "strategy_version": strategy_version(row.get("script_content")),
        "script_hash": strategy_version(row.get("script_content")),
        "config_version": paper_config_version(
            config,
            exchange=row.get("exchange"),
            symbols=row.get("symbols"),
        ),
        "data_window": {
            "start_at": start_date,
            "end_at": end_date,
            "timezone": "UTC",
        },
        "assumptions": evidence_assumptions(config, overrides=assumptions),
        "generated_at": generated,
        "timezone": "UTC",
    }
    evidence["evidence_version"] = sha256_version(evidence)
    return evidence


def legacy_backtest_evidence() -> Dict[str, Any]:
    return {
        "evidence_status": "legacy_unversioned",
        "strategy_version": None,
        "script_hash": None,
        "config_version": None,
        "data_window": None,
        "assumptions": None,
        "generated_at": None,
        "timezone": "UTC",
    }


def normalize_paper_event_type(payload: Mapping[str, Any] | None, *, level: str = "info") -> str:
    data = dict(payload or {})
    raw_type = str(data.get("type") or data.get("event_type") or "").strip().lower()
    if raw_type in {"started", "paused", "resumed", "stopped", "configured"}:
        return raw_type
    if raw_type in {"order_rejected", "ai_trade_rejected", "rejected"}:
        return "order_rejected"
    if raw_type in {"liquidation", "risk_trigger", "circuit_breaker"}:
        return "risk_trigger"
    text = " ".join(str(data.get(key) or "") for key in ("message", "reason", "error")).lower()
    if any(token in text for token in ("reject", "rejected", "拒绝", "拒单", "无法下单")):
        return "order_rejected"
    if any(token in text for token in ("ohlcv", "ticker", "行情", "数据", "k线", "k-line", "rate limit")):
        return "data_interruption"
    if any(token in text for token in ("risk", "风控", "爆仓", "liquidation", "circuit")):
        return "risk_trigger"
    if level.lower() in {"error", "critical"} or any(
        token in text for token in ("异常", "exception", "error", "fatal")
    ):
        return "strategy_exception"
    return raw_type or "log"
