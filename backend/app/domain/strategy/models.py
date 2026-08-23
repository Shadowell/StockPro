from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping
from uuid import UUID


class ImmutableEvidenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class StrategyVersionView:
    id: UUID
    strategy_id: int | None
    version: int
    name: str
    description: str
    script_content: str
    parameters: Mapping[str, object]
    content_hash: str
    validation_status: Literal["pending", "valid", "invalid"]
    historical_contract_metadata: Mapping[str, object] | None


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    issues: tuple[Mapping[str, object], ...]
    dependencies: tuple[str, ...]


@dataclass(frozen=True)
class ReplayResult:
    status: str
    promotion_status: Literal["not_evaluated"]
    intents: tuple[Mapping[str, object], ...]
    records: tuple[Mapping[str, object], ...]
