"""Bounded, versioned strategy time-series evidence over BitPro-owned facts."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.mcp.schemas import MCP_CONTRACT_VERSION
from app.services.paper_observability import (
    evidence_assumptions,
    paper_config_version,
    strategy_version,
)

STRATEGY_EVIDENCE_CONTRACT_VERSION = "bitpro-strategy-evidence-v1"
MAX_POINTS = 500
MAX_MEMBERS = 20
MAX_WINDOW_SECONDS = 366 * 24 * 60 * 60


class ContractValidationError(ValueError):
    pass


class ReturnSeriesRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_layer: Literal["backtest", "paper", "live"]
    source_id: str = Field(min_length=1, max_length=128)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    bucket_seconds: int = Field(default=3600, ge=60, le=86_400)
    limit: int = Field(default=200, ge=1, le=MAX_POINTS)
    cursor: str = Field(default="", max_length=32)

    @model_validator(mode="after")
    def validate_window(self) -> "ReturnSeriesRequestV1":
        if self.start_at is not None:
            self.start_at = _aware(self.start_at)
        if self.end_at is not None:
            self.end_at = _aware(self.end_at)
        if self.start_at and self.end_at:
            if self.end_at <= self.start_at:
                raise ValueError("end_at must be after start_at")
            if (self.end_at - self.start_at).total_seconds() > MAX_WINDOW_SECONDS:
                raise ValueError("strategy evidence window exceeds 366 days")
        if self.cursor and (not self.cursor.isdigit() or int(self.cursor) < 0):
            raise ValueError("cursor must be a non-negative integer offset")
        return self


class AlignmentRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    members: List[str] = Field(min_length=1, max_length=MAX_MEMBERS)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    bucket_seconds: int = Field(default=3600, ge=60, le=86_400)
    max_points: int = Field(default=200, ge=2, le=MAX_POINTS)

    @model_validator(mode="after")
    def validate_members(self) -> "AlignmentRequestV1":
        if len(set(self.members)) != len(self.members):
            raise ValueError("aligned matrix members must be unique")
        for member in self.members:
            layer, separator, source_id = member.partition(":")
            if separator != ":" or layer not in {"backtest", "paper", "live"} or not source_id:
                raise ValueError(f"invalid matrix member: {member}")
        ReturnSeriesRequestV1(
            source_layer="backtest",
            source_id="window-validation",
            start_at=self.start_at,
            end_at=self.end_at,
            bucket_seconds=self.bucket_seconds,
            limit=self.max_points,
        )
        return self


class StrategyEvidenceService:
    def __init__(self, database: Any) -> None:
        self.database = database

    def return_series(self, request: ReturnSeriesRequestV1) -> Dict[str, Any]:
        if request.source_layer == "backtest":
            source = self._backtest_source(request.source_id)
        elif request.source_layer == "paper":
            source = self._paper_source(
                request.source_id,
                start_at=request.start_at,
                end_at=request.end_at,
            )
        else:
            raise ContractValidationError("live_return_series_unavailable")

        points = _normalize_points(source["points"])
        now = datetime.now(timezone.utc)
        if any(_point_time(item) > now for item in points):
            raise ContractValidationError("future strategy return point is forbidden")
        start_ms = _epoch_ms(request.start_at) if request.start_at else None
        end_ms = _epoch_ms(request.end_at) if request.end_at else None
        points = [
            item
            for item in points
            if (start_ms is None or int(item["timestamp"]) >= start_ms)
            and (end_ms is None or int(item["timestamp"]) <= end_ms)
        ]
        if points and (
            int(points[-1]["timestamp"]) - int(points[0]["timestamp"])
        ) / 1000 > MAX_WINDOW_SECONDS:
            raise ContractValidationError("strategy evidence window exceeds 366 days")
        points = _bucket_points(points, request.bucket_seconds)
        if not points:
            raise ContractValidationError("return series has no points in requested window")

        costs = _validate_cost_model(source["cost_model"])
        initial_equity = float(points[0]["equity"])
        projected = [
            {
                "timestamp": _iso_from_ms(int(item["timestamp"])),
                "equity": _decimal_text(item["equity"]),
                "gross_return": None,
                "net_return": _decimal_text(
                    (float(item["equity"]) / initial_equity - 1.0) if initial_equity else 0.0
                ),
            }
            for item in points
        ]
        stable_source = {
            "source_layer": request.source_layer,
            "source_id": request.source_id,
            "strategy_id": source["strategy_id"],
            "strategy_version": source["strategy_version"],
            "config_version": source["config_version"],
            "timeframe": source["timeframe"],
            "currency": source["currency"],
            "cost_model": costs,
            "points": projected,
        }
        source_hash = _hash(stable_source)
        offset = int(request.cursor or "0")
        page = projected[offset : offset + request.limit]
        next_offset = offset + len(page)
        next_cursor = str(next_offset) if next_offset < len(projected) else ""
        as_of = page[-1]["timestamp"] if page else projected[-1]["timestamp"]
        payload: Dict[str, Any] = {
            "schema_version": "strategy_return_series.v1",
            "contract_version": MCP_CONTRACT_VERSION,
            "producer": STRATEGY_EVIDENCE_CONTRACT_VERSION,
            "source_layer": request.source_layer,
            "source_id": request.source_id,
            "strategy_id": source["strategy_id"],
            "strategy_version": source["strategy_version"],
            "config_version": source["config_version"],
            "symbols": source["symbols"],
            "timeframe": source["timeframe"],
            "bucket_seconds": request.bucket_seconds,
            "timezone": "UTC",
            "currency": source["currency"],
            "precision": {"equity": 8, "return": 12},
            "window": {
                "start_at": projected[0]["timestamp"],
                "end_at": projected[-1]["timestamp"],
            },
            "gross_return": None,
            "net_return": projected[-1]["net_return"],
            "cost_model": costs,
            "points": page,
            "data_gaps": ["gross_return_unavailable"],
            "pagination": {
                "limit": request.limit,
                "cursor": request.cursor,
                "next_cursor": next_cursor,
                "total_points": len(projected),
            },
            "as_of": as_of,
            "freshness": _freshness(as_of),
            "source_hash": source_hash,
            "recorded_at": now.isoformat(),
        }
        payload["content_hash"] = _hash(
            {key: value for key, value in payload.items() if key not in {"freshness", "recorded_at"}}
        )
        return payload

    def aligned_matrix(self, request: AlignmentRequestV1) -> Dict[str, Any]:
        recorded_at = datetime.now(timezone.utc)
        rows: List[Dict[str, Any]] = []
        missing: List[Dict[str, str]] = []
        for member in request.members:
            layer, source_id = member.split(":", 1)
            try:
                series = self.return_series(
                    ReturnSeriesRequestV1(
                        source_layer=layer,
                        source_id=source_id,
                        start_at=request.start_at,
                        end_at=request.end_at,
                        bucket_seconds=request.bucket_seconds,
                        limit=request.max_points,
                    )
                )
            except KeyError:
                missing.append({"member": member, "reason": "source_not_found"})
                continue
            except ContractValidationError as exc:
                missing.append({"member": member, "reason": str(exc)[:96]})
                continue
            rows.append({"member": member, "series": series})

        reason_codes: List[str] = []
        if missing:
            reason_codes.append("missing_member")
        comparable = len(rows) == len(request.members) and len(rows) >= 2
        if rows:
            contracts = {
                (
                    row["series"]["source_layer"],
                    json.dumps(row["series"]["cost_model"], sort_keys=True),
                    row["series"]["currency"],
                    row["series"]["timeframe"],
                    row["series"]["bucket_seconds"],
                )
                for row in rows
            }
            if len(contracts) > 1:
                comparable = False
                reason_codes.append("incompatible_member_contract")

        timestamps = (
            set.intersection(
                *[
                    {point["timestamp"] for point in row["series"]["points"]}
                    for row in rows
                ]
            )
            if rows
            else set()
        )
        if comparable and not timestamps:
            comparable = False
            reason_codes.append("no_common_samples")
        ordered_timestamps = sorted(timestamps)[: request.max_points]
        matrix_rows = []
        for row in rows:
            by_time = {point["timestamp"]: point["net_return"] for point in row["series"]["points"]}
            matrix_rows.append(
                {
                    "member": row["member"],
                    "source_hash": row["series"]["source_hash"],
                    "returns": [by_time[value] for value in ordered_timestamps],
                }
            )
        payload: Dict[str, Any] = {
            "schema_version": "aligned_strategy_return_matrix.v1",
            "contract_version": MCP_CONTRACT_VERSION,
            "producer": STRATEGY_EVIDENCE_CONTRACT_VERSION,
            "members": list(request.members),
            "denominator": len(request.members),
            "available_count": len(rows),
            "missing_members": missing,
            "alignment_method": "utc_bucket_intersection",
            "bucket_seconds": request.bucket_seconds,
            "sample_count": len(ordered_timestamps),
            "timestamps": ordered_timestamps,
            "rows": matrix_rows,
            "comparable": comparable,
            "reason_codes": sorted(set(reason_codes)),
            "source_hashes": [row["series"]["source_hash"] for row in rows],
            "as_of": (
                ordered_timestamps[-1] if ordered_timestamps else recorded_at.isoformat()
            ),
            "recorded_at": recorded_at.isoformat(),
        }
        payload["content_hash"] = _hash(
            {key: value for key, value in payload.items() if key != "recorded_at"}
        )
        return payload

    def execution_quality(self, *, source_layer: str, source_id: str) -> Dict[str, Any]:
        recorded_at = datetime.now(timezone.utc)
        if source_layer == "backtest":
            source = self._backtest_source(source_id)
            trades = list(source.get("trades") or [])[:MAX_POINTS]
            signal_count = None
            order_count = None
            fill_count = len(trades)
            data_gaps = ["signal_count_unavailable", "order_count_unavailable", "latency_unavailable"]
        elif source_layer == "paper":
            source = self._paper_source(source_id, latest_only=True)
            conn = self.database.get_connection()
            start_ms = int(source["start_ms"])
            end_ms = int(source["end_ms"])
            trades = conn.execute(
                """
                SELECT timestamp, price, quantity, fee, pnl, meta
                FROM strategy_trades
                WHERE strategy_id = ? AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp LIMIT ?
                """,
                (source["strategy_id"], start_ms, end_ms, MAX_POINTS),
            ).fetchall()
            signal_count = None
            order_count = None
            fill_count = len(trades)
            data_gaps = ["signal_count_unavailable", "order_count_unavailable", "latency_unavailable"]
        else:
            raise ContractValidationError("live_execution_quality_unavailable")

        cost_model = _validate_cost_model(source["cost_model"])
        fill_ratio = (
            _decimal_text(fill_count / order_count)
            if isinstance(order_count, int) and order_count > 0
            else None
        )
        payload: Dict[str, Any] = {
            "schema_version": "strategy_execution_quality.v1",
            "contract_version": MCP_CONTRACT_VERSION,
            "producer": STRATEGY_EVIDENCE_CONTRACT_VERSION,
            "source_layer": source_layer,
            "source_id": source_id,
            "strategy_id": source["strategy_id"],
            "strategy_version": source["strategy_version"],
            "signal_count": signal_count,
            "order_count": order_count,
            "fill_count": fill_count,
            "fill_ratio": fill_ratio,
            "reject_count": None,
            "cancel_count": None,
            "latency_ms": None,
            "slippage": cost_model["slippage"],
            "exposure": None,
            "turnover": None,
            "data_gaps": data_gaps + ["exposure_unavailable", "turnover_unavailable"],
            "errors": [],
            "as_of": source["as_of"],
            "source_hash": _hash(
                {
                    "source_layer": source_layer,
                    "source_id": source_id,
                    "strategy_version": source["strategy_version"],
                    "fill_count": fill_count,
                    "cost_model": cost_model,
                }
            ),
            "recorded_at": recorded_at.isoformat(),
        }
        payload["content_hash"] = _hash(
            {key: value for key, value in payload.items() if key != "recorded_at"}
        )
        return payload

    def _backtest_source(self, source_id: str) -> Dict[str, Any]:
        try:
            backtest_id = int(source_id)
        except ValueError as exc:
            raise KeyError(source_id) from exc
        conn = self.database.get_connection()
        row = conn.execute(
            """
            SELECT br.*, s.name, s.script_content, s.config, s.exchange, s.symbols
            FROM backtest_results br JOIN strategies s ON s.id = br.strategy_id
            WHERE br.id = ?
            """,
            (backtest_id,),
        ).fetchone()
        if row is None or str(row["status"] or "") != "completed":
            raise KeyError(source_id)
        result = _json_object(row["result_json"])
        config = _json_object(row["config"])
        costs = evidence_assumptions(
            config,
            overrides={
                "funding": {
                    "mode": config.get("funding_mode"),
                    "total_fee": result.get("funding_fee"),
                }
            },
        )
        points = result.get("equity_curve")
        if not isinstance(points, list) or not points:
            raise ContractValidationError("backtest equity curve is unavailable")
        return {
            "strategy_id": int(row["strategy_id"]),
            "strategy_version": strategy_version(row["script_content"]),
            "config_version": paper_config_version(
                config, exchange=row["exchange"], symbols=_json_list(row["symbols"])
            ),
            "symbols": _json_list(row["symbols"]),
            "timeframe": str(row["timeframe"] or config.get("timeframe") or ""),
            "currency": str(config.get("quote_currency") or "USDT").upper(),
            "cost_model": costs,
            "points": points,
            "trades": result.get("trades") if isinstance(result.get("trades"), list) else [],
            "as_of": _iso_from_ms(max(int(item.get("timestamp") or 0) for item in points)),
        }

    def _paper_source(
        self,
        source_id: str,
        *,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        latest_only: bool = False,
    ) -> Dict[str, Any]:
        conn = self.database.get_connection()
        row = conn.execute(
            """
            SELECT psi.*, s.config, s.exchange, s.symbols
            FROM paper_strategy_instances psi JOIN strategies s ON s.id = psi.strategy_id
            WHERE psi.instance_id = ?
            """,
            (source_id,),
        ).fetchone()
        if row is None:
            raise KeyError(source_id)
        config = _json_object(row["config_snapshot"])
        instance_start_ms = _parse_ms(row["started_at"] or row["configured_at"])
        instance_end_ms = _parse_ms(row["ended_at"] or datetime.now(timezone.utc).isoformat())
        start_ms = max(instance_start_ms, _epoch_ms(start_at)) if start_at else instance_start_ms
        end_ms = min(instance_end_ms, _epoch_ms(end_at)) if end_at else instance_end_ms
        order = "DESC" if latest_only else "ASC"
        limit = 1 if latest_only else MAX_POINTS + 1
        points = conn.execute(
            f"""
            SELECT timestamp, equity FROM strategy_equity_samples
            WHERE strategy_id = ? AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp {order} LIMIT ?
            """,
            (row["strategy_id"], start_ms, end_ms, limit),
        ).fetchall()
        if len(points) > MAX_POINTS:
            raise ContractValidationError("paper source exceeds bounded point contract")
        return {
            "strategy_id": int(row["strategy_id"]),
            "strategy_version": str(row["strategy_version"]),
            "config_version": str(row["config_version"]),
            "symbols": _json_list(row["symbols"]),
            "timeframe": str(config.get("timeframe") or ""),
            "currency": str(config.get("quote_currency") or "USDT").upper(),
            "cost_model": evidence_assumptions(config),
            "points": sorted((dict(item) for item in points), key=lambda item: item["timestamp"]),
            "start_ms": start_ms,
            "end_ms": end_ms,
            "as_of": _iso_from_ms(max([int(item["timestamp"]) for item in points] or [end_ms])),
        }


def _normalize_points(raw: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    by_time: Dict[int, float] = {}
    for item in raw:
        timestamp = int(item.get("timestamp") or 0)
        if timestamp < 10_000_000_000:
            timestamp *= 1000
        equity = _finite(item.get("equity"))
        if timestamp <= 0 or equity is None:
            raise ContractValidationError("return series contains invalid point")
        if timestamp in by_time and by_time[timestamp] != equity:
            raise ContractValidationError("return series contains conflicting duplicate point")
        by_time[timestamp] = equity
    return [{"timestamp": key, "equity": by_time[key]} for key in sorted(by_time)]


def _bucket_points(points: List[Dict[str, Any]], bucket_seconds: int) -> List[Dict[str, Any]]:
    buckets: Dict[int, Dict[str, Any]] = {}
    width = bucket_seconds * 1000
    for item in points:
        buckets[int(item["timestamp"]) // width] = item
    return [buckets[key] for key in sorted(buckets)]


def _validate_cost_model(value: Any) -> Dict[str, Any]:
    costs = dict(value or {})
    fees = dict(costs.get("fees") or {})
    slippage = dict(costs.get("slippage") or {})
    funding = dict(costs.get("funding") or {})
    if fees.get("taker_fee_bps") is None:
        raise ContractValidationError("cost model missing taker fee")
    if slippage.get("slippage_bps") is None:
        raise ContractValidationError("cost model missing slippage")
    if not str(funding.get("mode") or "").strip():
        raise ContractValidationError("cost model missing funding mode")
    return {"fees": fees, "slippage": slippage, "funding": funding}


def _json_object(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        parsed = []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _decimal_text(value: Any) -> str:
    return format(float(value), ".12g")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("strategy evidence timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _epoch_ms(value: datetime) -> int:
    return int(_aware(value).timestamp() * 1000)


def _parse_ms(value: Any) -> int:
    text = str(value or "").replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return _epoch_ms(parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed)


def _iso_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def _point_time(value: Mapping[str, Any]) -> datetime:
    return datetime.fromtimestamp(int(value["timestamp"]) / 1000, tz=timezone.utc)


def _freshness(as_of: str) -> str:
    age = datetime.now(timezone.utc) - datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    return "fresh" if age.total_seconds() <= 24 * 60 * 60 else "historical"
