"""Immutable FactorLab definition and instance models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple


@dataclass(frozen=True)
class FactorDefinition:
    definition_id: str
    definition_version: int
    display_name: str
    family: str
    role: str
    description: str
    kernel_name: str
    expression: Mapping[str, Any]
    inputs: Tuple[str, ...]
    parameter_schema: Mapping[str, Mapping[str, Any]]
    lookback_bars: int
    availability: str = "confirmed_bar_close"
    orientation: str = "higher_is_stronger"
    missing_policy: str = "block_new_entry"
    valid_min: Optional[float] = None
    valid_max: Optional[float] = None
    implementation_hash: str = ""
    status: str = "draft"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FactorInstance:
    instance_id: str
    definition_id: str
    definition_version: int
    parameters: Mapping[str, Any]
    parameter_hash: str
    required_bars: int
