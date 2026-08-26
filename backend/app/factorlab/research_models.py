"""Immutable contracts for FactorLab research tasks, datasets and trials."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tuple_of_strings(value: Any, *, field_name: str, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")
    normalized = tuple(str(item or "").strip() for item in value)
    if any(not item for item in normalized):
        raise ValueError(f"{field_name} contains an empty value")
    if not allow_empty and not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} contains duplicate values")
    return normalized


def _contains_sensitive_provider_key(value: Any) -> bool:
    sensitive = {
        "api_key",
        "apikey",
        "token",
        "cookie",
        "password",
        "secret",
        "private_key",
        "privatekey",
        "command",
        "command_path",
        "commandpath",
    }
    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            key = str(raw_key).strip().lower().replace("-", "_")
            if key in sensitive or _contains_sensitive_provider_key(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_sensitive_provider_key(item) for item in value)
    return False


@dataclass(frozen=True)
class FactorResearchTaskConfig:
    exchange: str
    market_type: str
    symbols: tuple[str, ...]
    timeframe: str
    start_ms: int
    end_ms: int
    mode: str
    factor_instance_ids: tuple[str, ...]
    manual_combinations: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    provider_key: str = ""
    model: str = ""
    reasoning_effort: str = "auto"
    speed_mode: str = "standard"
    provider_snapshot: Mapping[str, Any] = field(default_factory=dict)
    horizon_bars: int = 6
    base_cost_bps: float = 20.0
    stress_cost_bps: float = 40.0
    min_coverage: float = 0.95
    n_splits: int = 5
    max_candidates: int = 200
    max_runtime_sec: int = 7200
    max_no_improvement: int = 50
    max_combination_leaves: int = 8
    target_accepted_candidates: int = 1
    random_seed: int = 42

    def __post_init__(self) -> None:
        object.__setattr__(self, "exchange", str(self.exchange or "").strip().lower())
        object.__setattr__(self, "market_type", str(self.market_type or "").strip().lower())
        object.__setattr__(self, "symbols", _tuple_of_strings(self.symbols, field_name="symbols"))
        object.__setattr__(
            self,
            "factor_instance_ids",
            _tuple_of_strings(self.factor_instance_ids, field_name="factor_instance_ids"),
        )
        object.__setattr__(self, "timeframe", str(self.timeframe or "").strip().lower())
        object.__setattr__(self, "mode", str(self.mode or "").strip().lower())
        if not isinstance(self.manual_combinations, (list, tuple)) or any(
            not isinstance(item, Mapping) for item in self.manual_combinations
        ):
            raise ValueError("manual_combinations must be a list of objects")
        object.__setattr__(
            self,
            "manual_combinations",
            tuple(dict(item) for item in self.manual_combinations),
        )
        object.__setattr__(self, "provider_key", str(self.provider_key or "").strip())
        object.__setattr__(self, "model", str(self.model or "").strip())
        object.__setattr__(self, "provider_snapshot", dict(self.provider_snapshot or {}))

        if not self.exchange or self.market_type not in {"spot", "swap"} or not self.timeframe:
            raise ValueError("exchange, market_type and timeframe are required")
        if int(self.start_ms) < 0 or int(self.end_ms) <= int(self.start_ms):
            raise ValueError("research date range is invalid")
        if self.mode not in {"manual", "auto", "hybrid"}:
            raise ValueError("research mode must be manual, auto or hybrid")
        if self.mode in {"manual", "hybrid"} and not self.manual_combinations:
            raise ValueError("manual and hybrid research require manual combinations")
        if self.mode in {"auto", "hybrid"} and (
            not self.provider_key or not self.model or not self.provider_snapshot
        ):
            raise ValueError("auto and hybrid research require a pinned Provider")
        snapshot_provider = str(self.provider_snapshot.get("provider_key") or "").strip()
        if self.provider_snapshot and snapshot_provider != self.provider_key:
            raise ValueError("Provider snapshot does not match the research task")
        if _contains_sensitive_provider_key(self.provider_snapshot):
            raise ValueError("Provider snapshot contains sensitive or executable fields")
        if int(self.horizon_bars) <= 0:
            raise ValueError("horizon_bars must be positive")
        if float(self.base_cost_bps) < 0 or float(self.stress_cost_bps) < float(self.base_cost_bps):
            raise ValueError("cost assumptions are invalid")
        if not 0 < float(self.min_coverage) <= 1:
            raise ValueError("min_coverage must be within (0, 1]")
        if int(self.n_splits) < 2:
            raise ValueError("n_splits must be at least 2")
        for name in (
            "max_candidates",
            "max_runtime_sec",
            "max_no_improvement",
            "max_combination_leaves",
            "target_accepted_candidates",
        ):
            if int(getattr(self, name)) <= 0:
                raise ValueError(f"{name} must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "exchange": self.exchange,
            "market_type": self.market_type,
            "symbols": list(self.symbols),
            "timeframe": self.timeframe,
            "start_ms": int(self.start_ms),
            "end_ms": int(self.end_ms),
            "mode": self.mode,
            "factor_instance_ids": list(self.factor_instance_ids),
            "manual_combinations": [dict(item) for item in self.manual_combinations],
            "provider_key": self.provider_key,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "speed_mode": self.speed_mode,
            "provider_snapshot": dict(self.provider_snapshot),
            "horizon_bars": int(self.horizon_bars),
            "base_cost_bps": float(self.base_cost_bps),
            "stress_cost_bps": float(self.stress_cost_bps),
            "min_coverage": float(self.min_coverage),
            "n_splits": int(self.n_splits),
            "max_candidates": int(self.max_candidates),
            "max_runtime_sec": int(self.max_runtime_sec),
            "max_no_improvement": int(self.max_no_improvement),
            "max_combination_leaves": int(self.max_combination_leaves),
            "target_accepted_candidates": int(self.target_accepted_candidates),
            "random_seed": int(self.random_seed),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FactorResearchTaskConfig":
        return cls(**dict(payload))


@dataclass(frozen=True)
class FactorResearchTask:
    task_id: str
    status: str
    config: FactorResearchTaskConfig
    dataset_snapshot_id: str | None = None
    trial_cursor: int = 0
    best_trial_id: str | None = None
    stop_reason: str | None = None
    archived_at: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class DatasetSnapshot:
    snapshot_id: str
    task_id: str
    manifest: Mapping[str, Any]
    artifact_path: str
    row_count: int
    feature_count: int
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class FactorTrial:
    trial_id: str
    task_id: str
    ordinal: int
    semantic_hash: str
    model_type: str
    feature_ids: tuple[str, ...]
    parameters: Mapping[str, Any]
    status: str
    metrics: Mapping[str, Any]
    hard_gate_failures: tuple[str, ...]
    artifact_manifest: Mapping[str, Any]
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "feature_ids",
            _tuple_of_strings(self.feature_ids, field_name="feature_ids"),
        )
        object.__setattr__(
            self,
            "hard_gate_failures",
            _tuple_of_strings(
                self.hard_gate_failures,
                field_name="hard_gate_failures",
                allow_empty=True,
            ),
        )
        if int(self.ordinal) < 0:
            raise ValueError("trial ordinal must be non-negative")
        if self.status not in {"completed", "rejected", "failed"}:
            raise ValueError("trial status is invalid")
        if not self.trial_id or not self.task_id or not self.semantic_hash or not self.model_type:
            raise ValueError("trial identity is incomplete")
